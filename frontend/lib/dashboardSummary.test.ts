import { describe, expect, it } from "vitest";

import { SLOW_SUMMARY_HINT_MS, summaryLoadingHint } from "./dashboardSummary";

// Regression test for the dashboard's Executive Summary card showing a
// content-free skeleton indefinitely while GET /dashboard/executive-summary
// waits out the AI backend (default ollama_timeout_seconds=300s) before
// falling back to a template -- see app/dashboard/page.tsx and
// backend/app/ai/dashboard_summary.py. summaryLoadingHint() is what drives
// the "still generating" message that now appears under the skeleton once
// the request has been in flight for a while, instead of leaving the user
// with no feedback for up to ~300s.
describe("summaryLoadingHint()", () => {
  it("shows no hint immediately after the request starts (fast path stays silent)", () => {
    expect(summaryLoadingHint(0)).toBeUndefined();
    expect(summaryLoadingHint(SLOW_SUMMARY_HINT_MS - 1)).toBeUndefined();
  });

  it("surfaces an honest 'still generating' hint once the wait crosses the threshold", () => {
    const hint = summaryLoadingHint(SLOW_SUMMARY_HINT_MS);
    expect(hint).toBeDefined();
    expect(hint).toMatch(/still generating/i);
    expect(hint).toMatch(/minutes/i);
  });

  it("keeps showing the hint the longer a slow CPU-only Ollama call runs (up to the ~300s backend timeout)", () => {
    expect(summaryLoadingHint(60_000)).toBe(summaryLoadingHint(SLOW_SUMMARY_HINT_MS));
    expect(summaryLoadingHint(300_000)).toBe(summaryLoadingHint(SLOW_SUMMARY_HINT_MS));
  });
});
