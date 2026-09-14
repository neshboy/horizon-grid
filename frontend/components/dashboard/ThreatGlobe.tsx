"use client";

/**
 * 3D "threat globe" for the Executive Dashboard -- real per-country
 * investigation activity from GET /dashboard/geo-activity (see
 * lib/api.ts's getGeoActivity()), plotted on a globe using real
 * geographic reference coordinates (the `world-countries` package: static
 * ISO country metadata, no network calls, no fabricated positions).
 *
 * Hard rule for this component: a country with zero real activity in the
 * selected window gets no marker, ever. A country_code the backend reports
 * that this frontend can't resolve against `world-countries` is dropped
 * from rendering (never given a guessed position) but is still counted --
 * alongside the backend's own `unmapped_count` -- in a small caption, so
 * that real gap in coverage is always visible rather than silently eaten.
 *
 * Like RelationshipGraph3D.tsx, the actual R3F <Canvas> scene lives in the
 * sibling ThreatGlobeScene.tsx and is loaded here via
 * `next/dynamic(..., { ssr: false })`, so this file stays safe to render on
 * the server and the heavy three.js/r3f/drei chunk is only fetched once
 * this component actually mounts.
 *
 * Marker colors are derived from this app's live --primary/--destructive/
 * --border/--muted-foreground HSL CSS variables (see app/globals.css), read
 * via getComputedStyle exactly like RelationshipGraph3D.tsx -- never new
 * hardcoded hex values.
 */

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import countries from "world-countries";
import { Globe, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getGeoActivity } from "@/lib/api";
import type { GeoActivity } from "@/lib/types";
import type { FocusTarget, PositionedMarker } from "@/components/dashboard/ThreatGlobeScene";

const ThreatGlobeScene = dynamic(() => import("@/components/dashboard/ThreatGlobeScene"), { ssr: false });

export interface ThreatGlobeProps {
  height?: number;
  /** A specific investigation to fly the camera to and show an Intelligence
   * Card for -- set by the dashboard page from ?focusLookupId=... (wired up
   * in a separate change; see this component's own docstring). `countryCode`
   * MUST already be a real, resolved alpha-2 code (i.e. the caller already
   * confirmed GET /lookup/{id}/geo returned status "public_resolved") --
   * this component only ever renders a position it can resolve against real
   * world-countries reference coordinates, exactly like the country markers
   * above; it never geolocates or guesses on its own. */
  focusTarget?: {
    countryCode: string;
    countryName?: string | null;
    lookupId: string;
    iocValue: string;
    iocType: string;
    riskScore?: number | null;
    severity?: "critical" | "high" | "medium" | "low" | "informational" | null;
    confidenceScore?: number | null;
    providersCompleted?: number | null;
    providersTotal?: number | null;
    asn?: string | null;
    org?: string | null;
  } | null;
  onClearFocus?: () => void;
}

const RANGE_OPTIONS: { label: string; hours: number }[] = [
  { label: "7d", hours: 168 },
  { label: "30d", hours: 720 },
  { label: "90d", hours: 2160 },
];

const GLOBE_RADIUS = 6;
const MIN_MARKER_RADIUS = 0.14;
const MAX_MARKER_RADIUS = 0.46;

// Built once at module load (pure, no window/document access) -- real ISO
// country metadata, keyed by uppercase alpha-2 code, used only to look up
// WHERE a real country is on a globe. Never used to decide WHETHER activity
// happened there -- that always comes from the API response.
const COUNTRY_GEO_BY_CCA2: Map<string, { name: string; lat: number; lng: number }> = new Map(
  countries
    .filter((c) => Array.isArray(c.latlng) && c.latlng.length === 2)
    .map((c) => [c.cca2.toUpperCase(), { name: c.name.common, lat: c.latlng[0], lng: c.latlng[1] }])
);

interface ResolvedCountryActivity {
  code: string;
  name: string;
  lat: number;
  lng: number;
  total: number;
  high_risk: number;
  suspicious: number;
}

