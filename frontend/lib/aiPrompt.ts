// Formats a lookup's raw provider data into a single prompt for pasting into
// an external AI chat (Gemini, ChatGPT, etc.) -- used alongside the local
// Ollama summaries in the dashboard, for a second opinion using a bigger
// hosted model. See components/dashboard/AskAiPanel.tsx.
import type { CorrelationPayload, ProviderResult, ProviderSummary } from "./types";

export function buildAiAnalysisPrompt(
  iocValue: string,
  iocType: string | null,
  providerResults: ProviderResult[],
  providerSummaries: Record<string, ProviderSummary>,
  correlation: CorrelationPayload | null
): string {
  const lines: string[] = [];

  lines.push(
    "You are a senior SOC (Security Operations Center) threat analyst performing triage on a single IOC. " +
      "You have been handed raw intelligence pulled from multiple independent sources below. Your job is to " +
      "decide, with the judgment of a real analyst under time pressure, whether this needs to be escalated -- " +
      "and if so, to whom and how urgently. Do not hedge with generic disclaimers; commit to a call and justify it " +
      "from the evidence given. If the evidence is thin or contradictory, say so explicitly and state what's missing."
  );
  lines.push("");
  lines.push("Structure your response EXACTLY as follows:");
  lines.push("");
  lines.push("## Verdict");
  lines.push("One line: malicious / suspicious / benign / inconclusive -- and a confidence (low/medium/high).");
  lines.push("");
  lines.push("## Escalate? (Yes/No/Monitor)");
  lines.push(
    "State plainly whether this should be escalated right now. If yes, say to whom (e.g. IR team, " +
      "network team, management) and how urgently (immediate / same-day / routine). If no, say why not, and " +
      "what would change that answer."
  );
  lines.push("");
  lines.push("## Executive Summary");
  lines.push("2-3 sentences a manager could read with no technical background.");
  lines.push("");
  lines.push("## Key Evidence");
  lines.push("Bullet points, each citing the specific provider it came from. Only the evidence that actually drove the verdict -- skip noise.");
  lines.push("");
  lines.push("## What's Missing / Caveats");
  lines.push("Anything that would change the verdict if known -- gaps in coverage, providers with no data, conflicting signals.");
  lines.push("");
  lines.push("## Recommended Actions");
  lines.push(
    "Concrete, ordered next steps for the analyst handling this -- e.g. block/allow, isolate host, hunt for " +
      "related indicators, notify a specific team, or close as benign."
  );
  lines.push("");
  lines.push("---");
  lines.push("");
  lines.push(`IOC: ${iocValue}`);
  lines.push(`Type: ${iocType ?? "unknown"}`);
  lines.push("");
  lines.push("=== Provider Results ===");

  const withData = providerResults.filter((r) => r.status === "ok");
  const withoutData = providerResults.filter((r) => r.status !== "ok");

  if (withData.length === 0) {
    lines.push("(no provider returned data)");
  }
  for (const result of withData) {
    lines.push("");
    lines.push(`--- ${result.provider_name} (${result.category}) ---`);
    const summary = providerSummaries[result.provider_id];
    if (summary) {
      lines.push(`Reputation: ${summary.reputation}`);
      lines.push(`Threat level: ${summary.threat_level} (confidence: ${summary.confidence})`);
      if (summary.interesting_findings.length > 0) {
        lines.push(`Findings: ${summary.interesting_findings.join("; ")}`);
      }
    }
    lines.push("Raw data:");
    lines.push(JSON.stringify(result.data, null, 2));
  }

  if (withoutData.length > 0) {
    lines.push("");
    lines.push("=== Providers with no data / errors ===");
    for (const result of withoutData) {
      lines.push(`- ${result.provider_name}: ${result.status}${result.error_message ? ` (${result.error_message})` : ""}`);
    }
  }

  if (correlation && (correlation.nodes.length > 0 || correlation.edges.length > 0)) {
    lines.push("");
    lines.push("=== Correlation Graph ===");
    lines.push(`Nodes: ${correlation.nodes.map((n) => `${n.ioc_type}:${n.value}`).join(", ")}`);
    lines.push(
      `Edges: ${correlation.edges
        .map((e) => `${e.source} --[${e.relationship}]--> ${e.target} (via ${e.provenance})`)
        .join("; ")}`
    );
  }

  return lines.join("\n");
}
