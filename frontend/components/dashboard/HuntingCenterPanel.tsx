"use client";

/**
 * Threat Hunting Center: "Hunt this IOC" generates copyable queries across
 * SIEM/EDR query languages for the exact seed IOC plus hunting-expansion
 * queries for related indicators actually present in the correlation graph
 * (see backend/app/ai/hunting_service.py -- expansion targets are grounded,
 * never invented). "Create Detection" drafts a full production-style rule
 * with objective/data-source/logic/false-positive/severity/ATT&CK fields.
 */

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { Check, Copy, Crosshair, ShieldPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { createDetectionRule, huntThisIOC } from "@/lib/api";
import type { DetectionRuleDraft, HuntingPackage } from "@/lib/types";

export interface HuntingCenterPanelProps {
  lookupId: string;
}

const HUNT_FORMATS = [
  "sigma", "splunk_spl", "sentinel_kql", "elastic", "qradar_aql", "chronicle_yara_l", "suricata", "snort", "zeek",
];
const FORMAT_LABELS: Record<string, string> = {
  sigma: "Sigma",
  yara: "YARA",
  splunk_spl: "Splunk SPL",
  sentinel_kql: "Sentinel KQL",
  elastic: "Elastic",
  qradar_aql: "QRadar AQL",
  chronicle_yara_l: "Chronicle YARA-L",
  suricata: "Suricata",
  snort: "Snort",
  zeek: "Zeek",
};

function useCopy() {
  const [copiedKey, setCopiedKey] = React.useState<string | null>(null);
  const timeout = React.useRef<ReturnType<typeof setTimeout>>();
  const copy = React.useCallback((text: string, key: string) => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopiedKey(key);
        if (timeout.current) clearTimeout(timeout.current);
        timeout.current = setTimeout(() => setCopiedKey(null), 1500);
      })
      .catch(() => undefined);
  }, []);
  React.useEffect(() => () => { if (timeout.current) clearTimeout(timeout.current); }, []);
  return { copiedKey, copy };
}

