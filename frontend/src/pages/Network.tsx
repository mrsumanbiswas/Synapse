import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Cpu, Database, Lock, Plus, RefreshCw, Server, Unlock } from "lucide-react";
import { useState } from "react";
import { ShardBar } from "../charts/ShardBar";
import { Badge, ErrorState, PageLoader, Section, StatTile, StatusDot } from "../components/ui";
import { api, type ClusterStatus } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatBytes, formatDuration, formatNumber, timeAgo } from "../lib/format";

const PHASES: [string, string][] = [
  ["collect_stats", "Collect term stats"],
  ["collect_sample", "Collect samples"],
  ["svd", "SVD (LSA)"],
  ["clustering", "k-means + PCA"],
  ["install_model", "Broadcast model"],
  ["analytics", "Graph & temporal"],
  ["install_analytics", "Broadcast analytics"],
];

export function NetworkPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [peer, setPeer] = useState("");
  const cluster = useQuery({
    queryKey: ["cluster"],
    queryFn: () => api<ClusterStatus>("/cluster"),
    refetchInterval: (query) => (query.state.data?.rebuilding ? 2000 : 8000),
  });
  const rebuild = useMutation({
    mutationFn: () => api("/cluster/rebuild", { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["cluster"] }),
  });
  const addPeer = useMutation({
    mutationFn: (address: string) => api("/cluster/peers", { method: "POST", json: { address } }),
    onSuccess: () => {
      setPeer("");
      void client.invalidateQueries({ queryKey: ["cluster"] });
    },
  });

  if (cluster.isPending) return <PageLoader label="Pinging peers…" />;
  if (cluster.isError) return <div className="mx-auto max-w-3xl px-4 py-10"><ErrorState error={cluster.error} retry={() => cluster.refetch()} /></div>;
  const data = cluster.data;
  const alive = data.nodes.filter((n) => n.alive);
  const totalDocs = alive.reduce((sum, n) => sum + (n.stats?.documents ?? 0), 0);
  const versions = new Set(alive.map((n) => n.stats?.model_version ?? null));
  const lastRebuild = data.rebuilds.find((r) => r.status === "ok");

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Peer-to-peer network</h1>
          <p className="mt-1 max-w-3xl text-sm text-secondary">
            Every node stores a shard of the corpus in its own SQLite database. Queries are broadcast over TCP sockets to all nodes at once and the
            answers are merged; documents are placed with rendezvous hashing. You are connected to <strong className="text-ink">{data.self}</strong>.
          </p>
        </div>
        {can("curator") && (
          <button className="btn-primary" onClick={() => rebuild.mutate()} disabled={data.rebuilding || rebuild.isPending}>
            <RefreshCw className={clsx("size-4", data.rebuilding && "animate-spin")} />
            {data.rebuilding ? "Rebuilding model…" : "Rebuild global model"}
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Nodes online" value={`${alive.length} / ${data.nodes.length}`} icon={<Server className="size-3.5" />} />
        <StatTile label="Documents (all shards)" value={formatNumber(totalDocs)} icon={<Database className="size-3.5" />} />
        <StatTile
          label="Model version"
          value={data.model ? `v${String(data.model.version).slice(-6)}` : "none"}
          hint={versions.size > 1 ? "Nodes disagree: a re-sync is pending" : data.model ? `built ${timeAgo(data.model.built_at)} by ${data.model.leader}` : undefined}
          icon={<Cpu className="size-3.5" />}
        />
        <StatTile
          label="Peer traffic"
          value={data.secured ? "Signed" : "Open"}
          hint={data.secured ? "HMAC-SHA256 with the cluster secret" : "Set SYNAPSE_CLUSTER_SECRET to sign frames"}
          icon={data.secured ? <Lock className="size-3.5" /> : <Unlock className="size-3.5" />}
        />
      </div>

      <Section title="Shard distribution" className="mt-5">
        <ShardBar parts={alive.map((n) => ({ node: n.node_id ?? n.address, count: n.stats?.documents ?? 0 }))} />
      </Section>

      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.nodes.map((node) => (
          <div key={node.address} className={clsx("card p-4", node.self && "border-accent/50")}>
            <div className="flex items-center gap-2">
              <StatusDot state={node.alive ? "good" : "critical"} />
              <span className="font-medium text-ink">{node.node_id ?? "unknown"}</span>
              {node.self && <Badge tone="accent">this node</Badge>}
              <span className="ml-auto font-mono text-xs text-muted">{node.address}</span>
            </div>
            {node.alive && node.stats ? (
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                <dt className="text-muted">Documents</dt><dd className="tabular text-right text-ink">{formatNumber(node.stats.documents)}</dd>
                <dt className="text-muted">Index terms</dt><dd className="tabular text-right text-ink">{formatNumber(node.stats.terms)}</dd>
                <dt className="text-muted">Postings</dt><dd className="tabular text-right text-ink">{formatNumber(node.stats.postings)}</dd>
                <dt className="text-muted">Authors</dt><dd className="tabular text-right text-ink">{formatNumber(node.stats.authors)}</dd>
                <dt className="text-muted">Trie nodes</dt><dd className="tabular text-right text-ink">{formatNumber(node.stats.trie_nodes)}</dd>
                <dt className="text-muted">SQLite size</dt><dd className="tabular text-right text-ink">{formatBytes(node.stats.db_bytes)}</dd>
                <dt className="text-muted">Latency</dt><dd className="tabular text-right text-ink">{node.self ? "local" : `${(node.latency_ms ?? 0).toFixed(1)} ms`}</dd>
                <dt className="text-muted">Model</dt>
                <dd className="tabular text-right text-ink">{node.stats.model_version ? `v${String(node.stats.model_version).slice(-6)}` : "none"}</dd>
              </dl>
            ) : (
              <p className="mt-3 text-xs text-critical">{node.error ?? "Unreachable"} {node.last_seen ? `· last seen ${timeAgo(node.last_seen)}` : ""}</p>
            )}
            {!node.self && node.configured === false && <p className="mt-2 text-[11px] text-muted">Discovered through gossip</p>}
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Section title="Global model">
          {data.model ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted">Vocabulary</dt><dd className="tabular text-right">{formatNumber(data.model.vocabulary)} terms</dd>
              <dt className="text-muted">LSA concepts (k)</dt><dd className="tabular text-right">{data.model.concepts}</dd>
              <dt className="text-muted">Variance kept by SVD</dt><dd className="tabular text-right">{(data.model.explained_variance * 100).toFixed(1)}%</dd>
              <dt className="text-muted">Topics (k-means)</dt><dd className="tabular text-right">{data.model.topics}</dd>
              <dt className="text-muted">Trained on</dt><dd className="tabular text-right">{formatNumber(data.model.sample_size ?? 0)} of {formatNumber(data.model.documents)} docs</dd>
              <dt className="text-muted">Leader</dt><dd className="text-right">{data.model.leader}</dd>
            </dl>
          ) : (
            <p className="text-sm text-muted">No model yet. Ingest documents or start a rebuild.</p>
          )}
          {lastRebuild?.timings && (
            <div className="mt-4">
              <p className="eyebrow mb-2">Last rebuild: {formatDuration(Object.values(lastRebuild.timings).reduce((a, b) => a + b, 0))}</p>
              <ul className="space-y-1.5">
                {PHASES.filter(([key]) => lastRebuild.timings?.[key] !== undefined).map(([key, label]) => {
                  const ms = lastRebuild.timings![key];
                  const max = Math.max(...Object.values(lastRebuild.timings!));
                  return (
                    <li key={key} className="grid grid-cols-[9rem_minmax(0,1fr)_4rem] items-center gap-2 text-xs">
                      <span className="text-secondary">{label}</span>
                      <span className="h-1.5 overflow-hidden rounded-full bg-accent-soft"><span className="block h-full rounded-full bg-accent" style={{ width: `${(ms / max) * 100}%` }} /></span>
                      <span className="tabular text-right text-muted">{formatDuration(ms)}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </Section>
        <Section title="Rebuild history">
          {data.rebuilds.length === 0 ? (
            <p className="text-sm text-muted">No rebuild led by this node yet.</p>
          ) : (
            <ul className="divide-y divide-line">
              {data.rebuilds.map((r, i) => (
                <li key={i} className="py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <StatusDot state={r.status === "ok" ? "good" : r.status === "failed" ? "critical" : "idle"} />
                    <span className="text-ink">{r.status === "ok" ? `${formatNumber(r.documents ?? 0)} docs on ${r.nodes?.length ?? 0} nodes` : r.status}</span>
                    <span className="ml-auto text-xs text-muted">{timeAgo(r.finished_at)}</span>
                  </div>
                  <p className="ml-4 text-xs text-muted">{r.reason}{r.error ? ` · ${r.error}` : ""}</p>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      {can("admin") && (
        <Section title="Add a peer" className="mt-5">
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (peer.trim()) addPeer.mutate(peer.trim());
            }}
          >
            <input className="input max-w-xs font-mono" placeholder="192.168.1.20:7000" value={peer} onChange={(e) => setPeer(e.target.value)} />
            <button className="btn-secondary" disabled={addPeer.isPending}><Plus className="size-4" /> Connect</button>
          </form>
          {addPeer.isError && <p className="mt-2 text-xs text-critical">{(addPeer.error as Error).message}</p>}
          <p className="mt-2 text-xs text-muted">Only one existing address is needed: peers share their peer lists in every ping, so the rest is discovered automatically.</p>
        </Section>
      )}
    </div>
  );
}
