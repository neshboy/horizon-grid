"use client";

/**
 * Persistent search bar for the lookup pages -- lets an analyst pivot to a
 * new IOC without navigating back to the home page first. Pushes a new
 * ?value= onto /lookup/new; since that's the same route as the current page,
 * Next.js won't remount LookupNewPageInner on its own, so that page keys its
 * root element on the raw ?value= (see app/lookup/new/page.tsx) to force a
 * clean remount -- otherwise old provider results/summaries from the
 * previous IOC would linger alongside the new stream's events.
 */

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { isLoggedIn } from "@/lib/api";

interface TopSearchBarProps {
  initialValue?: string;
}

export function TopSearchBar({ initialValue = "" }: TopSearchBarProps) {
  const [value, setValue] = useState(initialValue);
  const router = useRouter();

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = value.trim();
      if (!trimmed) return;
      const target = `/lookup/new?value=${encodeURIComponent(trimmed)}`;
      if (!isLoggedIn()) {
        router.push(`/login?next=${encodeURIComponent(target)}`);
        return;
      }
      router.push(target);
    },
    [value, router]
  );

  return (
    <form onSubmit={handleSubmit} className="flex w-full items-center gap-2">
      <div className="flex flex-1 items-center gap-2 rounded-lg border border-border bg-card px-3 py-2">
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="IP, domain, URL, hash, CVE, threat actor, YARA rule..."
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
      <Button type="submit" size="default" disabled={!value.trim()}>
        Investigate
      </Button>
    </form>
  );
}
