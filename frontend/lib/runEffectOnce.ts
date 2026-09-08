/**
 * Guards a non-idempotent side effect (e.g. firing a real, costly POST
 * request) started from inside a `useEffect` against React 18 Strict
 * Mode's dev-only double-invoke of that effect on first mount
 * (setup -> cleanup -> setup, run synchronously, before the browser paints,
 * specifically to surface bugs like the one this fixes).
 *
 * Real P1 found live in app/lookup/new/page.tsx: that effect called
 * streamLookup() (a POST /api/v1/lookup/stream that the backend fully
 * processes -- one IOCLookup row, the whole provider fan-out, the whole AI
 * pipeline -- essentially as soon as it's received) and attached an
 * AbortController's signal, aborting it in the effect's cleanup. That's the
 * React-docs-recommended pattern for a plain fetch, but it only protects
 * against a *stale result* landing in state after cleanup -- it does nothing
 * to stop the request from having already reached and been fully processed
 * by the server before the abort is even called. Strict Mode's synchronous
 * double-invoke therefore fired two real, independent investigations (two
 * DB rows, double provider/AI cost, two consumed rate-limit slots) for one
 * user action -- confirmed live via network capture (2 identical POST
 * bodies a few ms apart) and via the database.
 *
 * `runEffectOnce` fixes this generically: `start()` is called at most once
 * per guard instance -- Strict Mode's second ("real", lasting) setup call
 * finds the guard already populated and, instead of starting a second real
 * side effect, cancels the abort that the first (transient) cleanup call had
 * scheduled. The abort itself is deferred by one macrotask
 * (`setTimeout(..., 0)`) specifically so a genuine unmount (real navigation
 * away, tab close) still cleans up correctly: on a genuine unmount there is
 * no subsequent setup call to cancel the pending timer, so it fires and
 * `onAbort` runs for real, same as an un-guarded `return () =>
 * controller.abort()` would have.
 *
 * Usage (inside a useEffect callback):
 * ```ts
 * const guardRef = useRef<OnceGuard<AbortController> | null>(null);
 * useEffect(() => {
 *   return runEffectOnce(
 *     guardRef,
 *     () => {
 *       const controller = new AbortController();
 *       doTheRealThing(controller.signal);
 *       return controller;
 *     },
 *     (controller) => controller.abort()
 *   );
 * }, [dep]);
 * ```
 */
export interface OnceGuard<T> {
  value: T;
  abortTimer: ReturnType<typeof setTimeout> | null;
}

export function runEffectOnce<T>(
  guardRef: { current: OnceGuard<T> | null },
  start: () => T,
  onAbort: (value: T) => void
): () => void {
  function scheduleAbort(guard: OnceGuard<T>): void {
    guard.abortTimer = setTimeout(() => {
      onAbort(guard.value);
      if (guardRef.current === guard) guardRef.current = null;
    }, 0);
  }

  const existing = guardRef.current;
  if (existing) {
    // This is Strict Mode's second (or, in principle, any subsequent)
    // invocation landing on a side effect already started by a prior
    // invocation of this same guard -- cancel the pending abort instead of
    // calling start() again.
    if (existing.abortTimer !== null) {
      clearTimeout(existing.abortTimer);
      existing.abortTimer = null;
    }
    return () => scheduleAbort(existing);
  }

  const guard: OnceGuard<T> = { value: start(), abortTimer: null };
  guardRef.current = guard;
  return () => scheduleAbort(guard);
}
