"use client";

/**
 * Administration console: multi-admin user management, the fixed
 * role/permission matrix (read-only -- ROLE_PERMISSIONS is static in-code,
 * see backend/app/models/user.py), and the shared configuration/audit log
 * (backend/app/core/audit.py), which user-management actions write into
 * alongside provider/AI configuration changes. Every mutating action here
 * is enforced server-side by require_permission("user:manage") -- this
 * page's own role check below only avoids showing a non-admin a screen
 * full of buttons that would 403.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import * as Tabs from "@radix-ui/react-tabs";
import { BrandHeader } from "@/components/dashboard/BrandHeader";
import { UsersManagementPanel } from "@/components/dashboard/UsersManagementPanel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { getAuditLog, getCurrentUser, getRoles, getUserStats, isLoggedIn } from "@/lib/api";
import type { AuditLogEntry, CurrentUser, RolePermissions, UserStats } from "@/lib/types";

const TAB_CLASS = cn(
  "rounded-md px-4 py-2 text-sm font-medium text-muted-foreground transition-colors",
  "hover:text-foreground",
  "data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
);

export default function AdminPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [stats, setStats] = useState<UserStats | null>(null);
  const [roles, setRoles] = useState<RolePermissions[]>([]);
  const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refreshAll = () => {
    getUserStats().then(setStats).catch(() => {});
    getRoles().then(setRoles).catch(() => {});
    getAuditLog(50).then(setAuditLog).catch(() => {});
  };

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/admin");
      return;
    }
    getCurrentUser()
      .then((user) => {
        if (user.role !== "admin") {
          router.replace("/");
          return;
        }
        setCurrentUser(user);
        refreshAll();
      })
      .catch(() => router.replace("/login?next=/admin"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  if (!currentUser) {
    return (
      <main className="min-h-screen px-4 py-8">
        <div className="mx-auto max-w-5xl text-sm text-muted-foreground">Loading...</div>
      </main>
    );
  }

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <BrandHeader />

        <div>
          <h1 className="font-display text-sm uppercase tracking-[0.08em] text-muted-foreground">Administration</h1>
          <p className="text-sm text-muted-foreground">
            Manage user accounts, review the fixed role/permission matrix, and audit every configuration and
            account change. Signed in as {currentUser.email} ({currentUser.role}).
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <Tabs.Root defaultValue="overview">
          <Tabs.List className="mb-4 flex gap-1 border-b border-border pb-2">
            <Tabs.Trigger value="overview" className={TAB_CLASS}>
              Overview
            </Tabs.Trigger>
            <Tabs.Trigger value="users" className={TAB_CLASS}>
              Users
            </Tabs.Trigger>
            <Tabs.Trigger value="roles" className={TAB_CLASS}>
              Roles &amp; Permissions
            </Tabs.Trigger>
            <Tabs.Trigger value="audit" className={TAB_CLASS}>
              Audit Log
            </Tabs.Trigger>
          </Tabs.List>

          <Tabs.Content value="overview" className="flex flex-col gap-4">
            {stats && (
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-xs text-muted-foreground">Total Users</CardTitle>
                  </CardHeader>
                  <CardContent className="font-data tabular-nums text-2xl font-semibold">{stats.total_users}</CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-xs text-muted-foreground">Active</CardTitle>
                  </CardHeader>
                  <CardContent className="font-data tabular-nums text-2xl font-semibold text-success">{stats.active_users}</CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-xs text-muted-foreground">Disabled</CardTitle>
                  </CardHeader>
                  <CardContent className="font-data tabular-nums text-2xl font-semibold text-destructive">
                    {stats.disabled_users}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-xs text-muted-foreground">Admins</CardTitle>
                  </CardHeader>
                  <CardContent className="font-data tabular-nums text-2xl font-semibold">{stats.by_role["admin"] ?? 0}</CardContent>
                </Card>
              </div>
            )}
            <Card>
              <CardHeader>
                <CardTitle>Recent Logins</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-col gap-2 text-sm">
                  {(!stats || stats.recent_logins.length === 0) && (
                    <li className="text-muted-foreground">No logins recorded yet.</li>
                  )}
                  {stats?.recent_logins.map((entry, i) => (
                    <li key={`${entry.email}-${i}`} className="flex justify-between border-b border-border/50 pb-2 last:border-none">
                      <span>{entry.email}</span>
                      <span className="font-data tabular-nums text-muted-foreground">{new Date(entry.last_login_at).toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </Tabs.Content>

          <Tabs.Content value="users">
            <UsersManagementPanel currentUser={currentUser} />
          </Tabs.Content>

          <Tabs.Content value="roles" className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">
              Roles and their permissions are fixed in code (not editable here) -- this is a read-only reference so
              an administrator can see exactly what each role can do.
            </p>
            {roles.map((r) => (
              <Card key={r.role}>
                <CardHeader>
                  <CardTitle className="capitalize">{r.role}</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-1.5">
                  {r.permissions.map((p) => (
                    <Badge key={p} variant="muted">
                      {p}
                    </Badge>
                  ))}
                </CardContent>
              </Card>
            ))}
          </Tabs.Content>

          <Tabs.Content value="audit">
            <Card>
              <CardHeader>
                <CardTitle>Audit Log</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="mb-3 text-xs text-muted-foreground">
                  Every configuration and account change, recorded without ever storing a credential or password
                  value.
                </p>
                <ul className="flex flex-col gap-2 text-sm">
                  {auditLog.length === 0 && <li className="text-muted-foreground">No changes recorded yet.</li>}
                  {auditLog.map((entry) => (
                    <li key={entry.id} className="border-b border-border/50 pb-2 last:border-none">
                      <span className="font-data tabular-nums text-xs text-muted-foreground">
                        {new Date(entry.timestamp).toLocaleString()}
                      </span>
                      {" -- "}
                      <span className="font-medium">{entry.action}</span>: {entry.detail}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </Tabs.Content>
        </Tabs.Root>
      </div>
    </main>
  );
}
