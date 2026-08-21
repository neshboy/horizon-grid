"use client";

/**
 * Composition root for viewing an *already-completed* lookup by id (no SSE --
 * a single fetch via getLookup() on mount). Renders the same real dashboard
 * components as app/lookup/new/page.tsx (ProviderCardGrid, FinalAssessmentPanel,
 * RelationshipGraph, etc.) from the fetched data instead of a live stream.
 *
 * Note on shape mismatches with the live stream: GET /api/v1/lookup/{id}
 * (see backend/app/api/routes/lookup.py get_lookup) rebuilds `correlation`
 * from persisted CorrelationEdgeRecord rows rather than returning the live
 * SSE event verbatim, but matches its {nodes, edges} shape. Its
 * `provider_results` rows also omit a few ProviderResult fields the SSE
 * `provider_result` event includes (ioc_value, ioc_type, fetched_at,
 * from_cache) -- those are backfilled from the parent lookup / sane defaults
 * below so the shared ProviderResult type still applies verbatim.
 */

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getLookup, isLoggedIn } from "@/lib/api";
import type {
  CorrelationPayload,
  FinalAssessment,
  ProviderResult,
  ProviderSummary,
} from "@/lib/types";
import { cn, verdictColor } from "@/lib/utils";
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
import { BrandHeader } from "@/components/dashboard/BrandHeader";
import { EvidencePanel } from "@/components/dashboard/EvidencePanel";
import { VerdictAnalysisPanel } from "@/components/dashboard/VerdictAnalysisPanel";
import { PivotPanel } from "@/components/dashboard/PivotPanel";
import { HuntingCenterPanel } from "@/components/dashboard/HuntingCenterPanel";
import { InvestigationCopilot } from "@/components/dashboard/InvestigationCopilot";
import { InvestigationActions } from "@/components/dashboard/InvestigationActions";
import { SecurityAssessmentPanel } from "@/components/dashboard/SecurityAssessmentPanel";

interface RawProviderResultRow {
  provider_id: string;
  provider_name: string;
  category: string;
  status: string;
  data: Record<string, unknown>;
  source_url?: string | null;
  error_message?: string | null;
  latency_ms?: number | null;
}

interface RawLookupDetail {
  id: string;
  ioc_value: string;
  ioc_type: string;
  status: string;
  final_verdict?: string | null;
  risk_score?: number | null;
  confidence_score?: number | null;
  final_assessment?: FinalAssessment | null;
  provider_results: RawProviderResultRow[];
  ai_summaries: ProviderSummary[];
  created_at: string;
  correlation?: CorrelationPayload | null;
}

export default function LookupDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const lookupId = params?.id;

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace(`/login?next=${encodeURIComponent(`/lookup/${lookupId ?? ""}`)}`);
    }
  }, [router, lookupId]);

  const [iocValue, setIocValue] = useState<string>("");
  const [iocType, setIocType] = useState<string | null>(null);
  const [providerResults, setProviderResults] = useState<Record<string, ProviderResult>>({});
  const [providerSummaries, setProviderSummaries] = useState<Record<string, ProviderSummary>>({});
  const [correlation, setCorrelation] = useState<CorrelationPayload | null>(null);
  const [finalAssessment, setFinalAssessment] = useState<FinalAssessment | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [highlightedEvidenceIds, setHighlightedEvidenceIds] = useState<string[] | undefined>(undefined);

  useEffect(() => {
    if (!lookupId || !isLoggedIn()) return;
    let cancelled = false;

    setLoading(true);
    setLoadError(null);

    getLookup(lookupId)
      .then((raw: RawLookupDetail) => {
        if (cancelled) return;

        setIocValue(raw.ioc_value);
        setIocType(raw.ioc_type);
        setStatus(raw.status);

        const resultsById: Record<string, ProviderResult> = {};
        for (const row of raw.provider_results ?? []) {
          resultsById[row.provider_id] = {
            provider_id: row.provider_id,
            provider_name: row.provider_name,
            category: row.category,
            status: row.status as ProviderResult["status"],
            ioc_value: raw.ioc_value,
            ioc_type: raw.ioc_type,
            data: row.data,
            source_url: row.source_url ?? null,
            error_message: row.error_message ?? null,
            latency_ms: row.latency_ms ?? null,
            fetched_at: 0,
            from_cache: false,
          };
        }
        setProviderResults(resultsById);

        const summariesById: Record<string, ProviderSummary> = {};
        for (const summary of raw.ai_summaries ?? []) {
          summariesById[summary.provider_id] = summary;
        }
        setProviderSummaries(summariesById);

        setCorrelation(raw.correlation ?? null);
        setFinalAssessment(raw.final_assessment ?? null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "Failed to load lookup");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [lookupId]);

  const verdict = finalAssessment?.final_verdict ?? null;
  const isCompleted = status === "completed";

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <BrandHeader />

        {/* Header bar: IOC value + detected type + verdict badge placeholder */}
        <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">
              Lookup <span className="font-data tabular-nums">{lookupId}</span>
            </span>
            <h1 className="break-all font-display text-xl font-semibold tracking-wide">
              {loading ? "Loading..." : iocValue || "(no value)"}
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <span className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground">
              {iocType ?? "unknown"}
            </span>
            <span
              className={cn(
                "rounded-full border border-border px-3 py-1 text-xs font-semibold uppercase tracking-wide",
                verdictColor(verdict)
              )}
            >
              {verdict ?? "pending"}
            </span>
            {status && (
              <span className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground">
                {status}
              </span>
            )}
          </div>
        </div>

        {loadError && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
            {loadError}
          </div>
        )}

        {/* 2-column responsive layout: main content spans 2 cols, sidebar is 1 col */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="flex flex-col gap-6 lg:col-span-2">
            <ThreatScoreGauge risk={finalAssessment?.risk ?? null} loading={loading} />

            <ProviderCardGrid
              results={Object.values(providerResults)}
              summaries={providerSummaries}
            />

            <FinalAssessmentPanel assessment={finalAssessment} />

            <RelationshipGraph data={correlation} />

            <MitreMatrix mappings={finalAssessment?.mitre_mappings ?? []} loading={loading} />

            <DetectionRulesPanel detectionRules={finalAssessment?.detection_rules ?? []} loading={loading} />

            <RecommendedActionsPanel assessment={finalAssessment} />

            {isCompleted && lookupId && (
              <>
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
              totalExpected={Math.max(Object.keys(providerResults).length, 1)}
            />

            {lookupId && <ExportMenu lookupId={lookupId} assessment={finalAssessment} />}

            {iocValue && <InvestigationActions iocValue={iocValue} iocType={iocType} lookupId={lookupId ?? null} />}

            <AskAiPanel
              iocValue={iocValue}
              iocType={iocType}
              providerResults={Object.values(providerResults)}
              providerSummaries={providerSummaries}
              correlation={correlation}
            />

            <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
              {loading ? "Loading static lookup data..." : "Static lookup data loaded (no live SSE stream)."}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
