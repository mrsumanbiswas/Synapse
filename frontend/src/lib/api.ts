// Typed client for the Synapse HTTP API (served under /api by every node).

export type Mode = "hybrid" | "keyword" | "semantic" | "boolean";
export type Sort = "relevance" | "year_desc" | "year_asc" | "citations" | "pagerank";
export type Role = "viewer" | "curator" | "admin";

export interface Segment {
  t: string;
  h: boolean;
}

export interface TopicRef {
  id: number;
  label: string;
}

export interface DocCard {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  url: string | null;
  source: string | null;
  cited_by_count: number | null;
  cluster: number | null;
  pagerank: number;
  pagerank_pct: number;
  in_citations: number;
  out_citations: number;
  external_id: string | null;
  filename: string | null;
  node: string;
  snippet?: Segment[];
  scores?: { keyword: number | null; semantic: number | null };
  topic: TopicRef | null;
  score?: number;
  rank?: number;
  bookmarked?: boolean;
  also_keyword?: boolean;
}

export interface NodeTiming {
  node: string;
  ok: boolean;
  ms: number;
  error: string | null;
  hits: number;
}

export interface Concept {
  term: string;
  weight: number;
}

export interface SearchResponse {
  query: string;
  mode: Mode;
  sort: Sort;
  page: number;
  size: number;
  total: number;
  results: DocCard[];
  facets: {
    years: [number, number][];
    topics: (TopicRef & { count: number })[];
    authors: [string, number][];
    sources: [string, number][];
  };
  nodes: NodeTiming[];
  did_you_mean: string | null;
  concepts: Concept[];
  parsed: { normalized: string; fallback: boolean; error: string | null; operators: boolean };
  model_versions: number[];
  took_ms: number;
}

export interface Suggestion {
  text: string;
  kind: "phrase" | "term" | "author" | "history" | "correction";
  count: number;
}

export interface AstNode {
  type: "term" | "phrase" | "field" | "and" | "or" | "not" | "all" | "none";
  value?: string;
  field?: string;
  children?: AstNode[];
}

export interface ExplainResponse {
  query: string;
  tokens: { type: string; text: string; implicit: boolean }[];
  rpn: string[];
  ast: AstNode;
  normalized: string;
  steps: { action: string; label: string; size: number; depth: number }[];
  matches: number;
  nodes: NodeTiming[];
}

export interface CompareResponse {
  query: string;
  keyword: DocCard[];
  semantic: DocCard[];
  overlap: number;
  concepts: Concept[];
}

export interface LightDoc {
  id: string;
  title: string;
  year: number | null;
  authors: string[];
  citations: number;
  pagerank: number;
}

export interface Reference {
  position: number;
  raw: string | null;
  title: string | null;
  year: number | null;
  keys: string[];
  resolved: string | null;
  resolved_title: string | null;
}

export interface DocumentDetail extends DocCard {
  abstract: string | null;
  body: string | null;
  body_length: number | null;
  published: string | null;
  language: string | null;
  categories: string[];
  ingested_at: number;
  ingested_via: string | null;
  job_id: string | null;
  content_hash: string;
  entities: Record<string, { value: string; count: number }[]>;
  references: Reference[];
  references_in_corpus: LightDoc[];
  references_total: number;
  cited_by: LightDoc[];
  identity_keys: string[];
  concepts?: Concept[];
  top_terms?: Concept[];
  metrics?: {
    pagerank: number;
    pagerank_pct: number;
    hub: number;
    authority: number;
    in_citations: number;
    out_citations: number;
    community: number;
  };
  topic: (TopicRef & { terms: string[] }) | null;
}

export interface GraphNode {
  id: string;
  type: "paper" | "author";
  role?: string;
  label: string;
  year?: number | null;
  cluster?: number | null;
  community?: number;
  pagerank?: number;
  pagerank_pct?: number;
  citations?: number;
  papers?: number;
  h_index?: number;
  similarity?: number;
  depth?: number;
}

