"use client";

/**
 * The actual @react-three/fiber <Canvas> scene for ThreatGlobe.tsx. Same
 * SSR-unsafe-module rationale as RelationshipGraph3DScene.tsx (three.js/
 * WebGL/window side effects at import/mount time) -- must only ever be
 * loaded via `next/dynamic(..., { ssr: false })` from ThreatGlobe.tsx, which
 * is the only file that should import this one.
 *
 * Every marker's position/size/color is computed once by the caller (a
 * real lat/lng->sphere-surface conversion of `world-countries` reference
 * coordinates for a real GeoActivityCountry the backend returned, plus
 * colors read from this app's live CSS variables) -- nothing in here
 * invents a marker, a position, or a count that wasn't in the `markers`
 * prop.
 */

import * as React from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";

// Same rationale as RelationshipGraph3DScene.tsx: this app hands three.js
// raw 0..1 RGB triples already converted from its own CSS HSL variables, so
// disabling three's automatic sRGB<->linear color-management pipeline keeps
// `new THREE.Color().setRGB(r, g, b)` a straight passthrough.
THREE.ColorManagement.enabled = false;

export interface PositionedMarker {
  code: string;
  name: string;
  total: number;
  high_risk: number;
  suspicious: number;
  position: [number, number, number];
  radius: number;
  color: [number, number, number];
}

/** A single investigated IP's real, resolved position -- distinct from the
 * per-country `PositionedMarker`s above (which represent aggregate activity,
 * never a single investigation). `position` is computed by the caller
 * (ThreatGlobe.tsx) using the exact same latLngToVector3/COUNTRY_GEO_BY_CCA2
 * machinery already used for country markers -- this file never invents a
 * position. `severity` drives the beacon's color only; it never gates
 * whether the beacon renders (a real resolved position with no/unknown
 * severity still gets a real beacon, just in a neutral color). */
export interface FocusTarget {
  position: [number, number, number];
  severity: "critical" | "high" | "medium" | "low" | "informational" | null;
}

export interface ThreatGlobeSceneProps {
  markers: PositionedMarker[];
  width: number;
  height: number;
  /** Sphere radius the markers were positioned on -- kept as a prop (rather
   * than a constant duplicated in both files) so the grid sphere and every
   * marker are always positioned on the exact same surface. */
  globeRadius: number;
  gridColor: [number, number, number];
  /** Optional single-IP focus target -- see FocusTarget above. Null/undefined
   * means "no analyst-initiated focus", which must leave every existing
   * country-marker behavior (including idle frameloop="demand") completely
   * unchanged. */
  focusTarget?: FocusTarget | null;
}

// --- Beacon coloring -------------------------------------------------------
// This app has no dedicated per-severity-tier CSS variable set (confirmed by
// grepping app/globals.css and lib/utils.ts) -- severity is always mapped
// onto the existing small semantic palette (--destructive/--warning/
// --primary/--success/--muted-foreground) at the point of use, e.g.
// lib/utils.ts's riskScoreColor() and SecurityAssessmentPanel.tsx's
// severityBadgeVariant(). This mirrors severityBadgeVariant's tier mapping
// exactly (critical/high -> destructive, medium -> warning, low -> the
// "default" badge variant's own color, which is --primary, anything else --
// including a real-but-unclassified "informational"/null severity --
// -> --muted-foreground, the same color severityBadgeVariant's own default
// branch and the Badge component's "muted" variant both already use) rather
// than inventing a new critical/high/medium/low/informational variable set.
function severityCssVar(severity: FocusTarget["severity"]): string {
  switch (severity) {
    case "critical":
    case "high":
      return "--destructive";
    case "medium":
      return "--warning";
    case "low":
      return "--primary";
    default:
      return "--muted-foreground";
  }
}

// Same getComputedStyle-based CSS-variable read ThreatGlobe.tsx/
// RelationshipGraph3D.tsx already use, kept as this module's own copy for the
// same reason both of those files keep their own (see ThreatGlobe.tsx's
// parseHslTriple docstring) -- this module has no other reason to import
// either of those files, and the parser is a handful of lines.
function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

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

