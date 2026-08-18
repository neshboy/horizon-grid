"use client";

import type { ProviderResult, ProviderSummary } from "@/lib/types";
import { ProviderCard } from "./ProviderCard";

export interface ProviderCardGridProps {
  results: ProviderResult[];
  summaries: Record<string, ProviderSummary>;
}

export function ProviderCardGrid({ results, summaries }: ProviderCardGridProps) {
  const sorted = [...results].sort((a, b) => {
    if (a.status === "ok" && b.status !== "ok") return -1;
    if (a.status !== "ok" && b.status === "ok") return 1;
    return 0;
  });

  if (sorted.length === 0) {
    return <p className="text-sm text-muted-foreground">No provider results yet.</p>;
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {sorted.map((result) => (
        <ProviderCard
          key={result.provider_id}
          result={result}
          summary={summaries[result.provider_id]}
        />
      ))}
    </div>
  );
}
