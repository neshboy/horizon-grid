"use client";

/**
 * Hourly investigation-activity timeline for the Executive Dashboard -- see
 * backend GET /dashboard/activity-timeline (gated by the same dashboard:read
 * permission as /kpis). One bucket per hour in the selected range, including
 * zero-activity hours (never a gap).
 *
 * high_risk/suspicious/failed are SUBSETS of `total`, not additive
 * categories -- they are never summed on top of total. `high_risk` is
 * rendered as a destructive-colored sub-segment stacked on top of the
 * "remainder" (total - high_risk) within the same bar, so each bar's total
 * height always equals `total` exactly, with the high-risk portion of that
 * same bar simply highlighted in the alarm color. suspicious/failed are
 * still real, non-fabricated numbers -- surfaced in the tooltip rather than
 * as further stacked segments, since stacking every subset independently
 * would make the bar taller than `total` and misrepresent the data.
 *
 * recharts is already a project dependency (unused elsewhere) -- this is
 * the first place it's actually imported. Axis/grid/tooltip colors are read
 * from this app's own HSL CSS variables via getComputedStyle, the same
 * pattern RelationshipGraph.tsx already uses for its node/edge colors, so
 * this stays in sync with dark mode automatically rather than hardcoding hex.
 */

import * as React from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { BarChart3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActivityTimeline } from "@/lib/api";
import type { ActivityTimelineBucket } from "@/lib/types";

const RANGE_OPTIONS: { label: string; hours: number }[] = [
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 24 * 7 },
];

interface ChartDatum {
  bucket: string;
  /** total - high_risk, i.e. the non-highlighted remainder of the bar --
   * exists purely so the stacked bar's total height equals `total` exactly
   * (see file header). Never rendered/labeled on its own. */
  base: number;
  high_risk: number;
  total: number;
  suspicious: number;
  failed: number;
}

interface ChartColors {
  primary: string;
  destructive: string;
  border: string;
  mutedForeground: string;
  foreground: string;
  card: string;
}

function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function hslVar(name: string, fallback: string): string {
  const raw = cssVar(name);
  return raw ? `hsl(${raw})` : fallback;
}

// Fallbacks only apply during SSR (no `window`/`document` yet) or if a
// variable is ever renamed in app/globals.css -- the real values are always
// read live from the CSS variables above once mounted in the browser.
function readChartColors(): ChartColors {
  return {
    primary: hslVar("--primary", "hsl(176 90% 45%)"),
    destructive: hslVar("--destructive", "hsl(4 72% 50%)"),
    border: hslVar("--border", "hsl(218 20% 18%)"),
    mutedForeground: hslVar("--muted-foreground", "hsl(217 18% 60%)"),
    foreground: hslVar("--foreground", "hsl(40 15% 94%)"),
    card: hslVar("--card", "hsl(220 22% 9%)"),
  };
}

