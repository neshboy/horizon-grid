"use client";

/**
 * "Show Receipts" -- renders next to any AI-generated claim that cites
 * evidence_ids. Clicking scrolls to and highlights those exact rows in the
 * EvidencePanel (via a shared onShowReceipts callback threaded down from the
 * page) so an analyst can verify a claim without hunting through the ledger.
 */

import { Receipt } from "lucide-react";

export interface ShowReceiptsLinkProps {
  evidenceIds: string[];
  onShowReceipts: (evidenceIds: string[]) => void;
}

export function ShowReceiptsLink({ evidenceIds, onShowReceipts }: ShowReceiptsLinkProps) {
  if (evidenceIds.length === 0) {
    return <span className="text-[11px] italic text-muted-foreground">No supporting evidence cited</span>;
  }
  return (
    <button
      type="button"
      onClick={() => onShowReceipts(evidenceIds)}
      className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
    >
      <Receipt className="h-3 w-3" aria-hidden="true" />
      Show receipts ({evidenceIds.length})
    </button>
  );
}
