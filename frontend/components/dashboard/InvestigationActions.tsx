"use client";

/**
 * "Add to Basket" / "Add to Case" quick actions for the current IOC --
 * placed in the lookup sidebar so an analyst collecting IOCs across an
 * investigation never has to leave the page or re-type the value.
 */

import * as React from "react";
import { Briefcase, FolderPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { addCaseIOC, addToBasket, listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";

export interface InvestigationActionsProps {
  iocValue: string;
  iocType: string | null;
  lookupId: string | null;
}

export function InvestigationActions({ iocValue, iocType, lookupId }: InvestigationActionsProps) {
  const [message, setMessage] = React.useState<string | null>(null);
  const [cases, setCases] = React.useState<CaseSummary[] | null>(null);
  const [showCasePicker, setShowCasePicker] = React.useState(false);
  const messageTimeout = React.useRef<ReturnType<typeof setTimeout>>();

  const showMessage = React.useCallback((text: string) => {
    setMessage(text);
    if (messageTimeout.current) clearTimeout(messageTimeout.current);
    messageTimeout.current = setTimeout(() => setMessage(null), 3000);
  }, []);

  React.useEffect(() => () => { if (messageTimeout.current) clearTimeout(messageTimeout.current); }, []);

  const handleAddToBasket = React.useCallback(async () => {
    try {
      await addToBasket(iocValue);
      showMessage("Added to basket.");
    } catch (err) {
      showMessage(err instanceof Error ? err.message : "Failed to add to basket.");
    }
  }, [iocValue, showMessage]);

  const handleOpenCasePicker = React.useCallback(async () => {
    setShowCasePicker((prev) => !prev);
    if (!cases) {
      try {
        setCases(await listCases());
      } catch {
        setCases([]);
      }
    }
  }, [cases]);

  const handleAddToCase = React.useCallback(
    async (caseId: string) => {
      try {
        await addCaseIOC(caseId, iocValue, iocType ?? "unknown", lookupId ?? undefined);
        showMessage("Added to case.");
        setShowCasePicker(false);
      } catch (err) {
        showMessage(err instanceof Error ? err.message : "Failed to add to case.");
      }
    },
    [iocValue, iocType, lookupId, showMessage]
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Investigation Actions</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={handleAddToBasket}>
            <Briefcase className="h-3.5 w-3.5" aria-hidden="true" />
            Add to Basket
          </Button>
          <Button size="sm" variant="outline" onClick={handleOpenCasePicker}>
            <FolderPlus className="h-3.5 w-3.5" aria-hidden="true" />
            Add to Case
          </Button>
        </div>
        {showCasePicker && (
          <div className="flex flex-col gap-1 rounded-md border border-border bg-muted/20 p-2">
            {cases === null && <p className="text-xs text-muted-foreground">Loading cases...</p>}
            {cases?.length === 0 && <p className="text-xs text-muted-foreground">No cases yet -- create one first.</p>}
            {cases?.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => handleAddToCase(c.id)}
                className="rounded-md px-2 py-1 text-left text-xs text-foreground transition-colors hover:bg-muted"
              >
                {c.title}
              </button>
            ))}
          </div>
        )}
        {message && <p className="text-xs text-muted-foreground">{message}</p>}
      </CardContent>
    </Card>
  );
}
