import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bookmark, BookmarkCheck, Quote, Server } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api, type DocCard, type Segment } from "../lib/api";
import { useAuth } from "../lib/auth";
import { authorList, formatNumber } from "../lib/format";
import { Badge } from "./ui";

export function Snippet({ segments, className }: { segments?: Segment[]; className?: string }) {
  if (!segments?.length) return null;
  return (
    <p className={clsx("text-sm leading-relaxed text-secondary", className)}>
      {segments.map((segment, i) => (segment.h ? <mark key={i} className="hl">{segment.t}</mark> : <span key={i}>{segment.t}</span>))}
    </p>
  );
}

export function BookmarkButton({ id, title, initial }: { id: string; title: string; initial?: boolean }) {
  const { user } = useAuth();
  const client = useQueryClient();
  const [saved, setSaved] = useState(Boolean(initial));
  const mutation = useMutation({
    mutationFn: (next: boolean) =>
      next
        ? api(`/me/bookmarks/${encodeURIComponent(id)}`, { method: "PUT", json: { title } })
        : api(`/me/bookmarks/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onMutate: (next) => setSaved(next),
    onError: (_, next) => setSaved(!next),
    onSettled: () => client.invalidateQueries({ queryKey: ["me", "bookmarks"] }),
  });
  if (!user) return null;
  const Icon = saved ? BookmarkCheck : Bookmark;
  return (
    <button
      className={clsx("btn-ghost p-1.5", saved && "text-accent")}
      onClick={() => mutation.mutate(!saved)}
      aria-pressed={saved}
      title={saved ? "Remove from library" : "Save to library"}
    >
      <Icon className="size-4" />
    </button>
  );
}

function ScoreBar({ label, value }: { label: string; value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  const pct = Math.max(4, Math.min(100, value * 100));
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted" title={`${label} similarity ${value.toFixed(3)}`}>
      {label}
      <span className="inline-block h-1.5 w-12 overflow-hidden rounded-full bg-accent-soft">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

export function ResultCard({ doc, showScores = true, compact = false }: { doc: DocCard; showScores?: boolean; compact?: boolean }) {
  return (
    <article className={clsx("card group transition-colors hover:border-axis", compact ? "p-4" : "p-5")}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <Link to={`/doc/${doc.id}`} className="text-[15px] font-semibold leading-snug text-ink decoration-accent/40 underline-offset-2 hover:underline">
            {doc.title}
          </Link>
          <p className="mt-1 truncate text-xs text-muted">
            {authorList(doc.authors)} · {doc.year ?? "n.d."}
            {doc.venue && <> · {doc.venue}</>}
          </p>
        </div>
        <BookmarkButton id={doc.id} title={doc.title} initial={doc.bookmarked} />
      </div>
      {!compact && <Snippet segments={doc.snippet} className="mt-2.5" />}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        {doc.topic && <Badge>{doc.topic.label}</Badge>}
        {doc.in_citations > 0 && (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted" title="Citations from other papers in this corpus">
            <Quote className="size-3" /> cited {formatNumber(doc.in_citations)}× here
          </span>
        )}
        {doc.pagerank_pct >= 90 && <Badge tone="accent" title="PageRank percentile in the citation graph">top {Math.max(1, Math.round(100 - doc.pagerank_pct))}% influence</Badge>}
        {doc.also_keyword === false && <Badge tone="accent" title="Found by LSA but not by keyword matching">semantic only</Badge>}
        {showScores && doc.scores && (
          <>
            <ScoreBar label="keyword" value={doc.scores.keyword} />
            <ScoreBar label="semantic" value={doc.scores.semantic} />
          </>
        )}
        <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-muted" title="The shard (node) that stores this document">
          <Server className="size-3" /> {doc.node}
        </span>
      </div>
    </article>
  );
}
