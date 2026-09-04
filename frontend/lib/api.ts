import type {
  AssessmentRecord,
  AuditLogEntry,
  BasketItem,
  CaseDetail,
  CaseSummary,
  ChallengeVerdict,
  CopilotAnswer,
  CorrelationPayload,
  CurrentUser,
  DashboardKpis,
  DetectionRuleDraft,
  DisagreementSummary,
  EvidenceItem,
  ExecutiveSummary,
  FalsePositiveAssessment,
  FinalAssessment,
  HuntingPackage,
  IntelligenceGaps,
  IOCComparisonResponse,
  NetworkInfo,
  PentestAssessment,
  PentestExploitAttempt,
  PentestExploitModuleCandidate,
  PentestExploitModuleOptions,
  PentestFinding,
  PentestFindingExplanation,
  PentestAssessmentSummaryReport,
  PentestValidationChecks,
  PivotSuggestion,
  ProviderResult,
  ProviderSummary,
  Role,
  RolePermissions,
  RuntimeProviderConfig,
  ScoreExplanation,
  SecurityAssessmentRun,
  SmartNextActions,
  ToolHealth,
  ToolProfile,
  User,
  UserListResponse,
  UserStats,
  WhatIsThisIOC,
  WhyMaliciousExplanation,
} from "./types";

/**
 * Resolves the backend base URL per-call from whatever host the browser
 * actually used to load this page, so the same built frontend works
 * whether opened via localhost, a LAN IP, or a hostname -- self-healing
 * across DHCP changes and restarts with no rebuild. NEXT_PUBLIC_API_URL,
 * if explicitly set, always wins (preserves the old fixed-URL behavior for
 * a reverse-proxy or other non-default setup). NEXT_PUBLIC_BACKEND_PORT is
 * a build-time var (defaults to 8000) used only when neither override
 * applies.
 *
 * Guarded for typeof window === "undefined" because this module is also
 * evaluated during Next.js's server-side render pass (same reason
 * getAccessToken() below already guards on window) -- no fetch() in this
 * file is ever actually invoked during that pass (every page fetches its
 * data in a useEffect after mount), so the fallback value here is never
 * used for a real request.
 */
export function getApiUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window === "undefined") return "http://localhost:8000";
  const port = process.env.NEXT_PUBLIC_BACKEND_PORT ?? "8000";
  return `${window.location.protocol}//${window.location.hostname}:${port}`;
}

function getAccessToken(): string | null {
  return typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
}

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function login(email: string, password: string) {
  const res = await fetch(`${getApiUrl()}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error("Login failed");
  const data = await res.json();
  localStorage.setItem("access_token", data.access_token);
  localStorage.setItem("refresh_token", data.refresh_token);
  return data;
}

export async function register(email: string, password: string, fullName: string) {
  const res = await fetch(`${getApiUrl()}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, full_name: fullName }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Registration failed");
  }
  return res.json();
}

/**
 * Exchanges the stored refresh token for a new access/refresh pair. Returns
 * false (and clears both tokens) if the refresh token is itself missing or
 * rejected, so callers can redirect to /login rather than retry forever.
 */
