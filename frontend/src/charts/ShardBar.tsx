import { useState } from "react";
import { formatNumber } from "../lib/format";
import { useChartColors } from "../lib/theme";
import { LegendItem } from "../components/ForceGraph";

/** Part-to-whole: how documents are split across nodes (one stacked bar, 2px gaps). */
export function ShardBar({ parts }: { parts: { node: string; count: number }[] }) {
  const colors = useChartColors();
  const [hover, setHover] = useState<string | null>(null);
  const sorted = [...parts].sort((a, b) => a.node.localeCompare(b.node));
  const shown = sorted.length > 8 ? [...sorted.slice(0, 7), { node: "Other", count: sorted.slice(7).reduce((s, p) => s + p.count, 0) }] : sorted;
  const total = shown.reduce((sum, part) => sum + part.count, 0);
  if (!total) return <p className="text-sm text-muted">No documents stored yet.</p>;
  const color = (i: number, node: string) => (node === "Other" ? colors.context : colors.series[i]);

  return (
    <div>
      <div className="flex h-6 w-full gap-[2px] overflow-hidden rounded-md" role="img" aria-label="Documents per node">
        {shown.map((part, i) =>
          part.count > 0 ? (
            <div
              key={part.node}
              className="h-full transition-opacity first:rounded-l-md last:rounded-r-md"
              style={{ width: `${(part.count / total) * 100}%`, background: color(i, part.node), opacity: hover && hover !== part.node ? 0.45 : 1 }}
              onMouseEnter={() => setHover(part.node)}
              onMouseLeave={() => setHover(null)}
              title={`${part.node}: ${formatNumber(part.count)} documents (${((part.count / total) * 100).toFixed(1)}%)`}
            />
          ) : null,
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
        {shown.map((part, i) => (
          <LegendItem
            key={part.node}
            color={color(i, part.node)}
            shape="square"
            label={
              <>
                {part.node} <span className="tabular text-ink">{formatNumber(part.count)}</span>{" "}
                <span className="text-muted">({((part.count / total) * 100).toFixed(0)}%)</span>
              </>
            }
          />
        ))}
      </div>
    </div>
  );
}
