import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useNavigate, useParams } from "react-router";
import { YearHistogram } from "../charts/YearHistogram";
import { ForceGraph, LegendItem, type GraphStyle } from "../components/ForceGraph";
import { ResultCard } from "../components/ResultCard";
import { Badge, ErrorState, PageLoader, Section, StatTile } from "../components/ui";
import { api, type AuthorProfile } from "../lib/api";
import { formatNumber, initials } from "../lib/format";
import { useChartColors } from "../lib/theme";

const coauthorStyle: GraphStyle = {
  color: (node, c) => (node.role === "focus" ? c.ink : c.series[1]),
  radius: (node) => (node.role === "focus" ? 7 : 3 + Math.min(6, Math.sqrt(node.papers ?? 1) * 1.5)),
  shape: () => "square",
  alwaysLabel: () => true,
};

export function AuthorPage() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const colors = useChartColors();
  const author = useQuery({ queryKey: ["author", name], queryFn: () => api<AuthorProfile>(`/authors/${encodeURIComponent(name)}`), retry: false });

  if (author.isPending) return <PageLoader />;
  if (author.isError)
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <ErrorState error={author.error} />
      </div>
    );
  const a = author.data;
  const m = a.metrics;
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <button className="btn-ghost -ml-2 mb-3 px-2 py-1 text-xs" onClick={() => navigate(-1)}>
        <ArrowLeft className="size-3.5" /> Back
      </button>
      <header className="mb-6 flex items-center gap-4">
        <span className="grid size-14 place-items-center rounded-2xl bg-series-2 text-lg font-semibold text-white">{initials(a.name)}</span>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{a.name}</h1>
          <p className="text-sm text-secondary">
            {m.first_year && m.last_year ? `Active ${m.first_year}–${m.last_year} in this corpus` : "Author"}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {a.topics.slice(0, 5).map((t) => (
              <Badge key={t.label}>{t.label} · {t.count}</Badge>
            ))}
          </div>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="Papers here" value={formatNumber(m.papers ?? a.papers.length)} />
        <StatTile label="Cited in corpus" value={formatNumber(m.citations ?? 0)} />
        <StatTile label="h-index (corpus)" value={m.h_index ?? 0} hint="h papers cited at least h times" />
        <StatTile label="Co-authors" value={formatNumber(m.coauthors ?? 0)} />
        <StatTile label="Collaboration rank" value={m.pagerank ? (m.pagerank * 1000).toFixed(2) + "‰" : "–"} hint="PageRank on the co-author graph" />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Section title={`Papers (${a.papers.length})`}>
          <div className="space-y-2">
            {a.papers.map((paper) => (
              <ResultCard key={paper.id} doc={paper} compact showScores={false} />
            ))}
          </div>
        </Section>
        <div className="space-y-5">
          <Section title="Collaboration network">
            {a.network.nodes.length > 1 ? (
              <>
                <div className="rounded-lg border border-line">
                  <ForceGraph
                    data={a.network}
                    style={coauthorStyle}
                    height={360}
                    onNodeClick={(node) => node.role !== "focus" && navigate(`/author/${encodeURIComponent(node.label)}`)}
                    tooltip={(node) => <p className="text-ink">{node.label} · {node.papers} papers</p>}
                  />
                </div>
                <div className="mt-2 flex gap-4">
                  <LegendItem color={colors.ink} shape="square" label={a.name} />
                  <LegendItem color={colors.series[1]} shape="square" label="Co-authors" />
                </div>
              </>
            ) : (
              <p className="text-sm text-muted">No co-authors in the corpus.</p>
            )}
          </Section>
          <Section title="Frequent co-authors">
            <ul className="divide-y divide-line">
              {a.coauthors.slice(0, 12).map((c) => (
                <li key={c.name} className="flex items-center justify-between py-1.5 text-sm">
                  <button className="text-left text-ink hover:text-accent" onClick={() => navigate(`/author/${encodeURIComponent(c.name)}`)}>{c.name}</button>
                  <span className="tabular text-xs text-muted">{c.weight} joint · {c.papers} papers</span>
                </li>
              ))}
            </ul>
          </Section>
          <Section title="Papers per year">
            <YearHistogram data={a.years} />
          </Section>
        </div>
      </div>
    </div>
  );
}
