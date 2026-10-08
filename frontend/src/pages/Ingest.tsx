import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CloudDownload, FileText, Folder, Globe, Loader2, Package, Plus, Server, UploadCloud, X } from "lucide-react";
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { ShardBar } from "../charts/ShardBar";
import { Badge, ErrorState, Modal, PageLoader, Tabs } from "../components/ui";
import { api, ApiError, getToken, type FtpEntry, type Job } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatBytes, formatDuration, formatNumber, initials, timeAgo } from "../lib/format";

const KIND_ICON: Record<Job["kind"], typeof FileText> = { upload: FileText, ftp: Server, remote: Globe, sample: Package };
const STAGES = [
  ["parsing", "Parse files (thread pool)"],
  ["distributing", "Route to shards (sockets)"],
  ["rebuilding", "Rebuild global model"],
  ["notifying", "E-mail alerts"],
] as const;
const ACCEPT = ".csv,.tsv,.json,.jsonl,.ndjson,.txt,.md,.markdown,.tex,.html,.htm,.pdf,.xml,.atom,.zip,.tar,.tgz,.gz";

function uploadFiles(files: File[], label: string, onProgress: (fraction: number) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    if (label) form.append("label", label);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/ingest/upload");
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => event.lengthComputable && onProgress(event.loaded / event.total);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Job);
      else reject(new ApiError(xhr.status, (body as { detail?: string })?.detail ?? xhr.statusText));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error while uploading"));
    xhr.send(form);
  });
}

function StatusBadge({ job }: { job: Job }) {
  if (job.status === "done") return <Badge tone="good"><CheckCircle2 className="size-3" /> done</Badge>;
  if (job.status === "failed") return <Badge tone="critical"><AlertTriangle className="size-3" /> failed</Badge>;
  return <Badge tone="accent"><Loader2 className="size-3 animate-spin" /> {job.stage}</Badge>;
}

function JobTile({ job, onOpen }: { job: Job; onOpen: () => void }) {
  const Icon = KIND_ICON[job.kind];
  return (
    <button onClick={onOpen} className="card flex h-full flex-col gap-3 p-4 text-left transition-colors hover:border-axis">
      <div className="flex items-start justify-between gap-2">
        <span className="grid size-10 place-items-center rounded-xl bg-accent-soft text-accent"><Icon className="size-5" /></span>
        <StatusBadge job={job} />
      </div>
      <div className="min-w-0">
        <p className="line-clamp-2 text-sm font-medium text-ink" title={job.label}>{job.label}</p>
        <p className="mt-1 text-xs text-muted">{job.kind} · {timeAgo(job.created_at)} · {job.user_name}</p>
      </div>
      <p className="tabular mt-auto text-xs text-secondary">
        {formatNumber(job.totals.stored)} stored
        {job.totals.duplicates > 0 && ` · ${formatNumber(job.totals.duplicates)} duplicates`}
        {job.totals.failed > 0 && ` · ${job.totals.failed} failed`}
      </p>
    </button>
  );
}