export interface GraphLink {
  source: string;
  target: string;
  type?: "cites" | "wrote" | "similar";
  weight?: number;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface Topic {
  id: number;
  label: string;
  terms: string[];
  size: number;
  share: number;
  recent: number;
  growth: number;
  sample_size: number;
  top_papers: { id: string; title: string; year: number | null }[];
}

export interface Burst {
  label: string;
  kind: "topic" | "term";
  start: number;
  end: number;
  weight: number;
  documents: number;
}

export interface EvolutionData {
  eras: { index: number; start: number; end: number; label: string }[];
  nodes: { id: string; era: number; period: string; start: number; end: number; size: number; label: string }[];
  links: { source: string; target: string; weight: number; weak: boolean }[];
  events: { type: "split" | "merge" | "emerge" | "fade"; node: string; era: string; label: string; into?: string[]; from?: string[] }[];
}

export interface Point {
  id: string;
  title: string;
  year: number | null;
  cluster: number | null;
  x: number;
  y: number;
  z: number;
  node: string;
}

export interface Overview {
  node: string;
  documents: number;
  nodes: { alive: number; known: number };
  graph: { papers?: number; citations?: number; authors?: number; collaborations?: number; communities?: number };
  model: ModelInfo | null;
  trending: { id: number; label: string; size: number; growth: number; recent: number; terms: string[] }[];
  bursts: Burst[];
  popular: { query: string; count: number }[];
  recent_searches: { query: string; mode: Mode; ts: number }[];
  recent_documents: (DocCard & { abstract?: string; ingested_at?: number })[];
  top_papers: GraphNode[];
  year_range: [number, number] | null;
}

export interface ModelInfo {
  version: number;
  leader: string;
  built_at: number;
  documents: number;
  vocabulary: number;
  concepts: number;
  explained_variance: number;
  topics: number;
  sample_size?: number;
  nodes?: string[];
}

export interface ClusterNode {
  node_id: string | null;
  name: string | null;
  address: string;
  alive: boolean;
  self: boolean;
  latency_ms: number | null;
  last_seen: number | null;
  configured?: boolean;
  info: Record<string, unknown>;
  stats: {
    documents: number;
    terms: number;
    postings: number;
    authors: number;
    avg_length: number;
    db_bytes: number;
    model_version: number | null;
    analytics_version: number | null;
    trie_nodes: number;
    loaded_in_ms: number;
  } | null;
  error: string | null;
}

export interface Rebuild {
  status: string;
  reason: string;
  version?: number;
  leader?: string;
  nodes?: string[];
  documents?: number;
  vocabulary?: number;
  concepts?: number;
  topics?: number;
  citations?: number;
  model_bytes?: number;
  timings?: Record<string, number>;
  finished_at: number;
  error?: string;
}

export interface ClusterStatus {
  self: string;
  version: string;
  uptime: number;
  nodes: ClusterNode[];
  model: ModelInfo | null;
  analytics: { version: number; built_at: number; leader: string; graph_stats: Overview["graph"] } | null;
  rebuilding: boolean;
  rebuilds: Rebuild[];
  secured: boolean;
}

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  created_at: number;
  last_login: number | null;
}

export interface Session {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Subscription {
  id: number;
  query: string;
  mode: Mode;
  min_score: number;
  active: number;
  created_at: number;
  last_notified_at: number | null;
  matches: number;
}

export interface NotificationItem {
  id: number;
  query: string | null;
  documents: { id: string; title: string; score: number }[];
  status: string;
  error: string | null;
  created_at: number;
}

export interface Bookmark {
  doc_id: string;
  title: string;
  note: string | null;
  created_at: number;
}

export interface JobFile {
  name: string;
  size: number | null;
  status: string;
  records: number;
  error: string | null;
}

export interface Job {
  id: string;
  kind: "upload" | "ftp" | "remote" | "sample";
  label: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  user_name: string;
  node: string;
  source: Record<string, unknown>;
  files: JobFile[];
  totals: { records: number; stored: number; duplicates: number; failed: number };
  per_node: Record<string, number>;
  errors: string[];
  rebuild: Rebuild | null;
  notified: number | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
}

export interface FtpEntry {
  name: string;
  path: string;
  size: number | null;
  is_dir: boolean;
  modified: string | null;
  supported: boolean;
}

export interface AuthorProfile {
  name: string;
  metrics: {
    papers?: number;
    citations?: number;
    h_index?: number;
    coauthors?: number;
    collaborations?: number;
    pagerank?: number;
    first_year?: number | null;
    last_year?: number | null;
  };
  coauthors: { name: string; weight: number; papers: number }[];
  papers: DocCard[];
  topics: { label: string; count: number }[];
  years: [number, number][];
  network: GraphData;
}

// --------------------------------------------------------------------------- transport

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const TOKEN_KEY = "synapse.token";
let token: string | null = null;
try {
  token = localStorage.getItem(TOKEN_KEY);
} catch {
  token = null;
}
let unauthorizedHandler: (() => void) | null = null;

export function setToken(value: string | null) {
  token = value;
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the session lasts until reload */
  }
}

export function getToken() {
  return token;
}

export function onUnauthorized(handler: () => void) {
  unauthorizedHandler = handler;
}

type RequestOptions = Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit | null };

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  }
  return fallback;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = options.body;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }
  const response = await fetch(`/api${path}`, { ...options, headers, body });
  if (!response.ok) {
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      /* not JSON */
    }
    if (response.status === 401 && token) unauthorizedHandler?.();
    throw new ApiError(response.status, errorMessage(data, response.statusText || "Request failed"));
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("json") ? response.json() : response.text()) as Promise<T>;
}

export function qs(params: Record<string, string | number | boolean | null | undefined | (string | number)[]>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)));
    else search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
