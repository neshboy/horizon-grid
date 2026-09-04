"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { buildAiAnalysisPrompt } from "@/lib/aiPrompt";
import type { CorrelationPayload, ProviderResult, ProviderSummary } from "@/lib/types";

interface AskAiPanelProps {
  iocValue: string;
  iocType: string | null;
  providerResults: ProviderResult[];
  providerSummaries: Record<string, ProviderSummary>;
  correlation: CorrelationPayload | null;
}

// Google blocks gemini.google.com from being loaded in an <iframe> (it sends
// X-Frame-Options / CSP frame-ancestors headers, same as Gmail or any other
// logged-in Google product) -- so a true embedded box isn't possible. A real
// separate popup *window* isn't a frame and isn't subject to that block, so
// this opens Gemini in a small, fixed-size popup positioned next to the
// dashboard -- as close to "a small Gemini box on this page" as the browser
// security model allows.
const POPUP_WIDTH = 420;
const POPUP_HEIGHT = 640;
const POPUP_NAME = "ioc-intel-gemini-popup";

function openGeminiPopup(): Window | null {
  // Deliberately no "noopener" here -- window.open() returns null when it's
  // set, which would break the focus()/closed re-use logic below. This opens
  // Gemini's own page, not user-supplied content, so keeping the opener
  // reference carries no meaningful risk.
  const left = window.screenX + window.outerWidth - POPUP_WIDTH - 24;
  const top = window.screenY + 80;
  const features = `width=${POPUP_WIDTH},height=${POPUP_HEIGHT},left=${left},top=${top},resizable=yes,scrollbars=yes`;
  return window.open("https://gemini.google.com/app", POPUP_NAME, features);
}

export function AskAiPanel({
  iocValue,
  iocType,
  providerResults,
  providerSummaries,
  correlation,
}: AskAiPanelProps) {
  const [message, setMessage] = React.useState<string | null>(null);
  const [fallbackPrompt, setFallbackPrompt] = React.useState<string | null>(null);
  const popupRef = React.useRef<Window | null>(null);

  const hasData = providerResults.some((r) => r.status === "ok");

  const handleAskGemini = React.useCallback(() => {
    const prompt = buildAiAnalysisPrompt(iocValue, iocType, providerResults, providerSummaries, correlation);
    setFallbackPrompt(null);

    // Real bug found live during overnight QA: window.open() used to run
    // AFTER an awaited clipboard write, outside the synchronous portion of
    // this click handler -- some browsers only honor the "genuine user
    // gesture" that unlocks a popup within that synchronous stack, so a
    // window.open() call reached after an await could get silently treated
    // as a blocked popup purely due to timing, independent of any actual
    // popup-blocker setting. Opening the popup first (still synchronously,
    // still inside the click handler) and copying to the clipboard
    // afterward, asynchronously, avoids that.
    let popup: Window | null = null;
    if (popupRef.current && !popupRef.current.closed) {
      popupRef.current.focus();
      popup = popupRef.current;
    } else {
      popup = openGeminiPopup();
      popupRef.current = popup;
    }

    void (async () => {
      try {
        await navigator.clipboard.writeText(prompt);
        // Real bug found live during overnight QA: window.open()'s null
        // return (the popup was genuinely blocked) was never checked --
        // the user was told "paste it into the Gemini box that just
        // opened" even when no box had opened at all.
        setMessage(
          popup
            ? "Prompt copied — paste it (Ctrl+V) into the Gemini box that just opened."
            : "Prompt copied, but the Gemini popup was blocked by your browser — allow popups for this " +
                "site, or open https://gemini.google.com/app yourself and paste it in."
        );
      } catch {
        // Real bug found live during overnight QA: this told the user to
        // "select and copy the prompt below," but the prompt text was
        // never actually rendered anywhere in this component -- there was
        // no "below" to select.
        setFallbackPrompt(prompt);
        setMessage("Couldn't copy automatically — select and copy the prompt below, then paste it into Gemini.");
      }
    })();
  }, [iocValue, iocType, providerResults, providerSummaries, correlation]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ask AI (Gemini second opinion)</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">
          Builds a full escalation-focused analyst prompt from everything pulled for this IOC, copies it, and
          opens a small Gemini box docked next to this window — paste it in for a second opinion using your own
          Gemini account, alongside the local summary above.
        </p>
        <Button size="sm" onClick={handleAskGemini} disabled={!hasData}>
          Copy prompt &amp; open Gemini box
        </Button>
        {!hasData && (
          <p className="text-xs text-muted-foreground">Waiting for provider data before a prompt can be built.</p>
        )}
        {message && <p className="text-xs text-muted-foreground">{message}</p>}
        {fallbackPrompt && (
          <textarea
            readOnly
            value={fallbackPrompt}
            onFocus={(e) => e.currentTarget.select()}
            className="h-40 w-full rounded-tight border border-border bg-background p-2 font-mono text-xs outline-none focus-visible:border-primary"
          />
        )}
      </CardContent>
    </Card>
  );
}
