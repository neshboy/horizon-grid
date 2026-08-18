"use client";

/**
 * The Investigation Copilot: a persistent Q&A panel scoped to the current
 * lookup's evidence ledger + correlation graph + analyst notes typed in this
 * session (backend/app/ai/analysis_service.py's answer_copilot_question).
 * The analyst never re-pastes context -- every question is answered against
 * whatever this lookup already knows, with Show Receipts on every answer.
 */

import * as React from "react";
import { Bot, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { askCopilot } from "@/lib/api";
import { ShowReceiptsLink } from "./ShowReceiptsLink";

export interface InvestigationCopilotProps {
  lookupId: string;
  onShowReceipts: (evidenceIds: string[]) => void;
}

interface ChatTurn {
  question: string;
  answer: string;
  evidenceIds: string[];
  followUps: string[];
}

const SUGGESTED_STARTERS = [
  "Why is this suspicious?",
  "What changed since last week?",
  "Which provider has the strongest evidence?",
  "Is this likely a false positive?",
  "What should I investigate next?",
];

export function InvestigationCopilot({ lookupId, onShowReceipts }: InvestigationCopilotProps) {
  const [turns, setTurns] = React.useState<ChatTurn[]>([]);
  const [question, setQuestion] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const ask = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;
      setLoading(true);
      setError(null);
      setQuestion("");
      try {
        const notes = turns.map((t) => `Q: ${t.question}\nA: ${t.answer}`);
        const result = await askCopilot(lookupId, trimmed, notes);
        setTurns((prev) => [
          ...prev,
          { question: trimmed, answer: result.answer, evidenceIds: result.evidence_ids, followUps: result.suggested_follow_ups },
        ]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Copilot request failed");
      } finally {
        setLoading(false);
      }
    },
    [lookupId, loading, turns]
  );

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bot className="h-4 w-4" aria-hidden="true" />
          Investigation Copilot
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {turns.length === 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground">Ask anything about this investigation. Try:</p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTED_STARTERS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => ask(s)}
                  className="rounded-full border border-border bg-muted/30 px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/60 hover:text-foreground"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div ref={scrollRef} className="flex max-h-96 flex-col gap-3 overflow-y-auto">
          {turns.map((turn, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <p className="text-xs font-medium text-muted-foreground">You: {turn.question}</p>
              <div className="rounded-md border border-border bg-muted/20 p-3">
                <p className="text-sm text-foreground">{turn.answer}</p>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <ShowReceiptsLink evidenceIds={turn.evidenceIds} onShowReceipts={onShowReceipts} />
                </div>
                {turn.followUps.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {turn.followUps.map((f) => (
                      <button
                        key={f}
                        type="button"
                        onClick={() => ask(f)}
                        className="rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/60 hover:text-foreground"
                      >
                        {f}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="flex items-center gap-2"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask the Copilot about this investigation..."
            disabled={loading}
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-primary"
          />
          <Button type="submit" size="sm" disabled={loading || !question.trim()}>
            <Send className="h-3.5 w-3.5" aria-hidden="true" />
            {loading ? "Thinking..." : "Ask"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
