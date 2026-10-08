import { useMemo, useState } from "react";
import type { EvolutionData } from "../lib/api";
import { useChartColors } from "../lib/theme";

/** Temporal concept graph: eras left to right, topics as nodes, continuity as curved links. */
export function EvolutionFlow({ data }: { data: EvolutionData }) {
  const colors = useChartColors();
  const [focus, setFocus] = useState<string | null>(null);

  const layout = useMemo(() => {
    const columns = Math.max(1, data.eras.length);
    const width = Math.max(760, columns * 170);
    const byEra = new Map<number, EvolutionData["nodes"]>();
    data.nodes.forEach((node) => byEra.set(node.era, [...(byEra.get(node.era) ?? []), node]));
    const rows = Math.max(1, ...[...byEra.values()].map((nodes) => nodes.length));
    const rowH = 74;
    const height = rows * rowH + 46;
    const maxSize = Math.max(1, ...data.nodes.map((n) => n.size));
    const pos = new Map<string, { x: number; y: number; r: number }>();
    byEra.forEach((nodes, era) => {
      [...nodes]
        .sort((a, b) => b.size - a.size)
        .forEach((node, i) => {
          const x = 80 + (era / Math.max(1, columns - 1)) * (width - 160);
          const offset = ((rows - nodes.length) * rowH) / 2;
          pos.set(node.id, { x, y: 46 + offset + i * rowH + 16, r: 4 + 11 * Math.sqrt(node.size / maxSize) });
        });
    });
    return { width, height, pos };
  }, [data]);

  const lineage = useMemo(() => {
    if (!focus) return null;
    const keep = new Set([focus]);
    const walk = (id: string, forward: boolean) => {
      data.links.forEach((link) => {
        const [from, to] = forward ? [link.source, link.target] : [link.target, link.source];
        if (from === id && !keep.has(to)) {
          keep.add(to);
          walk(to, forward);
        }
      });
    };
    walk(focus, true);
    walk(focus, false);
    return keep;
  }, [focus, data.links]);

  const events = new Map<string, string[]>();
  data.events.filter((e) => e.type === "split" || e.type === "merge").forEach((e) => events.set(e.node, [...(events.get(e.node) ?? []), e.type]));
  const { width, height, pos } = layout;
  const dim = (id: string) => (lineage && !lineage.has(id) ? 0.18 : 1);

  return (
    <div className="overflow-x-auto scrollbar-thin">
      <svg viewBox={`0 0 ${width} ${height}`} style={{ minWidth: Math.min(width, 900) }} className="w-full" role="img" aria-label="How topics continued, split and merged across eras">
        {data.eras.map((era) => {
          const x = 80 + (era.index / Math.max(1, data.eras.length - 1)) * (width - 160);
          return (
            <text key={era.index} x={x} y={18} fontSize={12} fontWeight={600} fill={colors.secondary} textAnchor="middle">
              {era.label}
            </text>
          );
        })}
        {data.links.map((link) => {
          const a = pos.get(link.source);
          const b = pos.get(link.target);
          if (!a || !b) return null;
          const mid = (a.x + b.x) / 2;
          const visible = !lineage || (lineage.has(link.source) && lineage.has(link.target));
          return (
            <path
              key={`${link.source}-${link.target}`}
              d={`M${a.x},${a.y} C${mid},${a.y} ${mid},${b.y} ${b.x},${b.y}`}
              fill="none"
              stroke={visible && lineage ? colors.series[0] : colors.axis}
              strokeWidth={1 + Math.max(0, link.weight - 0.5) * 6}
              strokeLinecap="round"
              opacity={visible ? (link.weak ? 0.45 : 0.9) : 0.12}
            />
          );
        })}
        {data.nodes.map((node) => {
          const p = pos.get(node.id);
          if (!p) return null;
          const tags = events.get(node.id);
          return (
            <g key={node.id} opacity={dim(node.id)} onMouseEnter={() => setFocus(node.id)} onMouseLeave={() => setFocus(null)} className="cursor-pointer">
              <circle cx={p.x} cy={p.y} r={p.r + 8} fill="transparent" />
              <circle cx={p.x} cy={p.y} r={p.r} fill={colors.series[0]} stroke={colors.surface} strokeWidth={2} />
              <text x={p.x} y={p.y + p.r + 13} fontSize={11} fill={colors.ink} textAnchor="middle">
                {node.label.length > 24 ? `${node.label.slice(0, 23)}…` : node.label}
              </text>
              <text x={p.x} y={p.y + p.r + 26} fontSize={10} fill={colors.muted} textAnchor="middle">
                {node.size} docs{tags ? ` · ${tags.join(" + ")}` : ""}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
