"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, register } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function RegisterPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register(email, password, fullName);
      await login(email, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-2xl font-bold tracking-tight">HORIZON GRID</h1>
        <p className="text-sm text-muted-foreground">
          Self-registration only works on a brand-new installation with no
          existing admin. If one already exists, ask an administrator to
          create your account from the Administration page.
        </p>
      </div>

      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Create account</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Full name"
              className="rounded-md border border-border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground"
            />
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              required
              autoFocus
              className="rounded-md border border-border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground"
            />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              required
              minLength={8}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground"
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button type="submit" disabled={submitting || !email || !password}>
              {submitting ? "Creating account..." : "Create account"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <a href="/login" className="text-xs text-muted-foreground hover:text-foreground">
        Already have an account? Sign in
      </a>
    </main>
  );
}
