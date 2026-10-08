import clsx from "clsx";

/** Three connected neurons: the Synapse mark. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={clsx("shrink-0", className)} aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-accent" />
      <g className="stroke-on-accent" strokeWidth="2" strokeLinecap="round" fill="none">
        <path d="M9 21 L16 10 L23 19 M9 21 L23 19" />
      </g>
      <g className="fill-on-accent">
        <circle cx="9" cy="21" r="3.2" />
        <circle cx="16" cy="10" r="3.2" />
        <circle cx="23" cy="19" r="3.2" />
      </g>
    </svg>
  );
}

export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark className={size === "lg" ? "size-12" : "size-7"} />
      <span className={clsx("font-semibold tracking-tight text-ink", size === "lg" ? "text-5xl" : "text-lg")}>
        Synapse
      </span>
    </span>
  );
}