export async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = typeof window !== "undefined" ? localStorage.getItem("refresh_token") : null;
  if (!refreshToken) return false;

  const res = await fetch(`${getApiUrl()}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    logout();
    return false;
  }
  const data = await res.json();
  localStorage.setItem("access_token", data.access_token);
  localStorage.setItem("refresh_token", data.refresh_token);
  return true;
}

export function isLoggedIn(): boolean {
  return typeof window !== "undefined" && !!localStorage.getItem("access_token");
}

/**
 * Real bug found live during overnight QA: this used to only clear
 * localStorage, with zero network call -- so a still-unexpired access
 * token (up to ~30 min) and its refresh token (up to 7 days) both kept
 * working indefinitely after "logging out" (e.g. if that token had
 * already leaked via XSS, a shared machine, or a synced browser profile).
 * The backend's new POST /auth/logout bumps token_version, immediately
 * invalidating every outstanding token for this user -- the same
 * mechanism already used for an admin-initiated password reset. Kept
 * synchronous-callable (existing callers don't need to change to `await
 * logout()`): the revocation call is fired but not awaited before
 * clearing local state, since the local sign-out should feel instant
 * either way and a failed revocation call (e.g. already offline) shouldn't
 * block the user from leaving the page.
 */
export function logout(): void {
  const token = getAccessToken();
  if (token) {
    fetch(`${getApiUrl()}/api/v1/auth/logout`, {
      method: "POST",
      headers: authHeaders(),
    }).catch(() => {
      // Best-effort -- the user is signing out regardless of whether the
      // revocation call itself succeeds (e.g. already offline).
    });
  }
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

/**
 * fetch() wrapper for authenticated JSON endpoints: on a 401 (expired/invalid
 * access token), transparently refreshes once and retries with the new token
 * before giving up -- this is the piece that was missing, which is why an
 * access token older than ACCESS_TOKEN_EXPIRE_MINUTES (30 min) produced a raw
 * 401 instead of silently refreshing.
 */
async function authedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const doFetch = () => fetch(url, { ...init, headers: { ...init.headers, ...authHeaders() } });

  let res = await doFetch();
  if (res.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await doFetch();
    }
  }
  return res;
}

export interface LookupStreamHandlers {
  onDetected?: (payload: { lookup_id: string; ioc_value: string; ioc_type: string }) => void;
  onProviderResult?: (payload: ProviderResult) => void;
  onProviderSummary?: (payload: ProviderSummary) => void;
  onCorrelation?: (payload: CorrelationPayload) => void;
  onFinalAssessment?: (payload: FinalAssessment) => void;
  onDone?: (payload: { lookup_id: string }) => void;
  onError?: (payload: { message: string }) => void;
  /** Called when the access token was expired/invalid AND the refresh attempt
   * also failed -- callers should redirect to /login, since retrying will
   * just 401 again. */
  onAuthExpired?: () => void;
}

/**
 * Consumes the backend's SSE stream (see backend/app/api/routes/lookup.py
 * `stream_lookup`) using fetch + a manual reader rather than EventSource,
 * because EventSource can't send an Authorization header and this endpoint
 * requires a bearer token.
 */
export interface StreamLookupOptions {
  /** Restrict this investigation to just these provider_ids (Phase 22:
   * "control which providers participate"). Omit for the default -- every
   * enabled provider that supports the detected IOC type. */
  providerIds?: string[];
  /** Run THIS investigation with a specific AI backend instead of whichever
   * one is currently active platform-wide. Omit to use the active one. */
  aiBackend?: string;
  /** Real gap found live during overnight QA: the backend's own
   * POST /lookup/stream (see backend/app/schemas/lookup.py's
   * ioc_type_hint field) has always accepted an explicit type hint for
   * values app/ioc/detector.py's auto-detection can't classify on its own
   * (a malware family name, a threat actor, a mutex, a bare process/service
   * name -- anything with no dots/hex pattern/URL scheme to key off of) --
   * but nothing on the frontend ever sent it, so any such value permanently
   * 422'd ("Could not determine IOC type; pass ioc_type_hint") with no way
   * to recover short of calling the API directly. Omit for the default
   * (auto-detect).*/
  iocTypeHint?: string;
}

export async function streamLookup(
  value: string,
  handlers: LookupStreamHandlers,
  signal?: AbortSignal,
  options?: StreamLookupOptions
): Promise<void> {
  const post = () =>
    fetch(`${getApiUrl()}/api/v1/lookup/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        value,
        provider_ids: options?.providerIds,
        ai_backend: options?.aiBackend,
        ioc_type_hint: options?.iocTypeHint,
      }),
      signal,
    });

  let res = await post();
  if (res.status === 401) {
    const refreshed = await refreshAccessToken();
    if (!refreshed) {
      handlers.onAuthExpired?.();
      handlers.onError?.({ message: "Your session expired. Please sign in again." });
      return;
    }
    res = await post();
  }

  if (!res.ok || !res.body) {
    // Real bug found live during overnight QA: this always discarded the
    // backend's own `detail` message (e.g. "Could not determine IOC type;
    // pass ioc_type_hint.") for EVERY non-ok status -- 422 validation
    // errors, 429 rate limits, 5xx errors, all of it -- showing only a
    // bare status code with no actionable information. `res.body` is
    // still readable here even when `!res.ok` (fetch only rejects on
    // network failure, never on a non-2xx status), so the real detail is
    // available, just never read.
    let detail: string | undefined;
    try {
      const body = await res.clone().json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body (e.g. a plain-text 500) -- fall through to the generic message below.
    }
    handlers.onError?.({ message: detail ?? `Request failed with status ${res.status}` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value: chunk } = await reader.read();
    if (done) break;
    buffer += decoder.decode(chunk, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const raw of events) {
      const lines = raw.split("\n");
      const eventLine = lines.find((l) => l.startsWith("event: "));
      const dataLine = lines.find((l) => l.startsWith("data: "));
      if (!eventLine || !dataLine) continue;

      const eventName = eventLine.replace("event: ", "").trim();
      const data = JSON.parse(dataLine.replace("data: ", ""));

      switch (eventName) {
        case "detected":
          handlers.onDetected?.(data);
          break;
        case "provider_result":
          handlers.onProviderResult?.(data);
          break;
        case "provider_summary":
          handlers.onProviderSummary?.(data);
          break;
        case "correlation":
          handlers.onCorrelation?.(data);
          break;
        case "final_assessment":
          handlers.onFinalAssessment?.(data);
          break;
        case "done":
          handlers.onDone?.(data);
          break;
        case "error":
          handlers.onError?.(data);
          break;
      }
    }
  }
}

