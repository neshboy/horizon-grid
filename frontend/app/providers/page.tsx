"use client";

/**
 * Manage Providers: the centralized runtime configuration surface (Phase 36
 * of the runtime-provider master prompt) -- two tabs, AI Providers and IOC
 * Providers, covering every configure/test/enable-disable/activate action
 * this session's backend work added. Every change here takes effect
 * immediately, with no restart (see backend/app/core/runtime_config.py).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import * as Tabs from "@radix-ui/react-tabs";
import { BrandHeader } from "@/components/dashboard/BrandHeader";
import { ProviderConfigRow } from "@/components/dashboard/ProviderConfigRow";
import { NetworkAccessPanel } from "@/components/dashboard/NetworkAccessPanel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  configureAIProvider,
  configureIOCProvider,
  getAuditLog,
  isLoggedIn,
  listAIProviders,
  listIOCProviders,
  recordAITestResult,
  recordIOCTestResult,
  setActiveAIBackend,
  setIOCProviderEnabled,
  testAIBackend,
  testIOCProvider,
} from "@/lib/api";
import type { AuditLogEntry, RuntimeProviderConfig } from "@/lib/types";

const TAB_CLASS = cn(
  "rounded-md px-4 py-2 text-sm font-medium text-muted-foreground transition-colors",
  "hover:text-foreground",
  "data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
);

const AI_CREDENTIAL_FIELDS: Record<string, string[]> = {
  ollama: ["base_url"],
  anthropic: ["api_key"],
  bedrock: ["bedrock_api_key", "aws_access_key_id", "aws_secret_access_key", "aws_region"],
  gemini: ["api_key"],
  groq: ["api_key"],
  openai: ["api_key"],
  kimi: ["api_key"],
  deepseek: ["api_key"],
  xai: ["api_key"],
  mistral: ["api_key"],
  openrouter: ["api_key"],
};

export default function ProvidersPage() {
  const router = useRouter();
  const [aiProviders, setAiProviders] = useState<RuntimeProviderConfig[]>([]);
  const [iocProviders, setIocProviders] = useState<RuntimeProviderConfig[]>([]);
  const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refreshAll = () => {
    listAIProviders().then(setAiProviders).catch(() => {});
    listIOCProviders().then(setIocProviders).catch(() => {});
    getAuditLog(50).then(setAuditLog).catch(() => {});
  };

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/providers");
      return;
    }
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <BrandHeader />

        <div>
          <h1 className="font-display text-sm uppercase tracking-[0.08em] text-muted-foreground">
            Manage Providers
          </h1>
          <p className="text-sm text-muted-foreground">
            Configure AI backends and threat-intelligence providers. Every change here takes
            effect on the next investigation immediately -- no restart, no editing files.
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <Tabs.Root defaultValue="ai">
          <Tabs.List className="mb-4 flex gap-1 border-b border-border pb-2">
            <Tabs.Trigger value="ai" className={TAB_CLASS}>
              AI Providers
            </Tabs.Trigger>
            <Tabs.Trigger value="ioc" className={TAB_CLASS}>
              IOC Providers
            </Tabs.Trigger>
            <Tabs.Trigger value="audit" className={TAB_CLASS}>
              Audit Log
            </Tabs.Trigger>
            <Tabs.Trigger value="network" className={TAB_CLASS}>
              Network Access
            </Tabs.Trigger>
          </Tabs.List>

          <Tabs.Content value="ai" className="flex flex-col gap-3">
            {aiProviders.map((p) => (
              <ProviderConfigRow
                key={p.provider_id}
                provider={p}
                fields={AI_CREDENTIAL_FIELDS[p.provider_id] ?? ["api_key"]}
                showModelField
                onSave={async (credentials, modelId) => {
                  try {
                    const updated = await configureAIProvider(p.provider_id, credentials, modelId);
                    setAiProviders((prev) => prev.map((x) => (x.provider_id === p.provider_id ? updated : x)));
                    refreshAll();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Failed to save");
                  }
                }}
                onTest={async (credentials, model) => {
                  const result = await testAIBackend(p.provider_id, credentials, model);
                  await recordAITestResult(p.provider_id, result.ok, result.message);
                  refreshAll();
                  return result;
                }}
                onSetActive={async () => {
                  try {
                    await setActiveAIBackend(p.provider_id);
                    refreshAll();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Failed to switch active provider");
                  }
                }}
              />
            ))}
          </Tabs.Content>

          <Tabs.Content value="ioc" className="flex flex-col gap-3">
            {iocProviders.map((p) => (
              <ProviderConfigRow
                key={p.provider_id}
                provider={p}
                fields={p.credential_fields ?? []}
                onSave={async (credentials) => {
                  try {
                    const updated = await configureIOCProvider(p.provider_id, credentials);
                    setIocProviders((prev) => prev.map((x) => (x.provider_id === p.provider_id ? updated : x)));
                    refreshAll();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Failed to save");
                  }
                }}
                onTest={async (credentials) => {
                  const result = await testIOCProvider(p.provider_id, credentials);
                  await recordIOCTestResult(p.provider_id, result.ok, result.message);
                  refreshAll();
                  return result;
                }}
                onToggleEnabled={async (enabled) => {
                  try {
                    await setIOCProviderEnabled(p.provider_id, enabled);
                    setIocProviders((prev) =>
                      prev.map((x) => (x.provider_id === p.provider_id ? { ...x, enabled } : x))
                    );
                    refreshAll();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Failed to update provider");
                  }
                }}
              />
            ))}
          </Tabs.Content>

          <Tabs.Content value="audit">
            <Card>
              <CardHeader>
                <CardTitle>Configuration Audit Log</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="mb-3 text-xs text-muted-foreground">
                  Every configuration change, recorded without ever storing a credential value.
                </p>
                <ul className="flex flex-col gap-2 text-sm">
                  {auditLog.length === 0 && <li className="text-muted-foreground">No changes recorded yet.</li>}
                  {auditLog.map((entry) => (
                    <li key={entry.id} className="border-b border-border/50 pb-2 last:border-none">
                      <span className="font-data tabular-nums text-xs text-muted-foreground">
                        {new Date(entry.timestamp).toLocaleString()}
                      </span>
                      {" -- "}
                      <span className="font-medium">{entry.action}</span>: {entry.detail}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </Tabs.Content>

          <Tabs.Content value="network">
            <NetworkAccessPanel />
          </Tabs.Content>
        </Tabs.Root>
      </div>
    </main>
  );
}
