import { beforeEach, describe, expect, it, vi } from "vitest";

// Regression test for authedFetch() (frontend/lib/api.ts): a dead session --
// either a 401 whose refresh attempt also fails (expired access token +
// invalid/garbage refresh token), or a 403 "Account disabled" for an account
// an admin just deactivated -- used to just come back as a plain failing
// Response, which every one of the ~10 authedFetch-based page components
// (dashboard, basket, cases, admin, providers, pentest, provider-health,
// ...) turned into its own generic "Failed to fetch X" message while
// leaving the user parked on the same broken-looking page with stale
// tokens still in localStorage and no in-page way to recover. Confirmed
// live against the running stack (disabling an account mid-session
// produced exactly this 403, and an expired access token + garbage refresh
// token produced exactly this 401) before this fix.
//
// Needs its own localStorage + window/location shims -- kept in this file
// rather than api.test.ts so they don't change that file's own
// getApiUrl()-fallback-dependent assertions. Every test dynamically
// re-imports "./api" after vi.resetModules() so the module-level
// `redirectingToLogin` latch (which intentionally only lets one redirect
// fire per page load) starts fresh each time, rather than leaking state
// across it() blocks that share one module instance.

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

const location = { pathname: "/dashboard", search: "", href: "" };
(globalThis as unknown as { window: unknown }).window = { location };

function mockFetchSequence(...responses: Array<{ status: number; body: unknown }>) {
  let call = 0;
  global.fetch = vi.fn().mockImplementation(() => {
    const r = responses[Math.min(call, responses.length - 1)];
    call += 1;
    const res = {
      ok: r.status >= 200 && r.status < 300,
      status: r.status,
      json: async () => r.body,
      clone() {
        return res;
      },
    };
    return Promise.resolve(res);
  }) as unknown as typeof fetch;
}

function fetchedUrls(): string[] {
  return (global.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]));
}

async function freshApi() {
  vi.resetModules();
  return import("./api");
}

describe("authedFetch() unrecoverable-auth handling", () => {
  beforeEach(() => {
    store.clear();
    location.pathname = "/dashboard";
    location.search = "";
    location.href = "";
    vi.restoreAllMocks();
  });

  it("hard-redirects to /login and clears both tokens when a 401 survives a failed refresh", async () => {
    localStorage.setItem("access_token", "dead-access");
    localStorage.setItem("refresh_token", "garbage-refresh");
    mockFetchSequence(
      { status: 401, body: { detail: "Could not validate credentials" } }, // original request
      { status: 401, body: { detail: "Invalid refresh token" } } // refresh attempt fails
    );

    const { getCurrentUser } = await freshApi();
    await expect(getCurrentUser()).rejects.toThrow();

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(location.href).toBe("/login?sessionExpired=1&next=%2Fdashboard");
  });

  it("hard-redirects to /login on a 403 'Account disabled' without ever attempting a token refresh", async () => {
    localStorage.setItem("access_token", "still-valid-but-account-disabled");
    localStorage.setItem("refresh_token", "still-valid-refresh");
    location.pathname = "/basket";
    mockFetchSequence({ status: 403, body: { detail: "Account disabled" } });

    const { listBasket } = await freshApi();
    await expect(listBasket()).rejects.toThrow();

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(location.href).toBe("/login?sessionExpired=1&next=%2Fbasket");
    expect(fetchedUrls().some((u) => u.includes("/auth/refresh"))).toBe(false);
  });

  it("does NOT redirect on a generic permission-denied 403 (a normal, recoverable authorization outcome)", async () => {
    localStorage.setItem("access_token", "valid-but-insufficient-role");
    localStorage.setItem("refresh_token", "valid-refresh");
    mockFetchSequence({
      status: 403,
      body: { detail: "Role 'analyst' lacks permission 'user:manage'" },
    });

    const { listBasket } = await freshApi();
    await expect(listBasket()).rejects.toThrow();

    // Not the unrecoverable-auth path -- tokens and location are untouched.
    expect(localStorage.getItem("access_token")).toBe("valid-but-insufficient-role");
    expect(location.href).toBe("");
  });

  it("still transparently retries once and returns real data after a successful refresh (no redirect)", async () => {
    localStorage.setItem("access_token", "expiring-access");
    localStorage.setItem("refresh_token", "still-good-refresh");
    mockFetchSequence(
      { status: 401, body: { detail: "Could not validate credentials" } },
      { status: 200, body: { access_token: "new-access", refresh_token: "new-refresh" } },
      { status: 200, body: { id: "u1", email: "user@example.com", role: "analyst", full_name: "User" } }
    );

    const { getCurrentUser } = await freshApi();
    const user = await getCurrentUser();

    expect(user).toEqual({ id: "u1", email: "user@example.com", role: "analyst", full_name: "User" });
    expect(localStorage.getItem("access_token")).toBe("new-access");
    expect(location.href).toBe("");
  });
});