export async function getLookup(id: string) {
  const res = await authedFetch(`${getApiUrl()}/api/v1/lookup/${id}`);
  if (!res.ok) throw new Error("Failed to fetch lookup");
  return res.json();
}

export async function listLookups() {
  const res = await authedFetch(`${getApiUrl()}/api/v1/lookup`);
  if (!res.ok) throw new Error("Failed to fetch lookups");
  return res.json();
}

export async function getProviderHealth() {
  const res = await authedFetch(`${getApiUrl()}/api/v1/providers/health`);
  if (!res.ok) throw new Error("Failed to fetch provider health");
  return res.json();
}

// --- Executive Dashboard ---
// See backend GET /dashboard/kpis and GET /dashboard/executive-summary. The
// latter is a new endpoint still being built in parallel -- it may 404 until
// it's propagated+rebuilt; callers should handle that gracefully.

export async function getKpis(): Promise<DashboardKpis> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/dashboard/kpis`);
  if (!res.ok) throw new Error("Failed to fetch dashboard KPIs");
  return res.json();
}

export async function getExecutiveSummary(): Promise<ExecutiveSummary> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/dashboard/executive-summary`);
  if (!res.ok) throw new Error("Failed to fetch executive summary");
  return res.json();
}

// --- Evidence / analysis ---

async function postAnalysis<T>(lookupId: string, path: string, body?: unknown): Promise<T> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/lookup/${lookupId}/analysis/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(`Failed to generate ${path} (status ${res.status})`);
  return res.json();
}

export async function getEvidence(lookupId: string): Promise<EvidenceItem[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/lookup/${lookupId}/analysis/evidence`);
  if (!res.ok) throw new Error("Failed to fetch evidence");
  return res.json();
}

export const explainWhyMalicious = (lookupId: string) =>
  postAnalysis<WhyMaliciousExplanation>(lookupId, "why");

export const explainWhatIsThis = (lookupId: string) => postAnalysis<WhatIsThisIOC>(lookupId, "what-is-this");

export const explainDisagreement = (lookupId: string) =>
  postAnalysis<DisagreementSummary>(lookupId, "disagreement");

export const checkFalsePositive = (lookupId: string) =>
  postAnalysis<FalsePositiveAssessment>(lookupId, "false-positive");

export const challengeVerdict = (lookupId: string) => postAnalysis<ChallengeVerdict>(lookupId, "challenge");

export const getNextActions = (lookupId: string) => postAnalysis<SmartNextActions>(lookupId, "next-actions");

export const getIntelligenceGaps = (lookupId: string) => postAnalysis<IntelligenceGaps>(lookupId, "gaps");

export const explainScore = (lookupId: string) => postAnalysis<ScoreExplanation>(lookupId, "score-explanation");

export const askCopilot = (lookupId: string, question: string, notes: string[] = []) =>
  postAnalysis<CopilotAnswer>(lookupId, "copilot", { question, notes });

// --- Hunting / detection ---

export async function huntThisIOC(lookupId: string, formats?: string[]): Promise<HuntingPackage> {
  const query = formats?.length ? `?${formats.map((f) => `formats=${encodeURIComponent(f)}`).join("&")}` : "";
  const res = await authedFetch(`${getApiUrl()}/api/v1/lookup/${lookupId}/hunt${query}`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to generate hunting package");
  return res.json();
}

export async function createDetectionRule(lookupId: string, format: string): Promise<DetectionRuleDraft> {
  const res = await authedFetch(
    `${getApiUrl()}/api/v1/lookup/${lookupId}/detection?format=${encodeURIComponent(format)}`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to generate detection rule");
  return res.json();
}

// --- Pivot ---

export async function getPivots(lookupId: string, limit = 10): Promise<PivotSuggestion[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/lookup/${lookupId}/pivots?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch pivots");
  return res.json();
}

// --- IOC Basket ---

export async function listBasket(): Promise<BasketItem[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/basket`);
  if (!res.ok) throw new Error("Failed to fetch basket");
  return res.json();
}

