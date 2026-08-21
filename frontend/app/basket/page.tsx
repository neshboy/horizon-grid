"use client";

/**
 * IOC Basket: an analyst's scratch space for collecting IOCs across an
 * investigation, then acting on the set (investigate all, compare, promote
 * to a case). See backend/app/models/basket.py for the model rationale.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Scale, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BrandHeader } from "@/components/dashboard/BrandHeader";
import { clearBasket, compareBasketIOCs, isLoggedIn, listBasket, removeFromBasket } from "@/lib/api";
import type { BasketItem, IOCComparisonResponse } from "@/lib/types";

export default function BasketPage() {
  const router = useRouter();
  const [items, setItems] = React.useState<BasketItem[] | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [comparison, setComparison] = React.useState<IOCComparisonResponse | null>(null);
  const [comparing, setComparing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/basket");
      return;
    }
    listBasket()
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load basket"));
  }, [router]);

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleRemove = async (id: string) => {
    await removeFromBasket(id);
    setItems((prev) => prev?.filter((i) => i.id !== id) ?? null);
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  };

  const handleClear = async () => {
    await clearBasket();
    setItems([]);
    setSelected(new Set());
  };

  const handleInvestigateAll = () => {
    const targets = items?.filter((i) => selected.has(i.id)) ?? [];
    for (const target of targets) {
      window.open(`/lookup/new?value=${encodeURIComponent(target.ioc_value)}`, "_blank");
    }
  };

  const handleCompare = async () => {
    const targets = items?.filter((i) => selected.has(i.id) && i.latest_lookup_id) ?? [];
    if (targets.length < 2) {
      setError("Select at least 2 basket items that already have a completed lookup to compare.");
      return;
    }
    setComparing(true);
    setError(null);
    try {
      const result = await compareBasketIOCs(targets.map((t) => t.latest_lookup_id as string));
      setComparison(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Comparison failed");
    } finally {
      setComparing(false);
    }
  };

  return (
    <main className="min-h-screen px-4 py-8">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <BrandHeader />

        <div className="flex items-center justify-between">
          <h1 className="font-display uppercase tracking-[0.08em] text-sm text-muted-foreground">IOC Basket</h1>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={handleInvestigateAll} disabled={selected.size === 0}>
              Investigate Selected
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
            <Button size="sm" variant="outline" onClick={handleCompare} disabled={selected.size < 2 || comparing}>
              <Scale className="h-3.5 w-3.5" aria-hidden="true" />
              {comparing ? "Comparing..." : "Compare Selected"}
            </Button>
            <Button size="sm" variant="destructive" onClick={handleClear} disabled={!items?.length}>
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              Clear Basket
            </Button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <Card>
          <CardHeader>
            <CardTitle>
              Collected IOCs{" "}
              {items ? <span className="font-data tabular-nums">({items.length})</span> : ""}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {!items && <p className="text-sm text-muted-foreground">Loading...</p>}
            {items?.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No IOCs collected yet -- use &quot;Add to Basket&quot; on any lookup page.
              </p>
            )}
            {items?.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2"
              >
                <label className="flex flex-1 items-center gap-3">
                  <input
                    type="checkbox"
                    checked={selected.has(item.id)}
                    onChange={() => toggleSelected(item.id)}
                    className="h-4 w-4"
                  />
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-foreground font-data tabular-nums">
                      {item.ioc_value}
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {item.ioc_type} {item.latest_lookup_id ? "· has completed lookup" : "· not yet investigated"}
                      {item.note ? ` · ${item.note}` : ""}
                    </span>
                  </div>
                </label>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => router.push(`/lookup/new?value=${encodeURIComponent(item.ioc_value)}`)}
                  >
                    Investigate
                  </Button>
                  <button
                    type="button"
                    onClick={() => handleRemove(item.id)}
                    className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Remove from basket"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        {comparison && (
          <Card>
            <CardHeader>
              <CardTitle>Comparison</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border text-muted-foreground">
                      <th className="py-2 pr-3">IOC</th>
                      <th className="py-2 pr-3">Verdict</th>
                      <th className="py-2 pr-3">Risk</th>
                      <th className="py-2 pr-3">ASN</th>
                      <th className="py-2 pr-3">Malware</th>
                      <th className="py-2 pr-3">Threat Actors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.rows.map((row) => (
                      <tr
                        key={row.ioc_value}
                        className={
                          "border-b border-border/50 last:border-none" +
                          (row.ioc_value === comparison.narrative.most_dangerous_ioc_value ? " bg-destructive/10" : "")
                        }
                      >
                        <td className="py-2 pr-3 font-medium text-foreground font-data tabular-nums">
                          {row.ioc_value}
                        </td>
                        <td className="py-2 pr-3 capitalize">{row.verdict.replace(/_/g, " ")}</td>
                        <td className="py-2 pr-3 font-data tabular-nums">{row.risk_score?.toFixed(0) ?? "—"}</td>
                        <td className="py-2 pr-3 font-data tabular-nums">{row.asn.join(", ") || "—"}</td>
                        <td className="py-2 pr-3">{row.malware_families.join(", ") || "—"}</td>
                        <td className="py-2 pr-3">{row.threat_actors.join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-sm text-foreground">{comparison.narrative.narrative}</p>
              {comparison.narrative.key_differences.length > 0 && (
                <ul className="flex flex-col gap-1 pl-4 text-sm text-foreground">
                  {comparison.narrative.key_differences.map((d, i) => (
                    <li key={i} className="list-disc">{d}</li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </main>
  );
}
