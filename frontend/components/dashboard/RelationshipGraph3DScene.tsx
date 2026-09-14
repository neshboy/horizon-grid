"use client";

/**
 * The actual @react-three/fiber <Canvas> scene for RelationshipGraph3D.tsx.
 * This module touches three.js/WebGL/window at import time (three.js's own
 * side effects, plus @react-three/fiber's Canvas creating a real WebGL
 * context on mount), so it must only ever be loaded via
 * `next/dynamic(..., { ssr: false })` -- see RelationshipGraph3D.tsx, which
 * is the only file that should import this one.
 *
 * Positions/colors are computed once by the caller (a deterministic radial
 * layout keyed by node degree, plus colors read from this app's live CSS
 * variables) -- nothing in here runs a physics simulation or generates any
 * node/edge that wasn't in the `nodes`/`links` props.
 */

import * as React from "react";
import * as THREE from "three";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Line, Html } from "@react-three/drei";
import type { GraphEdge, GraphNode } from "@/lib/types";

// This app hands three.js raw 0..1 RGB triples already converted from its
// own CSS HSL variables (see rgb01ForCssVar/hslToRgb01 in
// RelationshipGraph3D.tsx) specifically so they render unmodified --
// disabling three's automatic sRGB<->linear color-management pipeline here
// keeps `new THREE.Color().setRGB(r, g, b)` a straight passthrough instead
// of a second, redundant color-space conversion on top of the one already
// done by hand.
THREE.ColorManagement.enabled = false;

export interface PositionedNode extends GraphNode {
  id: string;
  degree: number;
  x: number;
  y: number;
  z: number;
  color: [number, number, number];
}

export interface PositionedLink extends GraphEdge {
  id: string;
  sourcePos: [number, number, number];
  targetPos: [number, number, number];
  color: [number, number, number];
}

export interface Scene3DProps {
  nodes: PositionedNode[];
  links: PositionedLink[];
  width: number;
  height: number;
  onNodeClick: (value: string) => void;
}

const NODE_RADIUS = 0.35;

function formatLabel(value: string | null | undefined): string {
  // Same defensive fallback as RelationshipGraph.tsx's formatLabel --
  // nothing currently produces an empty ioc_type, but nothing here would
  // catch it either if that ever changed.
  if (!value) return "unknown";
  return value.replace(/_/g, " ");
}

/** Frees the WebGL context on unmount -- belt-and-suspenders on top of R3F's
 * own default dispose-on-unmount behavior for the geometries/materials
 * declared below, so navigating away from this graph (this is a SPA; users
 * do this constantly) never leaks a WebGL context. */
function CanvasLifecycle() {
  const { gl } = useThree();
  React.useEffect(() => {
    return () => {
      gl.dispose();
    };
  }, [gl]);
  return null;
}

