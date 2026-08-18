# System Health

## A simple yes/no answer: is the platform up?

Before trusting any investigation result, it helps to know the backend itself is actually running and reachable. The platform exposes a small, unauthenticated health-check address for exactly this purpose. Opening it directly in a browser returns a short, raw JSON reply rather than a page of graphics -- it is meant to be read by a person in two seconds, or by a monitoring script in milliseconds.

[FIGURE: 27-system-health.png | The backend's own health-check address, opened directly in a browser, returns a short raw JSON reply confirming the service is up and reachable.]

The reply is deliberately minimal:

```
{"status":"ok","service":"HORIZON GRID"}
```

There is no login, no dashboard, and no extra detail here on purpose. This endpoint exists to answer one question only -- "is the backend up right now?" -- as unambiguously as possible. If the backend is down, still starting up, or unreachable, this address simply fails to load instead of returning the reply above; that failure to load is itself the signal that something needs attention.

## Checking health without touching Docker

The platform's actual runtime is a set of Docker containers, but an administrator running the Windows-installed version never needs to know that, let alone type a Docker command, just to check on it day to day. The Windows installer adds a Start Menu group that includes a **Service Status** shortcut and a **Diagnostics** shortcut, both built specifically so a routine health check is a single click rather than a terminal session.

- **Service Status** reports on whether the platform's services are up and healthy.
- **Diagnostics** is the equivalent shortcut for digging deeper when something looks wrong, without needing to know the underlying container commands.

Between these Start Menu shortcuts and the health-check address described above, an administrator has two independent, beginner-friendly ways to confirm the platform is alive -- one click, or one URL.

# Provider Health

## A dedicated page for "is every provider actually working right now?"

The single-page health check above answers "is the backend up." A separate, more detailed question -- "is every individual threat-intelligence provider actually working right now, or just configured" -- gets its own dedicated page. It's reachable from the new **Dashboard** entry in the global navigation, then **"View full Provider Health status"** on the Executive Dashboard's provider-health widget (or directly via the **Provider Health** link under the Operations group of the same navigation).

[FIGURE: dashboard-provider-health.png | The Provider Health page shows real per-provider status across four time windows, with healthy/degraded/down/unknown always paired with a distinct icon and label, not color alone.]

Unlike the old provider cards shown mid-investigation (still covered below), this page is not scoped to one lookup -- it is a real, database-backed table of every registered provider's status, built from the actual outcome of every real call that provider has made across the whole platform. Each row reports status, success rate, average latency, and consecutive-failure count, and reports all of that across four separate rolling windows -- 1 hour, 24 hours, 7 days, and 30 days -- so a brand-new problem and a month-long pattern are both visible without cross-referencing anything else; clicking a row expands all four windows side by side.

Status is always one of four values -- Healthy, Degraded, Down, or Unknown -- and each is always paired with its own distinct color, icon, and text label, never color alone, so the information doesn't depend on being able to distinguish colors.

**A guarantee worth stating explicitly: a provider that was never actually exercised in a given window shows "Unknown," never "Healthy."** Silence is not evidence of health -- a provider nobody has called in the last hour has no success rate to report for that hour, and reporting one anyway (even a reassuring one) would be reporting something the platform doesn't actually know.

**A related guarantee, found and fixed as a real bug during this feature's own testing:** a provider that correctly reports "nothing found" for a given indicator -- which is what most real-world lookups against most providers actually return, since no single provider's dataset covers every indicator -- counts as a healthy, successful outcome, not a failure. An earlier version of this page's health calculation miscounted that correct "no data" response as a failed attempt, which meant a provider working perfectly could have shown up as "Degraded" or "Down" simply for doing its job honestly. This was caught and fixed before release: a real provider (OTX) that had been reporting "Degraded" at 64% success under the flawed logic correctly reported "Healthy" at 100% once "nothing found" was counted as the successful outcome it actually is.

# Troubleshooting

The list below is not a set of hypothetical problems -- every item was either deliberately induced and observed, or organically encountered, during the platform's own end-to-end quality-assurance pass, then either fixed or documented as an honest, known limitation. It is written for the first time something looks unexpected during an investigation of an IOC (Indicator of Compromise -- a piece of evidence such as an IP address, domain, URL, file hash, or CVE ID -- Common Vulnerabilities and Exposures, a public catalog number for a known software vulnerability -- that a security analyst wants to look up).

## The AI summary says "Unknown" and every risk score reads 0

**What you'll see:** instead of a verdict like "malicious" or "benign," the final assessment reads "Unknown," the risk and confidence scores are both 0, and a note explains that AI summarization was unavailable.

**What it means:** the AI model the platform uses to summarize and correlate results (by default, a local model) could not be reached. Rather than guess and present a verdict it can't actually support, the platform is designed to report that failure honestly. During testing, this exact scenario was deliberately created by making the AI backend unreachable: every AI-dependent field correctly reported the failure instead of pretending to succeed, and every provider's own raw data (VirusTotal, AbuseIPDB, WHOIS, and so on) remained untouched and just as trustworthy as always -- only the AI-generated synthesis was affected. Restoring the connection to the AI backend and restarting immediately brought full AI functionality back on the next investigation.

**What to do:** re-run the Configuration shortcut to confirm the AI backend setting, verify the AI model/service it points to is reachable, and try the investigation again.

**A related point, even when the AI is healthy:** an "Unknown" verdict from an unreachable AI is a different situation from providers genuinely disagreeing with each other -- which the AI is designed to surface, not hide. Elsewhere in this guide, the IOC `8.8.8.8` is a real example where one provider (Spamhaus) flagged it malicious while two others (AbuseIPDB and VirusTotal) called it clean, and the AI's own summary spelled out that disagreement rather than silently picking a side. In every case, the AI's output is analytical assistance, not the final word -- every claim it makes can be checked against the underlying facts it was built from in the investigation's Evidence Ledger ("Show receipts"), rather than accepted on trust alone.

## The page shows a real error, or an investigation won't load at all

**What it means:** this is consistent with a database outage. When the platform's database was deliberately stopped mid-request during testing, the result was a clear, fully logged error -- not a silent failure, a crash, or corrupted data. Restarting the database restored full functionality immediately, and previously saved cases and Basket entries were confirmed completely intact afterward.

**What to do:** use the Restart Platform shortcut (or Diagnostics, if you want more detail first), then try again. Your previously saved data is not at risk from this kind of outage.

## A repeat lookup on the same IOC comes back noticeably faster

This is expected behavior, not a bug. Each provider's result is cached for up to an hour after it's first fetched, so looking up the same IOC again within that hour reuses the already-fetched provider data instead of re-querying every source from scratch. After that hour passes, the next lookup fetches fresh data again.

## One provider card shows "Not Configured," "Error," or "Rate Limited" while others show real results

This is normal and expected, not a malfunction. Each provider's status is reported honestly and independently: a provider you haven't set up a key for shows "Not Configured," a provider that genuinely failed to respond shows "Error," and a provider that has temporarily hit its own free-tier limit shows "Rate Limited." None of these ever get mislabeled as one another, and -- just as importantly -- one provider having a problem never blocks the rest of the investigation from completing.

## You closed the browser tab or lost your connection partway through an investigation

Provider results that had already come back before the disconnect are saved, not lost. Revisiting the investigation afterward shows every provider result that had completed up to that point, even though the investigation itself may show as failed if it didn't finish.

## Clicking "Export PDF" or "Export CSV" doesn't produce a file

[FIGURE: 21-investigation-export-menu.png | The Export menu offers PDF, Markdown, CSV, and JSON, but clicking Export PDF or Export CSV shows the honest message "Export format not yet available" instead of producing a file.]

This is a known, honest limitation, not a bug to work around: PDF and CSV export are not yet available in this release. Rather than fail silently or crash, the platform tells you so directly with the message shown above. **Export JSON and Export Markdown both work today** and are the way to get an investigation's results out of the platform in the meantime.

## You typed something and got "Could not determine IOC type"

This means the value entered didn't match any of the IOC formats the platform recognizes (IP address, domain, URL, file hash, CVE ID, and others). This is a deliberate, clean rejection with a clear message, not a crash -- double-check the value for typos and try again.
