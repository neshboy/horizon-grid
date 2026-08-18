"use client";

/**
 * Semicircular arc gauge for FinalAssessment.risk.overall_risk_score. Plain
 * SVG (no recharts dependency needed for a single-series arc) -- an arc path
 * for the track, a second arc for the fill, colored via riskScoreColor()'s
 * same thresholds so the gauge always agrees with any other risk-score text
 * on the page.
 *
 * Renders a pulsing skeleton arc when `risk` is null, since this sits above
 * the fold and the final_assessment SSE event is the last thing to arrive.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, riskScoreColor } from "@/lib/utils";
import type { RiskAssessment } from "@/lib/types";

export interface ThreatScoreGaugeProps {
  risk: RiskAssessment | null;
  loading?: boolean;
}

const SIZE = 220;
const STROKE = 16;
const CX = SIZE / 2;
const CY = SIZE / 2 + 6;
const RADIUS = SIZE / 2 - STROKE;

// A semicircle from the 9 o'clock point to the 3 o'clock point, sweeping
// over the top (i.e. the standard "speedometer" half).
const ARC_START = { x: CX - RADIUS, y: CY };
const ARC_END = { x: CX + RADIUS, y: CY };
const TRACK_PATH = `M ${ARC_START.x} ${ARC_START.y} A ${RADIUS} ${RADIUS} 0 0 1 ${ARC_END.x} ${ARC_END.y}`;
const ARC_LENGTH = Math.PI * RADIUS;

/** Maps the score's `text-*` utility class (from riskScoreColor) to the
 * matching `stroke-*` class so the arc fill always matches other risk-score
 * text on the page without hardcoding hex values. */
function scoreStrokeClass(score: number): string {
  const textClass = riskScoreColor(score);
  return textClass.replace("text-", "stroke-");
}

function severityLabel(severity: string): string {
  return severity.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function GaugeSkeleton() {
  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={SIZE} height={SIZE / 2 + STROKE} viewBox={`0 0 ${SIZE} ${SIZE / 2 + STROKE}`}>
        <path
          d={TRACK_PATH}
          fill="none"
          strokeWidth={STROKE}
          strokeLinecap="round"
          className="animate-pulse stroke-muted"
        />
      </svg>
      <div className="flex flex-col items-center gap-1">
        <div className="h-8 w-16 animate-pulse rounded bg-muted" />
        <div className="h-3 w-24 animate-pulse rounded bg-muted" />
      </div>
      <p className="text-xs text-muted-foreground">Awaiting final assessment…</p>
    </div>
  );
}

export function ThreatScoreGauge({ risk, loading }: ThreatScoreGaugeProps) {
  if (!risk || loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Threat Score</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center py-4">
          <GaugeSkeleton />
        </CardContent>
      </Card>
    );
  }

  const score = Math.max(0, Math.min(100, risk.overall_risk_score));
  const fillLength = (score / 100) * ARC_LENGTH;
  const strokeClass = scoreStrokeClass(score);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Threat Score</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center gap-1 sm:flex-row sm:items-center sm:justify-around sm:gap-4">
          <div className="relative flex flex-col items-center">
            <svg width={SIZE} height={SIZE / 2 + STROKE} viewBox={`0 0 ${SIZE} ${SIZE / 2 + STROKE}`}>
              <path
                d={TRACK_PATH}
                fill="none"
                strokeWidth={STROKE}
                strokeLinecap="round"
                className="stroke-muted"
              />
              <path
                d={TRACK_PATH}
                fill="none"
                strokeWidth={STROKE}
                strokeLinecap="round"
                strokeDasharray={`${fillLength} ${ARC_LENGTH}`}
                className={cn("transition-[stroke-dasharray] duration-700 ease-out", strokeClass)}
              />
            </svg>
            <div className="absolute bottom-0 flex flex-col items-center">
              <span className={cn("text-4xl font-bold tabular-nums", riskScoreColor(score))}>
                {score.toFixed(0)}
              </span>
              <span className="text-xs text-muted-foreground">/ 100</span>
            </div>
          </div>

          <div className="flex flex-col gap-3 text-center sm:text-left">
            <div className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">Severity</span>
              <span className={cn("text-lg font-semibold", riskScoreColor(score))}>
                {severityLabel(risk.severity)}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">Confidence</span>
              <span className="text-lg font-semibold tabular-nums text-foreground">
                {risk.confidence_score.toFixed(0)}%
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
