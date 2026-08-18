"use client";

/**
 * The evidence ledger for a completed lookup -- deterministically built by
 * backend/app/evidence/builder.py from provider summaries + correlation
 * edges, never by an AI call. This is the "Show Receipts" surface: every
 * AI-generated explanation elsewhere in the workspace (WHY, Challenge,
 * Score Explanation, Copilot) cites evidence_ids that resolve to rows here,
 * so an analyst can always click through from a claim to its source.
 */

import * as React from "react";
import { ChevronDown, ChevronRight, ExternalLink, FileSearch } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getEvidence } from "@/lib/api";
import type { EvidenceItem } from "@/lib/types";

export interface EvidencePanelProps {
  lookupId: string;
  /** When set, only evidence whose id is in this set is shown -- used by
   * "Show Receipts" to jump straight to the records backing one AI claim. */
  highlightIds?: string[];
}

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  detection: "Detection",
  reputation: "Reputation",
  relationship: "Relationship",
  malware_association: "Malware association",
  threat_actor_association: "Threat actor association",
  campaign_association: "Campaign association",
  mitre_technique: "MITRE technique",
  infrastructure: "Infrastructure",
  other: "Other",
};

function confidenceColor(confidence: number): string {
  if (confidence >= 75) return "text-destructive";
  if (confidence >= 40) return "text-warning";
  return "text-muted-foreground";
}

function EvidenceRow({ item, expanded, onToggle, highlighted }: {
  item: EvidenceItem;
  expanded: boolean;
  onToggle: () => void;
  highlighted: boolean;
}) {
  return (
    <div
      id={`evidence-${item.id}`}
      className={cn(
        "rounded-md border border-border/60 bg-muted/20 transition-colors",
        highlighted && "border-primary bg-primary/10"
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            {EVIDENCE_TYPE_LABELS[item.evidence_type] ?? item.evidence_type}
          </span>
          <span className="truncate text-xs text-foreground">{item.claim}</span>
        </div>
        <span className={cn("shrink-0 text-xs font-medium tabular-nums", confidenceColor(item.confidence))}>
          {item.confidence.toFixed(0)}%
        </span>
      </button>
      {expanded && (
        <div className="flex flex-col gap-1.5 border-t border-border/60 px-3 py-2 text-xs">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
            <span>
              Source: <span className="text-foreground">{item.source_label}</span>
            </span>
            {item.related_ioc_value && (
              <span>
                Related IOC: <span className="text-foreground">{item.related_ioc_type}:{item.related_ioc_value}</span>
              </span>
            )}
            {item.observed_at && <span>Observed: <span className="text-foreground">{item.observed_at}</span></span>}
            <span>Recorded: <span className="text-foreground">{new Date(item.created_at).toLocaleString()}</span></span>
          </div>
          {item.interpretation && <p className="text-foreground">{item.interpretation}</p>}
          {item.source_url && (
            <a
              href={item.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              Original source <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export function EvidencePanel({ lookupId, highlightIds }: EvidencePanelProps) {
  const [evidence, setEvidence] = React.useState<EvidenceItem[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [expandedIds, setExpandedIds] = React.useState<Set<string>>(new Set());
  const [typeFilter, setTypeFilter] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    getEvidence(lookupId)
      .then((items) => {
        if (!cancelled) setEvidence(items);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load evidence");
      });
    return () => {
      cancelled = true;
    };
  }, [lookupId]);

  React.useEffect(() => {
    if (highlightIds && highlightIds.length > 0) {
      setExpandedIds(new Set(highlightIds));
      const first = document.getElementById(`evidence-${highlightIds[0]}`);
      first?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightIds]);

  const toggle = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const types = React.useMemo(() => {
    if (!evidence) return [];
    return Array.from(new Set(evidence.map((e) => e.evidence_type)));
  }, [evidence]);

  const filtered = React.useMemo(() => {
    if (!evidence) return [];
    const base = highlightIds && highlightIds.length > 0 ? evidence.filter((e) => highlightIds.includes(e.id)) : evidence;
    return typeFilter ? base.filter((e) => e.evidence_type === typeFilter) : base;
  }, [evidence, typeFilter, highlightIds]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          <FileSearch className="h-4 w-4" aria-hidden="true" />
          Evidence Ledger
          {evidence && <span className="text-xs font-normal text-muted-foreground">({evidence.length})</span>}
        </CardTitle>
        {evidence && types.length > 1 && !highlightIds && (
          <div className="flex flex-wrap gap-1">
            <button
              type="button"
              onClick={() => setTypeFilter(null)}
              className={cn(
                "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide",
                !typeFilter ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
              )}
            >
              All
            </button>
            {types.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTypeFilter(t)}
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide",
                  typeFilter === t ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
                )}
              >
                {EVIDENCE_TYPE_LABELS[t] ?? t}
              </button>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-1.5">
        {error && <p className="text-xs text-destructive">{error}</p>}
        {!evidence && !error && <p className="text-xs text-muted-foreground">Loading evidence...</p>}
        {evidence && filtered.length === 0 && (
          <p className="text-xs text-muted-foreground">No evidence recorded for this lookup.</p>
        )}
        <div className="flex max-h-96 flex-col gap-1.5 overflow-y-auto">
          {filtered.map((item) => (
            <EvidenceRow
              key={item.id}
              item={item}
              expanded={expandedIds.has(item.id)}
              onToggle={() => toggle(item.id)}
              highlighted={!!highlightIds?.includes(item.id)}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
