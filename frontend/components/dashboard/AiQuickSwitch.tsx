"use client";

/**
 * Compact "which AI analyzes my next investigation" selector -- the
 * runtime-provider architecture's core UX moment (Phase 7/34 of the
 * runtime-provider master prompt): an analyst decides "I want Claude for
 * this" right before searching, with no restart and no trip to Settings.
 *
 * Reads/writes the platform-wide active AI backend
 * (GET/POST /api/v1/runtime/ai-active) -- switching here takes effect on
 * the very next investigation, anywhere in the app, immediately.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Settings2 } from "lucide-react";
import { getActiveAIBackend, listAIProviders, setActiveAIBackend } from "@/lib/api";
import type { RuntimeProviderConfig } from "@/lib/types";
import { cn } from "@/lib/utils";

const BACKEND_LABELS: Record<string, string> = {
  ollama: "Ollama (local)",
  anthropic: "Claude (Anthropic)",
  bedrock: "Claude (AWS Bedrock)",
  gemini: "Gemini",
  groq: "Groq",
  openai: "ChatGPT (OpenAI)",
};

export function AiQuickSwitch() {
  const [providers, setProviders] = useState<RuntimeProviderConfig[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    Promise.all([listAIProviders(), getActiveAIBackend()])
      .then(([list, activeInfo]) => {
        setProviders(list);
        setActive(activeInfo.backend);
      })
      .catch(() => {
        // Not logged in yet, or backend unreachable -- fail quiet, this is
        // a convenience control, not load-bearing for the page to render.
      });
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleChange = async (backend: string) => {
    setSwitching(true);
    setError(null);
    try {
      await setActiveAIBackend(backend);
      setActive(backend);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to switch AI provider");
    } finally {
      setSwitching(false);
    }
  };

  if (providers.length === 0) return null;

  const activeConfig = providers.find((p) => p.provider_id === active);

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-muted-foreground">AI:</span>
      <select
        value={active ?? ""}
        disabled={switching}
        onChange={(e) => handleChange(e.target.value)}
        className={cn(
          "rounded-md border border-border bg-card px-2 py-1 text-xs font-medium outline-none",
          "focus-visible:ring-1 focus-visible:ring-primary disabled:opacity-50"
        )}
      >
        {providers.map((p) => (
          <option key={p.provider_id} value={p.provider_id}>
            {BACKEND_LABELS[p.provider_id] ?? p.provider_id}
            {!p.configured && p.provider_id !== "ollama" ? " (not configured)" : ""}
          </option>
        ))}
      </select>
      {activeConfig && (
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            activeConfig.configured ? "bg-success" : "bg-muted-foreground/40"
          )}
          title={activeConfig.configured ? "Configured" : "Not configured"}
        />
      )}
      <Link
        href="/providers"
        className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        title="Manage AI and IOC providers"
      >
        <Settings2 className="h-3 w-3" aria-hidden="true" />
        Manage
      </Link>
      {error && <span className="text-destructive">{error}</span>}
    </div>
  );
}
