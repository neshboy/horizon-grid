"use client";

import * as React from "react";
import { ExternalLink } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ProviderResult, ProviderStatus, ProviderSummary } from "@/lib/types";

export interface ProviderCardProps {
  result: ProviderResult;
  summary?: ProviderSummary;
}

function formatLabel(key: string): string {
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function formatPrimitive(value: string | number | boolean): string {
  return typeof value === "boolean" ? (value ? "true" : "false") : String(value);
}

function isPrimitive(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function statusBadgeClasses(status: ProviderStatus): string {
  switch (status) {
    case "ok":
      return "border-success/40 bg-success/10 text-success";
    case "error":
      return "border-destructive/40 bg-destructive/10 text-destructive";
    case "timeout":
    case "rate_limited":
      return "border-warning/40 bg-warning/10 text-warning";
    case "not_configured":
    case "unsupported_ioc":
    case "no_data":
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function threatLevelBadgeClasses(level: string): string {
  switch (level) {
    case "critical":
    case "high":
      return "border-destructive/40 bg-destructive/10 text-destructive";
    case "medium":
      return "border-warning/40 bg-warning/10 text-warning";
    case "low":
      return "border-accent/40 bg-accent/10 text-accent";
    case "none":
      return "border-success/40 bg-success/10 text-success";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] text-foreground">
      {children}
    </span>
  );
}

/** Renders a single data field inline. Returns null for nested objects / arrays
 * of non-primitives, which are instead surfaced via the "Raw data" <details>. */
function DataField({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return (
      <div className="flex items-baseline justify-between gap-3 py-1 text-xs">
        <span className="shrink-0 text-muted-foreground">{label}</span>
        <span className="text-muted-foreground">—</span>
      </div>
    );
  }

  if (isPrimitive(value)) {
    return (
      <div className="flex items-baseline justify-between gap-3 py-1 text-xs">
        <span className="shrink-0 text-muted-foreground">{label}</span>
        <span className="break-all text-right text-foreground">{formatPrimitive(value)}</span>
      </div>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <div className="flex items-baseline justify-between gap-3 py-1 text-xs">
          <span className="shrink-0 text-muted-foreground">{label}</span>
          <span className="text-muted-foreground">—</span>
        </div>
      );
    }

    const allPrimitive = value.every((v) => v === null || isPrimitive(v));
    if (!allPrimitive) return null;

    if (value.length <= 6) {
      return (
        <div className="flex flex-col gap-1 py-1 text-xs">
          <span className="text-muted-foreground">{label}</span>
          <div className="flex flex-wrap gap-1">
            {value.map((v, i) => (
              <Pill key={i}>{v === null ? "—" : formatPrimitive(v)}</Pill>
            ))}
          </div>
        </div>
      );
    }

    return (
      <div className="flex items-baseline justify-between gap-3 py-1 text-xs">
        <span className="shrink-0 text-muted-foreground">{label}</span>
        <span className="break-all text-right text-foreground">
          {value.map((v) => (v === null ? "—" : formatPrimitive(v))).join(", ")}
        </span>
      </div>
    );
  }

  // Nested object -- deferred to the raw data <details>.
  return null;
}

interface OsintFinding {
  title?: string;
  url?: string;
  snippet?: string;
  published_at?: string | null;
  source?: string;
}

function isOsintFinding(value: unknown): value is OsintFinding {
  return typeof value === "object" && value !== null && "url" in value;
}

/** internet_intelligence's osint_findings is an array of {title,url,snippet,
 * published_at,source} objects -- DataField's generic array handling drops
 * non-primitive arrays (surfaced only in the raw-JSON <details>), so this
 * gives crawler findings a dedicated, per-item attributed link list instead. */
function OsintFindingsList({ findings }: { findings: OsintFinding[] }) {
  if (findings.length === 0) {
    return <p className="py-1 text-xs text-muted-foreground">No findings.</p>;
  }
  return (
    <ul className="flex flex-col gap-2 py-1">
      {findings.map((finding, i) => (
        <li key={i} className="flex flex-col gap-0.5 rounded-md border border-border/50 bg-muted/20 px-2 py-1.5">
          <a
            href={finding.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            {finding.title || finding.url}
            <ExternalLink className="h-3 w-3 shrink-0" />
          </a>
          {finding.snippet && (
            <p className="line-clamp-2 text-[11px] text-muted-foreground">{finding.snippet}</p>
          )}
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            {finding.source && <span className="capitalize">{finding.source.replace(/_/g, " ")}</span>}
            {finding.published_at && <span>{finding.published_at}</span>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function AISummarySection({ summary }: { summary: ProviderSummary }) {
  return (
    <div className="mt-3 space-y-2 border-t border-border pt-3">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          AI Summary
        </h4>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
            threatLevelBadgeClasses(summary.threat_level)
          )}
        >
          {summary.threat_level}
        </span>
      </div>

      {summary.what_it_knows && <p className="text-xs text-foreground">{summary.what_it_knows}</p>}

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="text-muted-foreground">Reputation: </span>
          <span className="text-foreground">{summary.reputation || "—"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Confidence: </span>
          <span className="capitalize text-foreground">{summary.confidence || "—"}</span>
        </div>
      </div>

      {summary.interesting_findings.length > 0 && (
        <div>
          <p className="text-[11px] font-medium text-muted-foreground">Interesting findings</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-foreground">
            {summary.interesting_findings.map((finding, i) => (
              <li key={i}>{finding}</li>
            ))}
          </ul>
        </div>
      )}

      {summary.relationships.length > 0 && (
        <div>
          <p className="text-[11px] font-medium text-muted-foreground">Relationships</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {summary.relationships.map((rel, i) => (
              <Pill key={i}>{rel}</Pill>
            ))}
          </div>
        </div>
      )}

      {summary.unique_observations.length > 0 && (
        <div>
          <p className="text-[11px] font-medium text-muted-foreground">Unique observations</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-foreground">
            {summary.unique_observations.map((obs, i) => (
              <li key={i}>{obs}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ProviderCard({ result, summary }: ProviderCardProps) {
  const dataEntries = Object.entries(result.data ?? {});
  const isOk = result.status === "ok";

  const osintFindingsRaw = result.data?.["osint_findings"];
  const osintFindings = Array.isArray(osintFindingsRaw) ? osintFindingsRaw.filter(isOsintFinding) : null;

  return (
    <Card className="flex flex-col">
      <CardHeader className="gap-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base">{result.provider_name}</CardTitle>
          <span
            className={cn(
              "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
              statusBadgeClasses(result.status)
            )}
          >
            {result.status.replace(/_/g, " ")}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span className="rounded-full border border-border bg-muted px-2 py-0.5 capitalize">
            {result.category.replace(/_/g, " ")}
          </span>
          {result.latency_ms != null && <span>{result.latency_ms} ms</span>}
          {result.from_cache && <span className="text-accent">cached</span>}
          {result.source_url && (
            <a
              href={result.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              Source <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col">
        {result.error_message && (
          <p className="mb-2 text-xs text-destructive">{result.error_message}</p>
        )}

        {dataEntries.length > 0 ? (
          <div className="divide-y divide-border/50">
            {dataEntries.map(([key, value]) =>
              key === "osint_findings" && osintFindings ? (
                <div key={key} className="py-1">
                  <span className="text-xs text-muted-foreground">{formatLabel(key)}</span>
                  <OsintFindingsList findings={osintFindings} />
                </div>
              ) : (
                <DataField key={key} label={formatLabel(key)} value={value} />
              )
            )}
          </div>
        ) : (
          !result.error_message && <p className="text-xs text-muted-foreground">No data returned.</p>
        )}

        {dataEntries.length > 0 && (
          <details className="mt-2 rounded-md border border-border bg-muted/30 p-2 text-xs">
            <summary className="cursor-pointer select-none font-medium text-muted-foreground hover:text-foreground">
              Raw data
            </summary>
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all text-[11px] text-muted-foreground">
              {JSON.stringify(result.data, null, 2)}
            </pre>
          </details>
        )}

        {isOk ? (
          summary ? (
            <AISummarySection summary={summary} />
          ) : (
            <div className="mt-3 animate-pulse border-t border-border pt-3 text-xs text-muted-foreground">
              Generating AI summary…
            </div>
          )
        ) : (
          <div className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
            No AI summary — provider status is &quot;{result.status.replace(/_/g, " ")}&quot;.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
