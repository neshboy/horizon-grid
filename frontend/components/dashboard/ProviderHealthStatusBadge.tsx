/**
 * Renders a provider-health window's status with a DISTINCT color, icon, AND
 * text label for each of healthy/degraded/down/unknown -- never color alone
 * (accessibility requirement), and "unknown" must never look like "healthy".
 *
 * ProviderConfigRow.tsx has its own `StatusBadge`, but it's a private,
 * boolean-only (ok/not-ok) component not exported from that file and not
 * shaped for a 4-state status -- so this is a new, purpose-built component
 * rather than a reuse/extension of that one.
 */

import { AlertTriangle, CheckCircle2, HelpCircle, XCircle, type LucideIcon } from "lucide-react";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ProviderHealthStatus } from "@/lib/types";

interface StatusVisual {
  label: string;
  icon: LucideIcon;
  variant: NonNullable<BadgeProps["variant"]>;
}

const STATUS_VISUALS: Record<ProviderHealthStatus, StatusVisual> = {
  healthy: { label: "Healthy", icon: CheckCircle2, variant: "success" },
  degraded: { label: "Degraded", icon: AlertTriangle, variant: "warning" },
  down: { label: "Down", icon: XCircle, variant: "destructive" },
  unknown: { label: "Unknown", icon: HelpCircle, variant: "muted" },
};

// Fallback for any status string this frontend doesn't recognize (a future
// backend value, a typo, a missing/null field, etc). MUST resolve to the
// same visual as "unknown", never "healthy" -- an unrecognized string is
// exactly as uninformative as "never exercised in this window", and styling
// it as healthy would misrepresent a real data gap as a clean bill of health.
const FALLBACK_VISUAL: StatusVisual = STATUS_VISUALS.unknown;

const KNOWN_STATUSES = new Set(Object.keys(STATUS_VISUALS));

export interface ProviderHealthStatusBadgeProps {
  status: ProviderHealthStatus | string | null | undefined;
  className?: string;
}

export function ProviderHealthStatusBadge({ status, className }: ProviderHealthStatusBadgeProps) {
  const visual =
    typeof status === "string" && KNOWN_STATUSES.has(status)
      ? STATUS_VISUALS[status as ProviderHealthStatus]
      : FALLBACK_VISUAL;
  const Icon = visual.icon;

  return (
    <Badge variant={visual.variant} className={cn("gap-1", className)}>
      <Icon className="h-3 w-3" aria-hidden="true" />
      {visual.label}
    </Badge>
  );
}
