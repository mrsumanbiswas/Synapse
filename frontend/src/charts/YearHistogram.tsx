import { useMemo, useState } from "react";
import { useChartColors } from "../lib/theme";

/** Documents per year as columns; click a column (or two) to filter a year range. */
export function YearHistogram({ data, from, to, onSelect, height = 84 }: {
  data: [number, number][];
  from?: number | null;
  to?: number | null;
  onSelect?: (from: number | null, to: number | null) => void;
  height?: number;
}) {
  const colors = useChartColors();
  const [hover, setHover] = useState<number | null>(null);
  const [anchor, setAnchor] = useState<number | null>(null);

  const series = useMemo(() => {
    if (!data.length) return [];
    const counts = new Map(data);
    const first = data[0][0];
    const last = data[data.length - 1][0];
    return Array.from({ length: last - first + 1 }, (_, i) => [first + i, counts.get(first + i) ?? 0] as [number, number]);
  }, [data]);

  if (!series.length) return <p className="text-xs text-muted">No dated documents.</p>;
  const max = Math.max(...series.map(([, c]) => c));
  const width = 260;
  const slot = width / series.length;
  const bar = Math.max(1, Math.min(24, slot - 2));
  const plot = height - 18;
  const selected = (year: number) => (from == null || year >= from) && (to == null || year <= to);

  const click = (year: number) => {
    if (!onSelect) return;
    if (anchor === null) {
      setAnchor(year);
      onSelect(year, year);
    } else {
      onSelect(Math.min(anchor, year), Math.max(anchor, year));
      setAnchor(null);
    }
  };

  const hovered = hover !== null ? series[hover] : null;
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Documents per year">
        <line x1={0} x2={width} y1={plot + 0.5} y2={plot + 0.5} stroke={colors.axis} strokeWidth={1} />
        {series.map(([year, count], i) => {
          const h = max ? Math.max(count ? 2 : 0, (count / max) * (plot - 4)) : 0;
          const x = i * slot + (slot - bar) / 2;
          const r = Math.min(4, bar / 2, h);
          return (
            <g key={year} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onClick={() => click(year)} className="cursor-pointer">
              <rect x={i * slot} y={0} width={slot} height={plot} fill="transparent" />
              {h > 0 && (
                <path
                  d={`M${x},${plot} v${-(h - r)} q0,${-r} ${r},${-r} h${bar - 2 * r} q${r},0 ${r},${r} v${h - r} z`}
                  fill={selected(year) ? colors.series[0] : colors.context}
                  opacity={hover === i ? 0.8 : 1}
                />
              )}
            </g>
          );
        })}
        <text x={0} y={height - 2} fontSize={10} fill={colors.muted}>{series[0][0]}</text>
        <text x={width} y={height - 2} fontSize={10} fill={colors.muted} textAnchor="end">{series[series.length - 1][0]}</text>
      </svg>
      <p className="tabular mt-1 h-4 text-xs text-secondary">
        {hovered ? <><strong className="text-ink">{hovered[1]}</strong> in {hovered[0]}</> : anchor !== null ? "Click another year to set a range" : ""}
      </p>
    </div>
  );
}
