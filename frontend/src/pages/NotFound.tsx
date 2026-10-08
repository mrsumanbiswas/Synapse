import { Link } from "react-router";

export function NotFoundPage({ title = "Page not found", detail = "The page you were looking for doesn't exist." }: { title?: string; detail?: string }) {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center px-4 text-center">
      <p className="text-5xl font-semibold text-accent">404</p>
      <h1 className="mt-3 text-xl font-semibold">{title}</h1>
      <p className="mt-1 text-sm text-secondary">{detail}</p>
      <Link to="/" className="btn-primary mt-6">Back to search</Link>
    </div>
  );
}
