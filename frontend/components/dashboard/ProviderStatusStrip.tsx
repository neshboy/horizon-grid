"use client";

/**
 * Compact "at a glance" per-provider status strip: one small colored dot +
 * name chip per provider that has reported in so far, sorted alphabetically.
 * Purely derived from the same `results` the page already accumulates from
 * provider_result SSE events (or the static lookup fetch) -- no fetching of
 * its own, and no attempt to guess at providers that haven't responded yet
 * (that's ProviderProgressTracker's job, in the sidebar). This sits in the
 * at-a-glance row so a viewer can see overall provider health in one
 * glance before drilling into the full ProviderCardGrid under the Evidence
 * tab.
 */

import { cn } from "@/lib/utils";
import type { ProviderResult, ProviderStatus } from "@/lib/types";

export interface ProviderStatusStripProps {
  results: ProviderResult[];
}

const DOT_CLASSES: Record<ProviderStatus, string> = {
  ok: "bg-success",
  error: "bg-destructive",
  timeout: "bg-warning",
  rate_limited: "bg-warning",
  not_configured: "bg-muted-foreground/40",
  unsupported_ioc: "bg-muted-foreground/40",
  no_data: "bg-muted-foreground/40",
  disabled: "bg-muted-foreground/40",
};

export function ProviderStatusStrip({ results }: ProviderStatusStripProps) {
  if (results.length === 0) {
    return <p className="text-xs text-muted-foreground">Waiting for providers to respond…</p>;
  }

  const sorted = [...results].sort((a, b) => a.provider_name.localeCompare(b.provider_name));

  return (
    <div className="flex flex-wrap gap-1.5">
      {sorted.map((result) => (
        <span
          key={result.provider_id}
          title={`${result.provider_name}: ${result.status.replace(/_/g, " ")}`}
          className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-2 py-1 text-[11px] text-foreground"
        >
          <span
            className={cn("h-2 w-2 shrink-0 rounded-full", DOT_CLASSES[result.status] ?? "bg-muted-foreground/40")}
            aria-hidden="true"
          />
          <span className="max-w-[9rem] truncate">{result.provider_name}</span>
        </span>
      ))}
    </div>
  );
}
