import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Check, Copy, Download, ExternalLink, FileText, Server, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ForceGraph, LegendItem, type GraphStyle } from "../components/ForceGraph";
import { BookmarkButton } from "../components/ResultCard";
import { Badge, EmptyState, ErrorState, Modal, PageLoader, Segmented, Spinner } from "../components/ui";
import { api, qs, type DocCard, type DocumentDetail, type GraphData, type LightDoc } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatNumber, timeAgo } from "../lib/format";
import { useChartColors } from "../lib/theme";

const connectionStyle: GraphStyle = {
  color: (node, c) =>
    ({ focus: c.ink, reference: c.series[0], citing: c.series[2], author: c.series[1], similar: c.muted })[node.role ?? ""] ?? c.context,
  radius: (node) => (node.role === "focus" ? 8 : node.type === "author" ? 3.6 : 3 + Math.min(5, Math.sqrt((node.pagerank ?? 0) * 4000))),
  shape: (node) => (node.type === "author" ? "square" : "circle"),
  linkColor: (link, c) => (link.type === "similar" ? c.muted : c.axis),
  linkDash: (link) => (link.type === "similar" ? [3, 3] : null),
  arrows: true,
  alwaysLabel: (node) => node.role === "focus",
};

function shownOf(shown: number, total?: number) {
  return total && total > shown ? `${shown} of ${total}` : String(shown);
}

function MetricTile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-raised px-3 py-2.5" title={hint}>
      <div className="text-[11px] text-muted">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-ink">{value}</div>
    </div>
  );
}

