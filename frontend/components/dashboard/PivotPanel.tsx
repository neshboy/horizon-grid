"use client";

/**
 * "Recommended pivots" -- a deterministic ranked list of every IOC directly
 * related to the seed (backend/app/evidence/pivot.py, a pure sort, never
 * AI-generated) plus the AI's "smart next actions" narrative on top of the
 * same graph. One click on any pivot navigates straight to investigating it.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Compass, HelpCircle, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getIntelligenceGaps, getNextActions, getPivots } from "@/lib/api";
import type { IntelligenceGap, NextAction, PivotSuggestion } from "@/lib/types";

export interface PivotPanelProps {
  lookupId: string;
}

function relevanceBadgeClass(relevance: string): string {
  switch (relevance) {
    case "high":
      return "border-destructive/40 bg-destructive/10 text-destructive";
    case "medium":
      return "border-warning/40 bg-warning/10 text-warning";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function priorityBadgeClass(priority: string): string {
  switch (priority) {
    case "high":
      return "border-destructive/40 bg-destructive/10 text-destructive";
    case "medium":
      return "border-warning/40 bg-warning/10 text-warning";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

export function PivotPanel({ lookupId }: PivotPanelProps) {
  const router = useRouter();
  const [pivots, setPivots] = React.useState<PivotSuggestion[] | null>(null);
  const [nextActions, setNextActions] = React.useState<NextAction[] | null>(null);
  const [loadingActions, setLoadingActions] = React.useState(false);
  const [gaps, setGaps] = React.useState<IntelligenceGap[] | null>(null);
  const [loadingGaps, setLoadingGaps] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    getPivots(lookupId)
      .then((result) => {
        if (!cancelled) setPivots(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load pivots");
      });
    return () => {
      cancelled = true;
    };
  }, [lookupId]);

  const handleGenerateNextActions = React.useCallback(async () => {
    setLoadingActions(true);
    try {
      const result = await getNextActions(lookupId);
      setNextActions(result.actions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate next actions");
    } finally {
      setLoadingActions(false);
    }
  }, [lookupId]);

  const handleGenerateGaps = React.useCallback(async () => {
    setLoadingGaps(true);
    try {
      const result = await getIntelligenceGaps(lookupId);
      setGaps(result.gaps);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to identify intelligence gaps");
    } finally {
      setLoadingGaps(false);
    }
  }, [lookupId]);

  const investigate = (iocValue: string) => {
    router.push(`/lookup/new?value=${encodeURIComponent(iocValue)}`);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Compass className="h-4 w-4" aria-hidden="true" />
          Pivot
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className="flex flex-col gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Recommended pivots
          </span>
          {!pivots && <p className="text-xs text-muted-foreground">Loading...</p>}
          {pivots && pivots.length === 0 && (
            <p className="text-xs text-muted-foreground">No directly related indicators discovered yet.</p>
          )}
          {pivots?.map((p) => (
            <button
              key={`${p.ioc_type}:${p.ioc_value}`}
              type="button"
              onClick={() => investigate(p.ioc_value)}
              className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 text-left transition-colors hover:border-primary/60 hover:bg-primary/10"
            >
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate text-sm font-medium text-foreground">{p.ioc_value}</span>
                <span className="text-[11px] text-muted-foreground">
                  {p.ioc_type} · {p.relationship.replace(/_/g, " ")} · {p.corroborating_providers} provider
                  {p.corroborating_providers === 1 ? "" : "s"} · {p.confidence.toFixed(0)}% confidence
                </span>
              </div>
              <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase", relevanceBadgeClass(p.relevance))}>
                {p.relevance}
              </span>
              <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <Lightbulb className="h-3.5 w-3.5" aria-hidden="true" />
              What should I do next?
            </span>
            <Button size="sm" variant="outline" onClick={handleGenerateNextActions} disabled={loadingActions}>
              {loadingActions ? "Thinking..." : nextActions ? "Regenerate" : "Ask AI"}
            </Button>
          </div>
          {nextActions?.map((action, i) => (
            <div key={i} className="flex flex-col gap-1 rounded-md border border-border bg-muted/20 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-foreground">{action.action}</span>
                <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase", priorityBadgeClass(action.priority))}>
                  {action.priority}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">{action.rationale}</p>
              {action.target_ioc_value && (
                <Button size="sm" variant="outline" className="w-fit" onClick={() => investigate(action.target_ioc_value!)}>
                  Investigate {action.target_ioc_value}
                  <ArrowRight className="h-3 w-3" aria-hidden="true" />
                </Button>
              )}
            </div>
          ))}
          {nextActions && nextActions.length === 0 && (
            <p className="text-xs text-muted-foreground">No high-value next actions identified.</p>
          )}
        </div>

        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" />
              What don&apos;t we know?
            </span>
            <Button size="sm" variant="outline" onClick={handleGenerateGaps} disabled={loadingGaps}>
              {loadingGaps ? "Thinking..." : gaps ? "Regenerate" : "Ask AI"}
            </Button>
          </div>
          {gaps?.map((gap, i) => (
            <div key={i} className="flex flex-col gap-1 rounded-md border border-border bg-muted/20 px-3 py-2">
              <span className="text-sm font-medium text-foreground">{gap.gap}</span>
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">How to close it: </span>
                {gap.how_to_close}
              </p>
            </div>
          ))}
          {gaps && gaps.length === 0 && (
            <p className="text-xs text-muted-foreground">No significant intelligence gaps identified.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