/** Frees the WebGL context on unmount -- same belt-and-suspenders as
 * RelationshipGraph3DScene.tsx's CanvasLifecycle. */
function CanvasLifecycle() {
  const { gl } = useThree();
  React.useEffect(() => {
    return () => {
      gl.dispose();
    };
  }, [gl]);
  return null;
}

/** A wireframe sphere whose lat/long segment lines double as the globe's
 * latitude/longitude grid -- no separate grid geometry needed, and nothing
 * here is a decorative texture/image, just a wireframe material colored
 * from this app's own --border CSS variable. */
function GlobeSphere({ radius, gridColor }: { radius: number; gridColor: [number, number, number] }) {
  const color = React.useMemo(() => new THREE.Color().setRGB(gridColor[0], gridColor[1], gridColor[2]), [gridColor]);
  return (
    <mesh>
      <sphereGeometry args={[radius, 32, 24]} />
      <meshBasicMaterial color={color} wireframe transparent opacity={0.3} toneMapped={false} />
    </mesh>
  );
}

function Markers({ markers }: { markers: PositionedMarker[] }) {
  const [hoveredCode, setHoveredCode] = React.useState<string | null>(null);
  const { invalidate } = useThree();

  const handlePointerOver = React.useCallback(
    (code: string) => (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation();
      setHoveredCode(code);
      invalidate();
    },
    [invalidate]
  );

  const handlePointerOut = React.useCallback(
    (code: string) => (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation();
      setHoveredCode((current) => (current === code ? null : current));
      invalidate();
    },
    [invalidate]
  );

  const hoveredMarker = markers.find((m) => m.code === hoveredCode) ?? null;

  return (
    <>
      {markers.map((marker) => {
        const isHovered = marker.code === hoveredCode;
        return (
          <mesh
            key={marker.code}
            position={marker.position}
            scale={isHovered ? 1.4 : 1}
            onPointerOver={handlePointerOver(marker.code)}
            onPointerOut={handlePointerOut(marker.code)}
          >
            <sphereGeometry args={[marker.radius, 14, 14]} />
            <meshBasicMaterial
              color={new THREE.Color().setRGB(marker.color[0], marker.color[1], marker.color[2])}
              toneMapped={false}
            />
          </mesh>
        );
      })}
      {hoveredMarker && (
        <Html position={hoveredMarker.position} center distanceFactor={10} style={{ pointerEvents: "none" }}>
          <div className="whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-xs shadow-md">
            <div className="font-semibold text-foreground">{hoveredMarker.name}</div>
            <div className="text-muted-foreground">Total: {hoveredMarker.total}</div>
            {hoveredMarker.high_risk > 0 && (
              <div className="text-muted-foreground">High-risk: {hoveredMarker.high_risk}</div>
            )}
            {hoveredMarker.suspicious > 0 && (
              <div className="text-muted-foreground">Suspicious: {hoveredMarker.suspicious}</div>
            )}
          </div>
        </Html>
      )}
    </>
  );
}

// Beacon dimensions, in the same world units as `globeRadius`/marker
// positions -- fixed absolute sizes (not scaled by globeRadius) since
// GLOBE_RADIUS is itself a fixed constant (ThreatGlobe.tsx's GLOBE_RADIUS =
// 6) in this app, never a caller-varying value in practice.
const BEACON_STEM_HEIGHT = 0.9;
const BEACON_STEM_RADIUS = 0.16;
const BEACON_RING_INNER_RADIUS = 0.35;
const BEACON_RING_OUTER_RADIUS = 0.5;
const BEACON_PULSE_SPEED = 1.6; // radians/sec-ish, drives the ring's sine pulse

/** The single-investigation beacon -- a short cone standing outward from the
 * globe surface plus a slowly pulsing ring at its base, deliberately
 * different in shape (not just color) from the small round markers
 * <Markers> renders for per-country activity, so an analyst can never
 * mistake "the IP I navigated here to see" for "a country with activity".
 * Continuously calls invalidate() via useFrame ONLY while mounted (i.e. only
 * while a real focusTarget exists) -- see ThreatGlobeScene's own docstring/
 * frameloop="demand" comment; this is the one deliberate, spec'd exception
 * to "no continuous render loop when idle", scoped to exactly the lifetime
 * of this component. */