function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** "215 20% 65%" -> { h: 215, s: 20, l: 65 }, or null if unparseable. Same
 * parser as RelationshipGraph3D.tsx, kept as a separate copy for the same
 * reason that file states: this module shouldn't take a dependency on it. */
function parseHslTriple(triple: string): { h: number; s: number; l: number } | null {
  const match = triple.match(/^(-?[\d.]+)\s+([\d.]+)%\s+([\d.]+)%$/);
  if (!match) return null;
  return { h: parseFloat(match[1]), s: parseFloat(match[2]), l: parseFloat(match[3]) };
}

function hslToRgb01(h: number, s: number, l: number): [number, number, number] {
  const S = s / 100;
  const L = l / 100;
  const C = (1 - Math.abs(2 * L - 1)) * S;
  const Hp = (((h % 360) + 360) % 360) / 60;
  const X = C * (1 - Math.abs((Hp % 2) - 1));
  let r1 = 0;
  let g1 = 0;
  let b1 = 0;
  if (Hp < 1) [r1, g1, b1] = [C, X, 0];
  else if (Hp < 2) [r1, g1, b1] = [X, C, 0];
  else if (Hp < 3) [r1, g1, b1] = [0, C, X];
  else if (Hp < 4) [r1, g1, b1] = [0, X, C];
  else if (Hp < 5) [r1, g1, b1] = [X, 0, C];
  else [r1, g1, b1] = [C, 0, X];
  const m = L - C / 2;
  return [r1 + m, g1 + m, b1 + m];
}

const FALLBACK_HSL_TRIPLE = "215 20% 65%";

function rgb01ForCssVar(varName: string): [number, number, number] {
  const triple = cssVar(varName) || FALLBACK_HSL_TRIPLE;
  const hsl = parseHslTriple(triple) ?? parseHslTriple(FALLBACK_HSL_TRIPLE)!;
  return hslToRgb01(hsl.h, hsl.s, hsl.l);
}

function lerpRgb(a: [number, number, number], b: [number, number, number], t: number): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  return [a[0] + (b[0] - a[0]) * clamped, a[1] + (b[1] - a[1]) * clamped, a[2] + (b[2] - a[2]) * clamped];
}

/** Standard lat/lng -> point-on-sphere-surface conversion (the same
 * spherical-to-Cartesian formula used by three.js globe demos). Purely
 * geometric -- takes real `world-countries` coordinates and places them on
 * the real sphere this component renders; invents nothing. */
function latLngToVector3(lat: number, lng: number, radius: number): [number, number, number] {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lng + 180) * (Math.PI / 180);
  const x = -radius * Math.sin(phi) * Math.cos(theta);
  const z = radius * Math.sin(phi) * Math.sin(theta);
  const y = radius * Math.cos(phi);
  return [x, y, z];
}

function GlobeSkeleton({ height }: { height: number }) {
  return (
    <div style={{ height }} className="flex items-center justify-center" aria-hidden="true">
      <div className="h-32 w-32 animate-pulse rounded-full border border-dashed border-border" />
    </div>
  );
}

function GlobeEmptyState({ height }: { height: number }) {
  return (
    <div
      style={{ height }}
      className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border text-center"
    >
      <Globe className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm text-muted-foreground">No geographic activity in this window yet.</p>
    </div>
  );
}

/** Maps this app's free-text risk.severity (see ThreatScoreGauge.tsx --
 * lowercase-ish strings like "none"/"low"/"medium"/"high"/"critical", never
 * a strict enum) onto ThreatGlobeScene's FocusTarget severity tiers. Anything
 * that isn't recognized (including "none"/empty/null -- a real, valid "not
 * elevated" outcome, not a missing value) lands on "informational", the same
 * neutral bucket the Scene's own severityCssVar() already treats that way --
 * never invents a more alarming tier than the data supports. */
