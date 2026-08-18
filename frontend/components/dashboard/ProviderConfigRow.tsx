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

import { useState } from "react";
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
  modelOptions?: string[];
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
  modelOptions,
}: ProviderConfigRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [modelId, setModelId] = useState(provider.model_id ?? "");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(values, showModelField ? modelId : undefined);
      setValues({});
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
            fields.map((field) => (
              <label key={field} className="flex flex-col gap-1 text-xs">
                <span className="capitalize text-muted-foreground">{field.replace(/_/g, " ")}</span>
                <input
                  type="password"
                  value={values[field] ?? ""}
                  onChange={(e) => setValues((prev) => ({ ...prev, [field]: e.target.value }))}
                  placeholder={
                    provider.masked_credentials?.[field] ? provider.masked_credentials[field] : "Not set"
                  }
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-1 focus-visible:ring-primary"
                />
              </label>
            ))
          )}

          {showModelField && (
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-muted-foreground">Model</span>
              {modelOptions && modelOptions.length > 0 ? (
                <select
                  value={modelId}
                  onChange={(e) => setModelId(e.target.value)}
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-1 focus-visible:ring-primary"
                >
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
