import { keepPreviousData, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Binary, Columns2, List, Server, SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { YearHistogram } from "../charts/YearHistogram";
import { ResultCard } from "../components/ResultCard";
import { searchUrl, SearchBox } from "../components/SearchBox";
import { EmptyState, ErrorState, Pagination, Spinner } from "../components/ui";
import { api, qs, type AstNode, type CompareResponse, type ExplainResponse, type Mode, type SearchResponse, type Sort } from "../lib/api";
import { formatNumber } from "../lib/format";

const SORTS: { value: Sort; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "pagerank", label: "Influence (PageRank)" },
  { value: "citations", label: "Most cited" },
  { value: "year_desc", label: "Newest" },
  { value: "year_asc", label: "Oldest" },
];

function AstTree({ node }: { node: AstNode }) {
  const leaf = node.type === "term" || node.type === "phrase" || node.type === "field" || node.type === "all";
  if (leaf) {
    const text = node.type === "field" ? `${node.field}:${node.value}` : node.type === "phrase" ? `"${node.value}"` : node.type === "all" ? "*" : node.value;
    return <span className="rounded-md border border-line bg-raised px-1.5 py-0.5 font-mono text-xs text-ink">{text}</span>;
  }
  return (
    <div className="flex flex-col gap-1.5">
      <span className="w-fit rounded-md bg-accent px-1.5 py-0.5 text-[11px] font-semibold text-on-accent">{node.type.toUpperCase()}</span>
      <div className="ml-2 flex flex-col gap-1.5 border-l border-line pl-3">
        {node.children?.map((child, i) => <AstTree key={i} node={child} />)}
      </div>
    </div>
  );
}

