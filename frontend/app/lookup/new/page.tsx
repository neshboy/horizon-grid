"use client";

/**
 * Composition root for a *live* IOC lookup. Reads the raw value the home
 * page search box navigated here with (?value=...), opens the SSE stream via
 * streamLookup(), and fans the incoming events out into local state consumed
 * by the real dashboard components under components/dashboard/ (ProviderCardGrid,
 * FinalAssessmentPanel, RelationshipGraph, MitreMatrix, and the rest).
 */

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getProviderHealth, isLoggedIn, streamLookup } from "@/lib/api";
import type {
  CorrelationPayload,
  FinalAssessment,
  ProviderResult,
  ProviderSummary,
} from "@/lib/types";
import { cn, verdictColor } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ThreatScoreGauge } from "@/components/dashboard/ThreatScoreGauge";
import { ProviderProgressTracker } from "@/components/dashboard/ProviderProgressTracker";
import { ProviderCardGrid } from "@/components/dashboard/ProviderCardGrid";
import { FinalAssessmentPanel } from "@/components/dashboard/FinalAssessmentPanel";
import { RelationshipGraph } from "@/components/dashboard/RelationshipGraph";
import { MitreMatrix } from "@/components/dashboard/MitreMatrix";
import { DetectionRulesPanel } from "@/components/dashboard/DetectionRulesPanel";
import { RecommendedActionsPanel } from "@/components/dashboard/RecommendedActionsPanel";
import { ExportMenu } from "@/components/dashboard/ExportMenu";
import { AskAiPanel } from "@/components/dashboard/AskAiPanel";
import { TopSearchBar } from "@/components/dashboard/TopSearchBar";
import { WorkspaceNav } from "@/components/dashboard/WorkspaceNav";
import { EvidencePanel } from "@/components/dashboard/EvidencePanel";
import { VerdictAnalysisPanel } from "@/components/dashboard/VerdictAnalysisPanel";
import { PivotPanel } from "@/components/dashboard/PivotPanel";
import { HuntingCenterPanel } from "@/components/dashboard/HuntingCenterPanel";
import { InvestigationCopilot } from "@/components/dashboard/InvestigationCopilot";
import { InvestigationActions } from "@/components/dashboard/InvestigationActions";
import { AiComparisonPanel } from "@/components/dashboard/AiComparisonPanel";
import { SecurityAssessmentPanel } from "@/components/dashboard/SecurityAssessmentPanel";

interface EventLogEntry {
  id: number;
  at: string;
  label: string;
}

function LookupNewPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawValue = searchParams.get("value") ?? "";

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace(`/login?next=${encodeURIComponent(`/lookup/new?value=${rawValue}`)}`);
    }
  }, [router, rawValue]);

  const [iocValue, setIocValue] = useState(rawValue);
  const [iocType, setIocType] = useState<string | null>(null);
  const [lookupId, setLookupId] = useState<string | null>(null);

  const [providerResults, setProviderResults] = useState<Record<string, ProviderResult>>({});
  const [providerSummaries, setProviderSummaries] = useState<Record<string, ProviderSummary>>({});
  const [correlation, setCorrelation] = useState<CorrelationPayload | null>(null);
  const [finalAssessment, setFinalAssessment] = useState<FinalAssessment | null>(null);

  const [streamError, setStreamError] = useState<string | null>(null);
  const [isDone, setIsDone] = useState(false);
  const [eventLog, setEventLog] = useState<EventLogEntry[]>([]);
  const [providerHealth, setProviderHealth] = useState<Array<{ supported_types: string[] }> | null>(null);
  const [highlightedEvidenceIds, setHighlightedEvidenceIds] = useState<string[] | undefined>(undefined);
  const eventCounter = useRef(0);

  useEffect(() => {
    getProviderHealth()
      .then((providers: Array<{ supported_types: string[] }>) => setProviderHealth(providers))
      .catch(() => setProviderHealth(null));
  }, []);

  const totalExpected = iocType && providerHealth
    ? providerHealth.filter((p) => p.supported_types.includes(iocType)).length
    : Object.keys(providerResults).length;

  const logEvent = (label: string) => {
    eventCounter.current += 1;
    setEventLog((prev) => [
      ...prev,
      { id: eventCounter.current, at: new Date().toLocaleTimeString(), label },
    ]);
  };

  useEffect(() => {
    if (!isLoggedIn()) return;

    if (!rawValue.trim()) {
      setStreamError("No IOC value provided (missing ?value= query param).");
      return;
    }

    const controller = new AbortController();

    streamLookup(
      rawValue.trim(),
      {
        onDetected: (payload) => {
          setLookupId(payload.lookup_id);
          setIocValue(payload.ioc_value);
          setIocType(payload.ioc_type);
          logEvent(`detected: ${payload.ioc_type}`);
        },
        onProviderResult: (payload) => {
          setProviderResults((prev) => ({ ...prev, [payload.provider_id]: payload }));
          logEvent(`provider_result: ${payload.provider_id} (${payload.status})`);
        },
        onProviderSummary: (payload) => {
          setProviderSummaries((prev) => ({ ...prev, [payload.provider_id]: payload }));
          logEvent(`provider_summary: ${payload.provider_id}`);
        },
        onCorrelation: (payload) => {
          setCorrelation(payload);
          logEvent(`correlation: ${payload.nodes.length} nodes / ${payload.edges.length} edges`);
        },
        onFinalAssessment: (payload) => {
          setFinalAssessment(payload);
          logEvent(`final_assessment: verdict=${payload.final_verdict}`);
        },
        onDone: () => {
          setIsDone(true);
          logEvent("done");
        },
        onError: (payload) => {
          setStreamError(payload.message);
          logEvent(`error: ${payload.message}`);
        },
        onAuthExpired: () => {
          router.replace(`/login?next=${encodeURIComponent(`/lookup/new?value=${rawValue}`)}`);
        },
      },
      controller.signal
    ).catch((err: unknown) => {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setStreamError(err instanceof Error ? err.message : "Unknown streaming error");
    });

    return () => controller.abort();
    // rawValue is derived once from the query param at mount; re-running this
    // effect is only desired if the user navigates to a brand new ?value=.
  }, [rawValue]);

  const verdict = finalAssessment?.final_verdict ?? null;

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <div className="flex items-center justify-between gap-4">
          <TopSearchBar initialValue={rawValue} />
          <WorkspaceNav />
        </div>

        {/* Header bar: IOC value + detected type + verdict badge placeholder */}
        <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">Investigating</span>
            <h1 className="break-all text-xl font-semibold">{iocValue || "(no value)"}</h1>
          </div>
          <div className="flex items-center gap-3">
            <span className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground">
              {iocType ?? "detecting..."}
            </span>
            <span
              className={cn(
                "rounded-full border border-border px-3 py-1 text-xs font-semibold uppercase tracking-wide",
                verdictColor(verdict)
              )}
            >
              {verdict ?? "pending"}
            </span>
            {isDone && (
              <span className="rounded-full border border-success/40 bg-success/10 px-3 py-1 text-xs font-medium text-success">
                complete
              </span>
            )}
          </div>
        </div>

        {streamError && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
            {streamError}
          </div>
        )}

        {/* 2-column responsive layout: main content spans 2 cols, sidebar is 1 col */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="flex flex-col gap-6 lg:col-span-2">
            <ThreatScoreGauge risk={finalAssessment?.risk ?? null} loading={!isDone} />

            <ProviderCardGrid
              results={Object.values(providerResults)}
              summaries={providerSummaries}
            />

            <FinalAssessmentPanel assessment={finalAssessment} />

            <RelationshipGraph data={correlation} />

            <MitreMatrix mappings={finalAssessment?.mitre_mappings ?? []} loading={!isDone} />

            <DetectionRulesPanel detectionRules={finalAssessment?.detection_rules ?? []} loading={!isDone} />

            <RecommendedActionsPanel assessment={finalAssessment} />

            {isDone && lookupId && (
              <>
                <AiComparisonPanel lookupId={lookupId} />
                <VerdictAnalysisPanel lookupId={lookupId} onShowReceipts={setHighlightedEvidenceIds} />
                <EvidencePanel lookupId={lookupId} highlightIds={highlightedEvidenceIds} />
                <PivotPanel lookupId={lookupId} />
                <HuntingCenterPanel lookupId={lookupId} />
                <InvestigationCopilot lookupId={lookupId} onShowReceipts={setHighlightedEvidenceIds} />
                {iocValue && <SecurityAssessmentPanel lookupId={lookupId} iocValue={iocValue} iocType={iocType} />}
              </>
            )}
          </div>

          <div className="flex flex-col gap-6">
            <ProviderProgressTracker
              results={providerResults}
              totalExpected={Math.max(totalExpected, 1)}
            />

            {lookupId && <ExportMenu lookupId={lookupId} assessment={finalAssessment} />}

            {iocValue && <InvestigationActions iocValue={iocValue} iocType={iocType} lookupId={lookupId} />}

            <AskAiPanel
              iocValue={iocValue}
              iocType={iocType}
              providerResults={Object.values(providerResults)}
              providerSummaries={providerSummaries}
              correlation={correlation}
            />

            {/* Debug: raw SSE event log, newest at the bottom */}
            <Card>
              <CardHeader>
                <CardTitle>Event log (debug)</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="max-h-64 space-y-1 overflow-y-auto text-xs text-muted-foreground">
                  {eventLog.length === 0 && <li>Waiting for events...</li>}
                  {eventLog.map((entry) => (
                    <li key={entry.id} className="border-b border-border/50 pb-1 last:border-none">
                      <span className="text-muted-foreground/70">{entry.at}</span> {entry.label}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </main>
  );
}

function LookupNewPageKeyed() {
  // Keyed on the raw ?value= so pivoting to a new IOC via TopSearchBar --
  // which pushes a new ?value= onto this same route -- fully remounts
  // LookupNewPageInner instead of reusing the mounted instance. Without
  // this, React would keep all of the previous IOC's state (provider
  // results, summaries, event log) and the new SSE stream's events would
  // land mixed in with it.
  const rawValue = useSearchParams().get("value") ?? "";
  return <LookupNewPageInner key={rawValue} />;
}

export default function LookupNewPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading...</div>}>
      <LookupNewPageKeyed />
    </Suspense>
  );
}