function Beacon({ position, color }: { position: [number, number, number]; color: THREE.Color }) {
  const { invalidate } = useThree();
  const ringRef = React.useRef<THREE.Mesh>(null);

  // Orients the beacon's local "up" (+Y) to point straight out of the globe
  // surface at `position` -- the same surface normal latLngToVector3 implies
  // for every point on the sphere -- so the cone/ring sit flush against the
  // globe everywhere, not just at the north pole.
  const quaternion = React.useMemo(() => {
    const normal = new THREE.Vector3(position[0], position[1], position[2]);
    if (normal.lengthSq() === 0) return new THREE.Quaternion();
    normal.normalize();
    return new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal);
  }, [position]);

  useFrame(({ clock }) => {
    const ring = ringRef.current;
    if (ring) {
      const pulse = (Math.sin(clock.elapsedTime * BEACON_PULSE_SPEED) + 1) / 2; // 0..1
      ring.scale.setScalar(1 + pulse * 0.7);
      const material = ring.material as THREE.MeshBasicMaterial;
      material.opacity = 0.55 - pulse * 0.4;
    }
    invalidate();
  });

  return (
    <group position={position} quaternion={quaternion}>
      <mesh position={[0, BEACON_STEM_HEIGHT / 2, 0]}>
        <coneGeometry args={[BEACON_STEM_RADIUS, BEACON_STEM_HEIGHT, 12]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
      <mesh ref={ringRef} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[BEACON_RING_INNER_RADIUS, BEACON_RING_OUTER_RADIUS, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.5} side={THREE.DoubleSide} toneMapped={false} />
      </mesh>
    </group>
  );
}

// Camera-flight tuning: a short hop across a few degrees stays snappy (1.5s),
// a full half-globe traverse takes the full 3s -- both comfortably inside the
// "roughly 1.5-3 seconds depending on angular distance" spec.
const FOCUS_FLIGHT_MIN_MS = 1500;
const FOCUS_FLIGHT_MAX_MS = 3000;
// How far outside the globe the camera parks once focused -- between
// OrbitControls' own minDistance (1.4x) and maxDistance (6x) below, and
// close enough to make the beacon read clearly without clipping into it.
const FOCUS_CAMERA_DISTANCE_MULTIPLIER = 2.2;

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

interface CameraFlightState {
  startPos: THREE.Vector3;
  endPos: THREE.Vector3;
  startTime: number;
  durationMs: number;
}

/** Drives the camera-flight animation described in ThreatGlobeScene's task
 * spec: on a NEW focusTarget position, eases the camera from wherever it
 * currently is to a point along the line from the globe center through
 * focusTarget.position, at FOCUS_CAMERA_DISTANCE_MULTIPLIER * globeRadius --
 * which keeps the camera looking directly at focusTarget.position (that
 * point and the camera's destination are colinear with the globe center) by
 * construction, no separate lookAt target needed beyond OrbitControls' own
 * default (0,0,0) target.
 *
 * `flightStateRef` is owned by the parent (ThreatGlobeScene's default
 * export) and also read/cleared by OrbitControls' own onStart handler there
 * -- the instant the user starts dragging, the parent nulls it out and this
 * component's next useFrame tick simply finds nothing to animate, handing
 * control back immediately rather than fighting the drag.
 */
