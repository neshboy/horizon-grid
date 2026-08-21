"use client";

/**
 * The app's branded header spine -- renders the HORIZON GRID mark, a live
 * SYSTEM STATUS read against the real backend (never hardcoded), the
 * existing TopSearchBar, and the existing WorkspaceNav, in that order.
 *
 * This intentionally does NOT repeat the tagline on every page -- the brief
 * itself warns against over-repeating it ("premium products use restraint").
 * The tagline appears on the login/register screens and the home page only;
 * every other page gets the wordmark alone, which is still real, consistent
 * brand visibility without becoming wallpaper.
 *
 * Drop-in replacement for the `<TopSearchBar /><WorkspaceNav />` pair every
 * page previously composed individually -- callers just swap those two
 * lines for `<BrandHeader searchBarProps={{ initialValue }} />` and nothing
 * else about the page changes.
 */
import { useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { StatusBadge, type OperationalStatus } from "@/components/StatusBadge";
import { TopSearchBar } from "@/components/dashboard/TopSearchBar";
import { WorkspaceNav } from "@/components/dashboard/WorkspaceNav";
import { getSystemHealth } from "@/lib/api";

function mapSystemStatus(status: string | undefined): OperationalStatus {
  if (status === "healthy") return "operational";
  if (status === "degraded") return "degraded";
  if (status === "down") return "offline";
  return "unknown";
}

function SystemStatusIndicator() {
  const [status, setStatus] = useState<OperationalStatus>("unknown");

  useEffect(() => {
    let cancelled = false;
    function poll() {
      getSystemHealth()
        .then((h) => {
          if (!cancelled) setStatus(mapSystemStatus(h.status));
        })
        .catch(() => {
          if (!cancelled) setStatus("offline");
        });
    }
    poll();
    // A light, infrequent poll -- this is a header glance-indicator, not a
    // live dashboard widget, so 60s is plenty and keeps this from adding any
    // meaningful request volume.
    const interval = setInterval(poll, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return <StatusBadge status={status} label={status === "unknown" ? "Checking" : undefined} />;
}

export interface BrandHeaderProps {
  searchBarInitialValue?: string;
}

export function BrandHeader({ searchBarInitialValue }: BrandHeaderProps) {
  return (
    <div className="flex flex-col gap-3 border-b border-border pb-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Logo size="compact" />
        <SystemStatusIndicator />
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <TopSearchBar initialValue={searchBarInitialValue} />
        <WorkspaceNav />
      </div>
    </div>
  );
}
