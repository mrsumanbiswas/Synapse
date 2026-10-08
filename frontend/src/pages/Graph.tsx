import { keepPreviousData, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDown, ArrowUp, Route, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ForceGraph, LegendItem, type GraphStyle } from "../components/ForceGraph";
import { EmptyState, ErrorState, Section, Spinner, Tabs } from "../components/ui";
import { api, qs, type DocCard, type GraphData, type GraphNode, type SearchResponse, type Topic } from "../lib/api";
import { formatNumber } from "../lib/format";
import { useChartColors } from "../lib/theme";

type Tab = "citations" | "authors" | "path";

function CitationNetwork() {
  const navigate = useNavigate();
  const colors = useChartColors();
  const [limit, setLimit] = useState(220);
  const [topic, setTopic] = useState<number | "">("");
  const [highlight, setHighlight] = useState<(number | null)[]>([null, null, null]);
  const topics = useQuery({ queryKey: ["topics"], queryFn: () => api<{ topics: Topic[] }>("/analytics/topics") });
  const network = useQuery({
    queryKey: ["citation-network", limit, topic],
    queryFn: () => api<GraphData>(`/graph/citations${qs({ limit, topic: topic === "" ? null : topic })}`),
    placeholderData: keepPreviousData,
  });
  const sortedTopics = useMemo(() => [...(topics.data?.topics ?? [])].sort((a, b) => b.size - a.size), [topics.data]);
  const highlighted = highlight.some((h) => h !== null);

  const style = useMemo<GraphStyle>(
    () => ({
      color: (node, c) => {
        if (!highlighted) return c.series[0];
        const slot = highlight.indexOf(node.cluster ?? -999);
        return slot >= 0 ? c.series[slot] : c.context;
      },
      radius: (node) => 2.5 + Math.min(9, Math.sqrt((node.pagerank ?? 0) * 6000)),
      arrows: true,
      alwaysLabel: (node) => (node.pagerank_pct ?? 0) >= 99.85,
    }),
    [highlight, highlighted],
  );

  const toggle = (id: number) => {
    const at = highlight.indexOf(id);
    if (at >= 0) setHighlight(highlight.map((h, i) => (i === at ? null : h)));
    else {
      const free = highlight.indexOf(null);
      if (free >= 0) setHighlight(highlight.map((h, i) => (i === free ? id : h)));
    }
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_19rem]">
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 text-xs text-secondary">
          <label className="flex items-center gap-2">
            Papers
            <input type="range" min={50} max={800} step={10} value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="accent-[var(--accent)]" />
            <span className="tabular w-8 text-ink">{limit}</span>
          </label>
          <label className="flex items-center gap-2">
            Only topic
            <select className="input w-44 py-1 text-xs" value={topic} onChange={(e) => setTopic(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">All topics</option>
              {sortedTopics.map((t) => (
                <option key={t.id} value={t.id}>{t.label}</option>
              ))}
            </select>
          </label>
          {network.data && (
            <span className="ml-auto">
              {formatNumber(network.data.nodes.length)} papers · {formatNumber(network.data.links.length)} citations
            </span>
          )}
        </div>
        <div className={clsx("transition-opacity", network.isFetching && "opacity-60")}>
          {network.isError ? (
            <div className="p-4"><ErrorState error={network.error} /></div>
          ) : network.data ? (
            <ForceGraph
              data={network.data}
              style={style}
              height="min(70vh, 680px)"
              onNodeClick={(node) => navigate(`/doc/${node.id}`)}
              tooltip={(node) => (
                <>
                  <p className="font-medium text-ink">{node.label}</p>
                  <p className="mt-0.5 text-muted">
                    {node.year ?? "n.d."} · cited {node.citations}× · PageRank {Math.round(node.pagerank_pct ?? 0)}th pct
                  </p>
                </>
              )}
            />
          ) : (
            <div className="flex h-96 items-center justify-center"><Spinner label="Laying out the graph…" /></div>
          )}
        </div>
      </div>
      <Section title="Highlight topics">
        <p className="mb-3 text-xs text-muted">Colour up to three topics; the rest stay grey. Node size follows PageRank; arrows point to the cited paper.</p>
        <ul className="-mx-2 max-h-[30rem] space-y-0.5 overflow-y-auto scrollbar-thin">
          {sortedTopics.map((t) => {
            const slot = highlight.indexOf(t.id);
            return (
              <li key={t.id}>
                <button onClick={() => toggle(t.id)} aria-pressed={slot >= 0} className={clsx("flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-accent-soft", slot >= 0 && "bg-accent-soft/60")}>
                  <span className="size-2.5 shrink-0 rounded-full border border-line" style={{ background: slot >= 0 ? colors.series[slot] : "transparent" }} />
                  <span className="flex-1 truncate text-ink">{t.label}</span>
                  <span className="tabular text-xs text-muted">{t.size}</span>
                </button>
              </li>
            );
          })}
        </ul>
        {highlighted && (
          <button className="link mt-3 text-xs" onClick={() => setHighlight([null, null, null])}>Clear highlights</button>
        )}
        {!highlighted && <div className="mt-3"><LegendItem color={colors.series[0]} label="Paper" /></div>}
      </Section>
    </div>
  );
}

function CollaborationNetwork() {
  const navigate = useNavigate();
  const [limit, setLimit] = useState(150);
  const network = useQuery({
    queryKey: ["author-network", limit],
    queryFn: () => api<GraphData>(`/graph/authors?limit=${limit}`),
    placeholderData: keepPreviousData,
  });
  const style: GraphStyle = {
    color: (_, c) => c.series[0],
    radius: (node) => 2.5 + Math.min(8, Math.sqrt(node.papers ?? 1) * 1.6),
    alwaysLabel: (node) => (node.papers ?? 0) >= 12,
  };
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 text-xs text-secondary">
        <label className="flex items-center gap-2">
          Authors
          <input type="range" min={30} max={500} step={10} value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="accent-[var(--accent)]" />
          <span className="tabular w-8 text-ink">{limit}</span>
        </label>
        <span className="text-muted">Edges are co-authorships; node size follows the number of papers.</span>
        {network.data && <span className="ml-auto">{network.data.nodes.length} authors · {network.data.links.length} collaborations</span>}
      </div>
      {network.isError ? (
        <div className="p-4"><ErrorState error={network.error} /></div>
      ) : network.data ? (
        <ForceGraph
          data={network.data}
          style={style}
          height="min(70vh, 680px)"
          onNodeClick={(node) => navigate(`/author/${encodeURIComponent(node.label)}`)}
          tooltip={(node: GraphNode) => (
            <>
              <p className="font-medium text-ink">{node.label}</p>
              <p className="mt-0.5 text-muted">{node.papers} papers · cited {node.citations ?? 0}× here · h-index {node.h_index ?? 0}</p>
            </>
          )}
        />
      ) : (
        <div className="flex h-96 items-center justify-center"><Spinner /></div>
      )}
    </div>
  );
}

