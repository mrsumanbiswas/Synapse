import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, LogOut, Menu, Monitor, Moon, Server, Shield, Sun, Upload, UserRound, X } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { initials } from "../lib/format";
import { useTheme, type ThemeChoice } from "../lib/theme";
import { Logo } from "./Logo";
import { PageLoader, StatusDot } from "./ui";

interface NodeInfo {
  node: string;
  name: string;
  version: string;
  documents: number;
  peers: number;
  smtp: boolean;
  signup: boolean;
}

export function useNodeInfo() {
  return useQuery({ queryKey: ["info"], queryFn: () => api<NodeInfo>("/info"), staleTime: 30_000 });
}

function ThemeToggle() {
  const { choice, setChoice } = useTheme();
  const order: ThemeChoice[] = ["system", "light", "dark"];
  const Icon = choice === "light" ? Sun : choice === "dark" ? Moon : Monitor;
  const next = order[(order.indexOf(choice) + 1) % order.length];
  return (
    <button className="btn-ghost p-2" onClick={() => setChoice(next)} title={`Theme: ${choice} (switch to ${next})`} aria-label={`Theme: ${choice}`}>
      <Icon className="size-4" />
    </button>
  );
}

function UserMenu() {
  const { user, logout, can } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    const close = (event: MouseEvent) => !ref.current?.contains(event.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  if (!user) {
    return (
      <Link to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} className="btn-secondary px-3 py-1.5">
        Sign in
      </Link>
    );
  }
  return (
    <div className="relative" ref={ref}>
      <button className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-accent-soft" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="grid size-7 place-items-center rounded-full bg-accent text-xs font-semibold text-on-accent">{initials(user.name)}</span>
        <span className="hidden text-sm text-ink sm:block">{user.name.split(" ")[0]}</span>
        <ChevronDown className="size-3.5 text-muted" />
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-56 rounded-xl border border-line bg-raised py-1.5 shadow-card">
          <div className="border-b border-line px-3.5 pb-2.5 pt-1">
            <p className="truncate text-sm font-medium">{user.name}</p>
            <p className="truncate text-xs text-muted">{user.email}</p>
            <p className="mt-1 text-[11px] font-medium uppercase tracking-wider text-accent">{user.role}</p>
          </div>
          <Link to="/account" className="flex items-center gap-2.5 px-3.5 py-2 text-sm text-secondary hover:bg-accent-soft hover:text-ink">
            <UserRound className="size-4" /> Account & alerts
          </Link>
          {can("curator") && (
            <Link to="/ingest" className="flex items-center gap-2.5 px-3.5 py-2 text-sm text-secondary hover:bg-accent-soft hover:text-ink">
              <Upload className="size-4" /> Ingest
            </Link>
          )}
          {can("admin") && (
            <Link to="/admin" className="flex items-center gap-2.5 px-3.5 py-2 text-sm text-secondary hover:bg-accent-soft hover:text-ink">
              <Shield className="size-4" /> Users & roles
            </Link>
          )}
          <button onClick={logout} className="flex w-full items-center gap-2.5 px-3.5 py-2 text-sm text-secondary hover:bg-accent-soft hover:text-ink">
            <LogOut className="size-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

const NAV = [
  { to: "/explore", label: "Explore" },
  { to: "/graph", label: "Knowledge graph" },
  { to: "/network", label: "Network" },
];

export function Layout() {
  const location = useLocation();
  const { can } = useAuth();
  const info = useNodeInfo();
  const [menu, setMenu] = useState(false);
  const home = location.pathname === "/";
  useEffect(() => {
    setMenu(false);
  }, [location.pathname]);
  useEffect(() => {
    window.scrollTo(0, 0); // returns a Promise in recent browsers, so keep it out of the effect return
  }, [location.pathname]);

  const links = [...NAV, ...(can("curator") ? [{ to: "/ingest", label: "Ingest" }] : [])];
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-raised focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className={clsx("sticky top-0 z-30 border-b backdrop-blur", home ? "border-transparent bg-page/70" : "border-line bg-page/85")}>
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
          <Link to="/" className={clsx(home && "invisible")} aria-label="Synapse home">
            <Logo />
          </Link>
          <nav className="ml-4 hidden items-center gap-1 md:flex" aria-label="Main">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  clsx("rounded-lg px-3 py-1.5 text-sm transition-colors", isActive ? "bg-accent-soft font-medium text-ink" : "text-secondary hover:text-ink")
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            {info.data && (
              <Link to="/network" className="hidden items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-secondary hover:text-ink lg:flex" title="The node this page talks to">
                <StatusDot state="good" />
                <Server className="size-3.5" /> {info.data.node}
              </Link>
            )}
            <ThemeToggle />
            <UserMenu />
            <button className="btn-ghost p-2 md:hidden" onClick={() => setMenu((v) => !v)} aria-label="Menu" aria-expanded={menu}>
              {menu ? <X className="size-4" /> : <Menu className="size-4" />}
            </button>
          </div>
        </div>
        {menu && (
          <nav className="border-t border-line px-4 py-2 md:hidden" aria-label="Main">
            {links.map((link) => (
              <NavLink key={link.to} to={link.to} className="block rounded-lg px-3 py-2 text-sm text-secondary hover:bg-accent-soft hover:text-ink">
                {link.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>

      <main id="main" className="flex-1">
        <Suspense fallback={<PageLoader />}>
          <Outlet />
        </Suspense>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-5 text-xs text-muted sm:px-6">
          <span>Synapse {info.data?.version ?? ""}: distributed knowledge graph & semantic search</span>
          <span className="hidden sm:inline">·</span>
          <span>Served by node {info.data?.node ?? "…"}</span>
          <a className="link ml-auto" href="/api/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
          <span>Sample data: OpenAlex & arXiv (CC0)</span>
        </div>
      </footer>
    </div>
  );
}
