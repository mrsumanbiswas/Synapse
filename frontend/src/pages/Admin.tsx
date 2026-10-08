import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { ErrorState, PageLoader } from "../components/ui";
import { api, type Role, type User } from "../lib/api";
import { useAuth } from "../lib/auth";
import { timeAgo } from "../lib/format";

const ROLE_HELP: Record<Role, string> = {
  viewer: "search, library, alerts",
  curator: "+ ingest files, rebuild the model",
  admin: "+ manage users, delete documents",
};

export function AdminPage() {
  const { user: me } = useAuth();
  const client = useQueryClient();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api<{ users: User[] }>("/admin/users") });
  const refresh = () => client.invalidateQueries({ queryKey: ["admin", "users"] });
  const setRole = useMutation({ mutationFn: ({ id, role }: { id: number; role: Role }) => api(`/admin/users/${id}`, { method: "PATCH", json: { role } }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: number) => api(`/admin/users/${id}`, { method: "DELETE" }), onSuccess: refresh });

  if (users.isPending) return <PageLoader />;
  if (users.isError) return <div className="mx-auto max-w-3xl px-4 py-10"><ErrorState error={users.error} /></div>;
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">Users & roles</h1>
      <p className="mb-5 mt-1 text-sm text-secondary">Grant the curator role to people who should be able to ingest files.</p>
      {(setRole.isError || remove.isError) && <div className="mb-4"><ErrorState error={setRole.error ?? remove.error} /></div>}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="px-4 py-2.5 font-medium">User</th>
              <th className="px-4 py-2.5 font-medium">Role</th>
              <th className="px-4 py-2.5 font-medium">Joined</th>
              <th className="px-4 py-2.5 font-medium">Last sign-in</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {users.data.users.map((u) => (
              <tr key={u.id} className="border-b border-line last:border-0">
                <td className="px-4 py-3">
                  <p className="font-medium text-ink">{u.name}{u.id === me?.id && <span className="ml-2 text-xs text-muted">(you)</span>}</p>
                  <p className="text-xs text-muted">{u.email}</p>
                </td>
                <td className="px-4 py-3">
                  <select className="input w-32 py-1 text-xs" value={u.role} onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value as Role })}>
                    {(["viewer", "curator", "admin"] as Role[]).map((role) => <option key={role} value={role}>{role}</option>)}
                  </select>
                  <p className="mt-1 text-[11px] text-muted">{ROLE_HELP[u.role]}</p>
                </td>
                <td className="px-4 py-3 text-xs text-secondary">{timeAgo(u.created_at)}</td>
                <td className="px-4 py-3 text-xs text-secondary">{timeAgo(u.last_login)}</td>
                <td className="px-4 py-3 text-right">
                  {u.id !== me?.id && (
                    <button className="btn-ghost p-1.5" onClick={() => window.confirm(`Delete ${u.email}?`) && remove.mutate(u.id)} aria-label={`Delete ${u.email}`}>
                      <Trash2 className="size-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
