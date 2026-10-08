import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Clock, Flame, Network, TrendingUp, Upload, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Logo } from "../components/Logo";
import { searchUrl, SearchBox } from "../components/SearchBox";
import { ErrorState, Spinner, StatTile } from "../components/ui";
import { api, type Mode, type Overview } from "../lib/api";
import { useAuth } from "../lib/auth";
import { authorList, formatNumber, timeAgo } from "../lib/format";
import { clearRecentSearches, recentSearches } from "../lib/recent";

const EXAMPLES: { q: string; mode: Mode; note: string }[] = [
  { q: "car", mode: "semantic", note: "finds autonomous-vehicle papers without the word" },
  { q: "word embeddings", mode: "hybrid", note: "" },
  { q: '"reinforcement learning" NOT robot', mode: "boolean", note: "" },
  { q: 'author:"Yoshua Bengio"', mode: "boolean", note: "" },
];

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <span className="text-accent">{icon}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

export function HomePage() {
  const { user, can } = useAuth();
  const [mode, setMode] = useState<Mode>("hybrid");
  const [recent, setRecent] = useState(recentSearches);
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/analytics/overview"), refetchInterval: 30_000 });
  const data = overview.data;

  return (
    <div className="mx-auto max-w-7xl px-4 pb-16 sm:px-6">
      <section className="relative pb-12 pt-10 sm:pt-16">
        <div className="absolute right-0 top-4">
          {can("curator") ? (
            <Link to="/ingest" className="btn-secondary">
              <Upload className="size-4" /> Ingest
            </Link>
          ) : (
            !user && (
              <Link to="/login?next=/ingest" className="text-xs text-muted hover:text-ink">
                Sign in to ingest files
              </Link>
            )
          )}
        </div>
        <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
          <Logo size="lg" />
          <p className="mt-4 max-w-xl text-balance text-secondary">
            Search research by meaning, not just keywords, across a peer-to-peer knowledge graph of papers, authors and
            citations.
          </p>
          <div className="mt-8 w-full">
            <SearchBox mode={mode} onModeChange={setMode} size="lg" autoFocus />
          </div>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2 text-xs text-muted">
            <span>Try</span>
            {EXAMPLES.map((example) => (
              <Link key={example.q} to={searchUrl(example.q, example.mode)} className="chip font-mono" title={example.note || undefined}>
                {example.q}
              </Link>
            ))}
          </div>
        </div>
      </section>

      {overview.isError && <ErrorState error={overview.error} retry={() => overview.refetch()} />}
      {overview.isPending && (
        <div className="flex justify-center py-10">
          <Spinner label="Reading the corpus…" />
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <StatTile label="Documents" value={formatNumber(data.documents)} hint={data.year_range ? `${data.year_range[0]}–${data.year_range[1]}` : undefined} />
            <StatTile label="Authors" value={formatNumber(data.graph.authors ?? 0)} hint={`${formatNumber(data.graph.collaborations ?? 0)} collaborations`} />
            <StatTile label="Citation links" value={formatNumber(data.graph.citations ?? 0)} hint={`${data.graph.communities ?? 0} communities`} />
            <StatTile label="Concepts (LSA)" value={formatNumber(data.model?.concepts ?? 0)} hint={`${formatNumber(data.model?.vocabulary ?? 0)} terms`} />
            <StatTile
              label="Nodes online"
              value={`${data.nodes.alive} / ${data.nodes.known}`}
              hint={<Link to="/network" className="link">Peer-to-peer network</Link>}
            />
          </div>

          <div className="mt-6 grid gap-4 lg:grid-cols-3">
            <Panel title="Trending topics" icon={<TrendingUp className="size-4" />}>
              {data.trending.length === 0 ? (
                <p className="text-sm text-muted">Topics appear after the first model build.</p>
              ) : (
                <ul className="space-y-1">
                  {data.trending.map((topic) => (
                    <li key={topic.id}>
                      <Link
                        to={`/search?q=${encodeURIComponent(topic.label)}&mode=semantic&topic=${topic.id}`}
                        className="group flex items-start justify-between gap-3 rounded-lg px-2 py-2 hover:bg-accent-soft"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-ink">{topic.label}</p>
                          <p className="truncate text-xs text-muted">{topic.terms.slice(0, 4).join(" · ")}</p>
                        </div>
                        <span className="tabular shrink-0 text-xs text-secondary" title="Share of recent papers relative to its overall share">
                          ×{topic.growth.toFixed(2)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel title="Bursts of activity" icon={<Flame className="size-4" />}>
              {data.bursts.length === 0 ? (
                <p className="text-sm text-muted">No recent bursts detected.</p>
              ) : (
                <ul className="space-y-1">
                  {data.bursts.map((burst) => (
                    <li key={`${burst.kind}-${burst.label}`}>
                      <Link to={searchUrl(burst.label, "hybrid")} className="flex items-center justify-between gap-3 rounded-lg px-2 py-2 hover:bg-accent-soft">
                        <span className="truncate text-sm text-ink">{burst.label}</span>
                        <span className="tabular shrink-0 text-xs text-muted">
                          {burst.start}–{burst.end} · {burst.kind}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-3 text-xs text-muted">Kleinberg burst detection over yearly frequencies.</p>
            </Panel>

            <Panel title="Searches" icon={<Clock className="size-4" />}>
              {recent.length > 0 && (
                <>
                  <div className="mb-1.5 flex items-center justify-between">
                    <p className="eyebrow">Your recent</p>
                    <button
                      className="text-xs text-muted hover:text-ink"
                      onClick={() => {
                        clearRecentSearches();
                        setRecent([]);
                      }}
                    >
                      <X className="inline size-3" /> Clear
                    </button>
                  </div>
                  <div className="mb-4 flex flex-wrap gap-1.5">
                    {recent.slice(0, 8).map((item) => (
                      <Link key={item.q} to={searchUrl(item.q, item.mode as Mode)} className="chip">
                        {item.q}
                      </Link>
                    ))}
                  </div>
                </>
              )}
              <p className="eyebrow mb-1.5">Popular across the network</p>
              {data.popular.length === 0 ? (
                <p className="text-sm text-muted">No searches yet. Be the first.</p>
              ) : (
                <ul>
                  {data.popular.map((item) => (
                    <li key={item.query}>
                      <Link to={searchUrl(item.query, "hybrid")} className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-accent-soft">
                        <span className="truncate text-ink">{item.query}</span>
                        <span className="tabular text-xs text-muted">{item.count}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Panel title="Most influential papers" icon={<Network className="size-4" />}>
              <ol className="space-y-1">
                {data.top_papers.map((paper, i) => (
                  <li key={paper.id}>
                    <Link to={`/doc/${paper.id}`} className="flex items-baseline gap-3 rounded-lg px-2 py-2 hover:bg-accent-soft">
                      <span className="tabular w-4 shrink-0 text-xs text-muted">{i + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-1 text-sm text-ink">{paper.label}</span>
                        <span className="text-xs text-muted">
                          {paper.year ?? "n.d."} · cited {paper.citations} times in the corpus
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
              <Link to="/explore?tab=influence" className="link mt-2 inline-flex items-center gap-1 text-xs">
                PageRank & HITS rankings <ArrowUpRight className="size-3" />
              </Link>
            </Panel>
            <Panel title="Recently added" icon={<Upload className="size-4" />}>
              <ul className="space-y-1">
                {data.recent_documents.map((doc) => (
                  <li key={doc.id}>
                    <Link to={`/doc/${doc.id}`} className="block rounded-lg px-2 py-2 hover:bg-accent-soft">
                      <span className="line-clamp-1 text-sm text-ink">{doc.title}</span>
                      <span className="line-clamp-1 text-xs text-muted">
                        {authorList(doc.authors, 2)} · {doc.year ?? "n.d."} · on {doc.node} · {timeAgo(doc.ingested_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
