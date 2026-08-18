"use client";

/** Case detail: status/severity controls, attached IOCs, and analyst notes. */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TopSearchBar } from "@/components/dashboard/TopSearchBar";
import { WorkspaceNav } from "@/components/dashboard/WorkspaceNav";
import { cn } from "@/lib/utils";
import { addCaseNote, getCase, isLoggedIn, updateCase } from "@/lib/api";
import type { CaseDetail, CaseStatus } from "@/lib/types";

const STATUSES: CaseStatus[] = ["open", "investigating", "contained", "resolved", "false_positive", "closed"];

export default function CaseDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const caseId = params?.id;

  const [caseDetail, setCaseDetail] = React.useState<CaseDetail | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [noteText, setNoteText] = React.useState("");
  const [savingNote, setSavingNote] = React.useState(false);

  const reload = React.useCallback(() => {
    if (!caseId) return;
    getCase(caseId)
      .then(setCaseDetail)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load case"));
  }, [caseId]);

  React.useEffect(() => {
    if (!isLoggedIn()) {
      router.replace(`/login?next=${encodeURIComponent(`/cases/${caseId ?? ""}`)}`);
      return;
    }
    reload();
  }, [router, caseId, reload]);

  const handleStatusChange = async (status: string) => {
    if (!caseId) return;
    await updateCase(caseId, { status });
    reload();
  };

  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!caseId || !noteText.trim()) return;
    setSavingNote(true);
    try {
      await addCaseNote(caseId, noteText.trim());
      setNoteText("");
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setSavingNote(false);
    }
  };

  if (error) {
    return (
      <main className="min-h-screen px-4 py-8">
        <div className="mx-auto max-w-4xl rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        <div className="flex items-center justify-between gap-4">
          <TopSearchBar />
          <WorkspaceNav />
        </div>

        {!caseDetail ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <>
            <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h1 className="text-xl font-semibold">{caseDetail.title}</h1>
                  {caseDetail.description && <p className="mt-1 text-sm text-muted-foreground">{caseDetail.description}</p>}
                </div>
                <select
                  value={caseDetail.status}
                  onChange={(e) => handleStatusChange(e.target.value)}
                  className="rounded-md border border-border bg-background px-2 py-1 text-xs capitalize"
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span className="rounded-full border border-border px-2 py-0.5 capitalize">{caseDetail.severity} severity</span>
                {caseDetail.tags.map((t) => (
                  <span key={t} className="rounded-full border border-border px-2 py-0.5">
                    {t}
                  </span>
                ))}
              </div>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>IOCs ({caseDetail.iocs.length})</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {caseDetail.iocs.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    No IOCs attached yet -- use &quot;Add to Case&quot; on any lookup page.
                  </p>
                )}
                {caseDetail.iocs.map((ioc) => (
                  <div key={ioc.id} className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2">
                    <span className="text-sm text-foreground">
                      {ioc.ioc_value} <span className="text-[11px] text-muted-foreground">({ioc.ioc_type})</span>
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => router.push(`/lookup/new?value=${encodeURIComponent(ioc.ioc_value)}`)}
                    >
                      Investigate
                      <ArrowRight className="h-3 w-3" aria-hidden="true" />
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Analyst Notes ({caseDetail.notes.length})</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {caseDetail.notes.map((note) => (
                  <div key={note.id} className="rounded-md border border-border bg-muted/20 px-3 py-2">
                    <p className="text-sm text-foreground">{note.body}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{new Date(note.created_at).toLocaleString()}</p>
                  </div>
                ))}
                <form onSubmit={handleAddNote} className="flex items-center gap-2">
                  <input
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    placeholder='e.g. "Observed this IP in firewall logs at 03:14."'
                    className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm outline-none"
                  />
                  <Button type="submit" size="sm" disabled={savingNote || !noteText.trim()}>
                    {savingNote ? "Saving..." : "Add Note"}
                  </Button>
                </form>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </main>
  );
}
