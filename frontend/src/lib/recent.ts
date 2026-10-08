// Recent searches are a per-browser convenience, so they live in localStorage.
const KEY = "synapse.recent";

export interface RecentSearch {
  q: string;
  mode: string;
  at: number;
}

export function recentSearches(): RecentSearch[] {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(value) ? value.slice(0, 12) : [];
  } catch {
    return [];
  }
}

export function rememberSearch(q: string, mode: string) {
  const query = q.trim();
  if (!query || query === "*") return;
  try {
    const rest = recentSearches().filter((item) => item.q.toLowerCase() !== query.toLowerCase());
    localStorage.setItem(KEY, JSON.stringify([{ q: query, mode, at: Date.now() }, ...rest].slice(0, 12)));
  } catch {
    /* storage unavailable */
  }
}

export function clearRecentSearches() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
}