export async function addToBasket(iocValue: string, note?: string): Promise<BasketItem> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/basket`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ioc_value: iocValue, note }),
  });
  if (!res.ok) throw new Error("Failed to add to basket");
  return res.json();
}

export async function removeFromBasket(itemId: string): Promise<void> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/basket/${itemId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to remove from basket");
}

export async function clearBasket(): Promise<void> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/basket`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to clear basket");
}

export async function compareBasketIOCs(lookupIds: string[]): Promise<IOCComparisonResponse> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/basket/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lookup_ids: lookupIds }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to compare IOCs");
  }
  return res.json();
}

// --- Case management ---

export async function listCases(): Promise<CaseSummary[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/cases`);
  if (!res.ok) throw new Error("Failed to fetch cases");
  return res.json();
}

export async function getCase(caseId: string): Promise<CaseDetail> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/cases/${caseId}`);
  if (!res.ok) throw new Error("Failed to fetch case");
  return res.json();
}

export async function createCase(title: string, description?: string, severity = "medium"): Promise<CaseDetail> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, description, severity }),
  });
  if (!res.ok) throw new Error("Failed to create case");
  return res.json();
}

export async function updateCase(caseId: string, updates: Record<string, unknown>): Promise<CaseDetail> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/cases/${caseId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error("Failed to update case");
  return res.json();
}

export async function addCaseIOC(caseId: string, iocValue: string, iocType: string, lookupId?: string): Promise<CaseDetail> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/cases/${caseId}/iocs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ioc_value: iocValue, ioc_type: iocType, lookup_id: lookupId }),
  });
  if (!res.ok) throw new Error("Failed to add IOC to case");
  return res.json();
}

export async function addCaseNote(caseId: string, body: string, anchorType?: string, anchorRef?: string): Promise<CaseDetail> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/cases/${caseId}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, anchor_type: anchorType, anchor_ref: anchorRef }),
  });
  if (!res.ok) throw new Error("Failed to add case note");
  return res.json();
}

// --- Runtime provider/AI configuration (no restart required) ---
// See backend/app/api/routes/runtime.py and backend/app/core/runtime_config.py.

export async function listAIProviders(): Promise<RuntimeProviderConfig[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/runtime/ai-providers`);
  if (!res.ok) throw new Error("Failed to list AI providers");
  return res.json();
}

export async function configureAIProvider(
  backend: string,
  credentials: Record<string, string>,
  modelId?: string | null
): Promise<RuntimeProviderConfig> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/runtime/ai-providers/${backend}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credentials, model_id: modelId ?? null }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to configure AI provider");
  }
  return res.json();
}

export async function setActiveAIBackend(backend: string): Promise<{ active_backend: string }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/runtime/ai-active`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ backend }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to switch active AI provider");
  }
  return res.json();
}

export async function getActiveAIBackend(): Promise<{ backend: string | null; model_id: string | null }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/runtime/ai-active`);
  if (!res.ok) throw new Error("Failed to fetch active AI provider");
  return res.json();
}

export async function recordAITestResult(backend: string, ok: boolean, message: string): Promise<void> {
  await authedFetch(`${getApiUrl()}/api/v1/runtime/ai-providers/${backend}/record-test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ok, message }),
  });
}

export async function testAIBackend(
  backend: string,
  credentials: Record<string, string>,
  model?: string
): Promise<{ backend: string; ok: boolean; message: string; model: string | null; latency_ms: number | null }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/ai/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ backend, credentials, model }),
  });
  if (!res.ok) throw new Error("AI connection test request failed");
  return res.json();
}

