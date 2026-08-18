"use client";

/**
 * Users tab of the Administration console: search/filter/sort/paginate,
 * create, edit (name/role), enable/disable (with confirmation), and
 * password reset. Every mutation here is enforced server-side by
 * require_permission("user:manage") on backend/app/api/routes/admin.py --
 * this component is UX only, never the authorization boundary.
 */

import { useEffect, useState } from "react";
import { createUser, listUsers, resetUserPassword, setUserActive, updateUser } from "@/lib/api";
import type { CurrentUser, Role, User } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";

const ROLE_OPTIONS: Role[] = ["admin", "analyst", "viewer"];
const PAGE_SIZE = 25;

function roleBadgeVariant(role: Role): "default" | "success" | "muted" {
  if (role === "admin") return "default";
  if (role === "analyst") return "success";
  return "muted";
}

const SELECT_CLASS = "rounded-md border border-border bg-background px-3 py-2 text-sm outline-none disabled:opacity-50";

interface UsersManagementPanelProps {
  currentUser: CurrentUser;
}

export function UsersManagementPanel({ currentUser }: UsersManagementPanelProps) {
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [searchInput, setSearchInput] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<Role | "">("");
  const [activeFilter, setActiveFilter] = useState<"" | "true" | "false">("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [resettingUser, setResettingUser] = useState<User | null>(null);
  const [togglingUser, setTogglingUser] = useState<User | null>(null);

  const refresh = () => {
    setLoading(true);
    listUsers({
      search: appliedSearch || undefined,
      role: roleFilter || undefined,
      isActive: activeFilter === "" ? undefined : activeFilter === "true",
      page,
      pageSize: PAGE_SIZE,
      sortBy,
      sortDir,
    })
      .then((res) => {
        setUsers(res.items);
        setTotal(res.total);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load users"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, sortBy, sortDir, roleFilter, activeFilter, appliedSearch]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const toggleSort = (column: string) => {
    if (sortBy === column) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(column);
      setSortDir("asc");
    }
    setPage(1);
  };

  const sortIndicator = (column: string) => (sortBy === column ? (sortDir === "asc" ? " ↑" : " ↓") : "");

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setAppliedSearch(searchInput.trim());
          }}
        >
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search email or name..."
            className="w-56"
          />
          <Button type="submit" variant="outline" size="sm">
            Search
          </Button>
        </form>

        <select
          value={roleFilter}
          onChange={(e) => {
            setPage(1);
            setRoleFilter(e.target.value as Role | "");
          }}
          className={SELECT_CLASS}
        >
          <option value="">All roles</option>
          {ROLE_OPTIONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>

        <select
          value={activeFilter}
          onChange={(e) => {
            setPage(1);
            setActiveFilter(e.target.value as "" | "true" | "false");
          }}
          className={SELECT_CLASS}
        >
          <option value="">Any status</option>
          <option value="true">Active</option>
          <option value="false">Disabled</option>
        </select>

        <div className="ml-auto">
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            + New User
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="cursor-pointer select-none px-4 py-2" onClick={() => toggleSort("email")}>
                  Email{sortIndicator("email")}
                </th>
                <th className="px-4 py-2">Full Name</th>
                <th className="cursor-pointer select-none px-4 py-2" onClick={() => toggleSort("role")}>
                  Role{sortIndicator("role")}
                </th>
                <th className="px-4 py-2">Status</th>
                <th className="cursor-pointer select-none px-4 py-2" onClick={() => toggleSort("last_login_at")}>
                  Last Login{sortIndicator("last_login_at")}
                </th>
                <th className="cursor-pointer select-none px-4 py-2" onClick={() => toggleSort("created_at")}>
                  Created{sortIndicator("created_at")}
                </th>
                <th className="px-4 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {!loading && users.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-muted-foreground">
                    No users match these filters.
                  </td>
                </tr>
              )}
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border/50 last:border-none">
                  <td className="px-4 py-2">
                    {u.email}
                    {u.id === currentUser.id && <span className="ml-2 text-xs text-muted-foreground">(you)</span>}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">{u.full_name || "—"}</td>
                  <td className="px-4 py-2">
                    <Badge variant={roleBadgeVariant(u.role)}>{u.role}</Badge>
                  </td>
                  <td className="px-4 py-2">
                    <Badge variant={u.is_active ? "success" : "destructive"}>
                      {u.is_active ? "Active" : "Disabled"}
                    </Badge>
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never"}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-2 text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="outline" onClick={() => setEditingUser(u)}>
                        Edit
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setResettingUser(u)}>
                        Reset Password
                      </Button>
                      <Button
                        size="sm"
                        variant={u.is_active ? "destructive" : "default"}
                        onClick={() => setTogglingUser(u)}
                      >
                        {u.is_active ? "Disable" : "Enable"}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{total === 0 ? "0 users" : `Showing page ${page} of ${totalPages} (${total} total)`}</span>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      </div>

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={refresh} />
      {editingUser && (
        <EditUserDialog
          user={editingUser}
          isSelf={editingUser.id === currentUser.id}
          onOpenChange={(open) => !open && setEditingUser(null)}
          onSaved={refresh}
        />
      )}
      {resettingUser && (
        <ResetPasswordDialog
          user={resettingUser}
          onOpenChange={(open) => !open && setResettingUser(null)}
          onReset={refresh}
        />
      )}
      {togglingUser && (
        <ToggleActiveDialog
          user={togglingUser}
          onOpenChange={(open) => !open && setTogglingUser(null)}
          onToggled={refresh}
        />
      )}
    </div>
  );
}

function CreateUserDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("analyst");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setEmail("");
    setPassword("");
    setFullName("");
    setRole("analyst");
    setError(null);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create user</DialogTitle>
          <DialogDescription>The account is active immediately -- no email verification exists.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setSubmitting(true);
            setError(null);
            try {
              await createUser(email, password, fullName, role);
              reset();
              onOpenChange(false);
              onCreated();
            } catch (err) {
              setError(err instanceof Error ? err.message : "Failed to create user");
            } finally {
              setSubmitting(false);
            }
          }}
        >
          <Input type="text" placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          <Input type="email" placeholder="Email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input
            type="password"
            placeholder="Initial password (min 8 characters)"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} className={SELECT_CLASS}>
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting || !email || password.length < 8}>
              {submitting ? "Creating..." : "Create user"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditUserDialog({
  user,
  isSelf,
  onOpenChange,
  onSaved,
}: {
  user: User;
  isSelf: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [fullName, setFullName] = useState(user.full_name);
  const [role, setRole] = useState<Role>(user.role);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <Dialog open onOpenChange={(next) => !next && onOpenChange(false)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit {user.email}</DialogTitle>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setSubmitting(true);
            setError(null);
            try {
              await updateUser(user.id, { full_name: fullName, role });
              onOpenChange(false);
              onSaved();
            } catch (err) {
              setError(err instanceof Error ? err.message : "Failed to update user");
            } finally {
              setSubmitting(false);
            }
          }}
        >
          <Input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Full name" />
          <select
            value={role}
            disabled={isSelf}
            onChange={(e) => setRole(e.target.value as Role)}
            className={SELECT_CLASS}
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          {isSelf && (
            <p className="text-xs text-muted-foreground">You can&apos;t change your own role -- ask another administrator.</p>
          )}
          {error && <p className="text-xs text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Saving..." : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({
  user,
  onOpenChange,
  onReset,
}: {
  user: User;
  onOpenChange: (open: boolean) => void;
  onReset: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mismatch = confirm.length > 0 && password !== confirm;

  return (
    <Dialog open onOpenChange={(next) => !next && onOpenChange(false)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset password for {user.email}</DialogTitle>
          <DialogDescription>
            This immediately signs the user out of every existing session -- they&apos;ll need to sign in again with
            the new password.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (password !== confirm) {
              setError("Passwords do not match.");
              return;
            }
            setSubmitting(true);
            setError(null);
            try {
              await resetUserPassword(user.id, password);
              onOpenChange(false);
              onReset();
            } catch (err) {
              setError(err instanceof Error ? err.message : "Failed to reset password");
            } finally {
              setSubmitting(false);
            }
          }}
        >
          <Input
            type="password"
            placeholder="New password (min 8 characters)"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Input
            type="password"
            placeholder="Confirm new password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          {mismatch && <p className="text-xs text-destructive">Passwords do not match.</p>}
          {error && <p className="text-xs text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting || password.length < 8 || mismatch}>
              {submitting ? "Resetting..." : "Reset password"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ToggleActiveDialog({
  user,
  onOpenChange,
  onToggled,
}: {
  user: User;
  onOpenChange: (open: boolean) => void;
  onToggled: () => void;
}) {
  const targetActive = !user.is_active;
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <Dialog open onOpenChange={(next) => !next && onOpenChange(false)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {targetActive ? "Enable" : "Disable"} {user.email}?
          </DialogTitle>
          <DialogDescription>
            {targetActive
              ? "They will regain access immediately, with no restart required."
              : "They will immediately lose access -- any current session stops working on their very next request."}
          </DialogDescription>
        </DialogHeader>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={targetActive ? "default" : "destructive"}
            disabled={submitting}
            onClick={async () => {
              setSubmitting(true);
              setError(null);
              try {
                await setUserActive(user.id, targetActive);
                onOpenChange(false);
                onToggled();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to update account status");
              } finally {
                setSubmitting(false);
              }
            }}
          >
            {submitting ? "Working..." : targetActive ? "Enable" : "Disable"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
