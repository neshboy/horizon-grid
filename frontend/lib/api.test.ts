import { beforeEach, describe, expect, it, vi } from "vitest";

// login() writes directly to `localStorage` (unguarded by a `typeof window`
// check on the write path -- see getAccessToken() for the pattern it does
// use elsewhere), so a bare Node test environment needs a stand-in before
// the module under test is imported.
const store = new Map<string, string>();
(globalThis as unknown as { localStorage: Storage }).localStorage = {
  getItem: (key: string) => (store.has(key) ? (store.get(key) as string) : null),
  setItem: (key: string, value: string) => {
    store.set(key, value);
  },
  removeItem: (key: string) => {
    store.delete(key);
  },
  clear: () => store.clear(),
  key: () => null,
  length: 0,
} as Storage;

import { ApiError, getAuditLog, getLoginErrorMessage, listAIModels, listIOCProviders, login } from "./api";

function mockFetchOnce(status: number, body: unknown, ok = status >= 200 && status < 300) {
  // Includes clone() (like a real Fetch API Response) since authedFetch()'s
  // unrecoverable-auth check reads a cloned copy of the body on every 403 --
  // see authedFetch.test.ts for that behavior's own dedicated coverage.
  const res = {
    ok,
    status,
    json: async () => body,
    clone() {
      return res;
    },
  };
  global.fetch = vi.fn().mockResolvedValue(res) as unknown as typeof fetch;
}

