"use client";

/**
 * Provider Health: one row per IOC provider, defaulting to the 24h window's
 * status/success_rate/avg_latency_ms/consecutive_failures. Click a row to
 * expand a details panel with all 4 windows (1h/24h/7d/30d) side by side.
 *
 * success_rate and avg_latency_ms render "N/A" when null (a provider with
 * zero attempts in that window) -- NEVER "0%"/"0ms", which would misrepresent
 * "no data" as "measured and zero". "unknown" status is rendered via
 * ProviderHealthStatusBadge, which is visually and textually distinct from
 * "healthy" for exactly this reason.
 */

import { Fragment, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, ChevronRight } from "lucide-react";
import { TopSearchBar } from "@/components/dashboard/TopSearchBar";
import { WorkspaceNav } from "@/components/dashboard/WorkspaceNav";
import { ProviderHealthStatusBadge } from "@/components/dashboard/ProviderHealthStatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { getProviderHealth, isLoggedIn } from "@/lib/api";
import type { ProviderHealthEntry, ProviderHealthWindow } from "@/lib/types";
import { cn } from "@/lib/utils";

const WINDOWS: { key: "1h" | "24h" | "7d" | "30d"; label: string }[] = [
  { key: "1h", label: "1 Hour" },
  { key: "24h", label: "24 Hours" },
  { key: "7d", label: "7 Days" },
  { key: "30d", label: "30 Days" },
];

function formatPercent(value: number | null): string {
  return value === null || value === undefined ? "N/A" : `${value.toFixed(1)}%`;
}

function formatLatency(value: number | null): string {
  return value === null || value === undefined ? "N/A" : `${value.toFixed(0)} ms`;
}

function WindowDetailCard({ label, window }: { label: string; window: ProviderHealthWindow | undefined }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-background/50 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
        <ProviderHealthStatusBadge status={window?.status} />
      </div>
      <dl className="grid grid-cols-2 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Success rate</dt>
        <dd className="text-right tabular-nums">{formatPercent(window?.success_rate ?? null)}</dd>
        <dt className="text-muted-foreground">Avg latency</dt>
        <dd className="text-right tabular-nums">{formatLatency(window?.avg_latency_ms ?? null)}</dd>
        <dt className="text-muted-foreground">Consecutive failures</dt>
        <dd className="text-right tabular-nums">{window?.consecutive_failures ?? "N/A"}</dd>
        <dt className="text-muted-foreground">Rate-limited count</dt>
        <dd className="text-right tabular-nums">{window?.rate_limited_count ?? "N/A"}</dd>
      </dl>
    </div>
  );
}

export default function ProviderHealthPage() {
  const router = useRouter();
  const [providers, setProviders] = useState<ProviderHealthEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/dashboard/provider-health");
      return;
    }
    setLoading(true);
    getProviderHealth()
      .then((data: ProviderHealthEntry[]) => {
        setProviders(data);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load provider health");
      })
      .finally(() => setLoading(false));
  }, [router]);

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <div className="flex items-center justify-between gap-4">
          <TopSearchBar />
          <WorkspaceNav />
        </div>

        <div>
          <h1 className="text-xl font-semibold">Provider Health</h1>
          <p className="text-sm text-muted-foreground">
            Status, success rate, latency, and failure streaks for every IOC provider. Defaults to
            the 24-hour window -- click a row for 1h/24h/7d/30d side by side.
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <Card>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-4 py-2" />
                  <th className="px-4 py-2">Provider</th>
                  <th className="px-4 py-2">Category</th>
                  <th className="px-4 py-2">Configured</th>
                  <th className="px-4 py-2">Status (24h)</th>
                  <th className="px-4 py-2">Success Rate (24h)</th>
                  <th className="px-4 py-2">Avg Latency (24h)</th>
                  <th className="px-4 py-2">Consecutive Failures (24h)</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={8} className="px-4 py-6 text-center text-muted-foreground">
                      Loading provider health...
                    </td>
                  </tr>
                )}
                {!loading && providers.length === 0 && !error && (
                  <tr>
                    <td colSpan={8} className="px-4 py-6 text-center text-muted-foreground">
                      No providers configured.
                    </td>
                  </tr>
                )}
                {providers.map((p) => {
                  const isExpanded = expandedId === p.provider_id;
                  const window24h = p["24h"];
                  return (
                    <Fragment key={p.provider_id}>
                      <tr
                        className="cursor-pointer border-b border-border/50 last:border-none hover:bg-muted/30"
                        onClick={() => setExpandedId(isExpanded ? null : p.provider_id)}
                      >
                        <td className="px-4 py-2">
                          {isExpanded ? (
                            <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                          ) : (
                            <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                          )}
                        </td>
                        <td className="px-4 py-2 font-medium">{p.provider_name || p.provider_id}</td>
                        <td className="px-4 py-2 text-muted-foreground">{p.category}</td>
                        <td className="px-4 py-2 text-muted-foreground">
                          {p.configured ? "Yes" : p.requires_key ? "No" : "N/A (no key required)"}
                        </td>
                        <td className="px-4 py-2">
                          <ProviderHealthStatusBadge status={window24h?.status} />
                        </td>
                        <td className="px-4 py-2 tabular-nums text-muted-foreground">
                          {formatPercent(window24h?.success_rate ?? null)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-muted-foreground">
                          {formatLatency(window24h?.avg_latency_ms ?? null)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-muted-foreground">
                          {window24h?.consecutive_failures ?? "N/A"}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="border-b border-border/50 last:border-none">
                          <td colSpan={8} className={cn("bg-muted/10 px-4 py-3")}>
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                              {WINDOWS.map((w) => (
                                <WindowDetailCard key={w.key} label={w.label} window={p[w.key]} />
                              ))}
                            </div>
                            {p.supported_types.length > 0 && (
                              <p className="mt-3 text-xs text-muted-foreground">
                                Supported IOC types: {p.supported_types.join(", ")}
                              </p>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
