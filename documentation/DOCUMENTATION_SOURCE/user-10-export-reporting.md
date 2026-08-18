# Exporting Findings

Every investigation the platform runs produces a lot of material worth keeping: a verdict, a risk score, per-provider evidence, correlation results, and an AI-written summary. Once you've reviewed an investigation, you'll usually want to get some or all of that out of the browser and into wherever the rest of your work lives — a ticket, an incident report, a chat message to a teammate, or another tool entirely.

The export controls for this live in the sidebar of every investigation page. Opening them shows four buttons: **Export JSON**, **Export Markdown**, **Export PDF**, and **Export CSV**.

[FIGURE: 21-investigation-export-menu.png | The export sidebar on an investigation page, showing all four export buttons and the real in-product message displayed when an unavailable format is clicked.]

Two of these — JSON and Markdown — work today and produce a real file. Two of them — PDF and CSV — are visible in the interface but not yet built. This section covers both honestly, because that's exactly what you'll see if you click each one.

## What works today: Export JSON and Export Markdown

Clicking **Export JSON** or **Export Markdown** downloads a real file to your browser's Downloads folder, built from the same investigation you're looking at on screen. Both formats carry the same underlying content, just structured for different purposes:

- **Export JSON** is the machine-readable version — the same assessment fields shown on screen, structured for a script, a SIEM (Security Information and Event Management system — the log-aggregation tool many SOCs use as their central alerting hub) ingestion pipeline, or another tool that expects structured data rather than prose.
- **Export Markdown** is the human-readable version — the same content laid out as readable text, suitable for pasting straight into a ticket, a wiki page, or an email.

Either export includes:

- The **verdict** and **risk score** the platform settled on for the IOC (Indicator of Compromise — a piece of evidence such as an IP address, domain, URL, file hash, or CVE ID that an analyst wants to investigate).
- The **executive and technical summary** — a plain-language explanation of what the IOC is and why it received the verdict it did, alongside the more detailed technical reasoning.
- A **supporting evidence** list — specific findings the AI pulled out of the per-provider results and correlation data to back up its verdict. This is a curated, AI-written excerpt list, not the full structured Evidence Ledger; for the complete per-provider findings with confidence scores on each item, use the Evidence Ledger inside the app itself (covered elsewhere in this document) — it isn't part of either export.
- Any **MITRE ATT&CK mappings** — techniques the evidence supports, when applicable.
- The **recommended actions** — practical next steps suggested for an analyst handling this IOC.
- Any **detection rules** the platform generated for that IOC, when the IOC type and available evidence supported generating one.

In other words, whichever format you pick, you get the verdict, risk score, and the AI's full written reasoning in one file — enough to hand this investigation off to a colleague, attach it to a ticket, or drop it into another tool without re-typing anything. If your use case specifically needs the full per-item Evidence Ledger with confidence scores rather than the AI's supporting-evidence excerpts, view that in the app itself — it isn't part of either export.

## What's not available yet: Export PDF and Export CSV

**Export PDF** and **Export CSV** appear as buttons in the same sidebar, but neither is built yet. Clicking either one shows the real message the product displays: **"Export format not yet available."** No file downloads, and nothing crashes — the platform tells you plainly that this format isn't ready rather than pretending it worked or failing silently.

This is a known, documented scope boundary, not a defect: the two working formats (JSON and Markdown) already cover both the machine-readable and human-readable cases most analysts need, and PDF/CSV support is simply not built out yet. If your workflow depends specifically on a PDF for a report template or a CSV for spreadsheet import, use Export Markdown or Export JSON as the source material for now and convert it with whatever tool your workflow already uses.

## A note on the AI-written portions of an export

Nearly everything in either export — the executive summary, technical summary, supporting-evidence excerpts, MITRE ATT&CK mappings, recommended actions, and any detection rules — comes from a single consolidated AI call, not hand-typed by a human analyst, and it is a separate thing from the platform's own non-AI-generated **Evidence Ledger**. Like any AI-generated analysis, an export is a starting point for your judgment, not a substitute for it. The platform's own Evidence Ledger and verdict-explanation tools (covered elsewhere in this document) are how you check an AI-written claim against the real, underlying evidence before you rely on it or pass it along in an exported report. Providers genuinely disagree on real IOCs — the 8.8.8.8 (Google Public DNS) investigation shown elsewhere in this document is a good real example, where one provider flagged it malicious and two others called it clean — and the platform's summaries are written to reflect that disagreement rather than paper over it, but it's still worth reading the underlying evidence yourself before treating an exported verdict as final.
