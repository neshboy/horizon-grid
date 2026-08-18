"use client";

/**
 * Live "who has answered so far" list for a lookup in progress. Purely
 * derived from the `results` map the page-level component accumulates from
 * provider_result SSE events -- this component does no fetching of its own.
 *
 * Providers that haven't reported yet aren't identifiable (the SSE stream
 * only tells us about a provider once it responds), so the gap between
 * `totalExpected` and the number of keys in `results` is rendered as
 * anonymous "running" placeholder rows with a spinner.
 */

import {
  BookUser,
  Bug,
  CheckCircle2,
  Clock,
  FileKey,
  FlaskConical,
  Globe,
  Loader2,
  MinusCircle,
  Network,
  ShieldAlert,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ProviderResult, ProviderStatus } from "@/lib/types";

export interface ProviderProgressTrackerProps {
  results: Record<string, ProviderResult>;
  totalExpected: number;
}

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  threat_intel: ShieldAlert,
  sandbox: FlaskConical,
  passive_dns: Network,
  certificate_intel: FileKey,
  whois: BookUser,
  vulnerability: Bug,
  osint: Globe,
};

function categoryIcon(category: string): LucideIcon {
  return CATEGORY_ICONS[category] ?? Globe;
}

interface StatusBadgeSpec {
  label: string;
  icon: LucideIcon;
  className: string;
  spin?: boolean;
}

const STATUS_BADGES: Record<ProviderStatus, StatusBadgeSpec> = {
  ok: { label: "OK", icon: CheckCircle2, className: "border-success/40 bg-success/10 text-success" },
  error: { label: "Error", icon: XCircle, className: "border-destructive/40 bg-destructive/10 text-destructive" },
  timeout: { label: "Timeout", icon: Clock, className: "border-warning/40 bg-warning/10 text-warning" },
  rate_limited: { label: "Rate Limited", icon: Clock, className: "border-warning/40 bg-warning/10 text-warning" },
  not_configured: {
    label: "Not Configured",
    icon: MinusCircle,
    className: "border-border bg-muted text-muted-foreground",
  },
  unsupported_ioc: {
    label: "Unsupported",
    icon: MinusCircle,
    className: "border-border bg-muted text-muted-foreground",
  },
  no_data: { label: "No Data", icon: MinusCircle, className: "border-border bg-muted text-muted-foreground" },
  disabled: { label: "Disabled", icon: MinusCircle, className: "border-border bg-muted text-muted-foreground" },
};

const RUNNING_BADGE: StatusBadgeSpec = {
  label: "Running",
  icon: Loader2,
  className: "border-primary/40 bg-primary/10 text-primary",
  spin: true,
};

function StatusBadge({ spec }: { spec: StatusBadgeSpec }) {
  const Icon = spec.icon;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        spec.className
      )}
    >
      <Icon className={cn("h-3 w-3", spec.spin && "animate-spin")} />
      {spec.label}
    </span>
  );
}

function ProviderRow({ result }: { result: ProviderResult }) {
  const Icon = categoryIcon(result.category);
  const badge = STATUS_BADGES[result.status] ?? RUNNING_BADGE;

  return (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <div className="flex min-w-0 items-center gap-2">
        <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="truncate text-sm text-foreground">{result.provider_name}</span>
      </div>
      <StatusBadge spec={badge} />
    </div>
  );
}

function PendingRow({ index }: { index: number }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <div className="flex min-w-0 items-center gap-2">
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
        <span className="truncate text-sm text-muted-foreground">Provider {index}</span>
      </div>
      <StatusBadge spec={RUNNING_BADGE} />
    </div>
  );
}

export function ProviderProgressTracker({ results, totalExpected }: ProviderProgressTrackerProps) {
  const rows = Object.values(results).sort((a, b) => a.provider_name.localeCompare(b.provider_name));
  const respondedCount = rows.length;
  const total = Math.max(totalExpected, respondedCount);
  const remaining = Math.max(0, total - respondedCount);
  const pct = total > 0 ? Math.min(100, Math.round((respondedCount / total) * 100)) : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Provider Progress</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {total > 0 ? (
                <>
                  <span className="font-medium text-foreground">{respondedCount}</span> / {total} providers
                  responded
                </>
              ) : (
                "Waiting for provider list…"
              )}
            </span>
            <span className="tabular-nums">{pct}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        <div className="flex flex-col divide-y divide-border/50">
          {rows.map((result) => (
            <ProviderRow key={result.provider_id} result={result} />
          ))}
          {Array.from({ length: remaining }, (_, i) => (
            <PendingRow key={`pending-${i}`} index={respondedCount + i + 1} />
          ))}
          {rows.length === 0 && remaining === 0 && (
            <p className="py-2 text-xs text-muted-foreground">No providers reporting yet.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
