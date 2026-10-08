import { useState } from "react";
import { useChartColors } from "../lib/theme";

/** Small multiples: one panel per topic, documents per year on a shared scale. */
export function TopicTimeline({ years, counts, topics }: {
  years: number[];
  counts: number[][];
  topics: { id: number; label: string; size: number }[];
}) {
  const colors = useChartColors();
  const [hover, setHover] = useState<{ topic: number; index: number } | null>(null);
  if (!years.length) return <p className="text-sm text-muted">No dated documents yet.</p>;
  const max = Math.max(1, ...counts.flat());
  const w = 240;
  const h = 92;
  const top = 8;
  const bottom = 16;
  const x = (i: number) => (i / Math.max(1, years.length - 1)) * w;
  const y = (v: number) => top + (1 - v / max) * (h - top - bottom);
  const ordered = [...topics].sort((a, b) => b.size - a.size);

  return (
    <div className="grid gap-x-5 gap-y-6 sm:grid-cols-2 xl:grid-cols-4">
      {ordered.map((topic) => {
        const series = counts[topic.id] ?? [];
        const line = series.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
        const area = `${line}L${w},${h - bottom}L0,${h - bottom}Z`;
        const peak = series.indexOf(Math.max(...series));
        const active = hover?.topic === topic.id ? hover.index : null;
        return (
          <figure key={topic.id} className="min-w-0">
            <figcaption className="mb-1 flex items-baseline justify-between gap-2">
              <span className="truncate text-sm font-medium text-ink" title={topic.label}>{topic.label}</span>
              <span className="tabular shrink-0 text-xs text-muted">{topic.size}</span>
            </figcaption>
            <svg
              viewBox={`0 0 ${w} ${h}`}
              className="w-full overflow-visible"
              role="img"
              aria-label={`${topic.label}: documents per year`}
              onMouseMove={(event) => {
                const box = event.currentTarget.getBoundingClientRect();
                const index = Math.round(((event.clientX - box.left) / box.width) * (years.length - 1));
                setHover({ topic: topic.id, index: Math.max(0, Math.min(years.length - 1, index)) });
              }}
              onMouseLeave={() => setHover(null)}
            >
              <line x1={0} x2={w} y1={h - bottom + 0.5} y2={h - bottom + 0.5} stroke={colors.axis} />
              <path d={area} fill={colors.series[0]} opacity={0.1} />
              <path d={line} fill="none" stroke={colors.series[0]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              {active !== null ? (
                <>
                  <line x1={x(active)} x2={x(active)} y1={top} y2={h - bottom} stroke={colors.axis} />
                  <circle cx={x(active)} cy={y(series[active] ?? 0)} r={4} fill={colors.series[0]} stroke={colors.surface} strokeWidth={2} />
                </>
              ) : (
                peak >= 0 && <circle cx={x(peak)} cy={y(series[peak] ?? 0)} r={4} fill={colors.series[0]} stroke={colors.surface} strokeWidth={2} />
              )}
              <text x={0} y={h - 2} fontSize={10} fill={colors.muted}>{years[0]}</text>
              <text x={w} y={h - 2} fontSize={10} fill={colors.muted} textAnchor="end">{years[years.length - 1]}</text>
            </svg>
            <p className="tabular h-4 text-xs text-secondary">
              {active !== null ? (
                <><strong className="text-ink">{series[active] ?? 0}</strong> in {years[active]}</>
              ) : (
                peak >= 0 && <>peak <strong className="text-ink">{series[peak]}</strong> in {years[peak]}</>
              )}
            </p>
          </figure>
        );
      })}
    </div>
  );
}
