import { lazy, type ReactNode } from "react";
import { createBrowserRouter, Navigate, RouterProvider, useLocation } from "react-router";
import { Layout } from "./components/Layout";
import { PageLoader } from "./components/ui";
import { useAuth } from "./lib/auth";
import type { Role } from "./lib/api";
import { HomePage } from "./pages/Home";
import { LoginPage, RegisterPage } from "./pages/Login";
import { NotFoundPage } from "./pages/NotFound";
import { SearchPage } from "./pages/Search";

// Heavier pages (graphs, charts) load on demand.
const AccountPage = lazy(() => import("./pages/Account").then((m) => ({ default: m.AccountPage })));
const AdminPage = lazy(() => import("./pages/Admin").then((m) => ({ default: m.AdminPage })));
const AuthorPage = lazy(() => import("./pages/Author").then((m) => ({ default: m.AuthorPage })));
const DocumentPage = lazy(() => import("./pages/Document").then((m) => ({ default: m.DocumentPage })));
const ExplorePage = lazy(() => import("./pages/Explore").then((m) => ({ default: m.ExplorePage })));
const GraphPage = lazy(() => import("./pages/Graph").then((m) => ({ default: m.GraphPage })));
const IngestPage = lazy(() => import("./pages/Ingest").then((m) => ({ default: m.IngestPage })));
const NetworkPage = lazy(() => import("./pages/Network").then((m) => ({ default: m.NetworkPage })));

function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { user, ready, can } = useAuth();
  const location = useLocation();
  if (!ready) return <PageLoader />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (!can(role)) return <NotFoundPage title="You don't have access to this page" detail={`It needs the ${role} role. An admin can grant it from Users & roles.`} />;
  return <>{children}</>;
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <HomePage /> },
      { path: "/search", element: <SearchPage /> },
      { path: "/doc/:id", element: <DocumentPage /> },
      { path: "/author/:name", element: <AuthorPage /> },
      { path: "/explore", element: <ExplorePage /> },
      { path: "/graph", element: <GraphPage /> },
      { path: "/network", element: <NetworkPage /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
      { path: "/ingest", element: <RequireRole role="curator"><IngestPage /></RequireRole> },
      { path: "/account", element: <RequireRole role="viewer"><AccountPage /></RequireRole> },
      { path: "/admin", element: <RequireRole role="admin"><AdminPage /></RequireRole> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
