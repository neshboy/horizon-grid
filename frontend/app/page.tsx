"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Search, ShieldCheck } from "lucide-react";
import { getCurrentUser, isLoggedIn, logout } from "@/lib/api";
import { AiQuickSwitch } from "@/components/dashboard/AiQuickSwitch";

export default function HomePage() {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
    if (isLoggedIn()) {
      // This is the page most users land on right after signing in, and it
      // (unlike /providers, /cases, /basket) never renders WorkspaceNav --
      // without this, an administrator has no visible path at all to the
      // Administration console unless they already know the /admin URL.
      getCurrentUser()
        .then((user) => setIsAdmin(user.role === "admin"))
        .catch(() => setIsAdmin(false));
    }
  }, []);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!value.trim()) return;
      setSubmitting(true);
      const target = `/lookup/new?value=${encodeURIComponent(value.trim())}`;
      if (!isLoggedIn()) {
        router.push(`/login?next=${encodeURIComponent(target)}`);
        return;
      }
      router.push(target);
    },
    [value, router]
  );

  const handleLogout = useCallback(() => {
    logout();
    setLoggedIn(false);
  }, []);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 px-4">
      <div className="absolute right-4 top-4">
        {loggedIn ? (
          <div className="flex items-center gap-2">
            {isAdmin && (
              <Button variant="outline" size="sm" onClick={() => router.push("/admin")}>
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                Administration
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={handleLogout}>
              Sign out
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => router.push("/login")}>
              Sign in
            </Button>
            <Button variant="outline" size="sm" onClick={() => router.push("/register")}>
              Register
            </Button>
          </div>
        )}
      </div>

      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-3xl font-bold font-display tracking-wide">HORIZON GRID</h1>
        <p className="text-sm text-muted-foreground">Every Signal. One Operational Picture.</p>
        <p className="max-w-xl text-sm text-muted-foreground">
          Enter any indicator of compromise. We query every configured provider in
          parallel, correlate the results, and let your configured AI backend produce
          an evidence-based assessment -- all in one place.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex w-full max-w-2xl items-center gap-2">
        <div className="flex flex-1 items-center gap-2 rounded-lg border border-border bg-card px-4 py-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="IP, domain, URL, hash, CVE, threat actor, YARA rule..."
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            autoFocus
          />
        </div>
        <Button type="submit" size="lg" disabled={submitting || !value.trim()}>
          Investigate
        </Button>
      </form>

      {/* Real bug found live during overnight QA: this rendered for every
          logged-in user regardless of role, but AiQuickSwitch's own
          listAIProviders()/getActiveAIBackend() calls hit GET
          /api/v1/runtime/ai-providers, which requires "provider:manage" --
          a permission only Admin holds. Every analyst/viewer login produced
          two 403 console errors and a permanently non-functional control
          (it just renders null once its own fetch fails). Gating on isAdmin
          here matches the Administration button's own existing pattern two
          lines below. */}
      {loggedIn && isAdmin && (
        <div className="flex w-full max-w-2xl justify-center">
          <AiQuickSwitch />
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground sm:grid-cols-4">
        {["8.8.8.8", "malicious-example.com", "CVE-2024-3400", "T1059"].map((example) => (
          <button
            key={example}
            onClick={() => setValue(example)}
            className="rounded-md border border-border px-3 py-1.5 font-data tabular-nums hover:bg-muted"
          >
            {example}
          </button>
        ))}
      </div>
    </main>
  );
}
