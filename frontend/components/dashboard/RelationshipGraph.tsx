"use client";

/**
 * Force-directed relationship graph for CorrelationPayload { nodes, edges }.
 * `react-force-graph-2d` touches canvas/window directly, so it's dynamically
 * imported with { ssr: false } -- this file must stay a client component and
 * must never be imported anywhere that could render on the server.
 *
 * Node/edge colors are derived from this app's own --primary/--accent/
 * --warning/--destructive/--success/--muted-foreground HSL CSS variables
 * (see app/globals.css) rather than new hardcoded hex values, so the graph
 * always matches the rest of the dark theme.
 */

import * as React from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { List, Waypoints } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CorrelationPayload, GraphEdge, GraphNode } from "@/lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

export interface RelationshipGraphProps {
  data: CorrelationPayload | null;
  height?: number;
}

interface GraphNodeDatum extends GraphNode {
  id: string;
}

interface GraphLinkDatum extends GraphEdge {
  id: string;
}

// One fixed hue per IOC-type family, each resolved from an existing CSS
// variable (see app/globals.css) at render time -- never a new hardcoded hex.
// Families group related types so the graph doesn't need a slot per enum
// value (there are ~30 IOCType values, but only a handful of visual families).
const TYPE_FAMILY_VAR: Record<string, string> = {
  // Network / infrastructure observables -> primary (cyan).
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
  // File / hash observables -> destructive (red).
  md5: "--destructive",
  sha1: "--destructive",
  sha256: "--destructive",
  sha512: "--destructive",
  file_name: "--destructive",
  file_path: "--destructive",
  // Threat-actor / campaign / malware attribution -> accent (violet).
  malware_family: "--accent",
  threat_actor: "--accent",
  campaign: "--accent",
  yara_rule: "--accent",
  sigma_rule: "--accent",
  // Vulnerability / technique context -> warning (amber).
  cve: "--warning",
  cwe: "--warning",
  capec: "--warning",
  mitre_technique: "--warning",
  // Host / endpoint artifacts -> success (green).
  registry_key: "--success",
  process_name: "--success",
  mutex: "--success",
  windows_service: "--success",
  // Everything else (email, user_agent, crypto_wallet, unknown, ...) falls
  // through to the default below.
};
const DEFAULT_TYPE_VAR = "--muted-foreground";

function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function colorForIocType(iocType: string): string {
  const varName = TYPE_FAMILY_VAR[iocType] ?? DEFAULT_TYPE_VAR;
  const hsl = cssVar(varName);
  return hsl ? `hsl(${hsl})` : "hsl(215 20% 65%)";
}

function formatLabel(value: string | null | undefined): string {
  // Defensive: every current edge-construction path in the backend only
  // ever produces a non-empty relationship/provenance string, but nothing
  // in the serialization layer (a raw dataclass __dict__ dump, no
  // validating response_model) would actually catch it if that ever
  // changed -- cheap insurance against the exact TypeError this shape of
  // bug would otherwise cause (`undefined.replace is not a function`).
  if (!value) return "unknown";
  return value.replace(/_/g, " ");
}

function nodeTooltip(node: GraphNodeDatum): string {
  return `<div style="font:12px sans-serif;padding:2px 4px"><strong>${escapeHtml(
    node.value
  )}</strong><br/><span style="opacity:.75">${escapeHtml(formatLabel(node.ioc_type))}</span></div>`;
}

function linkTooltip(link: GraphLinkDatum): string {
  const confidencePct = Math.round((link.confidence ?? 0) * 100);
  return `<div style="font:12px sans-serif;padding:2px 4px"><strong>${escapeHtml(
    formatLabel(link.relationship)
  )}</strong><br/><span style="opacity:.75">source: ${escapeHtml(
    link.provenance
  )}</span><br/><span style="opacity:.75">confidence: ${confidencePct}%</span></div>`;
}