function DocList({ docs, empty, limit = 8 }: { docs: LightDoc[]; empty: string; limit?: number }) {
  const [all, setAll] = useState(false);
  if (!docs.length) return <p className="text-sm text-muted">{empty}</p>;
  const shown = all ? docs : docs.slice(0, limit);
  return (
    <>
      <ul className="divide-y divide-line">
        {shown.map((doc) => (
          <li key={doc.id} className="py-2">
            <Link to={`/doc/${doc.id}`} className="text-sm text-ink hover:text-accent">{doc.title}</Link>
            <p className="text-xs text-muted">
              {doc.authors.slice(0, 3).join(", ")} · {doc.year ?? "n.d."} · cited {doc.citations}× here
            </p>
          </li>
        ))}
      </ul>
      {docs.length > limit && (
        <button className="link mt-2 text-xs" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show all ${docs.length}`}
        </button>
      )}
    </>
  );
}

function Block({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="border-t border-line pt-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

const ENTITY_LABELS: Record<string, string> = {
  email: "E-mail addresses",
  url: "URLs",
  doi: "DOIs mentioned",
  arxiv: "arXiv ids",
  citation: "Citation markers",
  author_year: "Author–year citations",
  keyword: "Keywords",
  category: "Categories",
};

function BibtexDialog({ id, open, onClose }: { id: string; open: boolean; onClose: () => void }) {
  const bibtex = useQuery({ queryKey: ["bibtex", id], queryFn: () => api<string>(`/documents/${encodeURIComponent(id)}/bibtex`), enabled: open });
  const [copied, setCopied] = useState(false);
  return (
    <Modal open={open} onClose={onClose} title="Cite this document">
      {bibtex.isPending ? (
        <Spinner />
      ) : bibtex.isError ? (
        <ErrorState error={bibtex.error} />
      ) : (
        <>
          <pre className="overflow-x-auto rounded-lg border border-line bg-raised p-3 font-mono text-xs leading-5 text-ink">{bibtex.data}</pre>
          <div className="mt-3 flex gap-2">
            <button
              className="btn-secondary"
              onClick={async () => {
                await navigator.clipboard.writeText(bibtex.data ?? "");
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check className="size-4" /> : <Copy className="size-4" />} {copied ? "Copied" : "Copy"}
            </button>
            <a className="btn-secondary" href={`data:application/x-bibtex;charset=utf-8,${encodeURIComponent(bibtex.data ?? "")}`} download={`${id.replace(":", "-")}.bib`}>
              <Download className="size-4" /> Download .bib
            </a>
          </div>
        </>
      )}
    </Modal>
  );
}

export function DocumentPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const colors = useChartColors();
  const [depth, setDepth] = useState<"1" | "2">("1");
  const [showAuthors, setShowAuthors] = useState(true);
  const [showSimilar, setShowSimilar] = useState(true);
  const [cite, setCite] = useState(false);
  const [fullText, setFullText] = useState(false);

  const doc = useQuery({ queryKey: ["document", id], queryFn: () => api<DocumentDetail>(`/documents/${encodeURIComponent(id)}`), retry: false });
  const graph = useQuery({
    queryKey: ["document-graph", id, depth, showAuthors, showSimilar],
    queryFn: () => api<GraphData>(`/documents/${encodeURIComponent(id)}/graph${qs({ depth, authors: showAuthors, similar: showSimilar })}`),
    enabled: doc.isSuccess,
  });
  const similar = useQuery({
    queryKey: ["similar", id],
    queryFn: () => api<{ results: DocCard[] }>(`/documents/${encodeURIComponent(id)}/similar?k=8`),
    enabled: doc.isSuccess,
  });
  const remove = useMutation({
    mutationFn: () => api(`/documents/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => navigate("/", { replace: true }),
  });

  if (doc.isPending) return <PageLoader label="Fetching from the owning shard…" />;
  if (doc.isError)
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <ErrorState error={doc.error} retry={() => doc.refetch()} />
      </div>
    );

  const d = doc.data;
  const metrics = d.metrics;
  const entities = Object.entries(d.entities).filter(([kind]) => kind !== "keyword" && kind !== "category");
  const keywords = [...(d.entities.keyword ?? []), ...(d.entities.category ?? [])].map((e) => e.value);
  const extracted = d.references.filter((ref) => ref.raw);
  const counts = graph.data
    ? graph.data.nodes.reduce<Record<string, number>>((acc, node) => ({ ...acc, [node.role ?? ""]: (acc[node.role ?? ""] ?? 0) + 1 }), {})
    : {};

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <button className="btn-ghost -ml-2 mb-3 px-2 py-1 text-xs" onClick={() => navigate(-1)}>
        <ArrowLeft className="size-3.5" /> Back
      </button>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {/* ------------------------------------------------ details */}
        <article className="card min-w-0 space-y-5 p-6">
          <header>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              {d.topic && (
                <Link to={`/search?q=${encodeURIComponent(d.topic.label)}&mode=semantic&topic=${d.topic.id}`}>
                  <Badge tone="accent">{d.topic.label}</Badge>
                </Link>
              )}
              {d.source && <Badge>{d.source}</Badge>}
              <Badge title="The shard that stores this document"><Server className="size-3" /> {d.node}</Badge>
            </div>
            <h1 className="text-2xl font-semibold leading-tight tracking-tight text-ink">{d.title}</h1>
            <p className="mt-2 text-sm text-secondary">
              {d.authors.length ? (
                d.authors.map((name, i) => (
                  <span key={name}>
                    {i > 0 && ", "}
                    <Link to={`/author/${encodeURIComponent(name)}`} className="hover:text-accent hover:underline">{name}</Link>
                  </span>
                ))
              ) : (
                "Unknown authors"
              )}
            </p>
            <p className="mt-1 text-sm text-muted">
              {d.year ?? "n.d."}
              {d.venue && <> · {d.venue}</>}
              {d.doi && <> · doi:{d.doi}</>}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <BookmarkButton id={d.id} title={d.title} initial={d.bookmarked} />
              <button className="btn-secondary px-3 py-1.5 text-xs" onClick={() => setCite(true)}>
                <FileText className="size-3.5" /> Cite (BibTeX)
              </button>
              {(d.url || d.doi) && (
                <a className="btn-secondary px-3 py-1.5 text-xs" href={d.url ?? `https://doi.org/${d.doi}`} target="_blank" rel="noreferrer">
                  <ExternalLink className="size-3.5" /> Source
                </a>
              )}
              {can("admin") && (
                <button className="btn-danger ml-auto px-3 py-1.5 text-xs" onClick={() => window.confirm("Delete this document from its shard?") && remove.mutate()}>
                  <Trash2 className="size-3.5" /> Delete
                </button>
              )}
            </div>
          </header>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MetricTile label="Cited in corpus" value={formatNumber(metrics?.in_citations ?? d.in_citations)} hint="Papers in this corpus that cite it" />
            <MetricTile label="References here" value={`${formatNumber(metrics?.out_citations ?? 0)} / ${formatNumber(d.references_total)}`} hint="References that resolve to papers in this corpus" />
            <MetricTile label="Influence" value={metrics ? `Top ${Math.max(1, Math.round(100 - metrics.pagerank_pct))}%` : "–"} hint={metrics ? `PageRank ${metrics.pagerank.toExponential(2)}, higher than ${Math.round(metrics.pagerank_pct)}% of papers` : undefined} />
            <MetricTile label="Cited worldwide" value={d.cited_by_count != null ? formatNumber(d.cited_by_count) : "–"} hint="Citation count reported by the source (e.g. OpenAlex)" />
          </div>

          {d.abstract ? (
            <Block title="Abstract">
              <p className="text-[15px] leading-relaxed text-ink">{d.abstract}</p>
            </Block>
          ) : (
            <Block title="Abstract">
              <p className="text-sm text-muted">No abstract available.</p>
            </Block>
          )}

          {(d.concepts?.length || d.top_terms?.length) && (
            <Block title="What it's about">
              {d.concepts && d.concepts.length > 0 && (
                <div className="mb-3">
                  <p className="mb-1.5 text-xs text-muted">LSA concept profile: terms its concept vector points to</p>
                  <div className="flex flex-wrap gap-1.5">
                    {d.concepts.map((c) => (
                      <Link key={c.term} to={`/search?q=${encodeURIComponent(c.term)}&mode=semantic`} className="chip">{c.term}</Link>
                    ))}
                  </div>
                </div>
              )}
              {d.top_terms && d.top_terms.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs text-muted">Highest TF-IDF terms</p>
                  <p className="text-sm text-secondary">{d.top_terms.map((t) => t.term).join(" · ")}</p>
                </div>
              )}
              {keywords.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1.5 text-xs text-muted">Keywords & categories</p>
                  <div className="flex flex-wrap gap-1.5">
                    {keywords.slice(0, 16).map((k) => (
                      <Badge key={k}>{k}</Badge>
                    ))}
                  </div>
                </div>
              )}
            </Block>
          )}

          {entities.length > 0 && (
            <Block title="Extracted with regular expressions">
              <dl className="space-y-3">
                {entities.map(([kind, values]) => (
                  <div key={kind}>
                    <dt className="mb-1 text-xs text-muted">{ENTITY_LABELS[kind] ?? kind}</dt>
                    <dd className="flex flex-wrap gap-1.5">
                      {values.slice(0, 30).map((entity) => (
                        <span key={entity.value} className="rounded-md border border-line bg-raised px-1.5 py-0.5 font-mono text-xs text-ink">
                          {kind === "url" ? (
                            <a href={entity.value.startsWith("http") ? entity.value : `https://${entity.value}`} target="_blank" rel="noreferrer nofollow" className="hover:text-accent">
                              {entity.value}
                            </a>
                          ) : (
                            entity.value
                          )}
                          {entity.count > 1 && <span className="ml-1 text-muted">×{entity.count}</span>}
                        </span>
                      ))}
                    </dd>
                  </div>
                ))}
              </dl>
            </Block>
          )}

          <Block title={`References in this corpus (${d.references_in_corpus.length})`}>
            <DocList docs={d.references_in_corpus} empty="None of its references are in the corpus yet." />
          </Block>

          {extracted.length > 0 && (
            <Block title={`Reference list (${extracted.length} parsed from the text)`}>
              <ol className="space-y-2">
                {extracted.slice(0, 40).map((ref) => (
                  <li key={ref.position} className="flex gap-2 text-xs">
                    <span className="tabular w-6 shrink-0 text-muted">[{ref.position + 1}]</span>
                    <span className="flex-1 text-secondary">
                      {ref.raw}
                      {ref.resolved ? (
                        <Link to={`/doc/${ref.resolved}`} className="link ml-1.5 whitespace-nowrap">→ in corpus</Link>
                      ) : (
                        ref.title && <span className="ml-1.5 text-muted">(title: {ref.title})</span>
                      )}
                    </span>
                  </li>
                ))}
              </ol>
            </Block>
          )}

          <Block title={`Cited by (${d.cited_by.length})`}>
            <DocList docs={d.cited_by} empty="No paper in the corpus cites this one yet." />
          </Block>

          <Block title="Semantically similar" aside={<span className="text-xs text-muted">cosine in LSA space</span>}>
            {similar.isPending ? (
              <Spinner />
            ) : similar.data?.results.length ? (
              <ul className="divide-y divide-line">
                {similar.data.results.map((hit) => (
                  <li key={hit.id} className="flex items-baseline gap-3 py-2">
                    <span className="tabular w-10 shrink-0 text-xs text-muted">{(hit.score ?? 0).toFixed(2)}</span>
                    <Link to={`/doc/${hit.id}`} className="flex-1 text-sm text-ink hover:text-accent">{hit.title}</Link>
                    <span className="shrink-0 text-xs text-muted">{hit.year ?? ""}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">No vector yet: similar papers appear after the next model rebuild.</p>
            )}
          </Block>

          {d.body && (
            <Block title="Full text" aside={<button className="link text-xs" onClick={() => setFullText((v) => !v)}>{fullText ? "Hide" : "Show"}</button>}>
              {fullText ? (
                <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-raised p-3 font-sans text-sm leading-relaxed text-secondary">{d.body}</pre>
              ) : (
                <p className="text-sm text-muted">{formatNumber(d.body_length ?? d.body.length)} characters of extracted text.</p>
              )}
            </Block>
          )}

          <Block title="Provenance">
            <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
              <dt className="text-muted">Document id</dt>
              <dd className="truncate font-mono text-ink">{d.id}</dd>
              <dt className="text-muted">Stored on</dt>
              <dd className="text-ink">{d.node} (sent by {d.ingested_via ?? "?"}) · {timeAgo(d.ingested_at)}</dd>
              {d.filename && (<><dt className="text-muted">File</dt><dd className="truncate text-ink">{d.filename}</dd></>)}
              <dt className="text-muted">Identity keys</dt>
              <dd className="break-all font-mono text-ink">{d.identity_keys.join("  ")}</dd>
            </dl>
          </Block>
        </article>

        {/* ------------------------------------------------ connection graph */}
        <aside className="min-w-0">
          <div className="card sticky top-20 p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h2 className="mr-auto text-sm font-semibold">Connection graph</h2>
              <Segmented size="sm" value={depth} onChange={setDepth} options={[{ value: "1", label: "1 hop" }, { value: "2", label: "2 hops" }]} label="Graph depth" />
            </div>
            <div className="mb-2 flex flex-wrap gap-3 text-xs text-secondary">
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={showAuthors} onChange={(e) => setShowAuthors(e.target.checked)} className="accent-[var(--accent)]" /> Authors</label>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={showSimilar} onChange={(e) => setShowSimilar(e.target.checked)} className="accent-[var(--accent)]" /> Similar (LSA)</label>
            </div>
            <div className={clsx("rounded-lg border border-line bg-surface transition-opacity", graph.isFetching && "opacity-60")}>
              {graph.isError ? (
                <div className="p-4"><ErrorState error={graph.error} /></div>
              ) : graph.data && graph.data.nodes.length > 1 ? (
                <ForceGraph
                  data={graph.data}
                  style={connectionStyle}
                  height="min(62vh, 560px)"
                  onNodeClick={(node) => {
                    if (node.type === "author") navigate(`/author/${encodeURIComponent(node.label)}`);
                    else if (node.id !== d.id) navigate(`/doc/${node.id}`);
                  }}
                  tooltip={(node) => (
                    <>
                      <p className="font-medium text-ink">{node.label}</p>
                      <p className="mt-0.5 text-muted">
                        {node.type === "author"
                          ? "Author · click for profile"
                          : `${node.year ?? "n.d."} · ${node.role === "similar" ? `similarity ${(node.similarity ?? 0).toFixed(2)}` : `cited ${node.citations ?? 0}× here`}`}
                      </p>
                    </>
                  )}
                />
              ) : graph.isPending ? (
                <div className="flex h-80 items-center justify-center"><Spinner label="Walking the graph…" /></div>
              ) : (
                <EmptyState title="No connections yet">Citation links appear once referenced papers are in the corpus.</EmptyState>
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
              <LegendItem color={colors.ink} label="This paper" />
              <LegendItem color={colors.series[0]} label={`References (${shownOf(counts.reference ?? 0, metrics?.out_citations)})`} />
              <LegendItem color={colors.series[2]} label={`Cited by (${shownOf(counts.citing ?? 0, metrics?.in_citations)})`} />
              {showAuthors && <LegendItem color={colors.series[1]} shape="square" label={`Authors (${counts.author ?? 0})`} />}
              {showSimilar && <LegendItem color={colors.muted} shape="line" dashed label={`Similar (${counts.similar ?? 0})`} />}
              {depth === "2" && <LegendItem color={colors.context} label="2nd hop" />}
            </div>
            <p className="mt-2 text-xs text-muted">Node size follows PageRank. Arrows point from citing to cited paper. Click a node to open it.</p>
          </div>
        </aside>
      </div>
      <BibtexDialog id={d.id} open={cite} onClose={() => setCite(false)} />
    </div>
  );
}
