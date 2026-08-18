"use client";

/** Case list: create a new case or open an existing one. */

import * as React from "react";
import { useRouter } from "next/navigation";
import { FolderKanban, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TopSearchBar } from "@/components/dashboard/TopSearchBar";
import { WorkspaceNav } from "@/components/dashboard/WorkspaceNav";
import { cn } from "@/lib/utils";
import { createCase, isLoggedIn, listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";

function statusBadgeClass(status: string): string {
  switch (status) {
    case "open":
      return "border-primary/40 bg-primary/10 text-primary";
    case "investigating":
      return "border-warning/40 bg-warning/10 text-warning";
    case "contained":
    case "resolved":
      return "border-success/40 bg-success/10 text-success";
    case "false_positive":
    case "closed":
      return "border-border bg-muted text-muted-foreground";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function severityBadgeClass(severity: string): string {
  switch (severity) {
    case "critical":
    case "high":
      return "border-destructive/40 bg-destructive/10 text-destructive";
    case "medium":
      return "border-warning/40 bg-warning/10 text-warning";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

export default function CasesPage() {
  const router = useRouter();
  const [cases, setCases] = React.useState<CaseSummary[] | null>(null);
  const [showNewForm, setShowNewForm] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [severity, setSeverity] = React.useState("medium");
  const [creating, setCreating] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/cases");
      return;
    }
    listCases()
      .then(setCases)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load cases"));
  }, [router]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const created = await createCase(title.trim(), description.trim() || undefined, severity);
      router.push(`/cases/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create case");
    } finally {
      setCreating(false);
    }
  };

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <div className="flex items-center justify-between gap-4">
          <TopSearchBar />
          <WorkspaceNav />
        </div>

        <div className="flex items-center justify-between">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <FolderKanban className="h-5 w-5" aria-hidden="true" />
            Cases
          </h1>
          <Button size="sm" onClick={() => setShowNewForm((v) => !v)}>
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            New Case
          </Button>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {showNewForm && (
          <Card>
            <CardHeader>
              <CardTitle>New Case</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleCreate} className="flex flex-col gap-3">
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Case title"
                  className="rounded-md border border-border bg-background px-3 py-2 text-sm outline-none"
                  autoFocus
                />
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Description (optional)"
                  rows={3}
                  className="rounded-md border border-border bg-background px-3 py-2 text-sm outline-none"
                />
                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted-foreground">Severity</label>
                  <select
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value)}
                    className="rounded-md border border-border bg-background px-2 py-1 text-xs"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
                <Button type="submit" size="sm" className="w-fit" disabled={creating || !title.trim()}>
                  {creating ? "Creating..." : "Create Case"}
                </Button>
              </form>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardContent className="flex flex-col gap-2 pt-4">
            {!cases && <p className="text-sm text-muted-foreground">Loading...</p>}
            {cases?.length === 0 && <p className="text-sm text-muted-foreground">No cases yet.</p>}
            {cases?.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => router.push(`/cases/${c.id}`)}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-left transition-colors hover:border-primary/60 hover:bg-primary/10"
              >
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-foreground">{c.title}</span>
                  <span className="text-[11px] text-muted-foreground">
                    {new Date(c.created_at).toLocaleString()}
                    {c.tags.length > 0 ? ` · ${c.tags.join(", ")}` : ""}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-medium capitalize", severityBadgeClass(c.severity))}>
                    {c.severity}
                  </span>
                  <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-medium capitalize", statusBadgeClass(c.status))}>
                    {c.status.replace(/_/g, " ")}
                  </span>
                </div>
              </button>
            ))}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