function ExplainPanel({ q }: { q: string }) {
  const explain = useQuery({ queryKey: ["explain", q], queryFn: () => api<ExplainResponse>(`/search/explain${qs({ q })}`), retry: false });
  if (explain.isPending) return <Spinner label="Parsing…" />;
  if (explain.isError) return <ErrorState error={explain.error} />;
  const data = explain.data;
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div>
        <p className="eyebrow mb-2">1 · Tokens</p>
        <div className="flex flex-wrap gap-1.5">
          {data.tokens.map((token, i) => (
            <span key={i} className={clsx("rounded-md px-1.5 py-0.5 font-mono text-xs", token.implicit ? "border border-dashed border-axis text-muted" : "border border-line bg-raised text-ink")} title={token.implicit ? "Implicit AND inserted by the lexer" : token.type}>
              {token.text}
            </span>
          ))}
        </div>
        <p className="eyebrow mb-2 mt-4">2 · Reverse Polish notation</p>
        <p className="font-mono text-xs leading-6 text-ink">{data.rpn.join("  ")}</p>
        <p className="mt-1 text-xs text-muted">Produced with an operator stack (shunting-yard).</p>
      </div>
      <div>
        <p className="eyebrow mb-2">3 · Parse tree</p>
        <AstTree node={data.ast} />
      </div>
      <div>
        <p className="eyebrow mb-2">4 · Operand stack, summed over {data.nodes.length} nodes</p>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted">
              <th className="pb-1 font-medium">Step</th>
              <th className="pb-1 font-medium">Operation</th>
              <th className="pb-1 text-right font-medium">Docs on top</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {data.steps.map((step, i) => (
              <tr key={i} className="border-t border-line">
                <td className="py-1 text-muted">{i + 1}</td>
                <td className="py-1 font-mono text-ink">{step.action === "push" ? `push ${step.label}` : step.label}</td>
                <td className="py-1 text-right text-ink">{formatNumber(step.size)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-secondary">
          {formatNumber(data.matches)} documents satisfy the expression exactly.
        </p>
      </div>
    </div>
  );
}

function CompareView({ q }: { q: string }) {
  const compare = useQuery({ queryKey: ["compare", q], queryFn: () => api<CompareResponse>(`/search/compare${qs({ q, size: 10 })}`) });
  if (compare.isPending) return <Spinner label="Ranking with both models…" />;
  if (compare.isError) return <ErrorState error={compare.error} />;
  const data = compare.data;
  return (
    <div>
      <p className="mb-4 text-sm text-secondary">
        The same query ranked two ways. <strong className="text-ink">{data.overlap}</strong> of the top 10 overlap. Papers marked
        <em> semantic only</em> were found by latent semantic analysis without sharing the query's words.
      </p>
      <div className="grid gap-5 lg:grid-cols-2">
        {([
          ["Keyword · TF-IDF cosine", "Exact vocabulary overlap, weighted by rarity.", data.keyword],
          ["Semantic · LSA (SVD)", `Concepts: ${data.concepts.slice(0, 6).map((c) => c.term).join(", ") || "–"}`, data.semantic],
        ] as const).map(([title, subtitle, docs]) => (
          <div key={title}>
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="mb-3 text-xs text-muted">{subtitle}</p>
            <div className="space-y-2">
              {docs.length === 0 && <p className="text-sm text-muted">No matches.</p>}
              {docs.map((doc) => (
                <ResultCard key={doc.id} doc={doc} compact showScores={false} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const mode = (params.get("mode") as Mode) || "hybrid";
  const page = Number(params.get("page") ?? 1) || 1;
  const sort = (params.get("sort") as Sort) || "relevance";
  const view = params.get("view") ?? "list";
  const yearFrom = params.get("year_from") ? Number(params.get("year_from")) : null;
  const yearTo = params.get("year_to") ? Number(params.get("year_to")) : null;
  const topics = params.getAll("topic").map(Number);
  const author = params.get("author");
  const [showFilters, setShowFilters] = useState(false);

  const update = (changes: Record<string, string | number | null | (string | number)[]>, resetPage = true) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      next.delete(key);
      if (Array.isArray(value)) value.forEach((v) => next.append(key, String(v)));
      else if (value !== null && value !== "") next.set(key, String(value));
    }
    if (resetPage) next.delete("page");
    setParams(next);
  };

  const search = useQuery({
    queryKey: ["search", q, mode, page, sort, yearFrom, yearTo, topics, author],
    queryFn: () =>
      api<SearchResponse>(`/search${qs({ q, mode, page, size: 10, sort, year_from: yearFrom, year_to: yearTo, topic: topics, author })}`),
    enabled: q.trim().length > 0 && view === "list",
    placeholderData: keepPreviousData,
    retry: false,
  });
  const data = search.data;
  const filtered = yearFrom !== null || yearTo !== null || topics.length > 0 || Boolean(author);

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <div className="max-w-3xl">
        <SearchBox initial={q} mode={mode} onModeChange={(m) => update({ mode: m === "hybrid" ? null : m })} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-b border-line pb-3">
        <div className="flex rounded-lg border border-line bg-raised p-0.5">
          {([
            ["list", "Results", List],
            ["compare", "TF-IDF vs LSA", Columns2],
            ["explain", "Explain query", Binary],
          ] as const).map(([value, label, Icon]) => (
            <button
              key={value}
              onClick={() => update({ view: value === "list" ? null : value }, false)}
              className={clsx("inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium", view === value ? "bg-accent text-on-accent" : "text-secondary hover:text-ink")}
            >
              <Icon className="size-3.5" /> {label}
            </button>
          ))}
        </div>
        {view === "list" && (
          <>
            <label className="ml-auto flex items-center gap-2 text-xs text-secondary">
              Sort
              <select className="input w-auto py-1 text-xs" value={sort} onChange={(event) => update({ sort: event.target.value === "relevance" ? null : event.target.value })}>
                {SORTS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <button className="btn-secondary px-2.5 py-1 text-xs lg:hidden" onClick={() => setShowFilters((v) => !v)}>
              <SlidersHorizontal className="size-3.5" /> Filters
            </button>
          </>
        )}
      </div>

      {!q.trim() && <EmptyState title="Type a query to search the corpus" />}

      {q.trim() && view === "explain" && (
        <div className="card mt-5 p-5">
          <ExplainPanel q={q} />
        </div>
      )}
      {q.trim() && view === "compare" && (
        <div className="mt-5">
          <CompareView q={q} />
        </div>
      )}

      {q.trim() && view === "list" && (
        <div className="mt-5 grid gap-6 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <aside className={clsx("space-y-5 lg:block", showFilters ? "block" : "hidden")}>
            {data && (
              <>
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="eyebrow">Publication year</p>
                    {(yearFrom !== null || yearTo !== null) && (
                      <button className="text-xs text-muted hover:text-ink" onClick={() => update({ year_from: null, year_to: null })}>Clear</button>
                    )}
                  </div>
                  <YearHistogram data={data.facets.years} from={yearFrom} to={yearTo} onSelect={(from, to) => update({ year_from: from, year_to: to })} />
                </div>
                {data.facets.topics.length > 0 && (
                  <div>
                    <p className="eyebrow mb-2">Topics</p>
                    <ul className="space-y-0.5">
                      {data.facets.topics.slice(0, 12).map((topic) => {
                        const active = topics.includes(topic.id);
                        return (
                          <li key={topic.id}>
                            <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-accent-soft">
                              <input
                                type="checkbox"
                                checked={active}
                                onChange={() => update({ topic: active ? topics.filter((t) => t !== topic.id) : [...topics, topic.id] })}
                                className="accent-[var(--accent)]"
                              />
                              <span className="flex-1 truncate text-ink">{topic.label}</span>
                              <span className="tabular text-xs text-muted">{formatNumber(topic.count)}</span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
                {data.facets.authors.length > 0 && (
                  <div>
                    <p className="eyebrow mb-2">Authors</p>
                    <ul className="space-y-0.5">
                      {data.facets.authors.slice(0, 10).map(([name, count]) => (
                        <li key={name}>
                          <button
                            onClick={() => update({ author: author === name ? null : name })}
                            className={clsx("flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-sm hover:bg-accent-soft", author === name && "bg-accent-soft")}
                          >
                            <span className="flex-1 truncate text-ink">{name}</span>
                            <span className="tabular text-xs text-muted">{count}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </aside>

          <div className={clsx("min-w-0 transition-opacity", search.isFetching && data && "opacity-60")}>
            {search.isPending && <Spinner label="Asking every node…" />}
            {search.isError && <ErrorState error={search.error} retry={() => search.refetch()} />}
            {data && (
              <>
                <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-secondary">
                  <span>
                    <strong className="text-ink">{formatNumber(data.total)}</strong> results in {data.took_ms} ms
                  </span>
                  <span className="flex flex-wrap items-center gap-1.5" title="Every node searched its own shard in parallel">
                    <Server className="size-3.5" />
                    {data.nodes.map((node) => (
                      <span key={node.node} className={clsx("rounded-md border px-1.5 py-0.5 text-[11px]", node.ok ? "border-line text-secondary" : "border-critical/40 text-critical")} title={node.ok ? `${node.hits} hits in ${node.ms} ms` : node.error ?? "unreachable"}>
                        {node.node} {node.ok ? `· ${node.hits}` : "· offline"}
                      </span>
                    ))}
                  </span>
                </div>

                {filtered && (
                  <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-muted">Filters:</span>
                    {(yearFrom !== null || yearTo !== null) && (
                      <button className="chip" onClick={() => update({ year_from: null, year_to: null })}>
                        {yearFrom}–{yearTo} <X className="size-3" />
                      </button>
                    )}
                    {topics.map((id) => (
                      <button key={id} className="chip" onClick={() => update({ topic: topics.filter((t) => t !== id) })}>
                        {data.facets.topics.find((t) => t.id === id)?.label ?? `topic ${id}`} <X className="size-3" />
                      </button>
                    ))}
                    {author && (
                      <button className="chip" onClick={() => update({ author: null })}>
                        {author} <X className="size-3" />
                      </button>
                    )}
                  </div>
                )}

                {data.did_you_mean && (
                  <p className="mb-4 text-sm">
                    Did you mean{" "}
                    <Link to={searchUrl(data.did_you_mean, mode)} className="link font-medium">
                      {data.did_you_mean}
                    </Link>
                    ?
                  </p>
                )}
                {data.parsed.fallback && data.parsed.error && (
                  <p className="mb-4 rounded-lg border border-line bg-surface px-3 py-2 text-xs text-secondary">
                    The query wasn't valid syntax ({data.parsed.error}), so it was read as plain words.
                  </p>
                )}
                {data.concepts.length > 0 && (
                  <div className="mb-5 flex flex-wrap items-center gap-1.5">
                    <span className="mr-1 text-xs text-muted" title="Terms that load on the same LSA concepts as your query">Also matched concepts</span>
                    {data.concepts.slice(0, 8).map((concept) => (
                      <Link key={concept.term} to={searchUrl(concept.term, mode)} className="chip">
                        {concept.term}
                      </Link>
                    ))}
                  </div>
                )}

                {data.results.length === 0 ? (
                  <EmptyState title="No documents matched">
                    Try semantic mode, fewer words, or remove filters.
                  </EmptyState>
                ) : (
                  <div className="space-y-3">
                    {data.results.map((doc) => (
                      <ResultCard key={doc.id} doc={doc} showScores={mode === "hybrid"} />
                    ))}
                  </div>
                )}
                <div className="mt-6">
                  <Pagination page={page} total={data.total} size={10} onPage={(p) => update({ page: p }, false)} />
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
