import { useMemo, useRef, useState } from "react";
import type { Point } from "../lib/api";
import { useChartColors } from "../lib/theme";

export type Slots = (number | null)[]; // up to three topic ids; the index is the colour slot

/** Documents in concept space. At most three topics are coloured; the rest stay grey for context. */
export function TopicScatter({ points, slots, labels, onSelect, height = 460 }: {
  points: Point[];
  slots: Slots;
  labels: Map<number, string>;
  onSelect?: (point: Point) => void;
  height?: number;
}) {
  const colors = useChartColors();
  const svg = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const width = 760;
  const pad = 14;

  const { scaled, slotOf } = useMemo(() => {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
    const sx = (v: number) => pad + ((v - x0) / (x1 - x0 || 1)) * (width - 2 * pad);
    const sy = (v: number) => height - pad - ((v - y0) / (y1 - y0 || 1)) * (height - 2 * pad);
    const slotOf = new Map<number, number>();
    slots.forEach((topic, slot) => topic !== null && slotOf.set(topic, slot));
    return { scaled: points.map((p) => ({ x: sx(p.x), y: sy(p.y), p })), slotOf };
  }, [points, slots, height]);

  const order = useMemo(() => {
    // Context first, highlighted topics on top.
    return scaled.map((_, i) => i).sort((a, b) => Number(slotOf.has(scaled[a].p.cluster ?? -1)) - Number(slotOf.has(scaled[b].p.cluster ?? -1)));
  }, [scaled, slotOf]);

  const nearest = (clientX: number, clientY: number) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return null;
    const x = ((clientX - box.left) / box.width) * width;
    const y = ((clientY - box.top) / box.height) * height;
    let best = -1;
    let bestDistance = 18 * 18 * (width / box.width) ** 2;
    scaled.forEach((point, i) => {
      const d = (point.x - x) ** 2 + (point.y - y) ** 2;
      if (d < bestDistance) {
        bestDistance = d;
        best = i;
      }
    });
    return best >= 0 ? best : null;
  };

  const hovered = hover !== null ? scaled[hover] : null;
  return (
    <div className="relative">
      <svg
        ref={svg}
        viewBox={`0 0 ${width} ${height}`}
        className="w-full cursor-crosshair"
        role="img"
        aria-label="Documents positioned by their LSA concept vectors"
        onMouseMove={(event) => setHover(nearest(event.clientX, event.clientY))}
        onMouseLeave={() => setHover(null)}
        onClick={() => hovered && onSelect?.(hovered.p)}
      >
        <rect x={0.5} y={0.5} width={width - 1} height={height - 1} fill="none" stroke={colors.hairline} />
        {order.map((i) => {
          const { x, y, p } = scaled[i];
          const slot = slotOf.get(p.cluster ?? -1);
          return slot === undefined ? (
            <circle key={p.id} cx={x} cy={y} r={2.4} fill={colors.context} />
          ) : (
            <circle key={p.id} cx={x} cy={y} r={4} fill={colors.series[slot]} stroke={colors.surface} strokeWidth={1.5} />
          );
        })}
        {hovered && <circle cx={hovered.x} cy={hovered.y} r={7} fill="none" stroke={colors.ink} strokeWidth={1.5} />}
      </svg>
      {hovered && (
        <div
          className="pointer-events-none absolute z-10 max-w-xs rounded-lg border border-line bg-raised px-3 py-2 text-xs shadow-card"
          style={{ left: `${Math.min(70, (hovered.x / width) * 100)}%`, top: `${Math.min(80, (hovered.y / height) * 100)}%`, transform: "translate(12px, 12px)" }}
        >
          <p className="font-medium text-ink">{hovered.p.title}</p>
          <p className="mt-0.5 text-muted">
            {hovered.p.year ?? "n.d."} · {labels.get(hovered.p.cluster ?? -1) ?? "unassigned"} · {hovered.p.node}
          </p>
        </div>
      )}
    </div>
  );
}