export function HuntingCenterPanel({ lookupId }: HuntingCenterPanelProps) {
  const [huntPackage, setHuntPackage] = React.useState<HuntingPackage | null>(null);
  const [loadingHunt, setLoadingHunt] = React.useState(false);
  const [detectionFormat, setDetectionFormat] = React.useState("sigma");
  const [detection, setDetection] = React.useState<DetectionRuleDraft | null>(null);
  const [loadingDetection, setLoadingDetection] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { copiedKey, copy } = useCopy();

  const handleHunt = React.useCallback(async () => {
    setLoadingHunt(true);
    setError(null);
    try {
      setHuntPackage(await huntThisIOC(lookupId, HUNT_FORMATS));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate hunting queries");
    } finally {
      setLoadingHunt(false);
    }
  }, [lookupId]);

  const handleCreateDetection = React.useCallback(async () => {
    setLoadingDetection(true);
    setError(null);
    try {
      setDetection(await createDetectionRule(lookupId, detectionFormat));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate detection rule");
    } finally {
      setLoadingDetection(false);
    }
  }, [lookupId, detectionFormat]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          <Crosshair className="h-4 w-4" aria-hidden="true" />
          Threat Hunting Center
        </CardTitle>
        <Button size="sm" onClick={handleHunt} disabled={loadingHunt}>
          {loadingHunt ? "Generating..." : huntPackage ? "Regenerate" : "Hunt This IOC"}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <p className="text-xs text-destructive">{error}</p>}

        {huntPackage && (
          <TabsPrimitive.Root defaultValue={huntPackage.exact_match_queries[0]?.format ?? HUNT_FORMATS[0]}>
            <TabsPrimitive.List className="flex flex-wrap gap-1 border-b border-border pb-2">
              {huntPackage.exact_match_queries.map((q) => (
                <TabsPrimitive.Trigger
                  key={q.format}
                  value={q.format}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors",
                    "hover:bg-muted hover:text-foreground",
                    "data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
                  )}
                >
                  {FORMAT_LABELS[q.format] ?? q.format}
                </TabsPrimitive.Trigger>
              ))}
            </TabsPrimitive.List>
            {huntPackage.exact_match_queries.map((q) => (
              <TabsPrimitive.Content key={q.format} value={q.format} className="flex flex-col gap-2 pt-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">{q.detects}</p>
                  <button
                    type="button"
                    onClick={() => copy(q.query, `exact-${q.format}`)}
                    className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    {copiedKey === `exact-${q.format}` ? (
                      <>
                        <Check className="h-3 w-3 text-success" /> Copied
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" /> Copy
                      </>
                    )}
                  </button>
                </div>
                <pre className="overflow-x-auto rounded-md border border-border bg-background p-3 text-xs">
                  <code className="font-mono text-foreground">{q.query}</code>
                </pre>
              </TabsPrimitive.Content>
            ))}
          </TabsPrimitive.Root>
        )}

        {huntPackage && huntPackage.expansion_targets.length > 0 && (
          <div className="flex flex-col gap-2 border-t border-border pt-3">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Hunting expansion -- related indicators
            </span>
            {huntPackage.expansion_targets.map((t, i) => (
              <div key={i} className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs">
                <span className="font-medium text-foreground">{t.related_ioc_type}: {t.related_ioc_value}</span>
                <p className="mt-0.5 text-muted-foreground">{t.rationale}</p>
              </div>
            ))}
            {huntPackage.broader_queries.map((q, i) => (
              <div key={i} className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-foreground">{FORMAT_LABELS[q.format] ?? q.format}</span>
                  <button
                    type="button"
                    onClick={() => copy(q.query, `broad-${i}`)}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                  >
                    {copiedKey === `broad-${i}` ? "Copied" : "Copy"}
                  </button>
                </div>
                <pre className="overflow-x-auto rounded-md border border-border bg-background p-2 text-[11px]">
                  <code className="font-mono text-foreground">{q.query}</code>
                </pre>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-col gap-3 border-t border-border pt-3">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <ShieldPlus className="h-3.5 w-3.5" aria-hidden="true" />
              Create Detection
            </span>
            <div className="flex items-center gap-2">
              <select
                value={detectionFormat}
                onChange={(e) => setDetectionFormat(e.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
              >
                {HUNT_FORMATS.concat("yara").map((f) => (
                  <option key={f} value={f}>
                    {FORMAT_LABELS[f] ?? f}
                  </option>
                ))}
              </select>
              <Button size="sm" variant="outline" onClick={handleCreateDetection} disabled={loadingDetection}>
                {loadingDetection ? "Drafting..." : "Generate"}
              </Button>
            </div>
          </div>

          {detection && (
            <div className="flex flex-col gap-2 rounded-md border border-border bg-muted/20 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-foreground">{detection.title}</span>
                <button
                  type="button"
                  onClick={() => copy(detection.rule, "detection")}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                >
                  {copiedKey === "detection" ? "Copied" : "Copy rule"}
                </button>
              </div>
              <pre className="overflow-x-auto rounded-md border border-border bg-background p-3 text-xs">
                <code className="font-mono text-foreground">{detection.rule}</code>
              </pre>
              <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                <div>
                  <span className="font-medium text-muted-foreground">Objective: </span>
                  <span className="text-foreground">{detection.detection_objective}</span>
                </div>
                <div>
                  <span className="font-medium text-muted-foreground">Data source: </span>
                  <span className="text-foreground">{detection.data_source}</span>
                </div>
                <div className="sm:col-span-2">
                  <span className="font-medium text-muted-foreground">Logic: </span>
                  <span className="text-foreground">{detection.logic_explanation}</span>
                </div>
                <div className="sm:col-span-2">
                  <span className="font-medium text-muted-foreground">False positive considerations: </span>
                  <span className="text-foreground">{detection.false_positive_considerations}</span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] uppercase capitalize text-muted-foreground">
                  Severity: {detection.severity}
                </span>
                {detection.mitre_technique_ids.map((id) => (
                  <span key={id} className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-[10px] text-warning">
                    {id}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
