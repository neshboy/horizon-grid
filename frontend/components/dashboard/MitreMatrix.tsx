"use client";

/**
 * Compact MITRE ATT&CK matrix: FinalAssessment["mitre_mappings"] grouped into
 * one column per tactic, each technique rendered as a styled (non-linking)
 * cell showing technique_id / technique_name / kill_chain_stage, with the
 * AI-authored rationale surfaced via a @radix-ui/react-tooltip on hover.
 */

import * as React from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { MitreMapping } from "@/lib/types";

export interface MitreMatrixProps {
  mappings: MitreMapping[];
  loading?: boolean;
}

function formatTactic(tactic: string): string {
  return tactic.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function groupByTactic(mappings: MitreMapping[]): Map<string, MitreMapping[]> {
  const grouped = new Map<string, MitreMapping[]>();
  for (const mapping of mappings) {
    const key = mapping.tactic || "Unattributed";
    const bucket = grouped.get(key);
    if (bucket) {
      bucket.push(mapping);
    } else {
      grouped.set(key, [mapping]);
    }
  }
  return grouped;
}

function attckReferenceUrl(techniqueId: string): string {
  // T1071.001 -> /techniques/T1071/001/, T1071 -> /techniques/T1071/
  const [base, sub] = techniqueId.split(".");
  return sub
    ? `https://attack.mitre.org/techniques/${base}/${sub}/`
    : `https://attack.mitre.org/techniques/${base}/`;
}

function TechniqueCell({ mapping }: { mapping: MitreMapping }) {
  return (
    <Tooltip.Root delayDuration={150}>
      <Tooltip.Trigger asChild>
        <button
          type="button"
          onClick={() => window.open(attckReferenceUrl(mapping.technique_id), "_blank", "noopener,noreferrer")}
          className={cn(
            "flex w-full flex-col gap-1 rounded-md border border-border bg-muted/30 px-2.5 py-2 text-left transition-colors",
            "hover:border-primary/60 hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
          )}
        >
          <span className="flex items-center justify-between gap-1">
            <span className="text-xs font-semibold text-primary">{mapping.technique_id}</span>
            {!mapping.grounded && (
              <span
                className="rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-600 dark:text-amber-400"
                title="Not directly surfaced by a provider's data -- AI-inferred from context"
              >
                AI-inferred
              </span>
            )}
          </span>
          <span className="text-xs leading-snug text-foreground">{mapping.technique_name}</span>
          {mapping.kill_chain_stage && (
            <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
              {mapping.kill_chain_stage}
            </span>
          )}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="top"
          align="start"
          sideOffset={6}
          className="z-50 max-w-xs rounded-md border border-border bg-card px-3 py-2 text-xs leading-relaxed text-foreground shadow-md"
        >
          {mapping.rationale}
          <Tooltip.Arrow className="fill-card" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border py-10 text-center">
      <ShieldAlert className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm text-muted-foreground">No MITRE ATT&amp;CK techniques identified</p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
      <div className="h-8 w-8 animate-pulse rounded-full bg-primary/40" />
      <p className="animate-pulse text-sm text-muted-foreground">Waiting for the final assessment...</p>
    </div>
  );
}

export function MitreMatrix({ mappings, loading = false }: MitreMatrixProps) {
  const grouped = React.useMemo(() => groupByTactic(mappings), [mappings]);
  const tactics = React.useMemo(() => Array.from(grouped.keys()), [grouped]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>MITRE ATT&amp;CK Matrix</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <LoadingState />
        ) : mappings.length === 0 ? (
          <EmptyState />
        ) : (
          <Tooltip.Provider delayDuration={150}>
            <div className="grid grid-flow-col auto-cols-[minmax(11rem,1fr)] gap-3 overflow-x-auto pb-1">
              {tactics.map((tactic) => (
                <div key={tactic} className="flex flex-col gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {formatTactic(tactic)}
                  </span>
                  <div className="flex flex-col gap-2">
                    {(grouped.get(tactic) ?? []).map((mapping, index) => (
                      <TechniqueCell key={`${mapping.technique_id}-${index}`} mapping={mapping} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Tooltip.Provider>
        )}
      </CardContent>
    </Card>
  );
}
