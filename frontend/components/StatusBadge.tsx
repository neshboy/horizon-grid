/**
 * The app-wide six-state operational status language. Every state pairs a
 * distinct hue, fill density, border style, icon, AND text label -- no two
 * states share the same combination, so removing color entirely (a
 * colorblind viewer, a grayscale printout) still leaves every state
 * distinguishable. OPERATIONAL/DEGRADED/OFFLINE reuse the lucide
 * signal-strength icon family so severity visually tracks "signal strength"
 * wherever plausible -- echoing the product's own tagline -- while
 * WARNING/CRITICAL intentionally break into alert-shaped icons (triangle vs.
 * octagon) specifically because those two must never be misread as a merely
 * weak reading.
 *
 * This is presentation-only: callers map their own domain status (provider
 * health's healthy/degraded/down/unknown, a scan's running/completed/failed,
 * etc.) onto one of these six labels -- this component has no knowledge of
 * any backend status vocabulary.
 */
import {
  CircleCheck,
  CircleDashed,
  OctagonAlert,
  SignalMedium,
  SignalZero,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type OperationalStatus = "operational" | "degraded" | "warning" | "critical" | "offline" | "unknown";

interface StatusSpec {
  label: string;
  icon: LucideIcon;
  className: string;
}

// Deliberately no CSS animation/pulsing anywhere in this table, including
// CRITICAL -- the brief's own performance constraint ("no resource-heavy
// animations") applies to alarm states too; CRITICAL's escalation is a
// heavier 2px border, not motion.
const STATUS_SPECS: Record<OperationalStatus, StatusSpec> = {
  operational: {
    label: "Operational",
    icon: CircleCheck,
    className: "border border-success bg-success text-success-foreground",
  },
  degraded: {
    label: "Degraded",
    icon: SignalMedium,
    className: "border border-accent bg-accent/10 text-accent",
  },
  warning: {
    label: "Warning",
    icon: TriangleAlert,
    className: "border border-warning bg-warning/10 text-warning",
  },
  critical: {
    label: "Critical",
    icon: OctagonAlert,
    className: "border-2 border-destructive bg-destructive text-destructive-foreground",
  },
  offline: {
    label: "Offline",
    icon: SignalZero,
    className: "border border-muted-foreground/40 bg-muted text-muted-foreground",
  },
  unknown: {
    label: "Unknown",
    icon: CircleDashed,
    className: "border border-dashed border-muted-foreground/50 bg-transparent text-muted-foreground",
  },
};

export interface StatusBadgeProps {
  status: OperationalStatus;
  /** Override the default label text (e.g. a longer domain-specific phrase)
   * while keeping the status's color/icon/border treatment. */
  label?: string;
  className?: string;
}

export function StatusBadge({ status, label, className }: StatusBadgeProps) {
  const spec = STATUS_SPECS[status] ?? STATUS_SPECS.unknown;
  const Icon = spec.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-tight px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide font-data",
        spec.className,
        className
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label ?? spec.label}
    </span>
  );
}