function DocPicker({ label, value, onChange }: { label: string; value: DocCard | null; onChange: (doc: DocCard | null) => void }) {
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(text), 250);
    return () => window.clearTimeout(timer);
  }, [text]);
  const results = useQuery({
    queryKey: ["doc-picker", debounced],
    queryFn: () => api<SearchResponse>(`/search${qs({ q: debounced, mode: "keyword", size: 6, log: false })}`),
    enabled: debounced.trim().length >= 3 && !value,
  });
  return (
    <div className="relative">
      <span className="label">{label}</span>
      {value ? (
        <div className="flex items-start gap-2 rounded-lg border border-line bg-raised px-3 py-2">
          <span className="flex-1 text-sm text-ink">{value.title} <span className="text-muted">({value.year ?? "n.d."})</span></span>
          <button className="text-xs text-muted hover:text-ink" onClick={() => onChange(null)}>Change</button>
        </div>
      ) : (
        <div className="relative">
          <Search className="absolute left-3 top-2.5 size-4 text-muted" />
          <input className="input pl-9" value={text} onChange={(e) => setText(e.target.value)} placeholder="Search a paper by title…" />
          {results.data && results.data.results.length > 0 && (
            <ul className="absolute inset-x-0 z-20 mt-1 rounded-xl border border-line bg-raised py-1 shadow-card">
              {results.data.results.map((doc) => (
                <li key={doc.id}>
                  <button className="w-full px-3 py-2 text-left text-sm hover:bg-accent-soft" onClick={() => { onChange(doc); setText(""); }}>
                    <span className="line-clamp-1 text-ink">{doc.title}</span>
                    <span className="text-xs text-muted">{doc.year ?? "n.d."} · {doc.authors.slice(0, 2).join(", ")}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function PathFinder() {
  const [source, setSource] = useState<DocCard | null>(null);
  const [target, setTarget] = useState<DocCard | null>(null);
  const path = useQuery({
    queryKey: ["path", source?.id, target?.id],
    queryFn: () => api<{ found: boolean; path: GraphNode[]; steps: string[] }>(`/graph/path${qs({ source: source!.id, target: target!.id })}`),
    enabled: Boolean(source && target),
  });
  return (
    <div className="grid gap-5 lg:grid-cols-[22rem_minmax(0,1fr)]">
      <Section title="How are two papers connected?">
        <div className="space-y-4">
          <DocPicker label="From" value={source} onChange={setSource} />
          <DocPicker label="To" value={target} onChange={setTarget} />
        </div>
        <p className="mt-4 text-xs text-muted">Finds the shortest chain of citations between them (in either direction) with networkx.</p>
      </Section>
      <Section title="Citation path">
        {!source || !target ? (
          <EmptyState title="Pick two papers" icon={<Route className="size-5" />}>Try a classic and a recent paper from the same field.</EmptyState>
        ) : path.isPending ? (
          <Spinner />
        ) : path.isError ? (
          <ErrorState error={path.error} />
        ) : !path.data.found ? (
          <EmptyState title="No connection">These papers sit in different components of the citation graph.</EmptyState>
        ) : (
          <ol>
            {path.data.path.map((node, i) => (
              <li key={node.id}>
                <Link to={`/doc/${node.id}`} className="block rounded-lg border border-line bg-raised px-4 py-3 hover:border-axis">
                  <span className="text-sm font-medium text-ink">{node.label}</span>
                  <span className="block text-xs text-muted">{node.year ?? "n.d."} · cited {node.citations}× here</span>
                </Link>
                {i < path.data.steps.length && (
                  <div className="flex items-center gap-2 py-1.5 pl-5 text-xs text-muted">
                    {path.data.steps[i] === "cites" ? <ArrowDown className="size-3.5" /> : <ArrowUp className="size-3.5" />}
                    {path.data.steps[i] === "cites" ? "cites" : "is cited by"}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </Section>
    </div>
  );
}

export function GraphPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "citations";
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge graph</h1>
        <p className="mt-1 text-sm text-secondary">Papers linked by citations and authors linked by collaboration, built with networkx and replicated to every node.</p>
      </div>
      <Tabs
        value={tab}
        tabs={[{ value: "citations", label: "Citation network" }, { value: "authors", label: "Collaboration network" }, { value: "path", label: "Path finder" }]}
        onChange={(value) => setParams(value === "citations" ? {} : { tab: value })}
      />
      <div className="mt-5">
        {tab === "citations" && <CitationNetwork />}
        {tab === "authors" && <CollaborationNetwork />}
        {tab === "path" && <PathFinder />}
      </div>
    </div>
  );
}
