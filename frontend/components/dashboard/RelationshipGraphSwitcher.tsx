"use client";

/**
 * Small 2D/3D toggle wrapping RelationshipGraph and its new 3D sibling.
 * Defaults to the proven, mature 2D view (react-force-graph-2d) -- the 3D
 * view (three.js/@react-three/fiber) is opt-in via the toggle, not a
 * wholesale replacement, so nothing about the existing analyst workflow
 * changes unless someone deliberately switches. Both underlying components
 * render their own Card/CardHeader; this only decides which one mounts.
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { RelationshipGraph } from "@/components/dashboard/RelationshipGraph";
import { RelationshipGraph3D } from "@/components/dashboard/RelationshipGraph3D";
import type { CorrelationPayload } from "@/lib/types";

export interface RelationshipGraphSwitcherProps {
  data: CorrelationPayload | null;
  height?: number;
}

export function RelationshipGraphSwitcher({ data, height }: RelationshipGraphSwitcherProps) {
  const [mode, setMode] = React.useState<"2d" | "3d">("2d");

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-end gap-1">
        <Button
          type="button"
          variant={mode === "2d" ? "default" : "outline"}
          size="sm"
          onClick={() => setMode("2d")}
        >
          2D
        </Button>
        <Button
          type="button"
          variant={mode === "3d" ? "default" : "outline"}
          size="sm"
          onClick={() => setMode("3d")}
        >
          3D
        </Button>
      </div>
      {mode === "2d" ? (
        <RelationshipGraph data={data} height={height} />
      ) : (
        <RelationshipGraph3D data={data} height={height} />
      )}
    </div>
  );
}