function escapeHtml(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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

export function RelationshipGraph({ data, height = 500 }: RelationshipGraphProps) {
  const router = useRouter();
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  const [viewMode, setViewMode] = React.useState<"graph" | "list">("graph");

  const handleNodeClick = React.useCallback(
    (node: GraphNodeDatum) => {
      router.push(`/lookup/new?value=${encodeURIComponent(node.value)}`);
    },
    [router]
  );

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  const graphData = React.useMemo(() => {
    const nodes: GraphNodeDatum[] = (data?.nodes ?? []).map((node) => ({ ...node, id: node.node_id }));
    const links: GraphLinkDatum[] = (data?.edges ?? []).map((edge) => ({
      ...edge,
      id: `${edge.source}->${edge.target}:${edge.relationship}`,
    }));
    return { nodes, links };
  }, [data]);

  // react-force-graph-2d's underlying d3-force simulation mutates its input
  // IN PLACE once it starts: it writes x/y/vx/vy/index onto every node
  // object, and -- critically -- replaces each link's `source`/`target`
  // (originally the plain string ids graphData was built with) with direct
  // references to the corresponding node objects. Confirmed live: switching
  // to "View as list" after the graph had already rendered crashed the
  // whole page with React error #31 ("Objects are not valid as a React
  // child"), because GraphListView's nodesById.get(link.source) then failed
  // (the key was no longer a string) and its `?? link.source` fallback
  // rendered the mutated node object itself as a table cell. Feeding the
  // force graph its own shallow-cloned copy keeps those mutations
  // contained to the simulation's own throwaway objects, so `graphData` --
  // shared with the list view -- is never touched no matter how many times
  // the graph has rendered.
  const forceGraphData = React.useMemo(
    () => ({
      nodes: graphData.nodes.map((n) => ({ ...n })),
      links: graphData.links.map((l) => ({ ...l })),
    }),
    [graphData]
  );

  const isEmpty = !data || data.edges.length === 0;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>Relationship Graph</CardTitle>
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
          ) : width > 0 ? (
            <div
              role="img"
              aria-label={`Force-directed relationship graph with ${graphData.nodes.length} nodes and ${graphData.links.length} relationships. Use "View as list" for a keyboard/screen-reader-accessible table of the same data.`}
            >
              <ForceGraph2D
                graphData={forceGraphData}
                width={width}
                height={height}
                backgroundColor="transparent"
                nodeId="id"
                nodeLabel={(node) => nodeTooltip(node as GraphNodeDatum)}
                nodeColor={(node) => colorForIocType((node as GraphNodeDatum).ioc_type)}
                onNodeClick={(node) => handleNodeClick(node as GraphNodeDatum)}
                nodeRelSize={5}
                nodeCanvasObjectMode={() => "after"}
                nodeCanvasObject={(node, ctx, globalScale) => {
                  const n = node as GraphNodeDatum & { x?: number; y?: number };
                  if (n.x == null || n.y == null) return;
                  const fontSize = 11 / globalScale;
                  ctx.font = `${fontSize}px sans-serif`;
                  ctx.textAlign = "center";
                  ctx.textBaseline = "top";
                  ctx.fillStyle = cssVar("--foreground") ? `hsl(${cssVar("--foreground")})` : "#e2e8f0";
                  ctx.fillText(n.value, n.x, n.y + 7);
                }}
                linkLabel={(link) => linkTooltip(link as GraphLinkDatum)}
                linkColor={(link) => {
                  const confidence = (link as GraphLinkDatum).confidence ?? 0.5;
                  const base = cssVar("--border");
                  // Lower-confidence edges render more translucent so a
                  // single-source, unverified relationship doesn't look as
                  // visually certain as a multi-provider-corroborated one.
                  const opacity = 0.25 + confidence * 0.55;
                  return base ? `hsl(${base} / ${opacity})` : `rgba(148,163,184,${opacity})`;
                }}
                linkWidth={(link) => 0.6 + ((link as GraphLinkDatum).confidence ?? 0.5) * 1.5}
                linkDirectionalArrowLength={4}
                linkDirectionalArrowRelPos={1}
                linkCurvature={0.15}
                cooldownTicks={100}
              />
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
