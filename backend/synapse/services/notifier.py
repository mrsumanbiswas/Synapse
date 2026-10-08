"""E-mail alerts: tell users when newly ingested documents match their saved interests.

After an ingest, the ingesting node broadcasts the new documents (NEW_DOCS).
Every node checks them against *its own* users' subscriptions:

* keyword / boolean interests are evaluated on a throw-away inverted index built
  from just the new documents, with the same stack-based query evaluator;
* semantic interests compare LSA vectors (cosine >= the subscription's threshold),
  so "car safety" also matches a paper about "vehicle collision avoidance".

Matches are grouped per user into one digest e-mail sent with ``smtplib``.
"""

from __future__ import annotations

import html
import logging
import smtplib
import ssl
import threading
from collections import defaultdict
from email.message import EmailMessage
from email.utils import make_msgid

import numpy as np

from ..config import Settings
from ..graph.knowledge_graph import author_key
from ..index.inverted_index import InvertedIndex
from ..index.query_parser import ALL, EMPTY, QuerySyntaxError, Resolver, evaluate, parse_query, year_bounds
from ..storage.app_store import AppStore
from ..text.tokenizer import analyze
from .shard import ShardEngine

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, settings: Settings, app: AppStore, engine: ShardEngine):
        self.settings = settings
        self.app = app
        self.engine = engine

    @property
    def configured(self) -> bool:
        return bool(self.settings.smtp_host)

    # ------------------------------------------------------------------ matching

    def _mini_index(self, docs: list[dict]) -> tuple[InvertedIndex, Resolver]:
        index = InvertedIndex()
        by_id = {d["id"]: d for d in docs}
        for doc in docs:
            index.add(doc["id"], analyze(doc.get("title") or ""), analyze(doc.get("abstract") or ""))

        def term(text: str) -> set[str]:
            terms = analyze(text)
            if not terms:
                return index.all_docs()
            return index.phrase_docs(terms) if len(terms) > 1 else index.docs(terms[0])

        def field(name: str, value: str) -> set[str]:
            if name == "author":
                wanted = author_key(value)
                return {d for d, doc in by_id.items() if any(wanted in author_key(a) for a in doc.get("authors", []))}
            if name == "year":
                low, high = year_bounds(value)
                return {d for d, doc in by_id.items() if doc.get("year") and (low is None or doc["year"] >= low)
                        and (high is None or doc["year"] <= high)}
            if name == "title":
                terms = analyze(value)
                return {d for d in index.phrase_docs(terms)} if terms else set()
            return set()

        return index, Resolver(term=term, phrase=lambda t: term(t), field=field, universe=index.all_docs)

    def _semantic(self, query: str, docs: list[dict], threshold: float) -> dict[str, float]:
        model = self.engine.model
        if model is None or model.lsa is None or not docs:
            return {}
        query_vector = model.vsm.query_vector(analyze(query))
        if query_vector.nnz == 0:
            return {}
        q = model.lsa.transform(query_vector)[0]
        tfs, titles = [], []
        for doc in docs:
            title_terms = analyze(doc.get("title") or "")
            counts: dict[str, int] = {}
            for term in title_terms + analyze(doc.get("abstract") or ""):
                counts[term] = counts.get(term, 0) + 1
            tfs.append(counts)
            titles.append(title_terms)
        vectors = model.lsa.transform(model.vsm.vectorize(tfs, titles))
        sims = vectors @ q
        return {doc["id"]: float(s) for doc, s in zip(docs, sims) if s >= threshold and np.isfinite(s)}

    def match(self, subscription: dict, docs: list[dict]) -> list[dict]:
        query, mode = subscription["query"], subscription["mode"]
        try:
            parsed = parse_query(query, strict=(mode == "boolean"))
        except QuerySyntaxError:
            return []
        _, resolver = self._mini_index(docs)
        scores: dict[str, float] = {}
        if mode == "boolean":
            for doc_id in evaluate(parsed.ast, resolver).docs:
                scores[doc_id] = 1.0
        else:
            constraint = parsed.constraint()
            allowed = None if constraint is ALL else (set() if constraint is EMPTY else evaluate(constraint, resolver).docs)
            if mode in ("keyword", "hybrid"):
                # An alert should be specific: every word of the interest must appear.
                for doc_id in evaluate(parsed.ast, resolver).docs:
                    scores[doc_id] = max(scores.get(doc_id, 0.0), 1.0)
            if mode in ("semantic", "hybrid"):
                terms_only = " ".join(leaf.text for leaf in parsed.positive_terms())
                for doc_id, sim in self._semantic(terms_only, docs, subscription["min_score"]).items():
                    if allowed is None or doc_id in allowed:
                        scores[doc_id] = max(scores.get(doc_id, 0.0), sim)
        by_id = {d["id"]: d for d in docs}
        return [{**by_id[d], "score": round(s, 3)} for d, s in sorted(scores.items(), key=lambda i: -i[1])]

    # ------------------------------------------------------------------ delivery

    def handle_new_documents(self, docs: list[dict]) -> dict:
        subscriptions = self.app.subscriptions(active_only=True)
        if not subscriptions or not docs:
            return {"subscriptions": len(subscriptions), "queued": 0}
        threading.Thread(target=self._deliver, args=(subscriptions, docs), name="alerts", daemon=True).start()
        return {"subscriptions": len(subscriptions), "queued": len(subscriptions)}

    def _deliver(self, subscriptions: list[dict], docs: list[dict]) -> None:
        per_user: dict[int, list[tuple[dict, list[dict]]]] = defaultdict(list)
        for subscription in subscriptions:
            matches = self.match(subscription, docs)
            if matches:
                per_user[subscription["user_id"]].append((subscription, matches))
        for user_id, groups in per_user.items():
            user = self.app.user(user_id)
            if not user:
                continue
            status, error = "sent", None
            try:
                self.send_digest(user, groups)
            except Exception as exc:  # noqa: BLE001 - recorded on the alert
                status, error = "failed", str(exc)
                log.warning("alert e-mail to %s failed: %s", user["email"], exc)
            for subscription, matches in groups:
                self.app.record_notification(user_id, subscription["id"], subscription["query"],
                                             [{"id": m["id"], "title": m["title"], "score": m["score"]} for m in matches],
                                             status, error)

    def send_digest(self, user: dict, groups: list[tuple[dict, list[dict]]]) -> None:
        count = sum(len(m) for _, m in groups)
        subject = f"Synapse: {count} new document{'s' if count != 1 else ''} match your interests"
        base = self.settings.public_url
        text_lines = [f"Hi {user['name']},", "", "New documents matching your Synapse alerts:", ""]
        html_parts = [f"<p>Hi {html.escape(user['name'])},</p><p>New documents matching your Synapse alerts:</p>"]
        for subscription, matches in groups:
            text_lines.append(f"Alert: {subscription['query']} ({subscription['mode']})")
            html_parts.append(f"<h3 style='margin:18px 0 6px;font:600 15px system-ui'>"
                              f"{html.escape(subscription['query'])}</h3><ul style='padding-left:18px'>")
            for doc in matches[:15]:
                link = f"{base}/doc/{doc['id']}"
                meta = ", ".join(filter(None, [", ".join(doc.get("authors", [])[:3]), str(doc.get("year") or "")]))
                text_lines += [f"  - {doc['title']} ({meta})", f"    {link}"]
                html_parts.append(
                    f"<li style='margin-bottom:8px'><a href='{html.escape(link)}' style='color:#2a78d6'>"
                    f"{html.escape(doc['title'])}</a><br><span style='color:#52514e;font-size:13px'>"
                    f"{html.escape(meta)}</span></li>")
            text_lines.append("")
            html_parts.append("</ul>")
        footer = f"Manage your alerts: {base}/account"
        text_lines.append(footer)
        html_parts.append(f"<p style='color:#898781;font-size:12px'>Manage your alerts at "
                          f"<a href='{html.escape(base)}/account'>{html.escape(base)}/account</a></p>")
        self.send_email(user["email"], subject, "\n".join(text_lines), "".join(html_parts))

    def send_email(self, to: str, subject: str, text: str, html_body: str) -> None:
        settings = self.settings
        if not settings.smtp_host:
            raise RuntimeError("SMTP is not configured (set SYNAPSE_SMTP_HOST)")
        message = EmailMessage()
        message["From"] = settings.mail_from
        message["To"] = to
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain="synapse.local")
        message.set_content(text)
        message.add_alternative(f"<div style='font:14px/1.5 system-ui,sans-serif;color:#0b0b0b'>{html_body}</div>",
                                subtype="html")
        context = ssl.create_default_context()
        if settings.smtp_ssl:
            client: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=context)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with client:
            client.ehlo()
            if settings.smtp_starttls and not settings.smtp_ssl:
                client.starttls(context=context)
                client.ehlo()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password or "")
            client.send_message(message)

    def send_test(self, user: dict) -> None:
        self.send_email(
            user["email"], "Synapse test alert",
            f"Hi {user['name']},\n\nE-mail alerts from Synapse node {self.settings.node_id} are working.",
            f"<p>Hi {html.escape(user['name'])},</p><p>E-mail alerts from Synapse node "
            f"<b>{html.escape(self.settings.node_id)}</b> are working.</p>",
        )