function formatBucketLabel(bucket: string, hours: number): string {
  const date = new Date(bucket);
  if (Number.isNaN(date.getTime())) return bucket;
  if (hours > 24) {
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" });
  }
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

// Mirrors the pulsing-bar skeleton language already used on this page (see
// SummarySkeleton in app/dashboard/page.tsx) -- a set of pulsing placeholder
// bars, never a chart pre-rendered with fabricated data.
function TimelineSkeleton() {
  const heights = [40, 65, 50, 80, 55, 70, 45, 85, 60, 90, 50, 65, 40, 75, 55, 60];
  return (
    <div className="flex h-[220px] items-end gap-1.5 px-1" aria-hidden="true">
      {heights.map((h, i) => (
        <div key={i} className="flex-1 animate-pulse rounded-t bg-muted" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

function TimelineEmptyState() {
  return (
    <div className="flex h-[220px] flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border text-center">
      <BarChart3 className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm text-muted-foreground">No investigation activity in this window</p>
    </div>
  );
}

function ActivityTooltip({
  active,
  payload,
  colors,
  hours,
}: TooltipProps<number, string> & { colors: ChartColors; hours: number }) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload as ChartDatum | undefined;
  if (!point) return null;
  return (
    <div
      className="rounded-md border px-3 py-2 text-xs"
      style={{ borderColor: colors.border, backgroundColor: colors.card, color: colors.foreground }}
    >
      <p className="mb-1 font-medium">{formatBucketLabel(point.bucket, hours)}</p>
      <p style={{ color: colors.primary }}>Total: {point.total}</p>
      {point.high_risk > 0 && <p style={{ color: colors.destructive }}>High-risk: {point.high_risk}</p>}
      {point.suspicious > 0 && <p style={{ color: colors.mutedForeground }}>Suspicious: {point.suspicious}</p>}
      {point.failed > 0 && <p style={{ color: colors.mutedForeground }}>Failed: {point.failed}</p>}
    </div>
  );
}

export function ActivityTimeline() {
  const [hours, setHours] = React.useState(24);
  const [buckets, setBuckets] = React.useState<ActivityTimelineBucket[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  // Independent fetch -- its own loading/error state, does not block or get
  // blocked by the KPI/executive-summary/provider-health fetches elsewhere
  // on this page. Re-fetches whenever the selected range changes.
  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getActivityTimeline(hours)
      .then((data) => {
        if (cancelled) return;
        setBuckets(data.buckets);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load activity timeline");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hours]);

  const chartData: ChartDatum[] = React.useMemo(
    () =>
      (buckets ?? []).map((b) => ({
        bucket: b.bucket,
        base: Math.max(0, b.total - b.high_risk),
        high_risk: b.high_risk,
        total: b.total,
        suspicious: b.suspicious,
        failed: b.failed,
      })),
    [buckets]
  );

  const totalSum = chartData.reduce((sum, d) => sum + d.total, 0);
  const highRiskSum = chartData.reduce((sum, d) => sum + d.high_risk, 0);
  const isEmpty = buckets !== null && totalSum === 0;

  const colors = readChartColors();
  // Cap the number of rendered x-axis ticks at ~8 regardless of range (6
  // buckets for 6h up to 168 for 7d) so labels never overlap.
  const tickInterval = chartData.length > 8 ? Math.ceil(chartData.length / 8) - 1 : 0;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>Activity Timeline</CardTitle>
        <div className="flex items-center gap-1">
          {RANGE_OPTIONS.map((opt) => (
            <Button
              key={opt.hours}
              type="button"
              size="sm"
              variant={hours === opt.hours ? "default" : "ghost"}
              className="h-7 px-2.5 text-xs"
              aria-pressed={hours === opt.hours}
              onClick={() => setHours(opt.hours)}
            >
              {opt.label}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        ) : loading ? (
          <TimelineSkeleton />
        ) : isEmpty ? (
          <TimelineEmptyState />
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colors.primary }} aria-hidden="true" />
                Total investigations
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colors.destructive }} aria-hidden="true" />
                High-risk
              </span>
              <span className="ml-auto font-data tabular-nums">
                {totalSum.toLocaleString()} total &middot; {highRiskSum.toLocaleString()} high-risk
              </span>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <ComposedChart data={chartData} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke={colors.border} strokeDasharray="3 3" />
                <XAxis
                  dataKey="bucket"
                  tickFormatter={(value: string) => formatBucketLabel(value, hours)}
                  interval={tickInterval}
                  tick={{ fill: colors.mutedForeground, fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: colors.border }}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: colors.mutedForeground, fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  width={32}
                />
                <Tooltip
                  cursor={{ fill: colors.border, opacity: 0.2 }}
                  content={(props: TooltipProps<number, string>) => (
                    <ActivityTooltip {...props} colors={colors} hours={hours} />
                  )}
                />
                <Bar dataKey="base" stackId="volume" fill={colors.primary} fillOpacity={0.55} isAnimationActive={false} />
                <Bar
                  dataKey="high_risk"
                  stackId="volume"
                  fill={colors.destructive}
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