export async function listIOCProviders(): Promise<RuntimeProviderConfig[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/runtime/ioc-providers`);
  if (!res.ok) throw new Error("Failed to list IOC providers");
  return res.json();
}

export async function configureIOCProvider(
  providerId: string,
  credentials: Record<string, string>,
  extraConfig?: Record<string, unknown> | null
): Promise<RuntimeProviderConfig> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/runtime/ioc-providers/${providerId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credentials, extra_config: extraConfig ?? null }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to configure provider");
  }
  return res.json();
}

export async function setIOCProviderEnabled(providerId: string, enabled: boolean): Promise<void> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/runtime/ioc-providers/${providerId}/enabled`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) throw new Error("Failed to update provider enabled state");
}

export async function recordIOCTestResult(providerId: string, ok: boolean, message: string): Promise<void> {
  await authedFetch(`${getApiUrl()}/api/v1/runtime/ioc-providers/${providerId}/record-test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ok, message }),
  });
}

export async function testIOCProvider(
  providerId: string,
  credentials: Record<string, string>
): Promise<{ provider_id: string; ok: boolean; message: string; latency_ms: number | null }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/providers/${providerId}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credentials }),
  });
  if (!res.ok) throw new Error("Provider connection test request failed");
  return res.json();
}

export async function getAuditLog(limit = 200): Promise<AuditLogEntry[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/runtime/audit-log?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch audit log");
  return res.json();
}

export async function reanalyzeLookup(lookupId: string, aiBackend: string): Promise<AssessmentRecord> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/lookup/${lookupId}/reanalyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ai_backend: aiBackend }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Re-analysis failed");
  }
  return res.json();
}

export async function listAssessments(lookupId: string): Promise<AssessmentRecord[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/lookup/${lookupId}/assessments`);
  if (!res.ok) throw new Error("Failed to fetch assessments");
  return res.json();
}

// Unauthenticated -- same trust model as the backend's /health.
export async function getNetworkInfo(): Promise<NetworkInfo> {
  const res = await fetch(`${getApiUrl()}/network-info`);
  if (!res.ok) throw new Error("Failed to fetch network info");
  return res.json();
}

export interface SystemHealth {
  status: "healthy" | "degraded" | "down" | string;
  version?: string;
  dependencies?: Record<string, { ok: boolean; detail?: string }>;
}

// Unauthenticated, dependency-aware -- used for the header's SYSTEM STATUS
// indicator. Deliberately calls /health/detailed (not the plain /health
// liveness check) so it reflects whether Postgres/Redis are genuinely
// reachable, not just that the backend process itself is up.
export async function getSystemHealth(): Promise<SystemHealth> {
  const res = await fetch(`${getApiUrl()}/health/detailed`);
  // A non-2xx here (e.g. 503 when Postgres is unreachable) is itself a real,
  // informative status -- the backend's own body still carries status:"down".
  return res.json();
}

export async function getCurrentUser(): Promise<CurrentUser> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/auth/me`);
  if (!res.ok) throw new Error("Failed to fetch current user");
  return res.json();
}

// --- Admin / user management (no restart required) ---
// See backend/app/api/routes/admin.py and backend/app/core/users.py. Every
// route there is server-side gated by require_permission("user:manage") --
// these functions and any role check built on top of them in the frontend
// are UX only, not the real authorization boundary.

export interface ListUsersParams {
  search?: string;
  role?: Role;
  isActive?: boolean;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortDir?: "asc" | "desc";
}

export async function listUsers(params: ListUsersParams = {}): Promise<UserListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.role) query.set("role", params.role);
  if (params.isActive !== undefined) query.set("is_active", String(params.isActive));
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 25));
  query.set("sort_by", params.sortBy ?? "created_at");
  query.set("sort_dir", params.sortDir ?? "desc");
  const res = await authedFetch(`${getApiUrl()}/api/v1/admin/users?${query.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch users");
  return res.json();
}

export async function getUserStats(): Promise<UserStats> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/admin/users/stats`);
  if (!res.ok) throw new Error("Failed to fetch user stats");
  return res.json();
}

export async function getRoles(): Promise<RolePermissions[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/admin/roles`);
  if (!res.ok) throw new Error("Failed to fetch roles");
  return res.json();
}