function JobDetail({ job }: { job: Job }) {
  const stageIndex = STAGES.findIndex(([key]) => key === job.stage);
  const finished = job.status !== "running" && job.status !== "queued";
  const duration = job.finished_at && job.started_at ? (job.finished_at - job.started_at) * 1000 : null;
  return (
    <div className="space-y-5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge job={job} />
        <span className="text-xs text-muted">started on {job.node} by {job.user_name} · {timeAgo(job.created_at)}{duration ? ` · took ${formatDuration(duration)}` : ""}</span>
      </div>
      <ol className="grid gap-2 sm:grid-cols-4">
        {STAGES.map(([key, label], i) => {
          const done = finished ? job.status === "done" || i < stageIndex : i < stageIndex;
          const current = !finished && i === stageIndex;
          return (
            <li key={key} className={clsx("rounded-lg border px-3 py-2 text-xs", current ? "border-accent bg-accent-soft text-ink" : done ? "border-line text-secondary" : "border-line text-muted")}>
              <span className="flex items-center gap-1.5">
                {current ? <Loader2 className="size-3 animate-spin" /> : done ? <CheckCircle2 className="size-3 text-good-text" /> : <span className="size-3" />}
                {label}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[["Records read", job.totals.records], ["Stored", job.totals.stored], ["Duplicates", job.totals.duplicates], ["Failed", job.totals.failed]].map(([label, value]) => (
          <div key={label} className="rounded-lg border border-line bg-raised px-3 py-2">
            <div className="text-[11px] text-muted">{label}</div>
            <div className="tabular text-lg font-semibold">{formatNumber(value as number)}</div>
          </div>
        ))}
      </div>
      {Object.keys(job.per_node).length > 0 && (
        <div>
          <p className="eyebrow mb-2">Where the documents went (rendezvous hashing)</p>
          <ShardBar parts={Object.entries(job.per_node).map(([node, count]) => ({ node, count }))} />
        </div>
      )}
      {job.files.length > 0 && (
        <div>
          <p className="eyebrow mb-2">Files</p>
          <ul className="divide-y divide-line rounded-lg border border-line">
            {job.files.map((file) => (
              <li key={file.name} className="flex items-center gap-3 px-3 py-2 text-xs">
                <FileText className="size-3.5 shrink-0 text-muted" />
                <span className="flex-1 truncate text-ink">{file.name}</span>
                {file.size != null && <span className="text-muted">{formatBytes(file.size)}</span>}
                <span className="tabular w-24 text-right text-secondary">{file.error ? <span className="text-critical">{file.status}</span> : `${formatNumber(file.records)} records`}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {job.rebuild && job.rebuild.status === "ok" && (
        <p className="text-xs text-secondary">
          Model v{String(job.rebuild.version).slice(-6)} rebuilt on {job.rebuild.nodes?.length} nodes: {formatNumber(job.rebuild.vocabulary ?? 0)} terms, {job.rebuild.concepts} concepts, {job.rebuild.topics} topics, {formatNumber(job.rebuild.citations ?? 0)} citation links.
          {job.notified ? ` Alerts checked on ${job.notified} subscription(s).` : ""}
        </p>
      )}
      {job.errors.length > 0 && (
        <div>
          <p className="eyebrow mb-2">Messages</p>
          <ul className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-line bg-raised p-3 font-mono text-[11px] text-secondary">
            {job.errors.map((error, i) => <li key={i}>{error}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function UploadTab({ onStarted }: { onStarted: (job: Job) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [label, setLabel] = useState("");
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const add = (list: FileList | null) => list && setFiles((current) => [...current, ...Array.from(list)]);
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDrag(false);
    add(event.dataTransfer.files);
  };
  const start = async () => {
    setError(null);
    setProgress(0);
    try {
      onStarted(await uploadFiles(files, label, setProgress));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProgress(null);
    }
  };
  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
        className={clsx("flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors", drag ? "border-accent bg-accent-soft" : "border-line hover:border-axis")}
      >
        <UploadCloud className="size-8 text-accent" />
        <p className="text-sm font-medium">Drop files here or click to choose</p>
        <p className="text-xs text-muted">CSV, JSON/JSONL, PDF, TXT/Markdown, HTML, arXiv XML, or ZIP/TAR/GZ archives of them</p>
        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => add(e.target.files)} />
      </div>
      {files.length > 0 && (
        <ul className="max-h-44 divide-y divide-line overflow-y-auto rounded-lg border border-line">
          {files.map((file, i) => (
            <li key={`${file.name}-${i}`} className="flex items-center gap-3 px-3 py-2 text-xs">
              <FileText className="size-3.5 text-muted" />
              <span className="flex-1 truncate">{file.name}</span>
              <span className="text-muted">{formatBytes(file.size)}</span>
              <button onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label={`Remove ${file.name}`}><X className="size-3.5 text-muted hover:text-ink" /></button>
            </li>
          ))}
        </ul>
      )}
      <label className="block">
        <span className="label">Label (optional)</span>
        <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Lab reading list, spring term" />
      </label>
      {progress !== null && (
        <div className="h-1.5 overflow-hidden rounded-full bg-accent-soft"><div className="h-full bg-accent transition-all" style={{ width: `${progress * 100}%` }} /></div>
      )}
      {error && <p className="text-sm text-critical">{error}</p>}
      <button className="btn-primary w-full" disabled={!files.length || progress !== null} onClick={start}>
        Upload & ingest {files.length ? `${files.length} file${files.length > 1 ? "s" : ""}` : ""}
      </button>
    </div>
  );
}

function FtpTab({ onStarted }: { onStarted: (job: Job) => void }) {
  const [form, setForm] = useState({ host: "ftp", port: 2121, username: "anonymous", password: "", path: "/", pattern: "*" });
  const browse = useMutation({ mutationFn: (path: string) => api<{ path: string; entries: FtpEntry[] }>("/ingest/ftp/browse", { method: "POST", json: { ...form, path } }) });
  const start = useMutation({ mutationFn: () => api<Job>("/ingest/ftp", { method: "POST", json: form }), onSuccess: onStarted });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: key === "port" ? Number(e.target.value) : e.target.value });
  const open = (path: string) => {
    setForm((f) => ({ ...f, path }));
    browse.mutate(path);
  };
  const parent = form.path.replace(/\/[^/]+\/?$/, "") || "/";
  return (
    <div className="space-y-4">
      <p className="text-xs text-secondary">Downloads every matching file with ftplib (several connections in parallel), then ingests them. The Docker setup includes a demo FTP server at <code className="font-mono">ftp:2121</code> (folders /papers and /arxiv).</p>
      <div className="grid grid-cols-[minmax(0,1fr)_6rem] gap-3">
        <label><span className="label">Host</span><input className="input" value={form.host} onChange={set("host")} /></label>
        <label><span className="label">Port</span><input className="input" type="number" value={form.port} onChange={set("port")} /></label>
        <label><span className="label">User</span><input className="input" value={form.username} onChange={set("username")} autoComplete="off" /></label>
        <label><span className="label">Password</span><input className="input" type="password" value={form.password} onChange={set("password")} autoComplete="off" /></label>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_8rem] gap-3">
        <label><span className="label">Remote path (file or folder)</span><input className="input font-mono" value={form.path} onChange={set("path")} /></label>
        <label><span className="label">File pattern</span><input className="input font-mono" value={form.pattern} onChange={set("pattern")} /></label>
      </div>
      <button className="btn-secondary" onClick={() => browse.mutate(form.path)} disabled={browse.isPending}>
        <Folder className="size-4" /> {browse.isPending ? "Listing…" : "Browse server"}
      </button>
      {browse.isError && <p className="text-sm text-critical">{(browse.error as Error).message}</p>}
      {browse.data && (
        <ul className="max-h-56 divide-y divide-line overflow-y-auto rounded-lg border border-line text-xs">
          {browse.data.path !== "/" && (
            <li><button className="flex w-full items-center gap-2 px-3 py-2 hover:bg-accent-soft" onClick={() => open(parent)}><Folder className="size-3.5 text-muted" /> ..</button></li>
          )}
          {browse.data.entries.map((entry) => (
            <li key={entry.path}>
              <button
                className={clsx("flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent-soft", !entry.supported && "opacity-50")}
                onClick={() => (entry.is_dir ? open(entry.path) : setForm((f) => ({ ...f, path: entry.path })))}
              >
                {entry.is_dir ? <Folder className="size-3.5 text-accent" /> : <FileText className="size-3.5 text-muted" />}
                <span className="flex-1 truncate font-mono">{entry.name}</span>
                {!entry.is_dir && <span className="text-muted">{formatBytes(entry.size)}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {start.isError && <p className="text-sm text-critical">{(start.error as Error).message}</p>}
      <button className="btn-primary w-full" onClick={() => start.mutate()} disabled={start.isPending || !form.host}>
        <CloudDownload className="size-4" /> Download & ingest {form.path}
      </button>
    </div>
  );
}

function RemoteTab({ onStarted }: { onStarted: (job: Job) => void }) {
  const [provider, setProvider] = useState<"openalex" | "arxiv">("arxiv");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(50);
  const start = useMutation({ mutationFn: () => api<Job>("/ingest/remote", { method: "POST", json: { provider, query, limit } }), onSuccess: onStarted });
  return (
    <div className="space-y-4">
      <p className="text-xs text-secondary">Pull open metadata straight from a scholarly API. OpenAlex includes citation links; arXiv has abstracts only.</p>
      <div className="grid grid-cols-2 gap-2">
        {(["arxiv", "openalex"] as const).map((p) => (
          <button key={p} onClick={() => setProvider(p)} className={clsx("rounded-lg border px-3 py-2.5 text-left text-sm", provider === p ? "border-accent bg-accent-soft" : "border-line hover:border-axis")}>
            <span className="font-medium">{p === "arxiv" ? "arXiv" : "OpenAlex"}</span>
            <span className="block text-xs text-muted">{p === "arxiv" ? "e.g. cat:cs.IR or all:transformer" : "full-text search, has abstracts"}</span>
          </button>
        ))}
      </div>
      <label className="block"><span className="label">Query</span><input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={provider === "arxiv" ? 'abs:"knowledge graph" AND cat:cs.AI' : "semantic search knowledge graphs"} /></label>
      <label className="block"><span className="label">How many papers ({limit})</span><input type="range" min={10} max={500} step={10} value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="w-full accent-[var(--accent)]" /></label>
      {start.isError && <p className="text-sm text-critical">{(start.error as Error).message}</p>}
      <button className="btn-primary w-full" disabled={query.trim().length < 2 || start.isPending} onClick={() => start.mutate()}>
        <Globe className="size-4" /> Import from {provider === "arxiv" ? "arXiv" : "OpenAlex"}
      </button>
    </div>
  );
}

function SampleTab({ onStarted }: { onStarted: (job: Job) => void }) {
  const start = useMutation({ mutationFn: () => api<Job>("/ingest/sample", { method: "POST" }), onSuccess: onStarted });
  return (
    <div className="space-y-4 text-sm">
      <p className="text-secondary">
        The bundled corpus: about 1,900 real papers from OpenAlex (CC0) across information retrieval, NLP, deep learning, graph learning, recommender
        systems, P2P and distributed systems, databases and autonomous vehicles, from the 1960s to today, with about 11,000 citation links between them.
      </p>
      <p className="text-xs text-muted">Re-importing is safe: documents already in the corpus are recognised by their DOI and skipped.</p>
      {start.isError && <p className="text-sm text-critical">{(start.error as Error).message}</p>}
      <button className="btn-primary w-full" onClick={() => start.mutate()} disabled={start.isPending}><Package className="size-4" /> Import sample corpus</button>
    </div>
  );
}

function AddDialog({ open, onClose, onStarted }: { open: boolean; onClose: () => void; onStarted: (job: Job) => void }) {
  const [tab, setTab] = useState<"upload" | "ftp" | "remote" | "sample">("upload");
  const started = (job: Job) => {
    onStarted(job);
    onClose();
  };
  return (
    <Modal open={open} onClose={onClose} title="Add documents" wide>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "upload", label: "Upload files" }, { value: "ftp", label: "FTP server" }, { value: "remote", label: "Scholarly API" }, { value: "sample", label: "Sample corpus" }]} />
      <div className="pt-4">
        {tab === "upload" && <UploadTab onStarted={started} />}
        {tab === "ftp" && <FtpTab onStarted={started} />}
        {tab === "remote" && <RemoteTab onStarted={started} />}
        {tab === "sample" && <SampleTab onStarted={started} />}
      </div>
    </Modal>
  );
}

export function IngestPage() {
  const { user } = useAuth();
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<{ jobs: Job[] }>("/ingest/jobs"),
    refetchInterval: (query) => (query.state.data?.jobs.some((j) => j.status === "running" || j.status === "queued") ? 1500 : 10_000),
  });
  if (!user) return null;
  if (jobs.isPending) return <PageLoader />;
  const list = jobs.data?.jobs ?? [];
  const job = list.find((j) => j.id === selected) ?? null;
  const stored = list.reduce((sum, j) => sum + j.totals.stored, 0);

  const header: ReactNode = (
    <div className="card flex flex-wrap items-center gap-4 p-4">
      <span className="grid size-12 place-items-center rounded-full bg-accent text-base font-semibold text-on-accent">{initials(user.name)}</span>
      <div className="min-w-0">
        <p className="font-medium text-ink">{user.name}</p>
        <p className="text-sm text-muted">{user.email}</p>
      </div>
      <Badge tone="accent">{user.role}</Badge>
      <div className="ml-auto flex gap-6 text-sm">
        <div><p className="text-xs text-muted">Ingest jobs</p><p className="tabular font-semibold">{list.length}</p></div>
        <div><p className="text-xs text-muted">Documents stored</p><p className="tabular font-semibold">{formatNumber(stored)}</p></div>
        <div><p className="text-xs text-muted">Member since</p><p className="font-semibold">{new Date(user.created_at * 1000).toLocaleDateString()}</p></div>
      </div>
    </div>
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      {header}
      <div className="mt-6 mb-3 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Ingested files</h1>
          <p className="text-sm text-secondary">Each tile is an ingest job. Records are parsed here and sent to the shard that owns them.</p>
        </div>
      </div>
      {jobs.isError && <ErrorState error={jobs.error} />}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {list.map((j) => (
          <JobTile key={j.id} job={j} onOpen={() => setSelected(j.id)} />
        ))}
        <button
          onClick={() => setAdding(true)}
          className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-line text-secondary transition-colors hover:border-accent hover:text-accent"
        >
          <Plus className="size-7" />
          <span className="text-sm font-medium">Add new file</span>
        </button>
      </div>
      <AddDialog
        open={adding}
        onClose={() => setAdding(false)}
        onStarted={(started) => {
          void client.invalidateQueries({ queryKey: ["jobs"] });
          setSelected(started.id);
        }}
      />
      <Modal open={Boolean(job)} onClose={() => setSelected(null)} title={job?.label ?? "Job"} wide>
        {job && <JobDetail job={job} />}
      </Modal>
    </div>
  );
}
