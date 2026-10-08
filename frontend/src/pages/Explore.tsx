import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { BurstChart } from "../charts/BurstChart";
import { EvolutionFlow } from "../charts/EvolutionFlow";
import { TopicScatter, type Slots } from "../charts/TopicScatter";
import { TopicTimeline } from "../charts/TopicTimeline";
import { EmptyState, ErrorState, PageLoader, Section, Segmented, Tabs } from "../components/ui";
import { api, type Burst, type EvolutionData, type GraphNode, type Point, type Topic } from "../lib/api";
import { formatNumber } from "../lib/format";
import { useChartColors, useTheme } from "../lib/theme";

type Tab = "topics" | "timeline" | "bursts" | "evolution" | "influence" | "figures";

function TopicsTab() {
  const colors = useChartColors();
  const navigate = useNavigate();
  const topics = useQuery({ queryKey: ["topics"], queryFn: () => api<{ topics: Topic[] }>("/analytics/topics") });
  const points = useQuery({ queryKey: ["points"], queryFn: () => api<{ points: Point[] }>("/analytics/points?limit=3000") });
  const [slots, setSlots] = useState<Slots | null>(null);
  const [notice, setNotice] = useState("");

  const sorted = useMemo(() => [...(topics.data?.topics ?? [])].sort((a, b) => b.size - a.size), [topics.data]);
  const active: Slots = slots ?? [sorted[0]?.id ?? null, sorted[1]?.id ?? null, sorted[2]?.id ?? null];
  const labels = useMemo(() => new Map(sorted.map((t) => [t.id, t.label])), [sorted]);

  if (topics.isError) return <ErrorState error={topics.error} />;
  if (!topics.data || !points.data) return <PageLoader label="Projecting documents into concept space…" />;
  if (!sorted.length) return <EmptyState title="No topics yet">Topics are found when the model is built.</EmptyState>;

  const toggle = (id: number) => {
    const index = active.indexOf(id);
    if (index >= 0) {
      setSlots(active.map((t, i) => (i === index ? null : t)));
      setNotice("");
      return;
    }
    const free = active.indexOf(null);
    if (free < 0) {
      setNotice("Up to three topics can be highlighted at once; clear one first.");
      return;
    }
    setSlots(active.map((t, i) => (i === free ? id : t)));
    setNotice("");
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Section title="Topic map" action={<span className="text-xs text-muted">{formatNumber(points.data.points.length)} documents · PCA of LSA vectors</span>}>
        <TopicScatter points={points.data.points} slots={active} labels={labels} onSelect={(p) => navigate(`/doc/${p.id}`)} />
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-secondary">
          {active.map((id, slot) =>
            id === null ? null : (
              <span key={slot} className="inline-flex items-center gap-1.5">
                <span className="size-2.5 rounded-full" style={{ background: colors.series[slot] }} /> {labels.get(id)}
              </span>
            ),
          )}
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: colors.context }} /> other topics
          </span>
        </div>
        <p className="mt-2 text-xs text-muted">
          Each dot is a paper placed by its concept vector (k-means topics found with scipy). Nearby papers share vocabulary patterns even
          when they use different words. Hover to inspect, click to open.
        </p>
      </Section>
      <Section title={`Topics (${sorted.length})`}>
        {notice && <p className="mb-2 text-xs text-critical">{notice}</p>}
        <ul className="-mx-2 max-h-[34rem] space-y-0.5 overflow-y-auto pr-1 scrollbar-thin">
          {sorted.map((topic) => {
            const slot = active.indexOf(topic.id);
            return (
              <li key={topic.id}>
                <button onClick={() => toggle(topic.id)} className={clsx("w-full rounded-lg px-2 py-2 text-left hover:bg-accent-soft", slot >= 0 && "bg-accent-soft/60")} aria-pressed={slot >= 0}>
                  <div className="flex items-center gap-2">
                    <span className="size-2.5 shrink-0 rounded-full border border-line" style={{ background: slot >= 0 ? colors.series[slot] : "transparent" }} aria-hidden />
                    <span className="flex-1 truncate text-sm font-medium text-ink">{topic.label}</span>
                    <span className="tabular text-xs text-muted">{topic.size}</span>
                  </div>
                  <p className="ml-[1.125rem] mt-0.5 truncate text-xs text-muted">{topic.terms.slice(0, 5).join(" · ")}</p>
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-xs text-muted">Select up to three topics to colour them on the map.</p>
      </Section>
      <Section title="Representative papers per topic" className="xl:col-span-2">
        <div className="grid gap-x-6 gap-y-5 md:grid-cols-2 xl:grid-cols-3">
          {sorted.map((topic) => (
            <div key={topic.id}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <Link to={`/search?q=${encodeURIComponent(topic.label)}&mode=semantic&topic=${topic.id}`} className="truncate text-sm font-semibold text-ink hover:text-accent">
                  {topic.label}
                </Link>
                <span className="tabular shrink-0 text-xs text-muted" title="Recent share relative to overall share">×{topic.growth.toFixed(2)}</span>
              </div>
              <ul className="space-y-1">
                {topic.top_papers.slice(0, 3).map((paper) => (
                  <li key={paper.id} className="truncate text-xs">
                    <Link to={`/doc/${paper.id}`} className="text-secondary hover:text-accent">{paper.title}</Link>
                    <span className="text-muted"> · {paper.year ?? "n.d."}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function TimelineTab() {
  const timeline = useQuery({
    queryKey: ["timeline"],
    queryFn: () => api<{ timeline: { years: number[]; counts: number[][]; totals: number[] }; topics: { id: number; label: string; size: number }[] }>("/analytics/timeline"),
  });
  if (timeline.isError) return <ErrorState error={timeline.error} />;
  if (!timeline.data) return <PageLoader />;
  const { timeline: t, topics } = timeline.data;
  return (
    <Section title="Topics over time" action={<span className="text-xs text-muted">documents per year, one panel per topic, shared scale</span>}>
      <TopicTimeline years={t.years} counts={t.counts} topics={topics} />
    </Section>
  );
}

function BurstsTab() {
  const navigate = useNavigate();
  const [kind, setKind] = useState<"terms" | "topics">("terms");
  const bursts = useQuery({ queryKey: ["bursts"], queryFn: () => api<{ terms: Burst[]; topics: Burst[] }>("/analytics/bursts") });
  if (bursts.isError) return <ErrorState error={bursts.error} />;
  if (!bursts.data) return <PageLoader />;
  const shown = bursts.data[kind].slice(0, 25);
  return (
    <Section
      title="Bursts of innovation"
      action={<Segmented size="sm" value={kind} onChange={setKind} options={[{ value: "terms", label: `Terms (${bursts.data.terms.length})` }, { value: "topics", label: `Topics (${bursts.data.topics.length})` }]} />}
    >
      <p className="mb-4 max-w-3xl text-sm text-secondary">
        A burst is a stretch of years in which a {kind === "terms" ? "word" : "topic"} appears far more often than its long-run rate. It is
        detected with Kleinberg's two-state automaton: entering the burst state costs γ·ln(n), and the cheapest state sequence is found
        with dynamic programming. The number at the end of each bar is the burst's strength; click a bar to search.
      </p>
      <BurstChart bursts={shown} onSelect={(b) => navigate(`/search?q=${encodeURIComponent(b.label)}&year_from=${b.start}&year_to=${b.end}`)} />
    </Section>
  );
}

function EvolutionTab() {
  const evolution = useQuery({ queryKey: ["evolution"], queryFn: () => api<EvolutionData>("/analytics/evolution") });
  if (evolution.isError) return <ErrorState error={evolution.error} />;
  if (!evolution.data) return <PageLoader />;
  const data = evolution.data;
  if (!data.nodes.length) return <EmptyState title="Not enough dated documents to trace topics over time" />;
  const notable = data.events.filter((e) => e.type === "split" || e.type === "merge");
  return (
    <div className="space-y-5">
      <Section title="Temporal concept graph" action={<span className="text-xs text-muted">hover a topic to trace its lineage</span>}>
        <p className="mb-4 max-w-3xl text-sm text-secondary">
          The corpus is cut into eras with similar numbers of papers, each era is clustered on its own, and topics in consecutive eras are
          linked (networkx) when their concept centroids are similar. A topic with two strong successors <em>split</em>; one with two strong
          predecessors is a <em>merger</em> of earlier lines of research.
        </p>
        <EvolutionFlow data={data} />
      </Section>
      <Section title={`Splits and merges (${notable.length})`}>
        {notable.length === 0 ? (
          <p className="text-sm text-muted">No splits or merges at the current similarity threshold.</p>
        ) : (
          <ul className="divide-y divide-line">
            {notable.map((event, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-2 py-2 text-sm">
                <span className="w-24 shrink-0 text-xs text-muted">{event.era}</span>
                <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold uppercase text-accent-strong">{event.type}</span>
                <span className="text-ink">
                  {event.type === "split" ? (
                    <><strong>{event.label}</strong> → {event.into?.join(", ")}</>
                  ) : (
                    <>{event.from?.join(" + ")} → <strong>{event.label}</strong></>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function InfluenceTab() {
  const influence = useQuery({
    queryKey: ["influence"],
    queryFn: () => api<{ papers: (GraphNode & { authors: string[] })[]; authors: { name: string; papers: number; citations: number; h_index: number; coauthors: number }[] }>("/analytics/influence"),
  });
  if (influence.isError) return <ErrorState error={influence.error} />;
  if (!influence.data) return <PageLoader />;
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Section title="Most influential papers" action={<span className="text-xs text-muted">PageRank on the citation graph</span>}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="pb-2 font-medium">#</th>
              <th className="pb-2 font-medium">Paper</th>
              <th className="pb-2 text-right font-medium">Cited here</th>
              <th className="pb-2 text-right font-medium">PageRank</th>
            </tr>
          </thead>
          <tbody>
            {influence.data.papers.map((paper, i) => (
              <tr key={paper.id} className="border-t border-line align-top">
                <td className="tabular py-2 pr-2 text-xs text-muted">{i + 1}</td>
                <td className="py-2 pr-3">
                  <Link to={`/doc/${paper.id}`} className="text-ink hover:text-accent">{paper.label}</Link>
                  <p className="text-xs text-muted">{paper.authors.slice(0, 3).join(", ")} · {paper.year ?? "n.d."}</p>
                </td>
                <td className="tabular py-2 text-right text-secondary">{paper.citations}</td>
                <td className="tabular py-2 text-right text-secondary">{((paper.pagerank ?? 0) * 1000).toFixed(2)}‰</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Most cited authors" action={<span className="text-xs text-muted">within this corpus</span>}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="pb-2 font-medium">Author</th>
              <th className="pb-2 text-right font-medium">Papers</th>
              <th className="pb-2 text-right font-medium">Cited</th>
              <th className="pb-2 text-right font-medium" title="h-index computed on in-corpus citations">h</th>
            </tr>
          </thead>
          <tbody>
            {influence.data.authors.map((author) => (
              <tr key={author.name} className="border-t border-line">
                <td className="py-2 pr-2">
                  <Link to={`/author/${encodeURIComponent(author.name)}`} className="text-ink hover:text-accent">{author.name}</Link>
                </td>
                <td className="tabular py-2 text-right text-secondary">{author.papers}</td>
                <td className="tabular py-2 text-right text-secondary">{author.citations}</td>
                <td className="tabular py-2 text-right text-secondary">{author.h_index}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

const FIGURES: { name: string; title: string; description: string; params?: string }[] = [
  { name: "topic_map", title: "Topic map (2-D)", description: "Documents in concept space, three largest topics highlighted." },
  { name: "topic_map", title: "Topic map (3-D)", description: "First three principal axes of the LSA vectors.", params: "dims=3" },
  { name: "topic_facets", title: "Where each topic lives", description: "Small multiples: one panel per topic." },
  { name: "topic_timeline", title: "Topics over time", description: "Documents per year per topic." },
  { name: "bursts", title: "Bursts of activity", description: "Strongest Kleinberg bursts." },
  { name: "evolution", title: "Temporal concept graph", description: "Topic continuity across eras." },
  { name: "citation_graph", title: "Citation network", description: "Top papers by PageRank (networkx layout)." },
  { name: "pagerank", title: "PageRank ranking", description: "The most influential papers." },
  { name: "degree_distribution", title: "Degree distribution", description: "Heavy tail of in-corpus citations." },
];

function FiguresTab() {
  const { resolved } = useTheme();
  return (
    <div>
      <p className="mb-4 max-w-3xl text-sm text-secondary">
        These figures are rendered on the server with Matplotlib (object-oriented API, Agg backend) from the same analytics the interactive views use.
        They follow the current theme and can be downloaded as PNG or SVG for reports.
      </p>
      <div className="grid gap-5 lg:grid-cols-2">
        {FIGURES.map((figure) => {
          const query = `theme=${resolved}${figure.params ? `&${figure.params}` : ""}`;
          return (
            <figure key={figure.title} className="card overflow-hidden">
              <img src={`/api/viz/${figure.name}.png?${query}`} alt={figure.title} loading="lazy" className="w-full bg-surface" />
              <figcaption className="flex items-start justify-between gap-3 border-t border-line px-4 py-3">
                <div>
                  <p className="text-sm font-medium">{figure.title}</p>
                  <p className="text-xs text-muted">{figure.description}</p>
                </div>
                <div className="flex shrink-0 gap-2 text-xs">
                  <a className="link inline-flex items-center gap-1" href={`/api/viz/${figure.name}.png?${query}`} target="_blank" rel="noreferrer">PNG <ExternalLink className="size-3" /></a>
                  <a className="link inline-flex items-center gap-1" href={`/api/viz/${figure.name}.svg?${query}`} target="_blank" rel="noreferrer">SVG <ExternalLink className="size-3" /></a>
                </div>
              </figcaption>
            </figure>
          );
        })}
      </div>
    </div>
  );
}

const TABS: { value: Tab; label: string }[] = [
  { value: "topics", label: "Topics" },
  { value: "timeline", label: "Timeline" },
  { value: "bursts", label: "Bursts" },
  { value: "evolution", label: "Evolution" },
  { value: "influence", label: "Influence" },
  { value: "figures", label: "Figures (Matplotlib)" },
];

export function ExplorePage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "topics";
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight">Explore the corpus</h1>
        <p className="mt-1 text-sm text-secondary">Topics found by k-means on LSA vectors, how they grow and burst over time, and who is most influential.</p>
      </div>
      <Tabs value={tab} tabs={TABS} onChange={(value) => setParams(value === "topics" ? {} : { tab: value })} />
      <div className="mt-5">
        {tab === "topics" && <TopicsTab />}
        {tab === "timeline" && <TimelineTab />}
        {tab === "bursts" && <BurstsTab />}
        {tab === "evolution" && <EvolutionTab />}
        {tab === "influence" && <InfluenceTab />}
        {tab === "figures" && <FiguresTab />}
      </div>
    </div>
  );
}
