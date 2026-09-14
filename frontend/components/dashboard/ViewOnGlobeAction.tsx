"use client";

/**
 * Shared "View on Globe" action for the IOC investigation pages (both the
 * live-SSE app/lookup/new/page.tsx and the static-replay
 * app/lookup/[id]/page.tsx use this, so the geo-status branching below has
 * exactly one implementation).
 *
 * Fetches GET /lookup/{id}/geo (see lib/api.ts's getLookupGeo()) once the
 * investigation is done and the IOC is an IP, and renders exactly one of:
 *   - nothing (non-IP IOC, or geo not loaded yet)
 *   - a "private network address" note (never a button, never a globe link --
 *     a private/loopback/reserved address must never be sent toward the globe)
 *   - a muted "location unavailable" note (a public IP this platform's own
 *     real provider data couldn't resolve a country for -- no fabricated
 *     destination to send the analyst to)
 *   - a working "View on Globe" button (only when the backend already
 *     resolved a real country for this specific investigation)
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getLookupGeo } from "@/lib/api";
import type { LookupGeo } from "@/lib/types";

export interface ViewOnGlobeActionProps {
  lookupId: string;
  iocType: string | null;
  ready: boolean;
}

export function ViewOnGlobeAction({ lookupId, iocType, ready }: ViewOnGlobeActionProps) {
  const router = useRouter();
  const [geo, setGeo] = React.useState<LookupGeo | null>(null);

  const applicable = iocType === "ipv4" || iocType === "ipv6";

  React.useEffect(() => {
    if (!ready || !applicable) return;
    let cancelled = false;
    getLookupGeo(lookupId)
      .then((data) => {
        if (!cancelled) setGeo(data);
      })
      .catch(() => {
        // No working button/badge on failure -- silent, non-blocking; this
        // action is a convenience on top of an already-complete investigation,
        // never something worth surfacing an error banner for.
      });
    return () => {
      cancelled = true;
    };
  }, [ready, applicable, lookupId]);

  if (!ready || !applicable || !geo || geo.status === "not_applicable") return null;

  if (geo.status === "private") {
    return (
      <span className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground">
        Private network address -- geographic location is not applicable
      </span>
    );
  }

  if (geo.status === "public_unresolved") {
    return (
      <span className="rounded-full border border-dashed border-border px-3 py-1 text-xs text-muted-foreground/70">
        Approximate location unavailable for this IOC
      </span>
    );
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="h-7 gap-1.5 px-3 text-xs"
      onClick={() => router.push(`/dashboard?focusLookupId=${lookupId}`)}
    >
      <Globe className="h-3.5 w-3.5" aria-hidden="true" />
      View on Globe
    </Button>
  );
}
