"use client";

/**
 * The "explain the verdict" cluster: WHY malicious, WHAT IS THIS, Score
 * Explanation, Provider Disagreement, False Positive Check, and Challenge
 * This Verdict ("argue against yourself"). Each is fetched on demand (not
 * automatically, since they're extra AI calls) and every claim carries a
 * "Show Receipts" link back to the EvidencePanel -- see
 * backend/app/ai/analysis_service.py for the grounding guarantee behind that.
 */

import * as React from "react";
import { AlertTriangle, HelpCircle, ScaleIcon, ShieldQuestion, Sparkles, Swords } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  challengeVerdict,
  checkFalsePositive,
  explainDisagreement,
  explainScore,
  explainWhatIsThis,
  explainWhyMalicious,
} from "@/lib/api";
import type {
  ChallengeVerdict as ChallengeVerdictType,
  DisagreementSummary,
  FalsePositiveAssessment,
  ScoreExplanation,
  WhatIsThisIOC,
  WhyMaliciousExplanation,
} from "@/lib/types";
import { ShowReceiptsLink } from "./ShowReceiptsLink";

type ModeKey = "why" | "what" | "score" | "disagreement" | "false_positive" | "challenge";

interface VerdictAnalysisPanelProps {
  lookupId: string;
  onShowReceipts: (evidenceIds: string[]) => void;
}

const MODES: { key: ModeKey; label: string; Icon: React.ComponentType<{ className?: string }> }[] = [
  { key: "why", label: "WHY?", Icon: HelpCircle },
  { key: "what", label: "What is this?", Icon: Sparkles },
  { key: "score", label: "Score Explanation", Icon: ScaleIcon },
  { key: "disagreement", label: "Intelligence Conflicts", Icon: AlertTriangle },
  { key: "false_positive", label: "False Positive Check", Icon: ShieldQuestion },
  { key: "challenge", label: "Challenge This Verdict", Icon: Swords },
];

type ResultMap = {
  why?: WhyMaliciousExplanation;
  what?: WhatIsThisIOC;
  score?: ScoreExplanation;
  disagreement?: DisagreementSummary;
  false_positive?: FalsePositiveAssessment;
  challenge?: ChallengeVerdictType;
};

