import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-2d";
import type { GraphData, GraphLink, GraphNode } from "../lib/api";
import { useChartColors, type ChartColors } from "../lib/theme";

type Node = NodeObject<GraphNode>;
type Link = LinkObject<GraphNode, GraphLink>;

export interface GraphStyle {
  color: (node: GraphNode, colors: ChartColors) => string;
  radius: (node: GraphNode) => number;
  shape?: (node: GraphNode) => "circle" | "square";
  linkColor?: (link: GraphLink, colors: ChartColors) => string;
  linkDash?: (link: GraphLink) => number[] | null;
  arrows?: boolean;
  alwaysLabel?: (node: GraphNode) => boolean;
}

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 600, height: 400 });
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width: Math.max(200, Math.floor(width)), height: Math.max(200, Math.floor(height)) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

export function ForceGraph({ data, style, onNodeClick, tooltip, height = 480, className }: {
  data: GraphData;
  style: GraphStyle;
  onNodeClick?: (node: GraphNode) => void;
  tooltip?: (node: GraphNode) => ReactNode;
  height?: number | string;
  className?: string;
}) {
  const colors = useChartColors();
  const [container, size] = useSize<HTMLDivElement>();
  const graph = useRef<ForceGraphMethods<Node, Link> | undefined>(undefined);
  const [hover, setHover] = useState<GraphNode | null>(null);
  const [pointer, setPointer] = useState({ x: 0, y: 0 });
  const fitted = useRef(false);

  // The library mutates nodes (x, y, vx...), so give it its own copy whenever the data changes.
  const graphData = useMemo(() => {
    fitted.current = false;
    return { nodes: data.nodes.map((n) => ({ ...n })), links: data.links.map((l) => ({ ...l })) };
  }, [data]);

  useEffect(() => {
    const engine = graph.current;
    if (!engine) return;
    engine.d3Force("charge")?.strength(-70);
    engine.d3Force("link")?.distance(48);
  }, [graphData]);

  const paint = useCallback(
    (node: Node, ctx: CanvasRenderingContext2D, scale: number) => {
      const r = style.radius(node);
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const shape = style.shape?.(node) ?? "circle";
      ctx.beginPath();
      if (shape === "square") {
        const s = r * 1.7;
        ctx.roundRect(x - s / 2, y - s / 2, s, s, Math.min(3, s / 4));
      } else {
        ctx.arc(x, y, r, 0, 2 * Math.PI);
      }
      ctx.fillStyle = style.color(node, colors);
      ctx.fill();
      ctx.lineWidth = Math.max(1, 2 / scale);
      ctx.strokeStyle = colors.surface;
      ctx.stroke();
      if (hover?.id === node.id) {
        ctx.lineWidth = 2 / scale;
        ctx.strokeStyle = colors.ink;
        ctx.stroke();
      }
      const label = hover?.id === node.id || style.alwaysLabel?.(node) || scale > 2.6;
      if (label) {
        const text = node.label.length > 48 ? `${node.label.slice(0, 46)}…` : node.label;
        const fontSize = Math.max(10 / scale, 2.5);
        ctx.font = `${fontSize}px system-ui, sans-serif`;
        const width = ctx.measureText(text).width;
        ctx.fillStyle = colors.surface;
        ctx.globalAlpha = 0.85;
        ctx.fillRect(x - width / 2 - 2 / scale, y + r + 2 / scale, width + 4 / scale, fontSize + 3 / scale);
        ctx.globalAlpha = 1;
        ctx.fillStyle = colors.ink;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(text, x, y + r + 3 / scale);
      }
    },
    [colors, hover, style],
  );

  const hitArea = useCallback(
    (node: Node, color: string, ctx: CanvasRenderingContext2D, scale: number) => {
      // A generous hit target: at least ~12 screen pixels around every node.
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, Math.max(style.radius(node) + 3, 12 / scale), 0, 2 * Math.PI);
      ctx.fill();
    },
    [style],
  );

  return (
    <div
      ref={container}
      className={className ?? "relative w-full overflow-hidden"}
      style={{ height }}
      onMouseMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        setPointer({ x: event.clientX - box.left, y: event.clientY - box.top });
      }}
    >
      <ForceGraph2D<GraphNode, GraphLink>
        ref={graph}
        graphData={graphData}
        width={size.width}
        height={size.height}
        backgroundColor="rgba(0,0,0,0)"
        nodeId="id"
        nodeLabel={() => ""}
        nodeCanvasObject={paint}
        nodePointerAreaPaint={hitArea}
        linkColor={(link) => (style.linkColor ? style.linkColor(link as GraphLink, colors) : colors.axis)}
        linkWidth={(link) => ((link as GraphLink).type === "similar" ? 1.2 : 0.8)}
        linkLineDash={(link) => style.linkDash?.(link as GraphLink) ?? null}
        linkDirectionalArrowLength={style.arrows ? 3.2 : 0}
        linkDirectionalArrowRelPos={0.92}
        onNodeHover={(node) => setHover((node as GraphNode) ?? null)}
        onNodeClick={(node) => onNodeClick?.(node as GraphNode)}
        cooldownTicks={140}
        d3VelocityDecay={0.32}
        onEngineStop={() => {
          if (!fitted.current) {
            graph.current?.zoomToFit(500, 36);
            fitted.current = true;
          }
        }}
      />
      {hover && tooltip && (
        <div
          className="pointer-events-none absolute z-10 max-w-xs rounded-lg border border-line bg-raised px-3 py-2 text-xs shadow-card"
          style={{ left: Math.min(pointer.x + 14, size.width - 260), top: Math.min(pointer.y + 14, size.height - 90) }}
        >
          {tooltip(hover)}
        </div>
      )}
    </div>
  );
}

export function LegendItem({ color, label, shape = "circle", dashed }: { color: string; label: ReactNode; shape?: "circle" | "square" | "line"; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-secondary">
      {shape === "line" ? (
        <svg width="18" height="6" aria-hidden>
          <line x1="0" y1="3" x2="18" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dashed ? "3 3" : undefined} />
        </svg>
      ) : (
        <span className={shape === "square" ? "size-2.5 rounded-[2px]" : "size-2.5 rounded-full"} style={{ background: color }} aria-hidden />
      )}
      {label}
    </span>
  );
}
