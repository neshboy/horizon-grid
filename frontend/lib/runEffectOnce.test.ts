import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runEffectOnce, type OnceGuard } from "./runEffectOnce";

// Regression test for a real P1 found live: app/lookup/new/page.tsx's
// useEffect that starts the SSE lookup stream used a plain
// `const controller = new AbortController(); ...; return () =>
// controller.abort();` -- the React-docs pattern for a "cancel a fetch on
// cleanup" effect. That's fine for an idempotent GET, but streamLookup()'s
// POST /api/v1/lookup/stream is fully processed by the backend (one
// IOCLookup row, the whole provider fan-out, the whole AI pipeline) well
// before the abort is even observed client-side. React 18 Strict Mode's
// dev-only double-invoke of this effect on first mount (setup -> cleanup ->
// setup) therefore fired the real side effect TWICE for one user action --
// confirmed live via network capture (2 identical POST bodies a few ms
// apart) and via the database (2 IOCLookup rows per search, most runs).
//
// These tests simulate that exact setup -> cleanup -> setup -> (eventually)
// real-unmount-cleanup sequence against runEffectOnce() directly, with fake
// timers standing in for the macrotask boundary Strict Mode's synchronous
// double-invoke happens inside of -- no React rendering required.
describe("runEffectOnce()", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("only calls start() once across a Strict Mode-style setup -> cleanup -> setup, and never calls onAbort until a real, unanswered cleanup", () => {
    const guardRef: { current: OnceGuard<string> | null } = { current: null };
    const start = vi.fn(() => "the-one-real-request");
    const onAbort = vi.fn();

    // First ("transient") setup call.
    const cleanup1 = runEffectOnce(guardRef, start, onAbort);
    expect(start).toHaveBeenCalledTimes(1);

    // Strict Mode immediately calls the cleanup returned by that first
    // setup call...
    cleanup1();
    // ...which merely SCHEDULES an abort rather than firing it synchronously.
    expect(onAbort).not.toHaveBeenCalled();

    // ...then immediately calls setup again (the second, "real", lasting
    // invocation) -- this must NOT start a second real request.
    const cleanup2 = runEffectOnce(guardRef, start, onAbort);
    expect(start).toHaveBeenCalledTimes(1);

    // The pending abort scheduled by cleanup1() must have been cancelled by
    // that second setup call -- advancing time must not abort the one real
    // request that's supposed to keep running.
    vi.runAllTimers();
    expect(onAbort).not.toHaveBeenCalled();

    // A genuine unmount calls the LAST cleanup (cleanup2) and nothing calls
    // setup again afterwards, so this time the scheduled abort must fire for
    // real.
    cleanup2();
    vi.runAllTimers();
    expect(onAbort).toHaveBeenCalledTimes(1);
    expect(onAbort).toHaveBeenCalledWith("the-one-real-request");
  });

  it("aborts immediately (after the deferral tick) on a plain single setup -> cleanup with no re-invocation, matching the pre-fix behavior for a genuine unmount", () => {
    const guardRef: { current: OnceGuard<string> | null } = { current: null };
    const start = vi.fn(() => "req");
    const onAbort = vi.fn();

    const cleanup = runEffectOnce(guardRef, start, onAbort);
    expect(start).toHaveBeenCalledTimes(1);

    cleanup();
    expect(onAbort).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(onAbort).toHaveBeenCalledTimes(1);
  });

  it("clears the guard after a real abort, so a later, genuinely new mount starts a brand-new request", () => {
    const guardRef: { current: OnceGuard<string> | null } = { current: null };
    const start = vi.fn(() => "req");
    const onAbort = vi.fn();

    const cleanup = runEffectOnce(guardRef, start, onAbort);
    cleanup();
    vi.runAllTimers();
    expect(guardRef.current).toBeNull();

    runEffectOnce(guardRef, start, onAbort);
    expect(start).toHaveBeenCalledTimes(2);
  });
});
