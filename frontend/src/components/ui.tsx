import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { ApiError } from "../lib/api";

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2 text-sm text-muted", className)} role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label ?? <span className="sr-only">Loading</span>}
    </span>
  );
}

export function PageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <Spinner label={label} />
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <div className="mb-1 rounded-full bg-accent-soft p-3 text-accent">{icon ?? <Inbox className="size-5" />}</div>
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="max-w-md text-sm text-secondary">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong";
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-surface p-4 text-sm" role="alert">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-critical" aria-hidden />
      <div className="flex-1">
        <p className="font-medium text-ink">Couldn't load this</p>
        <p className="mt-0.5 text-secondary">{message}</p>
      </div>
      {retry && (
        <button className="btn-secondary px-3 py-1.5 text-xs" onClick={retry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Badge({ children, tone = "neutral", className, title }: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "good" | "warning" | "critical";
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
        tone === "neutral" && "bg-hairline/60 text-secondary dark:bg-hairline",
        tone === "accent" && "bg-accent-soft text-accent-strong dark:text-accent-strong",
        tone === "good" && "bg-good/12 text-good-text",
        tone === "warning" && "bg-warning/20 text-secondary",
        tone === "critical" && "bg-critical/12 text-critical",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({ state }: { state: "good" | "warning" | "critical" | "idle" }) {
  return (
    <span
      aria-hidden
      className={clsx(
        "inline-block size-2 rounded-full",
        state === "good" && "bg-good",
        state === "warning" && "bg-warning",
        state === "critical" && "bg-critical",
        state === "idle" && "bg-axis",
      )}
    />
  );
}

export function StatTile({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="card flex flex-col gap-1 p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-secondary">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {hint && <div className="text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, size = "md", label }: {
  value: T;
  options: { value: T; label: ReactNode; title?: string }[];
  onChange: (value: T) => void;
  size?: "sm" | "md";
  label?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-raised p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={value === option.value}
          title={option.title}
          onClick={() => onChange(option.value)}
          className={clsx(
            "rounded-md font-medium transition-colors",
            size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm",
            value === option.value ? "bg-accent text-on-accent" : "text-secondary hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: {
  value: T;
  tabs: { value: T; label: ReactNode; count?: number }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line scrollbar-thin">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          role="tab"
          aria-selected={value === tab.value}
          onClick={() => onChange(tab.value)}
          className={clsx(
            "-mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
            value === tab.value ? "border-accent text-ink" : "border-transparent text-secondary hover:text-ink",
          )}
        >
          {tab.label}
          {tab.count !== undefined && <span className="tabular text-xs text-muted">{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(event) => event.target === ref.current && onClose()}
      className={clsx(
        "m-auto w-[calc(100%-2rem)] rounded-2xl border border-line bg-surface p-0 text-ink shadow-card backdrop:bg-black/40 backdrop:backdrop-blur-[2px]",
        wide ? "max-w-3xl" : "max-w-lg",
      )}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 className="text-base font-semibold">{title}</h2>
            <button className="btn-ghost p-1.5" onClick={onClose} aria-label="Close">
              <X className="size-4" />
            </button>
          </div>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
        </div>
      )}
    </dialog>
  );
}

export function Pagination({ page, total, size, onPage }: { page: number; total: number; size: number; onPage: (page: number) => void }) {
  const pages = Math.min(50, Math.ceil(total / size));
  if (pages <= 1) return null;
  const window = Array.from({ length: pages }, (_, i) => i + 1).filter((p) => p === 1 || p === pages || Math.abs(p - page) <= 2);
  return (
    <nav className="flex items-center justify-center gap-1 pt-2" aria-label="Pagination">
      <button className="btn-ghost px-3 py-1.5" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      {window.map((p, i) => (
        <span key={p} className="flex items-center">
          {i > 0 && window[i - 1] !== p - 1 && <span className="px-1 text-muted">…</span>}
          <button
            onClick={() => onPage(p)}
            aria-current={p === page ? "page" : undefined}
            className={clsx(
              "tabular min-w-9 rounded-lg px-2.5 py-1.5 text-sm",
              p === page ? "bg-accent text-on-accent" : "text-secondary hover:bg-accent-soft hover:text-ink",
            )}
          >
            {p}
          </button>
        </span>
      ))}
      <button className="btn-ghost px-3 py-1.5" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}

export function Section({ title, action, children, className }: {
  title: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx("card p-5", className)}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Meter({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="flex items-center gap-2" title={label}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-accent-soft">
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      {label && <span className="tabular w-10 text-right text-xs text-muted">{label}</span>}
    </div>
  );
}
