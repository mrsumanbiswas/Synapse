import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Clock, HelpCircle, Hash, Search, SpellCheck, Sparkles, User } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";
import { api, qs, type Mode, type Suggestion } from "../lib/api";
import { rememberSearch } from "../lib/recent";
import { Segmented } from "./ui";

export const MODES: { value: Mode; label: string; title: string }[] = [
  { value: "hybrid", label: "Hybrid", title: "Keyword and semantic rankings fused (reciprocal rank fusion)" },
  { value: "keyword", label: "Keyword", title: "TF-IDF cosine similarity on the inverted index" },
  { value: "semantic", label: "Semantic", title: "Latent semantic analysis: matches concepts, not just words" },
  { value: "boolean", label: "Boolean", title: "Exact AND / OR / NOT logic, parsed with a stack" },
];

const KIND_ICON: Record<Suggestion["kind"], typeof Search> = {
  phrase: Sparkles,
  term: Hash,
  author: User,
  history: Clock,
  correction: SpellCheck,
};

const KIND_LABEL: Record<Suggestion["kind"], string> = {
  phrase: "phrase",
  term: "word",
  author: "author",
  history: "popular search",
  correction: "did you mean",
};

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function searchUrl(q: string, mode: Mode) {
  return `/search${qs({ q, mode: mode === "hybrid" ? null : mode })}`;
}

export function SyntaxHelp() {
  const [open, setOpen] = useState(false);
  const rows: [string, string][] = [
    ["neural network", "both words (implicit AND)"],
    ['"neural network"', "exact phrase"],
    ["python OR java", "either word"],
    ["learning NOT reinforcement", "exclude a word (also: -word)"],
    ["(graph OR network) AND ranking", "grouping with parentheses"],
    ['author:"Geoffrey E. Hinton"', "papers by an author"],
    ["year:2015..2020  year:>2018", "publication year"],
    ["title:transformer  topic:3  venue:nature", "field filters"],
  ];
  return (
    <div className="relative">
      <button
        type="button"
        className="btn-ghost px-2 py-1.5"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Search syntax help"
        title="Search syntax"
      >
        <HelpCircle className="size-4" />
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-[22rem] max-w-[calc(100vw-2rem)] rounded-xl border border-line bg-raised p-4 text-left shadow-card">
          <p className="mb-2 text-sm font-semibold">Query syntax</p>
          <p className="mb-3 text-xs text-secondary">
            Operators are upper case. Boolean mode applies them exactly; the other modes use them as filters while
            ranking by relevance.
          </p>
          <dl className="space-y-1.5 text-xs">
            {rows.map(([example, meaning]) => (
              <div key={example} className="flex gap-3">
                <dt className="w-[11.5rem] shrink-0 font-mono text-ink">{example}</dt>
                <dd className="text-secondary">{meaning}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

export function SearchBox({ initial = "", mode, onModeChange, size = "md", autoFocus, showModes = true }: {
  initial?: string;
  mode: Mode;
  onModeChange?: (mode: Mode) => void;
  size?: "md" | "lg";
  autoFocus?: boolean;
  showModes?: boolean;
}) {
  const navigate = useNavigate();
  const [text, setText] = useState(initial);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const listId = useId();
  const wrapper = useRef<HTMLDivElement>(null);
  const debounced = useDebounced(text, 120);

  useEffect(() => {
    setText(initial);
  }, [initial]);

  const { data } = useQuery({
    queryKey: ["autocomplete", debounced],
    queryFn: () => api<{ suggestions: Suggestion[] }>(`/autocomplete${qs({ q: debounced, limit: 8 })}`),
    enabled: open && debounced.trim().length >= 2,
    staleTime: 60_000,
  });
  const suggestions = open && debounced.trim().length >= 2 ? data?.suggestions ?? [] : [];

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const submit = (query: string) => {
    const q = query.trim();
    if (!q) return;
    setOpen(false);
    setActive(-1);
    rememberSearch(q, mode);
    navigate(searchUrl(q, mode));
  };

  const choose = (suggestion: Suggestion) => {
    if (suggestion.kind === "author") {
      setOpen(false);
      navigate(`/author/${encodeURIComponent(suggestion.text)}`);
      return;
    }
    setText(suggestion.text);
    submit(suggestion.text);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" && suggestions.length) {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % suggestions.length);
    } else if (event.key === "ArrowUp" && suggestions.length) {
      event.preventDefault();
      setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0 && suggestions[active]) choose(suggestions[active]);
      else submit(text);
    } else if (event.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  };

  const large = size === "lg";
  return (
    <div ref={wrapper} className="w-full">
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          submit(text);
        }}
        className="relative"
      >
        <div
          className={clsx(
            "flex items-center gap-2 rounded-2xl border border-line bg-raised transition focus-within:border-accent focus-within:ring-4 focus-within:ring-accent/15",
            large ? "px-5 py-3.5 shadow-card" : "px-3.5 py-2",
          )}
        >
          <Search className={clsx("shrink-0 text-muted", large ? "size-5" : "size-4")} aria-hidden />
          <input
            value={text}
            autoFocus={autoFocus}
            onChange={(event) => {
              setText(event.target.value);
              setOpen(true);
              setActive(-1);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            placeholder="Type here to search…"
            aria-label="Search the corpus"
            role="combobox"
            aria-expanded={suggestions.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
            className={clsx("min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-muted", large ? "text-lg" : "text-sm")}
          />
          <SyntaxHelp />
          <button type="submit" className={clsx("btn-primary", large ? "px-5 py-2" : "px-3 py-1.5 text-xs")}>
            Search
          </button>
        </div>

        {suggestions.length > 0 && (
          <ul
            id={listId}
            role="listbox"
            className="absolute inset-x-0 z-20 mt-2 overflow-hidden rounded-xl border border-line bg-raised py-1 shadow-card"
          >
            {suggestions.map((suggestion, i) => {
              const Icon = KIND_ICON[suggestion.kind];
              return (
                <li
                  key={`${suggestion.kind}-${suggestion.text}`}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    choose(suggestion);
                  }}
                  onMouseEnter={() => setActive(i)}
                  className={clsx(
                    "flex cursor-pointer items-center gap-3 px-4 py-2 text-sm",
                    i === active ? "bg-accent-soft text-ink" : "text-secondary",
                  )}
                >
                  <Icon className="size-4 shrink-0 text-muted" aria-hidden />
                  <span className="flex-1 truncate text-ink">{suggestion.text}</span>
                  <span className="text-[11px] text-muted">{KIND_LABEL[suggestion.kind]}</span>
                </li>
              );
            })}
          </ul>
        )}
      </form>
      {showModes && onModeChange && (
        <div className={clsx("flex flex-wrap items-center gap-3", large ? "mt-4 justify-center" : "mt-2")}>
          <Segmented value={mode} options={MODES} onChange={onModeChange} size="sm" label="Search mode" />
        </div>
      )}
    </div>
  );
}
