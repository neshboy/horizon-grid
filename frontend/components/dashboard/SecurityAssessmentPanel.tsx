"use client";

/**
 * Security Assessment Toolkit UI -- active checks (Nmap/DNS/TLS/HTTP-header/
 * hash-metadata) against the investigation's own target, gated by a
 * mandatory, explicit scope/authorization confirmation before any run
 * starts. The real enforcement is server-side (backend/app/api/routes/
 * security_assessment.py's require_permission("security_assessment:create")
 * and its own target/authorization checks) -- this panel only avoids
 * showing a viewer a run form that would 403.
 *
 * Only `nmap` has more than one profile (quick/standard/web); every other
 * tool only defines "standard". Since one run request sends a single
 * shared `profile` for every selected tool, the profile picker here is
 * restricted to profile ids valid across EVERY currently-selected tool
 * (in practice, that's "standard" alone once more than one tool is
 * selected) -- this is a frontend-only fix, not a backend change, since
 * the backend contract is already tested and live-verified as-is.
 */

import * as React from "react";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import {
  cancelSecurityAssessmentRun,
  getCurrentUser,
  getSecurityAssessmentProfiles,
  getSecurityAssessmentToolHealth,
  listSecurityAssessmentRuns,
  runSecurityAssessment,
} from "@/lib/api";
import type { SecurityAssessmentFinding, SecurityAssessmentRun, Severity, ToolHealth, ToolProfile } from "@/lib/types";

export interface SecurityAssessmentPanelProps {
  lookupId: string;
  iocValue: string;
  iocType: string | null;
}

function severityBadgeVariant(severity: Severity): "default" | "success" | "warning" | "destructive" | "muted" {
  switch (severity) {
    case "critical":
    case "high":
      return "destructive";
    case "medium":
      return "warning";
    case "low":
      return "default";
    default:
      return "muted";
  }
}

const POLL_INTERVAL_MS = 2000;

