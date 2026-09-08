"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { login, getLoginErrorMessage } from "@/lib/api";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function LoginPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") ?? "/";
  // Set by lib/api.ts's handleUnrecoverableAuth() when an authedFetch call
  // hit a dead session (a 401 that survived a refresh attempt, or a 403
  // "Account disabled") and hard-redirected here rather than leaving the
  // user parked on a broken-looking protected page -- tells them why they
  // landed on the sign-in screen instead of just looking like a fresh visit.
  const sessionExpired = searchParams.get("sessionExpired") === "1";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      router.push(next);
    } catch (err) {
      // Distinguish a genuine bad-credential rejection (which should stay
      // vague, as before) from a 429 rate limit, a 5xx server error, a
      // disabled account (403), or a network-level failure that never even
      // reached the backend -- none of those mean the password is wrong, so
      // telling the user that is actively misleading. See
      // getLoginErrorMessage() in lib/api.ts for the full mapping.
      setError(getLoginErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="hg-grid-canvas relative flex min-h-screen flex-col items-center justify-center gap-8 overflow-hidden px-4">
      {/* A single, ultra-subtle horizon line + glow across the full width --
          decorative only, zero DOM cost beyond one div, no animation. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-0 top-1/2 h-px w-full bg-gradient-to-r from-transparent via-border to-transparent"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 h-40 w-[36rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary/5 blur-3xl"
      />

      <div className="relative z-10 flex flex-col items-center gap-3 text-center">
        <Logo size="full" className="scale-125" />
        <p className="font-display text-xs uppercase tracking-[0.15em] text-muted-foreground">
          Every Signal. One Operational Picture.
        </p>
      </div>

      <Card className="relative z-10 w-full max-w-sm border-border/80">
        <CardHeader>
          <CardTitle className="font-display text-xs uppercase tracking-[0.1em] text-muted-foreground">
            Operator Sign-In
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sessionExpired && (
            <p className="mb-3 text-xs text-muted-foreground">
              Your session ended. Please sign in again.
            </p>
          )}
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              required
              autoFocus
              className="rounded-tight border border-border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-primary"
            />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              required
              className="rounded-tight border border-border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-primary"
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button type="submit" disabled={submitting || !email || !password}>
              {submitting ? "Signing in..." : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <a href="/register" className="relative z-10 text-xs text-muted-foreground hover:text-foreground">
        Need an account? Register
      </a>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading...</div>}>
      <LoginPageInner />
    </Suspense>
  );
}
