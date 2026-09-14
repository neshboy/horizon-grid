"use client";

/**
 * 3D sibling of RelationshipGraph.tsx for the same CorrelationPayload
 * { nodes, edges } shape. Same props contract (`data`, `height`) and the
 * same click-to-pivot behavior (navigate to /lookup/new?value=...) so a
 * caller can swap `RelationshipGraph` for `RelationshipGraph3D` with no
 * other changes.
 *
 * `three` / `@react-three/fiber` / `@react-three/drei` touch canvas/WebGL/
 * window directly, so -- exactly like RelationshipGraph.tsx dynamically
 * imports `react-force-graph-2d` internally rather than making every caller
 * do it -- the actual R3F <Canvas> scene lives in the sibling
 * RelationshipGraph3DScene.tsx module and is loaded here via
 * `next/dynamic(..., { ssr: false })`. That keeps this file (and therefore
 * any caller that imports it normally, the way app/lookup/new/page.tsx
 * imports RelationshipGraph today) safe to render on the server, and it
 * code-splits the much heavier three.js/r3f/drei bundle into its own chunk
 * that's only ever fetched once this component actually mounts.
 *
 * This module is also safe to wrap in its own
 * `dynamic(() => import(".../RelationshipGraph3D"), { ssr: false })` at a
 * call site if a future caller prefers that -- it has a default export for
 * exactly that purpose -- but doing so is optional, not required, given the
 * internal dynamic import already covers SSR safety.
 *
 * Node/edge colors are derived from the exact same --primary/--accent/
 * --warning/--destructive/--success/--muted-foreground/--border HSL CSS
 * variables as the 2D graph (see app/globals.css), read live via
 * getComputedStyle -- never new hardcoded hex values -- so the 3D view
 * always matches the 2D view and the rest of the dark theme.
 */

import * as React from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { List, Waypoints } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CorrelationPayload, GraphEdge, GraphNode } from "@/lib/types";
import type { PositionedLink, PositionedNode } from "@/components/dashboard/RelationshipGraph3DScene";

const RelationshipGraph3DScene = dynamic(
  () => import("@/components/dashboard/RelationshipGraph3DScene"),
  { ssr: false }
);

export interface RelationshipGraph3DProps {
  data: CorrelationPayload | null;
  height?: number;
}

interface GraphNodeDatum extends GraphNode {
  id: string;
}

interface GraphLinkDatum extends GraphEdge {
  id: string;
}

// Identical family->CSS-variable mapping as RelationshipGraph.tsx, kept as a
// separate copy (rather than a shared import) so this file never has to
// touch, or take a dependency on, the 2D component's module.
const TYPE_FAMILY_VAR: Record<string, string> = {
  ipv4: "--primary",
  ipv6: "--primary",
  domain: "--primary",
  hostname: "--primary",
  url: "--primary",
  asn: "--primary",
  cidr: "--primary",
  tls_certificate: "--primary",
  ja3: "--primary",
  ja4: "--primary",
  md5: "--destructive",
  sha1: "--destructive",
  sha256: "--destructive",
  sha512: "--destructive",
  file_name: "--destructive",
  file_path: "--destructive",
  malware_family: "--accent",
  threat_actor: "--accent",
  campaign: "--accent",
  yara_rule: "--accent",
  sigma_rule: "--accent",
  cve: "--warning",
  cwe: "--warning",
  capec: "--warning",
  mitre_technique: "--warning",
  registry_key: "--success",
  process_name: "--success",
  mutex: "--success",
  windows_service: "--success",
};
const DEFAULT_TYPE_VAR = "--muted-foreground";
const FALLBACK_HSL_TRIPLE = "215 20% 65%";