export function VerdictAnalysisPanel({ lookupId, onShowReceipts }: VerdictAnalysisPanelProps) {
  const [active, setActive] = React.useState<ModeKey | null>(null);
  const [loading, setLoading] = React.useState<ModeKey | null>(null);
  const [results, setResults] = React.useState<ResultMap>({});
  const [errors, setErrors] = React.useState<Partial<Record<ModeKey, string>>>({});

  const handleClick = React.useCallback(
    async (mode: ModeKey) => {
      setActive(mode);
      if (results[mode]) return; // cached
      setLoading(mode);
      setErrors((prev) => ({ ...prev, [mode]: undefined }));
      try {
        let result;
        switch (mode) {
          case "why":
            result = await explainWhyMalicious(lookupId);
            break;
          case "what":
            result = await explainWhatIsThis(lookupId);
            break;
          case "score":
            result = await explainScore(lookupId);
            break;
          case "disagreement":
            result = await explainDisagreement(lookupId);
            break;
          case "false_positive":
            result = await checkFalsePositive(lookupId);
            break;
          case "challenge":
            result = await challengeVerdict(lookupId);
            break;
        }
        setResults((prev) => ({ ...prev, [mode]: result }));
      } catch (err) {
        setErrors((prev) => ({ ...prev, [mode]: err instanceof Error ? err.message : "Generation failed" }));
      } finally {
        setLoading(null);
      }
    },
    [lookupId, results]
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Verdict Analysis</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-2">
          {MODES.map(({ key, label, Icon }) => (
            <Button
              key={key}
              size="sm"
              variant={active === key ? "default" : "outline"}
              onClick={() => handleClick(key)}
              disabled={loading === key}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              {loading === key ? "Generating..." : label}
            </Button>
          ))}
        </div>

        {active && errors[active] && <p className="text-xs text-destructive">{errors[active]}</p>}

        {active === "why" && results.why && (
          <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/20 p-3">
            <p className="text-sm font-semibold text-foreground">{results.why.verdict_restated}</p>
            <ol className="flex flex-col gap-2 pl-5 text-sm text-foreground">
              {results.why.reasons.map((r, i) => (
                <li key={i} className="list-decimal leading-relaxed">
                  <div className="flex flex-wrap items-center gap-2">
                    <span>{r.reason}</span>
                    <ShowReceiptsLink evidenceIds={r.evidence_ids} onShowReceipts={onShowReceipts} />
                  </div>
                </li>
              ))}
            </ol>
            {results.why.reasons.length === 0 && (
              <p className="text-xs text-muted-foreground">No specific reasons could be grounded in the evidence.</p>
            )}
            {results.why.caveat && <p className="text-xs italic text-muted-foreground">{results.why.caveat}</p>}
          </div>
        )}

        {active === "what" && results.what && (
          <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/20 p-3">
            <p className="text-sm font-medium text-foreground">{results.what.plain_language_summary}</p>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Technical explanation
              </p>
              <p className="text-sm text-foreground">{results.what.technical_explanation}</p>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Confidence</p>
              <p className="text-sm text-foreground">{results.what.confidence_narrative}</p>
            </div>
            {results.what.related_infrastructure.length > 0 && (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Related infrastructure
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {results.what.related_infrastructure.map((ioc) => (
                    <span key={ioc} className="rounded-full border border-border bg-muted px-2 py-0.5 text-[11px]">
                      {ioc}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <ShowReceiptsLink evidenceIds={results.what.evidence_ids} onShowReceipts={onShowReceipts} />
          </div>
        )}

        {active === "score" && results.score && (
          <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/20 p-3">
            {results.score.components.map((c, i) => (
              <div key={i} className="flex flex-col gap-1 border-b border-border/50 pb-2 last:border-none">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-foreground">{c.component}</span>
                  <ShowReceiptsLink evidenceIds={c.evidence_ids} onShowReceipts={onShowReceipts} />
                </div>
                <p className="text-xs text-muted-foreground">{c.contribution}</p>
              </div>
            ))}
            <p className="text-sm text-foreground">{results.score.summary}</p>
          </div>
        )}

        {active === "disagreement" && results.disagreement && (
          <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/20 p-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-success">Agreement</p>
              <p className="text-sm text-foreground">{results.disagreement.agreement}</p>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-warning">Conflict</p>
              <p className="text-sm text-foreground">{results.disagreement.conflict}</p>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Missing Data</p>
              <p className="text-sm text-foreground">{results.disagreement.missing_data}</p>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">Most Reliable Evidence</p>
              <p className="text-sm text-foreground">{results.disagreement.most_reliable_evidence}</p>
            </div>
            <ShowReceiptsLink evidenceIds={results.disagreement.evidence_ids} onShowReceipts={onShowReceipts} />
          </div>
        )}

        {active === "false_positive" && results.false_positive && (
          <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/20 p-3">
            <span
              className={cn(
                "inline-flex w-fit items-center rounded-full border px-3 py-1 text-xs font-semibold",
                results.false_positive.likely_false_positive
                  ? "border-warning/40 bg-warning/10 text-warning"
                  : "border-success/40 bg-success/10 text-success"
              )}
            >
              {results.false_positive.likely_false_positive ? "Possible false positive" : "No false-positive indicators found"}
            </span>
            {results.false_positive.candidate_categories.filter((c) => c !== "none").length > 0 && (
              <div className="flex flex-wrap gap-1">
                {results.false_positive.candidate_categories
                  .filter((c) => c !== "none")
                  .map((c) => (
                    <span key={c} className="rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] capitalize">
                      {c.replace(/_/g, " ")}
                    </span>
                  ))}
              </div>
            )}
            <p className="text-sm text-foreground">{results.false_positive.explanation}</p>
            <ShowReceiptsLink evidenceIds={results.false_positive.evidence_ids} onShowReceipts={onShowReceipts} />
          </div>
        )}

        {active === "challenge" && results.challenge && (
          <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/20 p-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-success">Supporting Evidence</p>
              {results.challenge.supporting_evidence.length === 0 ? (
                <p className="text-xs text-muted-foreground">None identified.</p>
              ) : (
                <ul className="flex flex-col gap-1 pl-4 text-sm text-foreground">
                  {results.challenge.supporting_evidence.map((r, i) => (
                    <li key={i} className="list-disc">
                      <div className="flex flex-wrap items-center gap-2">
                        <span>{r.reason}</span>
                        <ShowReceiptsLink evidenceIds={r.evidence_ids} onShowReceipts={onShowReceipts} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-destructive">Contradictory Evidence</p>
              {results.challenge.contradictory_evidence.length === 0 ? (
                <p className="text-xs text-muted-foreground">None identified.</p>
              ) : (
                <ul className="flex flex-col gap-1 pl-4 text-sm text-foreground">
                  {results.challenge.contradictory_evidence.map((r, i) => (
                    <li key={i} className="list-disc">
                      <div className="flex flex-wrap items-center gap-2">
                        <span>{r.reason}</span>
                        <ShowReceiptsLink evidenceIds={r.evidence_ids} onShowReceipts={onShowReceipts} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {results.challenge.missing_evidence.length > 0 && (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Missing Evidence</p>
                <ul className="flex flex-col gap-1 pl-4 text-sm text-foreground">
                  {results.challenge.missing_evidence.map((m, i) => (
                    <li key={i} className="list-disc">{m}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Alternative Explanation</p>
              <p className="text-sm text-foreground">{results.challenge.alternative_explanation}</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Final Confidence</span>
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
                  results.challenge.final_confidence === "high"
                    ? "border-destructive/40 bg-destructive/10 text-destructive"
                    : results.challenge.final_confidence === "medium"
                    ? "border-warning/40 bg-warning/10 text-warning"
                    : "border-border bg-muted text-muted-foreground"
                )}
              >
                {results.challenge.final_confidence}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">{results.challenge.final_confidence_rationale}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