describe("login()", () => {
  beforeEach(() => {
    store.clear();
    vi.restoreAllMocks();
  });

  it("throws an ApiError carrying status 429 and the backend's rate-limit detail, not a generic message", async () => {
    const detail = "Too many login attempts for this account. Try again in under 60 seconds.";
    mockFetchOnce(429, { detail });

    let caught: unknown;
    try {
      await login("user@example.com", "wrong-password");
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(429);
    expect((caught as ApiError).message).toBe(detail);
  });

  it("throws an ApiError carrying a 5xx status for a server error", async () => {
    mockFetchOnce(500, { detail: "Internal Server Error" });

    let caught: unknown;
    try {
      await login("user@example.com", "whatever");
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(500);
  });

  it("throws an ApiError carrying status 401 for a genuine bad-credential rejection", async () => {
    mockFetchOnce(401, { detail: "Invalid email or password" });

    let caught: unknown;
    try {
      await login("user@example.com", "wrong-password");
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(401);
  });

  it("stores the returned tokens and resolves on a successful login", async () => {
    mockFetchOnce(200, { access_token: "access-123", refresh_token: "refresh-456" });

    const data = await login("user@example.com", "correct-password");

    expect(data).toEqual({ access_token: "access-123", refresh_token: "refresh-456" });
    expect(localStorage.getItem("access_token")).toBe("access-123");
    expect(localStorage.getItem("refresh_token")).toBe("refresh-456");
  });
});

// Regression test: the login page (frontend/app/login/page.tsx) used to only
// special-case a 429 rate limit and a >=500 server error here -- every other
// failure, including a disabled account (403, with the backend already
// returning the specific detail "Account disabled") and a genuine
// network-level failure where fetch() never got a response at all (so `err`
// isn't even an ApiError), fell into the same generic branch and showed
// "Invalid email or password.", identical to a real wrong-password
// rejection. Confirmed live via Playwright against the running frontend
// before this fix. getLoginErrorMessage() now owns that mapping so it's
// covered without needing to render the React page component.
describe("getLoginErrorMessage()", () => {
  it("keeps a genuine 401 bad-credential rejection deliberately vague", () => {
    expect(getLoginErrorMessage(new ApiError("Invalid email or password", 401))).toBe(
      "Invalid email or password."
    );
  });

  it("tells the user their account was disabled (403), not that the password was wrong", () => {
    expect(getLoginErrorMessage(new ApiError("Account disabled", 403))).toBe("Account disabled");
  });

  it("falls back to a disabled-account message if a 403 ever arrives with no detail", () => {
    expect(getLoginErrorMessage(new ApiError("", 403))).toBe("This account has been disabled.");
  });

  it("surfaces the backend's rate-limit detail on a 429", () => {
    const detail = "Too many login attempts for this account. Try again in under 60 seconds.";
    expect(getLoginErrorMessage(new ApiError(detail, 429))).toBe(detail);
  });

  it("shows a generic server-error message on a 5xx", () => {
    expect(getLoginErrorMessage(new ApiError("Internal Server Error", 500))).toBe(
      "Server error, try again later."
    );
  });

  it("shows a connectivity message -- not a credential claim -- when the request never reached the backend at all", () => {
    // fetch() itself throwing (DNS failure, connection refused, CORS, offline)
    // never produces an ApiError, since no HTTP response was ever received.
    const networkError = new TypeError("Failed to fetch");
    expect(getLoginErrorMessage(networkError)).toBe(
      "Unable to reach the server. Check your connection and try again."
    );
  });
});

// Regression test: the Manage Providers page (frontend/app/providers/page.tsx)
// never called this endpoint at all -- ProviderConfigRow's modelOptions/<select>
// branch was permanently dead code, so every AI backend's Model field was a
// blind free-text input even for backends the backend explicitly supports
// live/dynamic model discovery for (Groq, OpenAI, Ollama's actually-pulled
// models, etc.). This locks in the wrapper that page.tsx now calls via
// ProviderConfigRow's onFetchModels prop.
describe("listAIModels()", () => {
  beforeEach(() => {
    store.clear();
    vi.restoreAllMocks();
  });

  it("POSTs the candidate credentials to /api/v1/ai/{backend}/models and returns the parsed model list", async () => {
    const responseBody = { backend: "groq", models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"], source: "live", default: "llama-3.3-70b-versatile" };
    mockFetchOnce(200, responseBody);

    const result = await listAIModels("groq", { api_key: "gsk_candidate" });

    expect(result).toEqual(responseBody);
    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toContain("/api/v1/ai/groq/models");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ credentials: { api_key: "gsk_candidate" } });
  });

  it("defaults to an empty credentials object when none are supplied (still returns the curated fallback/static list)", async () => {
    const responseBody = { backend: "anthropic", models: ["claude-sonnet-4-5-20250929"], source: "static", default: "claude-sonnet-4-5-20250929" };
    mockFetchOnce(200, responseBody);

    const result = await listAIModels("anthropic");

    expect(result).toEqual(responseBody);
    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(call[1].body)).toEqual({ credentials: {} });
  });

  it("throws with the backend's detail message on a non-ok response instead of swallowing it", async () => {
    mockFetchOnce(403, { detail: "Role 'analyst' lacks permission 'provider:manage'" });

    await expect(listAIModels("groq", { api_key: "x" })).rejects.toThrow(
      "Role 'analyst' lacks permission 'provider:manage'"
    );
  });
});

// Regression test: the Manage Providers page (frontend/app/providers/page.tsx)
// called listIOCProviders()/getAuditLog() with `.catch(() => {})`, silently
// discarding whatever error came back. Both endpoints genuinely 403 for
// VIEWER/ANALYST (neither role holds provider:manage/audit:read -- see
// backend/app/models/user.py's ROLE_PERMISSIONS and
// backend/app/api/routes/runtime.py's list_ioc_providers/audit_log routes),
// so the page rendered an empty IOC Providers tab and "No changes recorded
// yet." indistinguishable from a genuinely empty result. Before this fix,
// these two functions threw a bare Error() with no status code at all,
// making it impossible for a caller to even tell a 403 apart from a 500.
// They must throw an ApiError carrying the real status so the page can
// branch on it. Confirmed live: a freshly created VIEWER account got HTTP
// 403 with detail "Role 'viewer' lacks permission 'provider:manage'"
// (and 'audit:read') from the real running backend.
describe("listIOCProviders()", () => {
  beforeEach(() => {
    store.clear();
    vi.restoreAllMocks();
  });

  it("throws an ApiError carrying status 403 and the backend's detail, not a bare Error", async () => {
    mockFetchOnce(403, { detail: "Role 'viewer' lacks permission 'provider:manage'" });

    let caught: unknown;
    try {
      await listIOCProviders();
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(403);
    expect((caught as ApiError).message).toBe("Role 'viewer' lacks permission 'provider:manage'");
  });

  it("still resolves normally with the provider list on success", async () => {
    const providers = [{ provider_id: "virustotal" }];
    mockFetchOnce(200, providers);

    await expect(listIOCProviders()).resolves.toEqual(providers);
  });
});

describe("getAuditLog()", () => {
  beforeEach(() => {
    store.clear();
    vi.restoreAllMocks();
  });

  it("throws an ApiError carrying status 403 and the backend's detail, not a bare Error", async () => {
    mockFetchOnce(403, { detail: "Role 'viewer' lacks permission 'audit:read'" });

    let caught: unknown;
    try {
      await getAuditLog(50);
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(403);
    expect((caught as ApiError).message).toBe("Role 'viewer' lacks permission 'audit:read'");
  });

  it("still resolves normally with the log entries on success", async () => {
    const entries = [{ id: "1", timestamp: "2026-01-01T00:00:00Z", action: "configure", detail: "x" }];
    mockFetchOnce(200, entries);

    await expect(getAuditLog(50)).resolves.toEqual(entries);
  });
});
