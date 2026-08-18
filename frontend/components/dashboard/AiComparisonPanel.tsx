"use client";

/**
 * "Analyze with a different AI" comparison feature (Phase 10 of the
 * runtime-provider master prompt): once an investigation's evidence has
 * been collected, an analyst can re-run JUST the final-assessment AI step
 * against a different backend -- e.g. compare Claude vs. Groq vs. local
 * Ollama on the exact same evidence -- without re-querying any provider.
 * Every result (the original plus every comparison) is durable
 * (GET /api/v1/lookup/{id}/assessments) and clearly attributed to which
 * backend/model produced it -- never silently presented as "the" answer.
 */

import { useEffect, useState } from "react";
import { listAIProviders, listAssessments, reanalyzeLookup } from "@/lib/api";
import type { AssessmentRecord, RuntimeProviderConfig } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn, verdictColor } from "@/lib/utils";

export interface AiComparisonPanelProps {
  lookupId: string;
}

function formatVerdict(verdict: string): string {
  return verdict.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function AiComparisonPanel({ lookupId }: AiComparisonPanelProps) {
  const [records, setRecords] = useState<AssessmentRecord[]>([]);
  const [providers, setProviders] = useState<RuntimeProviderConfig[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    listAssessments(lookupId)
      .then(setRecords)
      .catch(() => setRecords([]));
  };

  useEffect(() => {
    refresh();
    listAIProviders()
      .then((list) => {
        setProviders(list);
        const firstOther = list.find((p) => p.provider_id);
        if (firstOther) setSelected(firstOther.provider_id);
      })
      .catch(() => setProviders([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lookupId]);

  const handleAnalyze = async () => {
    if (!selected) return;
    setRunning(true);
    setError(null);
    try {
      await reanalyzeLookup(lookupId, selected);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-analysis failed");
    } finally {
      setRunning(false);
    }
  };

  const alreadyRunBackends = new Set(records.map((r) => r.ai_backend));

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Comparison</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-xs text-muted-foreground">
          Re-run the final assessment against a different AI backend, using the exact same
          collected evidence -- no providers are re-queried. Neither result is presented as
          more correct than the other; compare quality, consistency, and evidence use yourself.
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="rounded-md border border-border bg-card px-2 py-1.5 text-sm outline-none focus-visible:ring-1 focus-visible:ring-primary"
          >
            {providers.map((p) => (
              <option key={p.provider_id} value={p.provider_id}>
                {p.provider_id}
                {alreadyRunBackends.has(p.provider_id) ? " (already run)" : ""}
              </option>
            ))}
          </select>
          <Button size="sm" onClick={handleAnalyze} disabled={running || !selected}>
            {running ? "Analyzing..." : `Analyze with ${selected || "..."}`}
          </Button>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex flex-col gap-3">
          {records.map((r) => (
            <div key={r.id} className="flex flex-col gap-2 rounded-lg border border-border bg-muted/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {r.is_primary ? "Original" : "Comparison"} &middot;{" "}
                  <span className="text-foreground">{r.ai_backend}</span>
                  {r.ai_model ? <span className="font-mono text-muted-foreground"> ({r.ai_model})</span> : null}
                </span>
                <span
                  className={cn(
                    "rounded-full border-2 border-current px-2.5 py-0.5 text-xs font-bold",
                    verdictColor(r.assessment.final_verdict)
                  )}
                >
                  {formatVerdict(r.assessment.final_verdict)}
                </span>
              </div>
              <p className="text-sm text-foreground">{r.assessment.executive_summary}</p>
              <div className="flex gap-4 text-xs text-muted-foreground">
                <span>Risk: {r.assessment.risk.overall_risk_score.toFixed(0)}/100</span>
                <span>Confidence: {r.assessment.risk.confidence_score.toFixed(0)}/100</span>
                <span>Malicious probability: {r.assessment.risk.malicious_probability.toFixed(0)}%</span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