function cssVarTriple(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** "215 20% 65%" -> { h: 215, s: 20, l: 65 }, or null if unparseable. */
function parseHslTriple(triple: string): { h: number; s: number; l: number } | null {
  const match = triple.match(/^(-?[\d.]+)\s+([\d.]+)%\s+([\d.]+)%$/);
  if (!match) return null;
  return { h: parseFloat(match[1]), s: parseFloat(match[2]), l: parseFloat(match[3]) };
}

/**
 * Standard HSL->RGB conversion, returned as three.js's usual 0..1 float
 * triple. Used instead of handing three.js a "hsl(...)" CSS string: three's
 * own Color CSS parser expects comma-separated legacy syntax, while this
 * app's CSS variables are stored as bare "H S% L%" triples (modern
 * space-separated form, no `hsl()` wrapper) for use in `hsl(var(--x) / a)`
 * -- converting by hand sidesteps that mismatch entirely and guarantees the
 * 3D scene renders the identical color the 2D graph and the rest of the UI
 * use for the same CSS variable.
 */
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

function rgb01ForCssVar(varName: string): [number, number, number] {
  const triple = cssVarTriple(varName) || FALLBACK_HSL_TRIPLE;
  const hsl = parseHslTriple(triple) ?? parseHslTriple(FALLBACK_HSL_TRIPLE)!;
  return hslToRgb01(hsl.h, hsl.s, hsl.l);
}

function rgbForIocType(iocType: string): [number, number, number] {
  const varName = TYPE_FAMILY_VAR[iocType] ?? DEFAULT_TYPE_VAR;
  return rgb01ForCssVar(varName);
}

function formatLabel(value: string | null | undefined): string {
  if (!value) return "unknown";
  return value.replace(/_/g, " ");
}

function GraphListView({ nodes, links }: { nodes: GraphNodeDatum[]; links: GraphLinkDatum[] }) {
  const nodesById = React.useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  return (
    <table className="w-full text-left text-sm">
      <caption className="sr-only">
        Relationship graph as a table: {nodes.length} nodes, {links.length} relationships
      </caption>
      <thead>
        <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
          <th scope="col" className="py-2 pr-3">Source</th>
          <th scope="col" className="py-2 pr-3">Relationship</th>
          <th scope="col" className="py-2 pr-3">Target</th>
          <th scope="col" className="py-2 pr-3">Confidence</th>
          <th scope="col" className="py-2">Source(s)</th>
        </tr>
      </thead>
      <tbody>
        {links.map((link) => {
          const source = nodesById.get(link.source);
          const target = nodesById.get(link.target);
          return (
            <tr key={link.id} className="border-b border-border/50 last:border-none">
              <td className="py-2 pr-3">{source?.value ?? link.source}</td>
              <td className="py-2 pr-3 text-muted-foreground">{formatLabel(link.relationship)}</td>
              <td className="py-2 pr-3">{target?.value ?? link.target}</td>
              <td className="py-2 pr-3">{Math.round((link.confidence ?? 0) * 100)}%</td>
              <td className="py-2 text-muted-foreground">{link.provenance || "unknown"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function EmptyState({ height }: { height: number }) {
  return (
    <div
      style={{ height }}
      className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border text-center"
    >
      <Waypoints className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm text-muted-foreground">No relationships discovered yet</p>
    </div>
  );
}

/**
 * Deterministic radial/spherical layout keyed by node degree -- no physics
 * simulation, so there's nothing to settle and nothing that can jitter.
 * More-connected nodes are pulled toward the center (a "hub"), leaf nodes
 * sit on the outer shell; within a shell, nodes are spread with the golden
 * angle (Vogel's method), which distributes points on a sphere evenly for
 * any node count without needing randomness.
 */
function computeLayout(nodes: GraphNodeDatum[], links: GraphLinkDatum[]): PositionedNode[] {
  const degree = new Map<string, number>();
  for (const link of links) {
    degree.set(link.source, (degree.get(link.source) ?? 0) + 1);
    degree.set(link.target, (degree.get(link.target) ?? 0) + 1);
  }
  let maxDegree = 1;
  for (const node of nodes) maxDegree = Math.max(maxDegree, degree.get(node.id) ?? 0);

  const n = nodes.length;
  const minRadius = 3;
  const maxRadius = 10;
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  return nodes.map((node, i) => {
    const d = degree.get(node.id) ?? 0;
    const radius = minRadius + (1 - d / maxDegree) * (maxRadius - minRadius);
    const phi = n > 1 ? Math.acos(1 - (2 * (i + 0.5)) / n) : Math.PI / 2;
    const theta = goldenAngle * i;
    return {
      ...node,
      degree: d,
      x: radius * Math.sin(phi) * Math.cos(theta),
      y: radius * Math.sin(phi) * Math.sin(theta),
      z: radius * Math.cos(phi),
      color: rgbForIocType(node.ioc_type),
    };
  });
}

export function RelationshipGraph3D({ data, height = 500 }: RelationshipGraph3DProps) {
  const router = useRouter();
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  const [hasBeenVisible, setHasBeenVisible] = React.useState(false);
  const [viewMode, setViewMode] = React.useState<"graph" | "list">("graph");

  const handleNodeClick = React.useCallback(
    (value: string) => {
      router.push(`/lookup/new?value=${encodeURIComponent(value)}`);
    },
    [router]
  );

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    resizeObserver.observe(el);
    setWidth(el.getBoundingClientRect().width);

    // Performance requirement: don't create the WebGL context (or even fetch
    // the three.js/r3f/drei chunk) for a graph the analyst hasn't scrolled
    // to yet. Once it's been seen, keep it mounted -- repeatedly tearing
    // down and recreating a WebGL context on every scroll in/out is itself
    // expensive, so this is a one-way "lazy mount", not a visibility toggle.
    // The scene itself additionally never runs a continuous
    // requestAnimationFrame loop (it uses frameloop="demand"), so once
    // mounted it does no rendering work at all while idle, on- or
    // off-screen.
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

  const graphData = React.useMemo(() => {
    const nodes: GraphNodeDatum[] = (data?.nodes ?? []).map((node) => ({ ...node, id: node.node_id }));
    const links: GraphLinkDatum[] = (data?.edges ?? []).map((edge) => ({
      ...edge,
      id: `${edge.source}->${edge.target}:${edge.relationship}`,
    }));
    return { nodes, links };
  }, [data]);

  // Layout + live-theme colors are recomputed only from graphData (never
  // mutated in place, unlike react-force-graph-2d's d3-force simulation),
  // so graphData itself stays exactly what GraphListView renders.
  const positioned = React.useMemo(() => {
    const positionedNodes = computeLayout(graphData.nodes, graphData.links);
    const byId = new Map(positionedNodes.map((n) => [n.id, n]));
    const borderRgb = rgb01ForCssVar("--border");
    const links: PositionedLink[] = graphData.links.flatMap((link) => {
      const source = byId.get(link.source);
      const target = byId.get(link.target);
      if (!source || !target) return [];
      return [
        {
          ...link,
          sourcePos: [source.x, source.y, source.z] as [number, number, number],
          targetPos: [target.x, target.y, target.z] as [number, number, number],
          color: borderRgb,
        },
      ];
    });
    return { nodes: positionedNodes, links };
  }, [graphData]);

  const isEmpty = !data || data.edges.length === 0;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>Relationship Graph (3D)</CardTitle>
        {!isEmpty && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setViewMode((mode) => (mode === "graph" ? "list" : "graph"))}
          >
            <List className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            {viewMode === "graph" ? "View as list" : "View as graph"}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <div ref={containerRef} className="w-full">
          {isEmpty ? (
            <EmptyState height={height} />
          ) : viewMode === "list" ? (
            <div style={{ maxHeight: height }} className="overflow-y-auto">
              <GraphListView nodes={graphData.nodes} links={graphData.links} />
            </div>
          ) : width > 0 && !hasBeenVisible ? (
            // Lazy-mount placeholder (see the IntersectionObserver above) --
            // occupies the same footprint so nothing jumps once the real
            // scene mounts, without paying for a WebGL context this graph
            // hasn't scrolled into view to need yet.
            <div style={{ height }} className="animate-pulse rounded-md border border-dashed border-border" />
          ) : width > 0 ? (
            <div
              role="img"
              aria-label={`3D relationship graph with ${graphData.nodes.length} nodes and ${graphData.links.length} relationships. Use "View as list" for a keyboard/screen-reader-accessible table of the same data.`}
              style={{ height }}
            >
              <RelationshipGraph3DScene
                nodes={positioned.nodes}
                links={positioned.links}
                width={width}
                height={height}
                onNodeClick={handleNodeClick}
              />
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export default RelationshipGraph3D;
