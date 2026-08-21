"use client";

/**
 * A new, additive page (no existing route touched) -- version/build/platform
 * information for an operator or auditor who wants to confirm exactly what
 * they're running. Version comes from the real GET /health/detailed response
 * (already exposed by the backend); nothing here is hardcoded, and nothing
 * new was added to the backend to build this.
 */

import { useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { StatusBadge, type OperationalStatus } from "@/components/StatusBadge";
import { BrandHeader } from "@/components/dashboard/BrandHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getSystemHealth, isLoggedIn } from "@/lib/api";

function mapSystemStatus(status: string | undefined): OperationalStatus {
  if (status === "healthy") return "operational";
  if (status === "degraded") return "degraded";
  if (status === "down") return "offline";
  return "unknown";
}

export default function AboutPage() {
  const [version, setVersion] = useState<string | null>(null);
  const [status, setStatus] = useState<OperationalStatus>("unknown");
  const [dependencies, setDependencies] = useState<Record<string, { ok: boolean; detail?: string }>>({});
  // Deliberately starts false and is only ever set true inside an effect
  // (post-mount, client-only) -- isLoggedIn() reads localStorage, which
  // doesn't exist during SSR. Reading it directly in the render body would
  // make the server-rendered HTML (always "logged out") disagree with the
  // client's first paint whenever a session cookie/token already exists,
  // producing a real React hydration-mismatch warning (confirmed live via
  // browser console during this page's own screenshot QA pass).
  const [showHeader, setShowHeader] = useState(false);

  useEffect(() => {
    getSystemHealth()
      .then((h) => {
        setVersion(h.version ?? null);
        setStatus(mapSystemStatus(h.status));
        setDependencies(h.dependencies ?? {});
      })
      .catch(() => setStatus("offline"));
  }, []);

  useEffect(() => {
    setShowHeader(isLoggedIn());
  }, []);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-6">
      {showHeader && <BrandHeader />}

      <div className="flex flex-col items-center gap-3 py-6 text-center">
        <Logo size="full" className="scale-125" />
        <p className="font-display text-xs uppercase tracking-[0.15em] text-muted-foreground">
          Every Signal. One Operational Picture.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>System</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Version</span>
            <span className="font-data tabular-nums text-foreground">{version ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">System Status</span>
            <StatusBadge status={status} />
          </div>
          {Object.entries(dependencies).map(([name, dep]) => (
            <div key={name} className="flex items-center justify-between text-sm">
              <span className="capitalize text-muted-foreground">{name}</span>
              <StatusBadge status={dep.ok ? "operational" : "offline"} label={dep.detail} />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Supported Platforms</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
          <p>Windows 10/11 (64-bit), installed via the HORIZON GRID Setup Wizard.</p>
          <p>Debian 12 / Ubuntu 22.04+ (64-bit), installed via the horizon-grid .deb package.</p>
          <p>Both platforms run the identical Docker Compose application stack.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Documentation &amp; Source</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
          <p>
            Full documentation, release notes, and source code are published on the project&apos;s
            GitHub repository. Every release is version-tagged and synchronized with its
            corresponding CHANGELOG entry.
          </p>
        </CardContent>
      </Card>

      <p className="pb-6 text-center text-xs text-muted-foreground">
        &copy; {new Date().getFullYear()} HORIZON GRID. Self-hosted; you control the deployment,
        the data, and the credentials.
      </p>
    </main>
  );
}
