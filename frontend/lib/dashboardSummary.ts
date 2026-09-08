// Loading-state messaging for the Executive Summary card on /dashboard.
//
// GET /dashboard/executive-summary (backend/app/api/routes/dashboard.py)
// tries the configured AI backend before falling back to a deterministic
// template -- see app/ai/dashboard_summary.py and app/core/config.py's
// `ollama_timeout_seconds` (300s by default, and the shipped default model,
// llama3.2:3b on CPU, legitimately needs ~187-300s per call per this
// project's own measurements). That means this one request can take minutes
// to resolve, well after the KPI tiles and Provider Health widget next to it
// have already loaded from their own (fast) endpoints.
//
// Without any feedback, the card just shows a content-free skeleton for the
// full duration, which reads as broken/stuck rather than "still working".
// summaryLoadingHint() gives dashboard/page.tsx an honest, elapsed-time-aware
// message to show underneath the skeleton once the wait has gone on long
// enough that a generic spinner stops being reassuring.
export const SLOW_SUMMARY_HINT_MS = 4_000;

export function summaryLoadingHint(elapsedMs: number): string | undefined {
  if (elapsedMs < SLOW_SUMMARY_HINT_MS) {
    return undefined;
  }
  return "Still generating -- this can take a few minutes on a CPU-only AI backend.";
}
