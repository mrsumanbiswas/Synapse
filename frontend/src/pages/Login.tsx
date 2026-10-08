import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { useNodeInfo } from "../components/Layout";
import { LogoMark } from "../components/Logo";
import { useAuth } from "../lib/auth";

function safeNext(value: string | null) {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

function AuthCard({ title, subtitle, children }: { title: string; subtitle: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-sm flex-col justify-center px-4 py-10">
      <LogoMark className="mb-5 size-10" />
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mb-6 mt-1 text-sm text-secondary">{subtitle}</p>
      {children}
    </div>
  );
}

export function LoginPage() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={next} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate(next, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthCard title="Sign in" subtitle={<>New here? <Link to={`/register?next=${encodeURIComponent(next)}`} className="link">Create an account</Link></>}>
      <form onSubmit={submit} className="space-y-3">
        <label className="block"><span className="label">E-mail</span><input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required autoFocus /></label>
        <label className="block"><span className="label">Password</span><input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        {error && <p className="text-sm text-critical" role="alert">{error}</p>}
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="mt-6 text-xs text-muted">Accounts belong to the node you are connected to. Searching works without an account; ingesting needs the curator role.</p>
    </AuthCard>
  );
}

export function RegisterPage() {
  const { register, user } = useAuth();
  const info = useNodeInfo();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={next} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register(form.name, form.email, form.password);
      navigate(next, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (info.data && !info.data.signup) {
    return <AuthCard title="Sign-up is closed" subtitle="Ask an administrator of this node for an account."><Link to="/login" className="btn-secondary">Back to sign in</Link></AuthCard>;
  }
  return (
    <AuthCard title="Create an account" subtitle={<>Already registered? <Link to={`/login?next=${encodeURIComponent(next)}`} className="link">Sign in</Link></>}>
      <form onSubmit={submit} className="space-y-3">
        <label className="block"><span className="label">Name</span><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoComplete="name" required autoFocus /></label>
        <label className="block"><span className="label">E-mail</span><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} autoComplete="email" required /></label>
        <label className="block"><span className="label">Password (8+ characters)</span><input className="input" type="password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" required /></label>
        {error && <p className="text-sm text-critical" role="alert">{error}</p>}
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
      </form>
      <p className="mt-6 text-xs text-muted">New accounts can search, save papers and set up e-mail alerts. An admin can grant the curator role for ingesting.</p>
    </AuthCard>
  );
}