export async function createUser(email: string, password: string, fullName: string, role: Role): Promise<User> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/admin/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, full_name: fullName, role }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to create user");
  }
  return res.json();
}

export async function updateUser(userId: string, updates: { full_name?: string; role?: Role }): Promise<User> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to update user");
  }
  return res.json();
}

export async function setUserActive(userId: string, isActive: boolean): Promise<User> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/admin/users/${userId}/active`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: isActive }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to update account status");
  }
  return res.json();
}

export async function resetUserPassword(userId: string, newPassword: string): Promise<User> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/admin/users/${userId}/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_password: newPassword }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to reset password");
  }
  return res.json();
}

// --- Security Assessment Toolkit ---
// See backend/app/api/routes/security_assessment.py. Every run requires an
// explicit target_confirmation (must exactly match the investigation's own
// target) and authorization_confirmed=true -- enforced server-side; this
// client never constructs raw tool arguments, only ever a profile id.

export async function getSecurityAssessmentProfiles(): Promise<ToolProfile[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/security-assessment/profiles`);
  if (!res.ok) throw new Error("Failed to fetch security assessment profiles");
  return res.json();
}

export async function getSecurityAssessmentToolHealth(): Promise<ToolHealth[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/security-assessment/tool-health`);
  if (!res.ok) throw new Error("Failed to fetch tool health");
  return res.json();
}

export async function runSecurityAssessment(
  lookupId: string,
  toolIds: string[],
  profile: string,
  targetConfirmation: string,
  authorizationConfirmed: boolean
): Promise<{ run_id: string; status: string }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/security-assessment/${lookupId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tool_ids: toolIds,
      profile,
      target_confirmation: targetConfirmation,
      authorization_confirmed: authorizationConfirmed,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to start security assessment");
  }
  return res.json();
}

export async function listSecurityAssessmentRuns(lookupId: string): Promise<SecurityAssessmentRun[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/security-assessment/${lookupId}/runs`);
  if (!res.ok) throw new Error("Failed to fetch security assessment runs");
  return res.json();
}

export async function getSecurityAssessmentRun(runId: string): Promise<SecurityAssessmentRun> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/security-assessment/runs/${runId}`);
  if (!res.ok) throw new Error("Failed to fetch security assessment run");
  return res.json();
}

export async function cancelSecurityAssessmentRun(runId: string): Promise<{ run_id: string; status: string }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/security-assessment/runs/${runId}/cancel`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Failed to cancel security assessment run");
  }
  return res.json();
}

// --- Pentest Suite ---
// See backend/app/api/routes/pentest.py. Distinct from the Security
// Assessment Toolkit above -- a standalone, scope-enforced assessment
// workflow, not tied to a single IOC lookup.

export async function getPentestKillSwitch(): Promise<{ engaged: boolean }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/kill-switch`);
  if (!res.ok) throw new Error("Failed to fetch pentest kill switch status");
  return res.json();
}

export async function engagePentestKillSwitch(): Promise<{ engaged: boolean }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/kill-switch/engage`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to engage the pentest kill switch");
  }
  return res.json();
}

export async function disengagePentestKillSwitch(): Promise<{ engaged: boolean }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/kill-switch/disengage`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to disengage the pentest kill switch");
  }
  return res.json();
}

export async function getPentestValidationChecks(): Promise<PentestValidationChecks> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/validation-checks`);
  if (!res.ok) throw new Error("Failed to fetch pentest validation checks");
  return res.json();
}

export async function createPentestAssessment(
  name: string,
  profile: string,
  scopeDefinition: Record<string, unknown>,
  description?: string,
  maxRuntimeMinutes?: number,
  maxRequests?: number
): Promise<PentestAssessment> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      description: description ?? null,
      profile,
      scope_definition: scopeDefinition,
      ...(maxRuntimeMinutes !== undefined ? { max_runtime_minutes: maxRuntimeMinutes } : {}),
      ...(maxRequests !== undefined ? { max_requests: maxRequests } : {}),
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to create pentest assessment");
  }
  return res.json();
}

export async function listPentestAssessments(): Promise<PentestAssessment[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments`);
  if (!res.ok) throw new Error("Failed to fetch pentest assessments");
  return res.json();
}

export async function getPentestAssessment(assessmentId: string): Promise<PentestAssessment> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}`);
  if (!res.ok) throw new Error("Failed to fetch pentest assessment");
  return res.json();
}

