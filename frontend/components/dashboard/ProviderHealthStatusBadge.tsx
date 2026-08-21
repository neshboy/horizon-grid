/**
 * Renders a provider-health window's status using the app-wide operational
 * status language (StatusBadge) -- never color alone (accessibility
 * requirement), and "unknown" must never look like "healthy"/"operational".
 *
 * Maps the real 4-state backend vocabulary (healthy/degraded/down/unknown)
 * onto the broader 6-state UI language: healthy->operational, down->offline.
 * WARNING/CRITICAL have no equivalent here since provider health genuinely
 * only has 4 real states -- this component never fabricates a distinction
 * the backend doesn't report.
 */

import { StatusBadge, type OperationalStatus } from "@/components/StatusBadge";
import type { ProviderHealthStatus } from "@/lib/types";

const STATUS_MAP: Record<ProviderHealthStatus, OperationalStatus> = {
  healthy: "operational",
  degraded: "degraded",
  down: "offline",
  unknown: "unknown",
};

const KNOWN_STATUSES = new Set(Object.keys(STATUS_MAP));

export interface ProviderHealthStatusBadgeProps {
  status: ProviderHealthStatus | string | null | undefined;
  className?: string;
}

export function ProviderHealthStatusBadge({ status, className }: ProviderHealthStatusBadgeProps) {
  // Fallback for any status string this frontend doesn't recognize (a future
  // backend value, a typo, a missing/null field, etc). MUST resolve to
  // "unknown", never "operational" -- an unrecognized string is exactly as
  // uninformative as "never exercised in this window", and styling it as
  // healthy would misrepresent a real data gap as a clean bill of health.
  const mapped =
    typeof status === "string" && KNOWN_STATUSES.has(status) ? STATUS_MAP[status as ProviderHealthStatus] : "unknown";

  return <StatusBadge status={mapped} className={className} />;
}
