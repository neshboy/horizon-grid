"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getNetworkInfo } from "@/lib/api";
import type { NetworkInfo } from "@/lib/types";

export function NetworkAccessPanel() {
  const [info, setInfo] = React.useState<NetworkInfo | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);

  React.useEffect(() => {
    getNetworkInfo()
      .then(setInfo)
      .catch(() => setError("Could not reach the backend for network info."));
  }, []);

  const localUrl = typeof window !== "undefined" ? window.location.origin : "";
  const lanUrl = info?.detected_lan_ip ? `http://${info.detected_lan_ip}:${info.frontend_port}` : null;

  const copyLanUrl = React.useCallback(async () => {
    if (!lanUrl) return;
    try {
      await navigator.clipboard.writeText(lanUrl);
      setMessage("Copied.");
    } catch {
      setMessage("Couldn't copy automatically — select and copy the address above.");
    }
  }, [lanUrl]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Network Access</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <p className="text-xs text-muted-foreground">This computer</p>
          <p className="text-sm font-medium">{localUrl}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">
            From another device on this network (detected during setup — re-run &ldquo;Configuration&rdquo; from the Start
            Menu if your network has changed)
          </p>
          {lanUrl ? (
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium">{lanUrl}</p>
              <Button size="sm" onClick={copyLanUrl}>
                Copy LAN URL
              </Button>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Not detected. Run &ldquo;Configuration&rdquo; from the Start Menu to detect it.
            </p>
          )}
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Backend port</p>
          <p className="text-sm font-medium">{info?.backend_port ?? "—"}</p>
        </div>
        {message && <p className="text-xs text-muted-foreground">{message}</p>}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}
