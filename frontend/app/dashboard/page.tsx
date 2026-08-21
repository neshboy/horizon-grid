"use client";

/**
 * Executive Dashboard: the 30,000-foot view of the platform's current state
 * -- 7 top-line KPIs, an AI (or template-fallback) narrative summary, and a
 * compact provider-health widget linking to the full Provider Health page.
 *
 * Every number on this page comes from a real API response (getKpis(),
 * getExecutiveSummary(), getProviderHealth()) -- nothing here is hardcoded.
 *
 * getExecutiveSummary() hits a brand-new backend endpoint that may not exist
 * yet on every environment (404) or may fail for other reasons -- both are
 * handled with a graceful "Executive summary unavailable" fallback rather
 * than a crash, independent of whether the KPI tiles above loaded fine.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  FileWarning,
  FolderKanban,
  Gauge,
  Server,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { BrandHeader } from "@/components/dashboard/BrandHeader";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { ProviderHealthStatusBadge } from "@/components/dashboard/ProviderHealthStatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getExecutiveSummary, getKpis, getProviderHealth, isLoggedIn } from "@/lib/api";
import type { DashboardKpis, ExecutiveSummary, ProviderHealthEntry, ProviderHealthStatus } from "@/lib/types";
import { cn, riskScoreColor } from "@/lib/utils";

function SummarySkeleton() {
  return (
    <div className="flex flex-col gap-2">
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-11/12 animate-pulse rounded bg-muted" />
      <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
    </div>
  );
}

const HEALTH_ORDER: ProviderHealthStatus[] = ["healthy", "degraded", "down", "unknown"];

export default function DashboardPage() {
  const router = useRouter();

  const [kpis, setKpis] = useState<DashboardKpis | null>(null);
  const [kpisError, setKpisError] = useState<string | null>(null);
  const [kpisLoading, setKpisLoading] = useState(true);

  const [summary, setSummary] = useState<ExecutiveSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);

  const [providers, setProviders] = useState<ProviderHealthEntry[] | null>(null);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [providersLoading, setProvidersLoading] = useState(true);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/dashboard");
      return;
    }

    setKpisLoading(true);
    getKpis()
      .then((data) => {
        setKpis(data);
        setKpisError(null);
      })
      .catch((err: unknown) => {
        setKpisError(err instanceof Error ? err.message : "Failed to load KPIs");
      })
      .finally(() => setKpisLoading(false));

    setSummaryLoading(true);
    getExecutiveSummary()
      .then((data) => {
        setSummary(data);
        setSummaryError(null);
      })
      .catch(() => {
        // Expected while the executive-summary endpoint hasn't been
        // propagated+rebuilt yet -- render the fallback message below rather
        // than surface a raw error.
        setSummaryError("Executive summary unavailable");
      })
      .finally(() => setSummaryLoading(false));

    setProvidersLoading(true);
    getProviderHealth()
      .then((data: ProviderHealthEntry[]) => {
        setProviders(data);
        setProvidersError(null);
      })
      .catch((err: unknown) => {
        setProvidersError(err instanceof Error ? err.message : "Failed to load provider health");
      })
      .finally(() => setProvidersLoading(false));
  }, [router]);

  const healthCounts: Record<ProviderHealthStatus, number> = {
    healthy: 0,
    degraded: 0,
    down: 0,
    unknown: 0,
  };
  (providers ?? []).forEach((p) => {
    const status = p["24h"]?.status;
    if (status && status in healthCounts) {
      healthCounts[status] += 1;
    } else {
      healthCounts.unknown += 1;
    }
  });
  const nonHealthyProviders = (providers ?? []).filter((p) => p["24h"]?.status !== "healthy");

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <BrandHeader />

        <div>
          <h1 className="font-display text-sm uppercase tracking-[0.08em] text-muted-foreground">
            Executive Dashboard
          </h1>
          <p className="text-sm text-muted-foreground">
            Platform-wide status at a glance -- investigations, cases, provider health, and AI
            performance.
          </p>
        </div>

        {kpisError && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {kpisError}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Active Investigations"
            value={kpisLoading ? null : kpis?.active_investigations ?? null}
            icon={Activity}
            nullLabel={kpisLoading ? "…" : "N/A"}
          />
          <KpiCard
            label="Critical / High-Risk IOCs"
            value={kpisLoading ? null : kpis?.critical_high_risk_iocs ?? null}
            icon={ShieldAlert}
            nullLabel={kpisLoading ? "…" : "N/A"}
          />
          <KpiCard
            label="Open Cases"
            value={kpisLoading ? null : kpis?.open_cases ?? null}
            icon={FolderKanban}
            nullLabel={kpisLoading ? "…" : "N/A"}
          />
          <KpiCard
            label="Open Critical Cases"
            value={kpisLoading ? null : kpis?.open_critical_cases ?? null}
            icon={FileWarning}
            nullLabel={kpisLoading ? "…" : "N/A"}
          />
          <KpiCard
            label="Avg Threat Score"
            value={kpisLoading ? null : kpis?.avg_threat_score ?? null}
            icon={Gauge}
            caption="out of 100"
            nullLabel={kpisLoading ? "…" : "N/A"}
            valueClassName={
              !kpisLoading && kpis ? riskScoreColor(kpis.avg_threat_score) : undefined
            }
          />
          <KpiCard
            label="Provider Health"
            value={kpisLoading ? null : kpis?.provider_health_percentage ?? null}
            suffix="%"
            icon={Server}
            nullLabel={kpisLoading ? "…" : "N/A"}
          />
          <KpiCard
            label="AI Success Rate (30d)"
            value={kpisLoading ? null : kpis?.ai_success_rate ?? null}
            suffix="%"
            icon={Sparkles}
            caption={
              !kpisLoading && kpis && kpis.ai_success_rate === null
                ? "No AI activity in the last 30 days"
                : undefined
            }
            nullLabel={kpisLoading ? "…" : "N/A"}
          />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader className="flex-row items-center justify-between gap-2">
              <CardTitle>Executive Summary</CardTitle>
              {summary && (
                <Badge variant={summary.source === "ai" ? "default" : "muted"}>
                  {summary.source === "ai" ? "AI-generated" : "Template fallback"}
                </Badge>
              )}
            </CardHeader>
            <CardContent>
              {summaryLoading ? (
                <SummarySkeleton />
              ) : summary ? (
                <p className="whitespace-pre-wrap text-sm leading-relaxed">{summary.summary}</p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {summaryError ?? "Executive summary unavailable"} -- KPI tiles above still reflect
                  live data.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Provider Health (24h)</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {providersLoading ? (
                <div className="flex flex-col gap-2">
                  <div className="h-4 w-full animate-pulse rounded bg-muted" />
                  <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
                </div>
              ) : providersError ? (
                <p className="text-sm text-muted-foreground">{providersError}</p>
              ) : (
                <>
                  <div className="flex flex-wrap gap-2">
                    {HEALTH_ORDER.map((status) => (
                      <div key={status} className="flex items-center gap-1.5">
                        <ProviderHealthStatusBadge status={status} />
                        <span className="text-xs font-medium font-data tabular-nums text-muted-foreground">
                          {healthCounts[status]}
                        </span>
                      </div>
                    ))}
                  </div>

                  {nonHealthyProviders.length > 0 ? (
                    <ul className="flex flex-col gap-1.5 text-xs">
                      {nonHealthyProviders.slice(0, 5).map((p) => (
                        <li key={p.provider_id} className="flex items-center justify-between gap-2">
                          <span className="truncate text-muted-foreground">{p.provider_name}</span>
                          <ProviderHealthStatusBadge status={p["24h"]?.status} />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      All configured providers are healthy in the last 24h.
                    </p>
                  )}
                </>
              )}

              <Link
                href="/dashboard/provider-health"
                className={cn(
                  "mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary",
                  "hover:underline"
                )}
              >
                View full Provider Health status
                <ArrowRight className="h-3 w-3" aria-hidden="true" />
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
