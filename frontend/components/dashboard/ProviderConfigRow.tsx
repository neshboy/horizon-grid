"use client";

/**
 * One provider's row in the Manage Providers panel (Phase 36 of the
 * runtime-provider master prompt) -- works for both AI providers and IOC
 * providers, since both are the same underlying shape
 * (RuntimeProviderConfig). Expands into an edit form with exactly the
 * credential fields that provider needs (Phase 18: "the exact fields must
 * depend on the selected provider" -- driven by credential_fields for IOC
 * providers, or a fixed api_key+model shape for AI backends).
 */

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { RuntimeProviderConfig } from "@/lib/types";

export interface ProviderConfigRowProps {
  provider: RuntimeProviderConfig;
  /** AI backends have a fixed credential shape per backend; IOC providers
   * declare their own via credential_fields. */
  fields: string[];
  onSave: (credentials: Record<string, string>, modelId?: string) => Promise<void>;
  onTest: (credentials: Record<string, string>, model?: string) => Promise<{ ok: boolean; message: string }>;
  onToggleEnabled?: (enabled: boolean) => Promise<void>;
  onSetActive?: () => Promise<void>;
  showModelField?: boolean;
  /** Fetches this backend's model list (see lib/api.ts `listAIModels`, which
   * calls POST /api/v1/ai/{backend}/models) using whatever credentials are
   * currently typed into this row's form. Real/live discovery for backends
   * that support it (Groq, OpenAI, Kimi, DeepSeek, xAI, Mistral,
   * OpenRouter, Ollama's actually-pulled models); a curated static list
   * otherwise (Anthropic/Gemini/Bedrock). Omit to keep the Model field a
   * plain free-text input -- e.g. IOC providers, which have no model
   * concept at all. */
  onFetchModels?: (credentials: Record<string, string>) => Promise<{ models: string[]; default: string | null }>;
  /** Fields that are real config (e.g. Ollama's base_url), not secrets --
   * the backend returns these in masked_credentials unmasked, so pre-fill
   * the edit form from them (matching how modelId already pre-fills below)
   * instead of leaving them blank like a true credential. */
  plaintextFields?: string[];
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        ok ? "border-success/30 bg-success/10 text-success" : "border-border bg-muted/40 text-muted-foreground"
      )}
    >
      {label}
    </span>
  );
}

