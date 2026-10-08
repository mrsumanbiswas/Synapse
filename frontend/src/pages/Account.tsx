import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Bookmark, History, Mail, Trash2, UserRound } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { MODES, searchUrl } from "../components/SearchBox";
import { Badge, EmptyState, ErrorState, Section, Spinner, Tabs } from "../components/ui";
import { api, type Bookmark as BookmarkItem, type Mode, type NotificationItem, type Subscription } from "../lib/api";
import { useAuth } from "../lib/auth";
import { timeAgo } from "../lib/format";

function AlertsTab() {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<Mode>("hybrid");
  const [threshold, setThreshold] = useState(0.35);
  const [message, setMessage] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ id: number; matches: { id: string; title: string; score: number }[]; checked: number } | null>(null);
  const subs = useQuery({ queryKey: ["me", "subscriptions"], queryFn: () => api<{ subscriptions: Subscription[]; smtp: boolean }>("/me/subscriptions") });
  const refresh = () => client.invalidateQueries({ queryKey: ["me", "subscriptions"] });
  const add = useMutation({
    mutationFn: () => api("/me/subscriptions", { method: "POST", json: { query, mode, min_score: threshold } }),
    onSuccess: () => { setQuery(""); void refresh(); },
  });
  const toggle = useMutation({ mutationFn: (s: Subscription) => api(`/me/subscriptions/${s.id}`, { method: "PATCH", json: { active: !s.active } }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: number) => api(`/me/subscriptions/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const test = useMutation({
    mutationFn: () => api<{ to: string }>("/me/test-email", { method: "POST" }),
    onSuccess: (r) => setMessage(`Test e-mail sent to ${r.to}.`),
    onError: (e) => setMessage((e as Error).message),
  });
  const previewMutation = useMutation({
    mutationFn: (id: number) => api<{ matches: { id: string; title: string; score: number }[]; checked: number }>(`/me/subscriptions/${id}/preview`, { method: "POST" }),
    onSuccess: (data, id) => setPreview({ id, ...data }),
  });
  const notifications = useQuery({ queryKey: ["me", "notifications"], queryFn: () => api<{ notifications: NotificationItem[] }>("/me/notifications") });

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Section title="Create an alert" action={<BellRing className="size-4 text-accent" />}>
        <p className="mb-4 text-sm text-secondary">
          When new documents are ingested anywhere in the network, every node checks them against its users' alerts and sends one digest
          e-mail (smtplib). Semantic alerts also match papers that describe your interest in different words.
        </p>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (query.trim()) add.mutate(); }}>
          <label className="block"><span className="label">Interest (any search query)</span>
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder='e.g. "graph neural networks" recommendation' />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label><span className="label">Matching</span>
              <select className="input" value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
                {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </label>
            <label><span className="label">Semantic threshold ({threshold.toFixed(2)})</span>
              <input type="range" min={0.1} max={0.8} step={0.05} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} className="mt-2 w-full accent-[var(--accent)]" disabled={mode === "keyword" || mode === "boolean"} />
            </label>
          </div>
          {add.isError && <p className="text-sm text-critical">{(add.error as Error).message}</p>}
          <button className="btn-primary" disabled={!query.trim() || add.isPending}>Add alert</button>
        </form>
        <div className="mt-5 flex items-center gap-3 border-t border-line pt-4">
          <button className="btn-secondary" onClick={() => test.mutate()} disabled={test.isPending || subs.data?.smtp === false}><Mail className="size-4" /> Send test e-mail</button>
          {subs.data?.smtp === false && <span className="text-xs text-muted">This node has no SMTP server configured.</span>}
          {message && <span className="text-xs text-secondary">{message}</span>}
        </div>
      </Section>

      <Section title="Your alerts">
        {subs.isPending ? <Spinner /> : subs.isError ? <ErrorState error={subs.error} /> : subs.data.subscriptions.length === 0 ? (
          <EmptyState title="No alerts yet">Create one to get e-mailed about new matching papers.</EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {subs.data.subscriptions.map((s) => (
              <li key={s.id} className="py-3">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <Link to={searchUrl(s.query, s.mode)} className="font-medium text-ink hover:text-accent">{s.query}</Link>
                    <p className="text-xs text-muted">
                      {s.mode}{s.mode === "semantic" || s.mode === "hybrid" ? ` ≥ ${s.min_score.toFixed(2)}` : ""} · {s.matches} matches sent · last {timeAgo(s.last_notified_at)}
                    </p>
                  </div>
                  <label className="flex items-center gap-1.5 text-xs text-secondary">
                    <input type="checkbox" checked={Boolean(s.active)} onChange={() => toggle.mutate(s)} className="accent-[var(--accent)]" /> on
                  </label>
                  <button className="btn-ghost px-2 py-1 text-xs" onClick={() => previewMutation.mutate(s.id)}>Preview</button>
                  <button className="btn-ghost p-1.5" onClick={() => remove.mutate(s.id)} aria-label="Delete alert"><Trash2 className="size-4" /></button>
                </div>
                {preview?.id === s.id && (
                  <div className="mt-2 rounded-lg border border-line bg-raised p-3 text-xs">
                    <p className="mb-1 text-muted">Would match {preview.matches.length} of the {preview.checked} most recently ingested documents:</p>
                    <ul className="space-y-1">
                      {preview.matches.slice(0, 6).map((m) => (
                        <li key={m.id}><Link to={`/doc/${m.id}`} className="text-ink hover:text-accent">{m.title}</Link> <span className="text-muted">({m.score.toFixed(2)})</span></li>
                      ))}
                    </ul>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Alert history" className="lg:col-span-2">
        {notifications.isPending ? <Spinner /> : !notifications.data?.notifications.length ? (
          <p className="text-sm text-muted">No alerts sent yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {notifications.data.notifications.map((n) => (
              <li key={n.id} className="py-2.5 text-sm">
                <div className="flex items-center gap-2">
                  <Badge tone={n.status === "sent" ? "good" : "critical"}>{n.status}</Badge>
                  <span className="text-ink">{n.query}</span>
                  <span className="ml-auto text-xs text-muted">{timeAgo(n.created_at)}</span>
                </div>
                <p className="mt-1 text-xs text-secondary">
                  {n.documents.slice(0, 3).map((d) => d.title).join(" · ")}{n.documents.length > 3 ? ` +${n.documents.length - 3} more` : ""}
                </p>
                {n.error && <p className="mt-1 text-xs text-critical">{n.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function LibraryTab() {
  const client = useQueryClient();
  const bookmarks = useQuery({ queryKey: ["me", "bookmarks"], queryFn: () => api<{ bookmarks: BookmarkItem[] }>("/me/bookmarks") });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/me/bookmarks/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["me", "bookmarks"] }),
  });
  if (bookmarks.isPending) return <Spinner />;
  if (bookmarks.isError) return <ErrorState error={bookmarks.error} />;
  if (!bookmarks.data.bookmarks.length) return <EmptyState title="Your library is empty" icon={<Bookmark className="size-5" />}>Use the bookmark button on any result to save it here.</EmptyState>;
  return (
    <ul className="card divide-y divide-line">
      {bookmarks.data.bookmarks.map((b) => (
        <li key={b.doc_id} className="flex items-center gap-3 px-4 py-3">
          <Link to={`/doc/${b.doc_id}`} className="flex-1 text-sm text-ink hover:text-accent">{b.title}</Link>
          <span className="text-xs text-muted">saved {timeAgo(b.created_at)}</span>
          <button className="btn-ghost p-1.5" onClick={() => remove.mutate(b.doc_id)} aria-label="Remove bookmark"><Trash2 className="size-4" /></button>
        </li>
      ))}
    </ul>
  );
}

function HistoryTab() {
  const client = useQueryClient();
  const history = useQuery({ queryKey: ["me", "history"], queryFn: () => api<{ history: { query: string; mode: Mode; results: number; took_ms: number; ts: number }[] }>("/me/history") });
  const clear = useMutation({ mutationFn: () => api("/me/history", { method: "DELETE" }), onSuccess: () => client.invalidateQueries({ queryKey: ["me", "history"] }) });
  if (history.isPending) return <Spinner />;
  if (history.isError) return <ErrorState error={history.error} />;
  if (!history.data.history.length) return <EmptyState title="No searches yet" icon={<History className="size-5" />} />;
  return (
    <div className="card">
      <div className="flex justify-end border-b border-line px-4 py-2"><button className="btn-ghost px-2 py-1 text-xs" onClick={() => clear.mutate()}>Clear history</button></div>
      <table className="w-full text-sm">
        <tbody>
          {history.data.history.map((h, i) => (
            <tr key={i} className="border-b border-line last:border-0">
              <td className="px-4 py-2"><Link to={searchUrl(h.query, h.mode)} className="text-ink hover:text-accent">{h.query}</Link></td>
              <td className="px-2 py-2 text-xs text-muted">{h.mode}</td>
              <td className="tabular px-2 py-2 text-right text-xs text-secondary">{h.results} results</td>
              <td className="px-4 py-2 text-right text-xs text-muted">{timeAgo(h.ts)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProfileTab() {
  const { user, refresh } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api("/auth/me", { method: "PATCH", json: { name, ...(next ? { current_password: current, new_password: next } : {}) } }),
    onSuccess: async () => { setDone("Saved."); setCurrent(""); setNext(""); await refresh(); },
  });
  if (!user) return null;
  return (
    <Section title="Profile" className="max-w-lg" action={<UserRound className="size-4 text-accent" />}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <label className="block"><span className="label">Name</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="block"><span className="label">E-mail</span><input className="input" value={user.email} disabled /></label>
        <label className="block"><span className="label">Current password</span><input className="input" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" /></label>
        <label className="block"><span className="label">New password (8+ characters)</span><input className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></label>
        {save.isError && <p className="text-sm text-critical">{(save.error as Error).message}</p>}
        {done && <p className="text-sm text-good-text">{done}</p>}
        <button className="btn-primary" disabled={save.isPending}>Save changes</button>
      </form>
      <p className="mt-4 text-xs text-muted">Accounts are local to this node: each team member's node keeps its own users.</p>
    </Section>
  );
}

export function AccountPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "alerts" | "library" | "history" | "profile") || "alerts";
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <h1 className="mb-5 text-2xl font-semibold tracking-tight">Your account</h1>
      <Tabs value={tab} onChange={(t) => setParams(t === "alerts" ? {} : { tab: t })} tabs={[{ value: "alerts", label: "E-mail alerts" }, { value: "library", label: "Library" }, { value: "history", label: "Search history" }, { value: "profile", label: "Profile" }]} />
      <div className="mt-5">
        {tab === "alerts" && <AlertsTab />}
        {tab === "library" && <LibraryTab />}
        {tab === "history" && <HistoryTab />}
        {tab === "profile" && <ProfileTab />}
      </div>
    </div>
  );
}