export async function updatePentestScope(
  assessmentId: string,
  scopeDefinition: Record<string, unknown>
): Promise<PentestAssessment> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/scope`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope_definition: scopeDefinition }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to update assessment scope");
  }
  return res.json();
}

export async function addPentestTarget(
  assessmentId: string,
  targetType: string,
  value: string,
  options?: { port?: number; assetLabel?: string; environment?: string; targetGroup?: string }
): Promise<PentestAssessment["targets"][number]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/targets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_type: targetType,
      value,
      port: options?.port ?? null,
      asset_label: options?.assetLabel ?? null,
      environment: options?.environment ?? null,
      target_group: options?.targetGroup ?? null,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to add pentest target");
  }
  return res.json();
}

export async function startPentestAssessment(assessmentId: string, toolIds?: string[]): Promise<Record<string, unknown>> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool_ids: toolIds ?? null }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to start pentest assessment");
  }
  return res.json();
}

export async function pausePentestAssessment(assessmentId: string): Promise<Record<string, unknown>> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/pause`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to pause pentest assessment");
  }
  return res.json();
}

export async function resumePentestAssessment(assessmentId: string): Promise<Record<string, unknown>> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/resume`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to resume pentest assessment");
  }
  return res.json();
}

export async function cancelPentestAssessment(assessmentId: string): Promise<Record<string, unknown>> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/cancel`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to cancel pentest assessment");
  }
  return res.json();
}

export async function emergencyStopPentestAssessment(assessmentId: string): Promise<Record<string, unknown>> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/emergency-stop`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to emergency-stop pentest assessment");
  }
  return res.json();
}

export async function listPentestFindings(assessmentId: string): Promise<PentestFinding[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/findings`);
  if (!res.ok) throw new Error("Failed to fetch pentest findings");
  return res.json();
}

export async function getPentestAssessmentSummary(assessmentId: string): Promise<PentestAssessmentSummaryReport> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/summary`);
  if (!res.ok) throw new Error("Failed to fetch pentest assessment summary");
  return res.json();
}

export async function validatePentestFinding(findingId: string, checkId: string): Promise<PentestFinding> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/findings/${findingId}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ check_id: checkId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to validate pentest finding");
  }
  return res.json();
}

export async function explainPentestFinding(findingId: string): Promise<PentestFindingExplanation> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/findings/${findingId}/explain`);
  if (!res.ok) throw new Error("Failed to fetch pentest finding explanation");
  return res.json();
}

// --- Pentest Suite: gated real-exploit validation (Metasploit) ---
// See backend/app/api/routes/pentest_exploit.py. pentest:exploit is
// ADMIN-only server-side; every mode="exploit" call requires confirmed=true
// on every single request -- never cached/remembered client-side.

export async function getMsfHealth(): Promise<{ available: boolean }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/msf/health`);
  if (!res.ok) throw new Error("Failed to fetch Metasploit health");
  return res.json();
}

export async function searchExploitModulesForFinding(findingId: string): Promise<PentestExploitModuleCandidate[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/findings/${findingId}/exploit/modules`);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to search exploit modules");
  }
  return res.json();
}

export async function getExploitModuleOptions(moduleFullname: string): Promise<PentestExploitModuleOptions> {
  const res = await authedFetch(
    `${getApiUrl()}/api/v1/pentest/exploit/modules/options?module_fullname=${encodeURIComponent(moduleFullname)}`
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to fetch module options");
  }
  return res.json();
}

export async function runExploitAttempt(
  findingId: string,
  moduleFullname: string,
  options: Record<string, unknown>,
  mode: "check" | "exploit",
  confirmed: boolean
): Promise<PentestExploitAttempt> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/findings/${findingId}/exploit/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ module_fullname: moduleFullname, options, mode, confirmed }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to run exploit action");
  }
  return res.json();
}

export async function listExploitAttempts(assessmentId: string): Promise<PentestExploitAttempt[]> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/assessments/${assessmentId}/exploit-attempts`);
  if (!res.ok) throw new Error("Failed to fetch exploit attempts");
  return res.json();
}

export async function stopExploitSession(attemptId: string): Promise<{ stopped: boolean; session_id: number }> {
  const res = await authedFetch(`${getApiUrl()}/api/v1/pentest/exploit-attempts/${attemptId}/stop-session`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Failed to stop session");
  }
  return res.json();
}