export function ProviderConfigRow({
  provider,
  fields,
  onSave,
  onTest,
  onToggleEnabled,
  onSetActive,
  showModelField,
  onFetchModels,
  plaintextFields,
}: ProviderConfigRowProps) {
  const plaintextInitialValues = () => {
    const initial: Record<string, string> = {};
    for (const field of plaintextFields ?? []) {
      const current = provider.masked_credentials?.[field];
      if (current) initial[field] = current;
    }
    return initial;
  };

  const [expanded, setExpanded] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(plaintextInitialValues);
  const [modelId, setModelId] = useState(provider.model_id ?? "");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);

  const fetchModels = async () => {
    if (!onFetchModels) return;
    setModelsLoading(true);
    try {
      const result = await onFetchModels(values);
      setModelOptions(result.models);
    } catch {
      // Best-effort: leave whatever options (if any) were already loaded --
      // the Model field still falls back to a free-text input below when
      // modelOptions ends up empty, so discovery failing never blocks
      // configuring a model id by hand.
    } finally {
      setModelsLoading(false);
    }
  };

  // Load this backend's model list once per expand, seeded with whatever
  // credentials are already typed/pre-filled (e.g. Ollama's base_url) --
  // the "Refresh models" button below re-runs this with freshly typed
  // credentials (a new API key, say) without requiring Save first.
  useEffect(() => {
    if (expanded && showModelField && onFetchModels) {
      fetchModels();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(values, showModelField ? modelId : undefined);
      // Deliberately NOT resetting `values` here. It used to reset to
      // plaintextInitialValues() (i.e. wipe every true-secret field back to
      // empty) on the theory that only plaintext fields need to survive a
      // save. Real bug found live: /ai/test and /ai/{backend}/models always
      // test the *candidate* value passed in the request, never the
      // already-saved one server-side -- so wiping the just-saved secret
      // meant clicking Test Connection immediately after Save (a completely
      // normal "did that work?" click) sent blank credentials and failed
      // every single time, no matter how many times the same correct key
      // was re-typed and re-saved.
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      // Test whatever's currently typed, falling back to the already-saved
      // (masked) credential's field names so re-testing a saved key doesn't
      // require re-typing it -- the backend's own test endpoint takes the
      // candidate value directly, never the stored one, so we can only
      // usefully re-test values just typed in this form.
      const result = await onTest(values, showModelField ? modelId : undefined);
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, message: err instanceof Error ? err.message : "Test failed" });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          )}
          <span className="font-medium">{provider.provider_name || provider.provider_id}</span>
          {provider.is_active && <StatusBadge ok label="Active" />}
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge ok={provider.configured} label={provider.configured ? "Configured" : "Not configured"} />
          {onToggleEnabled && (
            <StatusBadge ok={provider.enabled} label={provider.enabled ? "Enabled" : "Disabled"} />
          )}
        </div>
      </button>

      {expanded && (
        <div className="flex flex-col gap-3 border-t border-border px-4 py-3">
          {fields.length === 0 ? (
            <p className="text-xs text-muted-foreground">This provider needs no API key.</p>
          ) : (
            fields.map((field) => {
              return (
                <label key={field} className="flex flex-col gap-1 text-xs">
                  <span className="capitalize text-muted-foreground">{field.replace(/_/g, " ")}</span>
                  <input
                    type="text"
                    value={values[field] ?? ""}
                    onChange={(e) => setValues((prev) => ({ ...prev, [field]: e.target.value }))}
                    placeholder={
                      provider.masked_credentials?.[field] ? provider.masked_credentials[field] : "Not set"
                    }
                    className="rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-1 focus-visible:ring-primary"
                  />
                </label>
              );
            })
          )}

          {showModelField && (
            <label className="flex flex-col gap-1 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Model</span>
                {onFetchModels && (
                  <button
                    type="button"
                    onClick={fetchModels}
                    disabled={modelsLoading}
                    className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
                  >
                    {modelsLoading ? "Loading models..." : "Refresh models"}
                  </button>
                )}
              </div>
              {modelOptions.length > 0 ? (
                <select
                  value={modelId}
                  onChange={(e) => setModelId(e.target.value)}
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-1 focus-visible:ring-primary"
                >
                  {/* Keeps an already-configured model id selectable even if
                   * it isn't in the fetched list (e.g. a custom/newer model
                   * id typed by hand before this dropdown existed) --
                   * without this, the <select> would silently fall back to
                   * showing its first option while `modelId` state still
                   * held the real value, misleading the operator into
                   * re-saving a different model than the one configured. */}
                  {modelId && !modelOptions.includes(modelId) && (
                    <option key={modelId} value={modelId}>
                      {modelId}
                    </option>
                  )}
                  {modelOptions.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  value={modelId}
                  onChange={(e) => setModelId(e.target.value)}
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-1 focus-visible:ring-primary"
                />
              )}
            </label>
          )}

          {provider.last_test_message && (
            <p className="text-xs text-muted-foreground">
              Last test: {provider.last_test_ok ? "OK" : "Failed"} -- {provider.last_test_message}
            </p>
          )}
          {testResult && (
            <p className={cn("text-xs font-medium", testResult.ok ? "text-success" : "text-destructive")}>
              {testResult.ok ? "OK: " : "Failed: "}
              {testResult.message}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={handleTest} disabled={testing}>
              {testing ? "Testing..." : "Test Connection"}
            </Button>
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
            {onSetActive && !provider.is_active && (
              <Button size="sm" variant="outline" onClick={onSetActive}>
                Set Active
              </Button>
            )}
            {onToggleEnabled && (
              <Button size="sm" variant="outline" onClick={() => onToggleEnabled(!provider.enabled)}>
                {provider.enabled ? "Disable" : "Enable"}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
