/**
 * Single stat tile for the Executive Dashboard's KPI row. Modeled on the
 * Card/CardHeader/CardTitle/CardContent primitives in components/ui/card.tsx
 * so it looks native to this app rather than bespoke.
 *
 * `value === null` renders as "N/A" (or `nullLabel`, if given) -- it is NEVER
 * coerced to 0 or left blank, since for these KPIs (e.g. ai_success_rate) a
 * null genuinely means "no data to report", which is a different fact than
 * "measured and zero".
 */

import type { LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface KpiCardProps {
  label: string;
  value: number | string | null;
  /** Appended after a non-null numeric/string value only (e.g. "%"). Never
   * shown alongside the null fallback text. */
  suffix?: string;
  icon?: LucideIcon;
  /** Small muted line under the value, e.g. extra context or a trend note. */
  caption?: string;
  /** Text to render in place of null/undefined. Defaults to "N/A". */
  nullLabel?: string;
  /** Extra classes for the value text when it IS present (e.g. a color from
   * riskScoreColor()) -- ignored while the value is null, since the null
   * state always renders in muted text regardless. */
  valueClassName?: string;
}

function formatValue(value: number | string | null): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") {
    if (Number.isNaN(value)) return null;
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  }
  return value;
}

export function KpiCard({
  label,
  value,
  suffix,
  icon: Icon,
  caption,
  nullLabel = "N/A",
  valueClassName,
}: KpiCardProps) {
  const formatted = formatValue(value);
  const isMissing = formatted === null;
  const displayValue = isMissing ? nullLabel : `${formatted}${suffix ?? ""}`;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 pb-1">
        <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </CardTitle>
        {Icon && <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
      </CardHeader>
      <CardContent>
        <div
          className={cn(
            "text-2xl font-bold tabular-nums",
            isMissing ? "text-muted-foreground" : valueClassName
          )}
        >
          {displayValue}
        </div>
        {caption && <p className="mt-1 text-xs text-muted-foreground">{caption}</p>}
      </CardContent>
    </Card>
  );
}