function NodeInstances({
  nodes,
  onNodeClick,
}: {
  nodes: PositionedNode[];
  onNodeClick: (value: string) => void;
}) {
  const meshRef = React.useRef<THREE.InstancedMesh>(null);
  const [hoveredIndex, setHoveredIndex] = React.useState<number | null>(null);
  const { invalidate } = useThree();
  const dummy = React.useMemo(() => new THREE.Object3D(), []);
  const scratchColor = React.useMemo(() => new THREE.Color(), []);

  // Instance transforms/colors are written once per `nodes` change (a new
  // correlation payload or a live theme-color change), never per frame --
  // this is one-time setup for an already laid-out, static point set.
  React.useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    nodes.forEach((node, i) => {
      dummy.position.set(node.x, node.y, node.z);
      dummy.scale.setScalar(1);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, scratchColor.setRGB(node.color[0], node.color[1], node.color[2]));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    invalidate();
  }, [nodes, dummy, scratchColor, invalidate]);

  const setInstanceColor = React.useCallback(
    (index: number, rgb: [number, number, number], mix = 0) => {
      const mesh = meshRef.current;
      if (!mesh) return;
      scratchColor.setRGB(rgb[0], rgb[1], rgb[2]);
      if (mix > 0) scratchColor.lerp(new THREE.Color(1, 1, 1), mix);
      mesh.setColorAt(index, scratchColor);
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    },
    [scratchColor]
  );

  const handlePointerOver = React.useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation();
      const index = e.instanceId;
      if (index == null || index === hoveredIndex) return;
      if (hoveredIndex != null && nodes[hoveredIndex]) {
        setInstanceColor(hoveredIndex, nodes[hoveredIndex].color);
      }
      if (nodes[index]) setInstanceColor(index, nodes[index].color, 0.5);
      setHoveredIndex(index);
      invalidate();
    },
    [hoveredIndex, nodes, setInstanceColor, invalidate]
  );

  const handlePointerOut = React.useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation();
      if (hoveredIndex != null && nodes[hoveredIndex]) {
        setInstanceColor(hoveredIndex, nodes[hoveredIndex].color);
      }
      setHoveredIndex(null);
      invalidate();
    },
    [hoveredIndex, nodes, setInstanceColor, invalidate]
  );

  const handleClick = React.useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      const index = e.instanceId;
      if (index == null) return;
      const node = nodes[index];
      if (node) onNodeClick(node.value);
    },
    [nodes, onNodeClick]
  );

  const hoveredNode = hoveredIndex != null ? nodes[hoveredIndex] ?? null : null;

  return (
    <>
      <instancedMesh
        ref={meshRef}
        args={[undefined, undefined, nodes.length]}
        onPointerOver={handlePointerOver}
        onPointerOut={handlePointerOut}
        onClick={handleClick}
      >
        <sphereGeometry args={[NODE_RADIUS, 16, 16]} />
        <meshBasicMaterial vertexColors toneMapped={false} />
      </instancedMesh>
      {hoveredNode && (
        <Html
          position={[hoveredNode.x, hoveredNode.y, hoveredNode.z]}
          center
          distanceFactor={8}
          style={{ pointerEvents: "none" }}
        >
          <div className="whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-xs shadow-md">
            <div className="font-semibold text-foreground">{hoveredNode.value}</div>
            <div className="text-muted-foreground">{formatLabel(hoveredNode.ioc_type)}</div>
          </div>
        </Html>
      )}
    </>
  );
}

function Edges({ links }: { links: PositionedLink[] }) {
  // A handful to a few hundred edges at this app's real graph sizes -- one
  // <Line> (one draw call) per edge is well within budget and, unlike a
  // single merged-geometry approach, lets each edge keep its own
  // confidence-driven opacity exactly like RelationshipGraph.tsx's linkColor
  // does for the 2D canvas.
  return (
    <>
      {links.map((link) => {
        const confidence = link.confidence ?? 0.5;
        return (
          <Line
            key={link.id}
            points={[link.sourcePos, link.targetPos]}
            color={new THREE.Color().setRGB(link.color[0], link.color[1], link.color[2])}
            transparent
            opacity={0.25 + confidence * 0.55}
            lineWidth={0.6 + confidence * 1.5}
            toneMapped={false}
          />
        );
      })}
    </>
  );
}

export default function RelationshipGraph3DScene({ nodes, links, width, height, onNodeClick }: Scene3DProps) {
  return (
    <div style={{ width, height }}>
      <Canvas
        // "demand" (not the default "always") means R3F never runs a
        // continuous per-frame render loop -- it renders exactly one frame
        // whenever something calls invalidate() (initial mount, a prop
        // change on a declared three object, or the interaction handlers
        // above) and then goes fully idle again. Combined with the
        // lazy/one-time mount gate in RelationshipGraph3D.tsx, an idle or
        // off-screen graph does zero rendering work.
        frameloop="demand"
        dpr={[1, 2]}
        gl={{ alpha: true, antialias: true, powerPreference: "low-power" }}
        camera={{ position: [0, 0, 22], fov: 50 }}
        flat
      >
        <CanvasLifecycle />
        {nodes.length > 0 && <NodeInstances nodes={nodes} onNodeClick={onNodeClick} />}
        <Edges links={links} />
        <OrbitControls makeDefault enableDamping={false} />
      </Canvas>
    </div>
  );
}
