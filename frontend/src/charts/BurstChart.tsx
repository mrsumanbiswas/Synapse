import { useState } from "react";
import type { Burst } from "../lib/api";
import { useChartColors } from "../lib/theme";

/** Kleinberg burst intervals as bars on one shared year axis. */
export function BurstChart({ bursts, onSelect }: { bursts: Burst[]; onSelect?: (burst: Burst) => void }) {
  const colors = useChartColors();
  const [hover, setHover] = useState<number | null>(null);
  if (!bursts.length) return <p className="text-sm text-muted">No bursts detected.</p>;
  const lo = Math.min(...bursts.map((b) => b.start)) - 1;
  const hi = Math.max(...bursts.map((b) => b.end)) + 1;
  const labelW = 150;
  const valueW = 44;
  const w = 760;
  const row = 26;
  const bar = 14;
  const axis = 22;
  const h = bursts.length * row + axis;
  const x = (year: number) => labelW + ((year - lo) / (hi - lo)) * (w - labelW - valueW);
  const ticks: number[] = [];
  const step = hi - lo > 40 ? 10 : 5;
  for (let year = Math.ceil(lo / step) * step; year <= hi; year += step) ticks.push(year);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label="Burst intervals">
      {ticks.map((year) => (
        <g key={year}>
          <line x1={x(year)} x2={x(year)} y1={0} y2={h - axis} stroke={colors.hairline} />
          <text x={x(year)} y={h - 6} fontSize={10} fill={colors.muted} textAnchor="middle">{year}</text>
        </g>
      ))}
      {bursts.map((burst, i) => {
        const y = i * row + (row - bar) / 2;
        const x0 = x(burst.start - 0.45);
        const x1 = x(burst.end + 0.45);
        return (
          <g
            key={`${burst.kind}-${burst.label}-${burst.start}`}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            onClick={() => onSelect?.(burst)}
            className={onSelect ? "cursor-pointer" : undefined}
          >
            <rect x={0} y={i * row} width={w} height={row} fill={hover === i ? colors.hairline : "transparent"} opacity={0.5} />
            <text x={labelW - 10} y={y + bar / 2 + 4} fontSize={12} fill={colors.ink} textAnchor="end">
              {burst.label.length > 22 ? `${burst.label.slice(0, 21)}…` : burst.label}
            </text>
            <rect x={x0} y={y} width={Math.max(4, x1 - x0)} height={bar} rx={4} fill={colors.series[0]} />
            <text x={x1 + 6} y={y + bar / 2 + 4} fontSize={10} fill={colors.muted}>
              {hover === i ? `${burst.start}–${burst.end} · ${burst.documents} docs` : burst.weight.toFixed(0)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
