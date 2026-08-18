"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { getApiUrl } from "@/lib/api";
import type { FinalAssessment } from "@/lib/types";

interface ExportMenuProps {
  lookupId: string;
  assessment: FinalAssessment | null;
}

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function buildMarkdown(assessment: FinalAssessment): string {
  const lines: string[] = [];
  lines.push(`# IOC Assessment: ${assessment.ioc_value}`);
  lines.push("");
  lines.push(`**Type:** ${assessment.ioc_type}`);
  lines.push(`**Final Verdict:** ${assessment.final_verdict}`);
  lines.push(
    `**Risk Score:** ${assessment.risk.overall_risk_score} (confidence ${assessment.risk.confidence_score})`
  );
  lines.push("");
  lines.push("## Executive Summary");
  lines.push(assessment.executive_summary);
  lines.push("");
  lines.push("## Technical Summary");
  lines.push(assessment.technical_summary);
  lines.push("");
  lines.push("## Threat Assessment");
  lines.push(assessment.threat_assessment);
  lines.push("");
  lines.push("## Verdict Rationale");
  lines.push(assessment.verdict_rationale);
  lines.push("");

  if (assessment.supporting_evidence.length > 0) {
    lines.push("## Supporting Evidence");
    assessment.supporting_evidence.forEach((item) => lines.push(`- ${item}`));
    lines.push("");
  }

  if (assessment.mitre_mappings.length > 0) {
    lines.push("## MITRE ATT&CK Mappings");
    assessment.mitre_mappings.forEach((m) =>
      lines.push(`- **${m.technique_id}** ${m.technique_name} (${m.tactic}): ${m.rationale}`)
    );
    lines.push("");
  }

  if (assessment.recommended_actions.length > 0) {
    lines.push("## Recommended Actions");
    assessment.recommended_actions.forEach((item) => lines.push(`- ${item}`));
    lines.push("");
  }

  if (assessment.investigation_priorities.length > 0) {
    lines.push("## Investigation Priorities");
    assessment.investigation_priorities.forEach((item) => lines.push(`- ${item}`));
    lines.push("");
  }

  if (assessment.incident_response_recommendations.length > 0) {
    lines.push("## Incident Response Recommendations");
    assessment.incident_response_recommendations.forEach((item) => lines.push(`- ${item}`));
    lines.push("");
  }

  if (assessment.detection_rules.length > 0) {
    lines.push("## Detection Rules");
    assessment.detection_rules.forEach((rule) => {
      lines.push(`### ${rule.title} (${rule.format})`);
      lines.push("```");
      lines.push(rule.rule);
      lines.push("```");
      lines.push("");
    });
  }

  return lines.join("\n");
}

export function ExportMenu({ lookupId, assessment }: ExportMenuProps) {
  const [message, setMessage] = React.useState<string | null>(null);
  const messageTimeout = React.useRef<ReturnType<typeof setTimeout>>();

  const showMessage = React.useCallback((text: string) => {
    setMessage(text);
    if (messageTimeout.current) clearTimeout(messageTimeout.current);
    messageTimeout.current = setTimeout(() => setMessage(null), 4000);
  }, []);

  React.useEffect(() => {
    return () => {
      if (messageTimeout.current) clearTimeout(messageTimeout.current);
    };
  }, []);

  const handleExportJson = React.useCallback(() => {
    if (!assessment) {
      showMessage("No assessment data available yet.");
      return;
    }
    const blob = new Blob([JSON.stringify(assessment, null, 2)], { type: "application/json" });
    triggerDownload(blob, `ioc-assessment-${lookupId}.json`);
  }, [assessment, lookupId, showMessage]);

  const handleExportMarkdown = React.useCallback(() => {
    if (!assessment) {
      showMessage("No assessment data available yet.");
      return;
    }
    const blob = new Blob([buildMarkdown(assessment)], { type: "text/markdown" });
    triggerDownload(blob, `ioc-assessment-${lookupId}.md`);
  }, [assessment, lookupId, showMessage]);

  const handleServerExport = React.useCallback(
    async (format: "pdf" | "csv") => {
      try {
        const res = await fetch(`${getApiUrl()}/api/v1/lookup/${lookupId}/export?format=${format}`, {
          method: "POST",
          headers: authHeaders(),
        });
        if (res.status === 404) {
          showMessage("Export format not yet available.");
          return;
        }
        if (!res.ok) {
          showMessage(`Export failed with status ${res.status}.`);
          return;
        }
        const blob = await res.blob();
        triggerDownload(blob, `ioc-assessment-${lookupId}.${format}`);
      } catch {
        showMessage("Export format not yet available.");
      }
    },
    [lookupId, showMessage]
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => handleServerExport("pdf")}>
          Export PDF
        </Button>
        <Button size="sm" variant="outline" onClick={handleExportMarkdown}>
          Export Markdown
        </Button>
        <Button size="sm" variant="outline" onClick={() => handleServerExport("csv")}>
          Export CSV
        </Button>
        <Button size="sm" variant="outline" onClick={handleExportJson}>
          Export JSON
        </Button>
      </div>
      {message && <p className="text-xs text-muted-foreground">{message}</p>}
    </div>
  );
}