export function SecurityAssessmentPanel({ lookupId, iocValue, iocType }: SecurityAssessmentPanelProps) {
  const [canRun, setCanRun] = React.useState(false);
  const [profiles, setProfiles] = React.useState<ToolProfile[]>([]);
  const [toolHealth, setToolHealth] = React.useState<ToolHealth[]>([]);
  const [runs, setRuns] = React.useState<SecurityAssessmentRun[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  const [selectedTools, setSelectedTools] = React.useState<Set<string>>(new Set());
  const [selectedProfile, setSelectedProfile] = React.useState<string>("");
  const [targetConfirmation, setTargetConfirmation] = React.useState("");
  const [authorizationConfirmed, setAuthorizationConfirmed] = React.useState(false);
  const [starting, setStarting] = React.useState(false);
  const [cancellingRunId, setCancellingRunId] = React.useState<string | null>(null);
  const [activeFinding, setActiveFinding] = React.useState<SecurityAssessmentFinding | null>(null);

  const refreshRuns = React.useCallback(() => {
    listSecurityAssessmentRuns(lookupId).then(setRuns).catch(() => {});
  }, [lookupId]);

  React.useEffect(() => {
    getCurrentUser()
      .then((user) => setCanRun(user.role === "admin" || user.role === "analyst"))
      .catch(() => setCanRun(false));
    getSecurityAssessmentProfiles().then(setProfiles).catch(() => {});
    getSecurityAssessmentToolHealth().then(setToolHealth).catch(() => {});
    refreshRuns();
  }, [refreshRuns]);

  // Poll while any run is still in flight.
  React.useEffect(() => {
    const hasActiveRun = runs.some((r) => r.status === "pending" || r.status === "running");
    if (!hasActiveRun) return;
    const interval = setInterval(refreshRuns, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [runs, refreshRuns]);

  const availableTools = React.useMemo(() => {
    const byTool = new Map<string, { tool_id: string; tool_name: string; profiles: ToolProfile[] }>();
    for (const p of profiles) {
      if (iocType && !p.supported_types.includes(iocType)) continue;
      const entry = byTool.get(p.tool_id) ?? { tool_id: p.tool_id, tool_name: p.tool_name, profiles: [] };
      entry.profiles.push(p);
      byTool.set(p.tool_id, entry);
    }
    return Array.from(byTool.values());
  }, [profiles, iocType]);

  const availableProfileIds = React.useMemo(() => {
    const selected = availableTools.filter((t) => selectedTools.has(t.tool_id));
    if (selected.length === 0) return [];
    const [first, ...rest] = selected;
    let ids = new Set(first.profiles.map((p) => p.profile_id));
    for (const tool of rest) {
      const toolIds = new Set(tool.profiles.map((p) => p.profile_id));
      ids = new Set([...ids].filter((id) => toolIds.has(id)));
    }
    return [...ids];
  }, [availableTools, selectedTools]);

  React.useEffect(() => {
    if (availableProfileIds.length > 0 && !availableProfileIds.includes(selectedProfile)) {
      setSelectedProfile(availableProfileIds[0]);
    }
  }, [availableProfileIds, selectedProfile]);

  const toolIsAvailable = (toolId: string) => toolHealth.find((t) => t.tool_id === toolId)?.available ?? true;

  const toggleTool = (toolId: string) => {
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolId)) next.delete(toolId);
      else next.add(toolId);
      return next;
    });
  };

  const canSubmit =
    selectedTools.size > 0 &&
    selectedProfile !== "" &&
    targetConfirmation === iocValue &&
    authorizationConfirmed &&
    !starting;

  const handleRun = async () => {
    setStarting(true);
    setError(null);
    try {
      await runSecurityAssessment(lookupId, [...selectedTools], selectedProfile, targetConfirmation, authorizationConfirmed);
      setTargetConfirmation("");
      setAuthorizationConfirmed(false);
      refreshRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start security assessment");
    } finally {
      setStarting(false);
    }
  };

  const handleCancel = async (runId: string) => {
    setCancellingRunId(runId);
    setError(null);
    try {
      await cancelSecurityAssessmentRun(runId);
      refreshRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel security assessment run");
    } finally {
      setCancellingRunId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4" aria-hidden="true" />
          Security Assessment
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-xs text-muted-foreground">
          Active checks (Nmap port/service scan, DNS enumeration, TLS certificate inspection, HTTP security
          headers) against this investigation&apos;s own target. Every run requires explicit authorization -- only
          test targets you own or are authorized to assess.
        </p>

        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {canRun && (
          <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/20 p-3">
            <div className="flex flex-wrap gap-2">
              {availableTools.length === 0 && (
                <p className="text-xs text-muted-foreground">No security-assessment tool supports this IOC type.</p>
              )}
              {availableTools.map((tool) => (
                <button
                  key={tool.tool_id}
                  type="button"
                  onClick={() => toggleTool(tool.tool_id)}
                  disabled={!toolIsAvailable(tool.tool_id)}
                  title={!toolIsAvailable(tool.tool_id) ? `${tool.tool_name} is not available on this host` : undefined}
                  className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                    selectedTools.has(tool.tool_id)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {tool.tool_name}
                  {!toolIsAvailable(tool.tool_id) && " (unavailable)"}
                </button>
              ))}
            </div>

            {availableProfileIds.length > 0 && (
              <select
                value={selectedProfile}
                onChange={(e) => setSelectedProfile(e.target.value)}
                className="w-fit rounded-md border border-border bg-background px-3 py-2 text-sm outline-none"
              >
                {availableProfileIds.map((id) => {
                  const label = profiles.find((p) => p.profile_id === id)?.name ?? id;
                  return (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  );
                })}
              </select>
            )}

            <Input
              value={targetConfirmation}
              onChange={(e) => setTargetConfirmation(e.target.value)}
              placeholder={`Type "${iocValue}" to confirm the target`}
            />

            <label className="flex items-start gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={authorizationConfirmed}
                onChange={(e) => setAuthorizationConfirmed(e.target.checked)}
                className="mt-0.5"
              />
              I am authorized to run active security checks against this target.
            </label>

            <Button size="sm" className="w-fit" disabled={!canSubmit} onClick={handleRun}>
              {starting ? "Starting..." : "Run Security Assessment"}
            </Button>
          </div>
        )}

        <div className="flex flex-col gap-2">
          {runs.length === 0 && <p className="text-xs text-muted-foreground">No security assessment runs yet.</p>}
          {runs.map((run) => (
            <div key={run.id} className="flex flex-col gap-2 rounded-md border border-border bg-muted/10 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">
                  {new Date(run.authorization_confirmed_at).toLocaleString()} -- {run.tool_ids.join(", ")} ({run.profile})
                </span>
                <div className="flex items-center gap-2">
                  <Badge
                    variant={
                      run.status === "completed"
                        ? "success"
                        : run.status === "failed"
                          ? "destructive"
                          : run.status === "cancelled"
                            ? "warning"
                            : "muted"
                    }
                  >
                    {run.status}
                  </Badge>
                  {(run.status === "pending" || run.status === "running") && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={cancellingRunId === run.id}
                      onClick={() => handleCancel(run.id)}
                    >
                      {cancellingRunId === run.id ? "Cancelling..." : "Cancel Scan"}
                    </Button>
                  )}
                </div>
              </div>
              {run.error_message && <p className="text-xs text-destructive">{run.error_message}</p>}
              {run.status === "cancelled" && (
                <p className="text-xs text-muted-foreground">This scan was cancelled before it finished.</p>
              )}
              {run.findings.length > 0 && (
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="text-muted-foreground">
                      <th className="py-1">Severity</th>
                      <th className="py-1">Finding</th>
                      <th className="py-1">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.findings.map((finding) => (
                      <tr
                        key={finding.id}
                        className="cursor-pointer border-t border-border/50 hover:bg-muted/30"
                        onClick={() => setActiveFinding(finding)}
                      >
                        <td className="py-1.5 pr-2">
                          <Badge variant={severityBadgeVariant(finding.severity)}>{finding.severity}</Badge>
                        </td>
                        <td className="py-1.5 pr-2 font-medium text-foreground">{finding.title}</td>
                        <td className="py-1.5 text-muted-foreground">{finding.target_detail ?? "--"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      </CardContent>

      <Dialog open={activeFinding !== null} onOpenChange={(open) => !open && setActiveFinding(null)}>
        <DialogContent>
          {activeFinding && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                  {activeFinding.title}
                </DialogTitle>
                <DialogDescription>{activeFinding.description}</DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-2 text-xs">
                <div className="flex items-center gap-2">
                  <Badge variant={severityBadgeVariant(activeFinding.severity)}>{activeFinding.severity}</Badge>
                  <span className="text-muted-foreground">{activeFinding.tool_id} -- {activeFinding.finding_type}</span>
                </div>
                {activeFinding.cve_ids.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {activeFinding.cve_ids.map((cve) => (
                      <Badge key={cve} variant="destructive">
                        {cve}
                      </Badge>
                    ))}
                  </div>
                )}
                <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/20 p-2 text-[11px]">
                  {JSON.stringify(activeFinding.evidence, null, 2)}
                </pre>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setActiveFinding(null)}>
                  Close
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