function CameraFocusAnimator({
  focusTarget,
  globeRadius,
  flightStateRef,
}: {
  focusTarget: FocusTarget | null | undefined;
  globeRadius: number;
  flightStateRef: React.MutableRefObject<CameraFlightState | null>;
}) {
  const { camera, controls, invalidate } = useThree();
  // Only auto-animate once per distinct focusTarget position -- re-renders
  // with the SAME position (e.g. a parent re-render that doesn't actually
  // change where the analyst is looking) must never restart the flight.
  const lastAnimatedKeyRef = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (!focusTarget) return;
    const key = focusTarget.position.join(",");
    if (lastAnimatedKeyRef.current === key) return;

    const endPos = new THREE.Vector3(...focusTarget.position);
    if (endPos.lengthSq() === 0) return; // degenerate/unresolvable position -- never fly to the globe's own center
    endPos.normalize().multiplyScalar(globeRadius * FOCUS_CAMERA_DISTANCE_MULTIPLIER);

    lastAnimatedKeyRef.current = key;
    const startPos = camera.position.clone();
    const angularDistance = startPos.clone().normalize().angleTo(endPos.clone().normalize());
    const durationMs =
      FOCUS_FLIGHT_MIN_MS + (FOCUS_FLIGHT_MAX_MS - FOCUS_FLIGHT_MIN_MS) * Math.min(1, angularDistance / Math.PI);

    flightStateRef.current = { startPos, endPos, startTime: performance.now(), durationMs };
    invalidate();
  }, [focusTarget, globeRadius, camera, invalidate, flightStateRef]);

  useFrame(() => {
    const flight = flightStateRef.current;
    if (!flight) return;
    const elapsed = performance.now() - flight.startTime;
    const t = Math.min(1, elapsed / flight.durationMs);
    camera.position.lerpVectors(flight.startPos, flight.endPos, easeInOutCubic(t));
    camera.lookAt(0, 0, 0);
    // Resyncs OrbitControls' own internal spherical state to the position
    // we just drove directly, so a drag starting the instant this flight
    // ends (or mid-flight, via the cancellation path documented above)
    // continues smoothly from where the camera visually is.
    (controls as { update?: () => void } | null)?.update?.();
    invalidate();
    if (t >= 1) flightStateRef.current = null;
  });

  return null;
}

export default function ThreatGlobeScene({
  markers,
  width,
  height,
  globeRadius,
  gridColor,
  focusTarget,
}: ThreatGlobeSceneProps) {
  const flightStateRef = React.useRef<CameraFlightState | null>(null);

  // Recomputed only when the beacon's severity changes (or the beacon
  // appears/disappears) -- same one-time-per-relevant-change convention
  // ThreatGlobe.tsx's own rgb01ForCssVar callers already use for marker
  // colors, not a per-frame CSS read.
  const beaconColor = React.useMemo(() => {
    if (!focusTarget) return null;
    const rgb = rgb01ForCssVar(severityCssVar(focusTarget.severity));
    return new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2]);
  }, [focusTarget?.severity]);

  return (
    <div style={{ width, height }}>
      <Canvas
        // Same "no continuous render loop" rationale as
        // RelationshipGraph3DScene.tsx -- renders exactly one frame whenever
        // something calls invalidate() (initial mount, a declared three
        // object prop change, or the hover handlers above), then goes fully
        // idle again. The one deliberate exception is the Beacon component
        // below, which invalidates every frame for as long as (and only as
        // long as) a real focusTarget is mounted -- see its own docstring.
        frameloop="demand"
        dpr={[1, 2]}
        gl={{ alpha: true, antialias: true, powerPreference: "low-power" }}
        camera={{ position: [0, 0, globeRadius * 2.7], fov: 45 }}
        flat
      >
        <CanvasLifecycle />
        <GlobeSphere radius={globeRadius} gridColor={gridColor} />
        {markers.length > 0 && <Markers markers={markers} />}
        {focusTarget && beaconColor && <Beacon position={focusTarget.position} color={beaconColor} />}
        <CameraFocusAnimator focusTarget={focusTarget} globeRadius={globeRadius} flightStateRef={flightStateRef} />
        <OrbitControls
          makeDefault
          enableDamping={false}
          minDistance={globeRadius * 1.4}
          maxDistance={globeRadius * 6}
          onStart={() => {
            // The analyst grabbed the globe -- cancel any in-flight
            // auto-animation immediately and leave the camera exactly where
            // it is; never fight the user for control.
            flightStateRef.current = null;
          }}
        />
      </Canvas>
    </div>
  );
}