function toFocusSeverity(severity: string | null | undefined): FocusTarget["severity"] {
  switch ((severity ?? "").toLowerCase()) {
    case "critical":
      return "critical";
    case "high":
      return "high";
    case "medium":
      return "medium";
    case "low":
      return "low";
    default:
      return "informational";
  }
}

/** Same tier mapping as SecurityAssessmentPanel.tsx's severityBadgeVariant()
 * (critical/high -> destructive, medium -> warning, low -> default,
 * else -> muted) applied to the Intelligence Card's own severity tiers, kept
 * as a local copy since the two "severity" types aren't the same union. */
function focusSeverityBadgeVariant(
  severity: FocusTarget["severity"]
): "default" | "success" | "warning" | "destructive" | "muted" {
  switch (severity) {
    case "critical":
    case "high":
      return "destructive";
    case "medium":
      return "warning";
    case "low":
      return "default";
    default:
      return "muted";
  }
}

export function ThreatGlobe({ height = 420, focusTarget, onClearFocus }: ThreatGlobeProps) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  const [hasBeenVisible, setHasBeenVisible] = React.useState(false);

  const [hours, setHours] = React.useState(720);
  const [geoActivity, setGeoActivity] = React.useState<GeoActivity | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  // Independent fetch -- own loading/error state, re-fetches on range change,
  // same pattern as ActivityTimeline's getActivityTimeline() effect.
  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getGeoActivity(hours)
      .then((data) => {
        if (cancelled) return;
        setGeoActivity(data);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load geographic activity");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hours]);

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    resizeObserver.observe(el);
    setWidth(el.getBoundingClientRect().width);

    // Same lazy-mount rationale as RelationshipGraph3D.tsx: don't create a
    // WebGL context (or fetch the three.js/r3f/drei chunk) for a globe the
    // analyst hasn't scrolled to yet. One-way gate, not a visibility toggle
    // -- the scene itself uses frameloop="demand" so once mounted it does no
    // rendering work at all while idle, on- or off-screen.
    const intersectionObserver = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry?.isIntersecting) {
          setHasBeenVisible(true);
          intersectionObserver.disconnect();
        }
      },
      { threshold: 0.01 }
    );
    intersectionObserver.observe(el);

    return () => {
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
    };
  }, []);

  // Resolve each real GeoActivityCountry against real world-countries
  // reference coordinates. total <= 0 is filtered out (no marker for zero
  // activity); a country_code with no match in world-countries is dropped
  // from rendering but tallied in `unresolvedCount` -- never given a
  // guessed position.
  const { resolved, unresolvedCount } = React.useMemo(() => {
    const resolvedList: ResolvedCountryActivity[] = [];
    let unresolved = 0;
    for (const country of geoActivity?.countries ?? []) {
      if (country.total <= 0) continue;
      const geo = COUNTRY_GEO_BY_CCA2.get(country.country_code.toUpperCase());
      if (!geo) {
        unresolved += 1;
        continue;
      }
      resolvedList.push({
        code: country.country_code,
        name: geo.name,
        lat: geo.lat,
        lng: geo.lng,
        total: country.total,
        high_risk: country.high_risk,
        suspicious: country.suspicious,
      });
    }
    return { resolved: resolvedList, unresolvedCount: unresolved };
  }, [geoActivity]);

  // Positions/sizes/colors computed once per resolved-country change, same
  // as RelationshipGraph3D.tsx's computeLayout -- nothing here mutates in
  // place or runs per-frame.
  const positionedMarkers = React.useMemo<PositionedMarker[]>(() => {
    if (resolved.length === 0) return [];
    const totals = resolved.map((m) => m.total);
    const maxTotal = Math.max(...totals);
    const minTotal = Math.min(...totals);
    const spread = maxTotal - minTotal;
    const primaryRgb = rgb01ForCssVar("--primary");
    const alarmRgb = rgb01ForCssVar("--destructive");
    const mutedRgb = rgb01ForCssVar("--muted-foreground");

    return resolved.map((marker) => {
      // 1 when this country has the highest total among currently-rendered
      // markers, 0 at the lowest -- drives both size and color intensity so
      // "biggest/brightest" always tracks real volume, never a fixed look.
      const normalized = spread > 0 ? (marker.total - minTotal) / spread : 1;
      const radius = MIN_MARKER_RADIUS + normalized * (MAX_MARKER_RADIUS - MIN_MARKER_RADIUS);
      // Warmer/alarm-colored (destructive) the moment any high-risk activity
      // is present for that country, regardless of total -- otherwise the
      // same primary color the rest of the dashboard uses for "total".
      const baseRgb = marker.high_risk > 0 ? alarmRgb : primaryRgb;
      // Lower-total markers are washed toward muted-foreground so color
      // intensity itself also reflects real volume, not just marker size.
      const color = lerpRgb(baseRgb, mutedRgb, (1 - normalized) * 0.5);
      return {
        code: marker.code,
        name: marker.name,
        total: marker.total,
        high_risk: marker.high_risk,
        suspicious: marker.suspicious,
        position: latLngToVector3(marker.lat, marker.lng, GLOBE_RADIUS),
        radius,
        color,
      };
    });
  }, [resolved]);

  const gridColor = rgb01ForCssVar("--border");
  const unmappedCount = geoActivity?.unmapped_count ?? 0;
  const hasCoverageGap = !loading && !error && geoActivity !== null && (unmappedCount > 0 || unresolvedCount > 0);
  // Real absence of geo-attributable activity, per the data contract --
  // distinct from "all reported countries happened to be unresolvable",
  // which still renders (an inert globe with zero markers, per spec) rather
  // than claiming there was no activity at all. A focusTarget still needs the
  // real globe (to show its beacon) even when aggregate activity is empty.
  const isEmpty = !loading && !error && geoActivity !== null && geoActivity.countries.length === 0 && !focusTarget;
  // The analyst navigated here specifically via "View on Globe" -- never
  // make them wait for the lazy-mount IntersectionObserver gate first.
  const shouldMount = hasBeenVisible || !!focusTarget;

  // Resolve the focused investigation's country against the SAME real
  // world-countries reference coordinates the aggregate markers use -- never
  // a separate/guessed lookup. If the code can't be resolved here (should be
  // rare: the caller is only expected to pass a country_code that GET
  // /lookup/{id}/geo already reported as "public_resolved"), the focus is
  // simply dropped rather than rendering at a made-up position.
  const resolvedFocus = React.useMemo<FocusTarget | null>(() => {
    if (!focusTarget) return null;
    const geo = COUNTRY_GEO_BY_CCA2.get(focusTarget.countryCode.toUpperCase());
    if (!geo) return null;
    return {
      position: latLngToVector3(geo.lat, geo.lng, GLOBE_RADIUS),
      severity: toFocusSeverity(focusTarget.severity),
    };
  }, [focusTarget]);
  const focusCountryName = focusTarget
    ? (COUNTRY_GEO_BY_CCA2.get(focusTarget.countryCode.toUpperCase())?.name ?? focusTarget.countryName ?? null)
    : null;

  React.useEffect(() => {
    if (focusTarget) containerRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusTarget]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>Threat Globe</CardTitle>
        <div className="flex items-center gap-1">
          {RANGE_OPTIONS.map((opt) => (
            <Button
              key={opt.hours}
              type="button"
              size="sm"
              variant={hours === opt.hours ? "default" : "ghost"}
              className="h-7 px-2.5 text-xs"
              aria-pressed={hours === opt.hours}
              onClick={() => setHours(opt.hours)}
            >
              {opt.label}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        <div ref={containerRef} className="relative w-full">
          {error ? (
            <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          ) : loading ? (
            <GlobeSkeleton height={height} />
          ) : isEmpty ? (
            <GlobeEmptyState height={height} />
          ) : width > 0 && !shouldMount ? (
            // Lazy-mount placeholder (see the IntersectionObserver above) --
            // occupies the same footprint so nothing jumps once the real
            // scene mounts, without paying for a WebGL context this globe
            // hasn't scrolled into view to need yet.
            <div style={{ height }} className="animate-pulse rounded-md border border-dashed border-border" />
          ) : width > 0 ? (
            <div
              role="img"
              aria-label={`3D threat globe with ${positionedMarkers.length} countries with activity in the selected window.`}
              style={{ height }}
            >
              <ThreatGlobeScene
                markers={positionedMarkers}
                width={width}
                height={height}
                globeRadius={GLOBE_RADIUS}
                gridColor={gridColor}
                focusTarget={resolvedFocus}
              />
            </div>
          ) : null}

          {focusTarget && resolvedFocus && (
            <Card className="absolute right-2 top-2 w-72 border-border/80 bg-card/95 shadow-lg backdrop-blur-sm">
              <CardHeader className="flex-row items-start justify-between gap-2 pb-2">
                <div className="flex flex-col gap-1">
                  <CardTitle className="text-sm">IP Intelligence</CardTitle>
                  <span className="break-all font-data text-xs text-muted-foreground">{focusTarget.iocValue}</span>
                </div>
                {onClearFocus && (
                  <Button type="button" variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={onClearFocus}>
                    <X className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="sr-only">Close</span>
                  </Button>
                )}
              </CardHeader>
              <CardContent className="flex flex-col gap-2 pt-0 text-xs">
                {typeof focusTarget.riskScore === "number" && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Threat Score</span>
                    <span className="font-data font-semibold">{focusTarget.riskScore} / 100</span>
                  </div>
                )}
                {focusTarget.severity && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Severity</span>
                    <Badge variant={focusSeverityBadgeVariant(toFocusSeverity(focusTarget.severity))} className="text-xs capitalize">
                      {focusTarget.severity}
                    </Badge>
                  </div>
                )}
                {typeof focusTarget.confidenceScore === "number" && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Confidence</span>
                    <span className="font-data">{focusTarget.confidenceScore}%</span>
                  </div>
                )}
                {focusCountryName && (
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Approximate Location</span>
                      <span>{focusCountryName}</span>
                    </div>
                    <p className="mt-0.5 text-[10px] leading-snug text-muted-foreground/80">
                      Approximate IP geolocation -- may reflect network registration, hosting, or
                      cloud-region data rather than a precise physical location.
                    </p>
                  </div>
                )}
                {focusTarget.asn && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">ASN</span>
                    <span className="font-data">{focusTarget.asn}</span>
                  </div>
                )}
                {focusTarget.org && (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-muted-foreground">Organization</span>
                    <span className="truncate text-right">{focusTarget.org}</span>
                  </div>
                )}
                {typeof focusTarget.providersCompleted === "number" &&
                  typeof focusTarget.providersTotal === "number" && (
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Providers</span>
                      <span className="font-data">
                        {focusTarget.providersCompleted} / {focusTarget.providersTotal}
                      </span>
                    </div>
                  )}
                <Button asChild size="sm" className="mt-1 w-full">
                  <Link href={`/lookup/${focusTarget.lookupId}`}>Open Investigation</Link>
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
        {hasCoverageGap && (
          <p className="mt-2 text-xs text-muted-foreground">
            {unmappedCount > 0 && (
              <>
                {unmappedCount.toLocaleString()} lookup{unmappedCount === 1 ? "" : "s"} with no attributable
                country
              </>
            )}
            {unmappedCount > 0 && unresolvedCount > 0 && " · "}
            {unresolvedCount > 0 && (
              <>
                {unresolvedCount.toLocaleString()} country code{unresolvedCount === 1 ? "" : "s"} unmapped/unresolvable
              </>
            )}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default ThreatGlobe;
