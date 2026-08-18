# HORIZON GRID — Quick Start Guide

This guide assumes you have never installed, configured, or used a threat-intelligence tool before. Every term gets explained the first time it comes up, and every step tells you exactly what to click. By the end, you will have installed HORIZON GRID, configured two real intelligence providers and an AI backend, run your first investigation, and know how to read what it tells you — including the one distinction that trips up almost everyone the first time (threat score and confidence are **not** the same number, and they don't mean the same thing).

If you want the deeper mechanics behind any step here — every Setup Wizard page, system requirements, upgrading, uninstalling — see the **Windows Installation** guide. This document is deliberately the short version.

## Step 1: Install HORIZON GRID

Three things, in order:

1. Make sure **Docker Desktop** is installed and running on your Windows machine first. HORIZON GRID's real services (its database, its web server, and a few supporting background processes) run inside Docker containers, not as ordinary Windows programs — Docker Desktop is what makes those containers run at all. If it isn't installed and running, the installer will tell you before it lets you continue.
2. Run the installer (`HORIZON-GRID-Setup-<version>.exe`) **as an administrator**. Click through the destination folder, optional desktop icon, and "Ready to Install" pages, then let it copy files.
3. When the installer finishes, leave the "Launch the setup wizard now" box checked. This hands off to a second program — the **Setup Wizard** — which is where you'll create your administrator account, and which finishes the job of actually starting the platform.

[FIGURE: 04-installer-finished.png | The installer's final "Completing Setup" screen, with the box checked to launch the Setup Wizard immediately afterward.]

## Step 2: Launch — The Setup Wizard Does the Rest

The Setup Wizard walks you through a fixed sequence of pages: Welcome, Administrator Account, AI Configuration, Threat Intelligence Providers, Network Ports, and a final Ready to Install summary. For this quick start, the important thing to know is that you don't have to get everything right here — every choice on every one of these pages can be changed later from inside the app itself or by re-running the wizard from the **Configuration** shortcut. So it's fine to click through the Administrator Account page (this is the one page that matters most — it's covered in Step 5 below) and accept the defaults everywhere else; Steps 6 and 7 of this guide show you how to configure your first provider and AI backend from inside the running app, which works identically whether you filled anything in here or not.

Once you click "Start Installation" on the summary page, the wizard downloads and starts everything the platform needs. This can take several minutes the first time — it's pulling down real software components, not just copying a few files.

[FIGURE: standalone-wizard-finish.png | The Setup Wizard's "Setup Complete" page, showing the local address to open the platform on this computer and, if detected, a second address for other devices on the same network.]

## Step 3: What "localhost," Ports, and "Frontend vs. Backend" Actually Mean

Before you open a browser, it's worth understanding three words you're about to see, because they'll come up constantly:

- **localhost** just means "this computer, right now" — it's a special address every computer understands to mean itself, so typing `localhost` into a browser on the machine running HORIZON GRID always reaches it, with no network setup required.
- A **port** is like a numbered door on the same building (your computer). One program can be listening on door 3000, a completely different program on door 8000, and they never get confused with each other, because they're each answering only their own door. When you see an address like `http://localhost:3000`, you're saying "this computer, door 3000."
- HORIZON GRID is actually two separate programs working together, each behind its own door. The **frontend**, on port `3000`, is the website you actually look at and click things in. The **backend**, on port `8000`, is a separate program the frontend quietly talks to behind the scenes to fetch data, run investigations, and so on — you'll rarely open this one directly yourself, except for a one-line health check covered in Step 13.

Behind those two, the platform also runs a handful of internal ports for its own database and supporting pieces (by default `5433`, `6379`, `7475`, `7688`, and `9200`). You will basically never need to know or type these — they're deliberately locked to "this computer only" and don't accept connections from anywhere else, unlike the frontend and backend ports, which (if your network is set to "Private" in Windows) other devices on your home or office network can genuinely reach too. The exact numbers are configurable during setup if something else on your machine is already using one of them, but the ones above are what a fresh install actually uses.

[FIGURE: quickstart-ports-diagram.png | Diagram: your browser talking to the frontend on port 3000, the frontend talking to the backend on port 8000, and the backend talking to its own database and supporting services on internal, locked-down ports that nothing outside this computer can reach.]

## Step 4: Open the Platform in Your Browser

Open any web browser on the same computer and go to:

```
http://localhost:3000
```

That's the address the Setup Wizard's final page showed you (Step 2's screenshot). Typing it in takes you straight to the sign-in page.

[FIGURE: quickstart-browser-address-bar.png | A browser's address bar with http://localhost:3000 entered, about to load the HORIZON GRID sign-in page.]

## Step 5: Log In

Sign in with the administrator email and password you set on the Setup Wizard's Administrator Account page. There's no separate "create an account" step to do here — the wizard already registered that account for you as part of finishing installation, and on a brand-new install, whoever's account that was automatically became the administrator.

[FIGURE: 15-login.png | The Sign in page — enter the administrator email and password you set during the Setup Wizard.]

One thing worth knowing for later: HORIZON GRID only lets the very first account on a fresh install register itself this way. If a colleague needs an account after that, you (the administrator) create it for them from the Administration page and pick their role at that point — they can't just sign themselves up.

## Step 6: Configure Your First Providers

A **provider**, in HORIZON GRID, is any outside source the platform can ask about an indicator — a malware database, a government vulnerability catalog, a DNS blocklist, and so on. Out of the box, several of the platform's 18 built-in providers need absolutely nothing from you and are already switched on; others need a free (or paid) API key from that service before they'll return anything. Let's configure one of each, so you can see both patterns.

Sign in as the administrator, then open **Providers** in the top navigation, and select the **IOC Providers** tab.

[FIGURE: 34-manage-providers-ioc-tab.png | The IOC Providers tab, listing all 18 registered providers with their real configured/enabled status.]

**The easy case — a provider that needs no key at all.** Find **crt.sh** (or **Spamhaus**) in the list. You'll notice it already shows as configured/enabled with nothing typed in anywhere — that's expected, not a mistake. crt.sh searches public Certificate Transparency logs (a public, tamper-evident record every trusted website certificate gets logged into), and Spamhaus is a DNS-based blocklist checked with a plain DNS query — neither one requires an account or a key to use, so there's genuinely nothing to configure. All you can do here is confirm it's enabled.

[FIGURE: quickstart-spamhaus-no-key-toggle.png | The Spamhaus row expanded, showing only an Enable/Disable toggle and no credential field at all — this provider needs no key to work.]

**The realistic case — a provider that needs a key.** Find **VirusTotal** and expand its row. VirusTotal is a well-known multi-engine file/URL scanner; to use it, you need a free account at virustotal.com and the API key from your account's profile page. Paste that key into the field (it displays as masked dots once saved, the same way a password field would), then click **Test Connection**. A working key reports back a real, genuine success message from VirusTotal's own service — not a placeholder checkmark. Click **Save** once the test passes.

[FIGURE: quickstart-virustotal-key-entry.png | The VirusTotal row expanded for editing, with an API key entered (shown masked) and the Test Connection / Save controls visible.]

You don't need to configure all 18 providers to get useful results — the platform works correctly with any subset configured, including just these two. Every future investigation automatically uses whichever providers are enabled and relevant to the type of indicator you submit.

## Step 7: Configure an AI Backend

Every investigation ends with an AI-written explanation of what was found. HORIZON GRID supports five interchangeable AI backends, and you pick one from the same **Providers** page, under the **AI Providers** tab.

[FIGURE: 32-manage-providers-ai-tab.png | The AI Providers tab, listing each of the five supported AI backends with its live configured/active status.]

For a genuinely zero-cost way to get started, expand **Ollama**. This runs a small AI model entirely on your own machine — no account, no API key, no per-request cost, and nothing about your investigations ever leaves this computer for the AI step. Click **Test Connection** to confirm it responds, then **Set Active** to make it the backend used for your next investigation. (If you'd rather use a larger, more capable hosted model instead, Anthropic, AWS Bedrock, Google Gemini, and Groq are all supported the same way — each just needs its own API key. You can switch between any of these at any time later with no restart, so this choice is never permanent.)

[FIGURE: 33-manage-providers-ai-edit-masked.png | An AI backend's row expanded for editing, showing the masked API key field, the model field, and the Test Connection / Save / Set Active controls.]

## Step 8: Run Your First Investigation

You're ready. Go to the platform's home page, and type an IOC — an **Indicator of Compromise**, meaning a specific piece of evidence like an IP address, domain, URL, file hash, or CVE ID — into the search box. For this first run, use:

```
8.8.8.8
```

This is Google's public DNS resolver — a real, well-known, entirely legitimate internet service, and a genuinely useful first example precisely because, as you'll see in the next step, not every provider will agree it's harmless. (If you'd rather try a domain name instead, `google.com` works too — the platform automatically detects what kind of indicator you typed before deciding which providers to query.)

[FIGURE: 40-ioc-input-typed-ollama-selected.png | 8.8.8.8 typed into the home page search box, ready to submit — the "AI:" selector next to it shows which backend will analyze this investigation.]

Click submit. The platform detects the indicator type, queries every provider you've enabled that supports IP addresses, and starts streaming results back to the page within seconds — you don't need to refresh anything.

## Step 9: Read the Provider Results

As each provider finishes, a card appears with that provider's own verdict. Watch for exactly this kind of pattern, because it's real and it's instructive: **Spamhaus** may show a verdict of malicious — but if you read the reason it gives, it's a query-permission error ("public/open resolver not permitted to query Spamhaus"), not an actual detection of anything harmful. Meanwhile **AbuseIPDB** shows zero abuse reports, and **VirusTotal** reports it clean.

[FIGURE: 17-investigation-benign-ip-result.png | Provider result cards arriving live for 8.8.8.8 — Spamhaus flags it malicious for an unrelated DNS-policy reason, while AbuseIPDB and VirusTotal both report it clean.]

This is the single most important habit to build on day one: **a provider's verdict label is not the whole story — read the reason underneath it.** Providers disagreeing with each other is normal, expected behavior, not a bug, and it's exactly why the next two steps matter so much.

## Step 10: Threat Score and Confidence Are Two Different Questions

Once every provider has reported in, the page shows a **Threat Score** — a single number from 0 to 100 with a plain-language severity label (none/low/medium/high/critical) — and, right next to it, a separate **Confidence** percentage. It is genuinely easy to assume these are the same kind of number measured twice. They are not, and mixing them up is the single most common misreading of this platform.

- **Threat Score** asks: *how malicious does the evidence look?* It's built from two things added together — how much the providers that responded actually agree the indicator is bad, and any malicious-looking relationships the correlation engine found (shared malware families, MITRE ATT&CK techniques, exploited CVEs). One provider flagging something, with nobody else agreeing, only ever pulls this number up a limited amount on its own — it takes several independent providers agreeing to push it toward its maximum.
- **Confidence** asks a completely different question: *how much should you trust that score?* This number is calculated from how much the providers agreed with **each other** — not from how bad the finding looks. If your providers all point the same direction, confidence stays high. If they're split — exactly like the 8.8.8.8 example above, where Spamhaus disagrees with AbuseIPDB and VirusTotal — confidence drops, specifically *because* of that disagreement, even if the Threat Score itself is still sitting at a moderate or high number.

So a real, correct result can legitimately look like "Threat Score: high, Confidence: low" — and that combination means exactly what it sounds like: *the evidence leans toward malicious, but it's thin or conflicted, so verify it yourself before treating it as settled.* It is not the platform contradicting itself. For the exact formula behind both numbers, including a real worked example with the underlying arithmetic, see the **Threat Scoring** guide.

[FIGURE: quickstart-threat-score-confidence.png | The Threat Score gauge (0-100, with a Severity label) shown next to the separate Confidence percentage on the same investigation — two different numbers answering two different questions.]

## Step 11: Read the AI's Assessment

Scroll down to the **Final Assessment** section. This is the AI's consolidated read on the whole investigation, written only after every provider has reported back — and for a case like 8.8.8.8, a good AI assessment will say so directly: something to the effect of "considered malicious by Spamhaus, but its reputation as clean is supported by AbuseIPDB and VirusTotal," rather than quietly picking a side. Every Final Assessment also carries a small badge naming exactly which AI backend and model produced it (for example, `ollama / llama3.2:3b`), so you always know what generated a given explanation.

Don't stop at the prose, though. The same page includes an **Evidence Ledger** — a plain list of the concrete, individually-numbered facts the AI's explanation is supposed to be traceable back to — plus a set of tools built specifically so you don't have to just trust the summary: **"Why?"** (asks the AI to justify the verdict against real evidence), **"Challenge This Verdict"** (asks the AI to argue against its own conclusion), and **"False Positive Check."** Get in the habit of using at least one of these on your first few investigations until the pattern feels familiar.

[FIGURE: 18-investigation-benign-ip-full.png | The full investigation page for 8.8.8.8: the Final Assessment's Executive Summary explaining the Spamhaus-vs-AbuseIPDB/VirusTotal disagreement, alongside the Evidence Ledger and Verdict Analysis tools.]

## Step 12: Export Your First Report

In the sidebar of the investigation page, open the export controls. You'll see four buttons: **Export JSON**, **Export Markdown**, **Export CSV**, and **Export PDF** — all four produce a real downloaded file today, built from the same investigation you're looking at on screen, and the CSV/PDF paths carry real, tested protections against a malicious value trying to smuggle a spreadsheet formula or injected markup into the exported file. Pick Markdown if you want something readable to paste into a ticket or a chat message, or JSON if you want the structured data for another tool.

[FIGURE: 21-investigation-export-menu.png | The export sidebar on a completed investigation page, showing all four working export buttons: JSON, Markdown, CSV, and PDF.]

One role-related note for later, once you're not the only user: PDF and CSV export require a specific permission that Admin and Analyst accounts have but a Viewer account does not — a Viewer can still export Markdown or JSON (those build locally in the browser with no permission check) but gets blocked specifically on PDF/CSV.

## Step 13: Check Provider Health

Now that you've run at least one real investigation, open **Provider Health** in the top navigation (under the Operations group). This page answers a different question than any single investigation does: *is every provider actually working right now, across the whole platform, not just in this one lookup?* Each row shows status — Healthy, Degraded, Down, or Unknown — across four separate time windows (1 hour, 24 hours, 7 days, 30 days), built from real, database-backed outcomes of every call that provider has actually made.

One honest guarantee worth knowing up front: a provider you haven't exercised yet in a given window always shows **Unknown**, never **Healthy** — silence isn't evidence of health. And a provider that correctly reports "nothing found" for a given indicator (which is normal — no single provider's dataset covers every indicator) counts as a healthy, successful outcome, not a failure.

[FIGURE: dashboard-provider-health.png | The Provider Health page, showing real per-provider status across four time windows, with Healthy/Degraded/Down/Unknown always paired with a distinct icon and label, not color alone.]

You can also check the backend by itself is up, at any time, without logging in at all, by opening `http://localhost:8000/health` directly in a browser — it returns a short, raw reply like `{"status":"ok","service":"HORIZON GRID"}`.

## Step 14: The Executive Dashboard

Finally, open **Dashboard** in the top navigation (the Command group) — this is the "one operational picture" the platform is built around. It shows seven live numbers at a glance: active investigations, critical/high-risk IOC count, open cases and open critical cases (as two separate numbers), average threat score, provider health percentage, and AI success rate over the last 30 days — every single one computed live from the real database, never hardcoded. Next to the tiles, an Executive Summary card gives you a short AI-written narrative explaining what those numbers mean; if the AI backend is unreachable when the page loads, this card honestly falls back to a plain, number-accurate template sentence instead, and tells you which one you're looking at with an "AI-generated" or "Template fallback" badge.

[FIGURE: dashboard-executive-overview.png | The Executive Dashboard: seven live KPI tiles, the labeled AI-generated (or template-fallback) executive summary, and a compact provider-health widget linking through to the full Provider Health page.]

## Where to Go Next

You've now installed the platform, configured a no-key provider and a key-required provider, picked an AI backend, run and read a real investigation, exported it, and checked both the provider fleet's health and the platform-wide dashboard. From here:

- The **User Manual** covers everything on an investigation page in full depth — cases, the IOC Basket, the Relationship Graph, and the Security Assessment Toolkit's active checks.
- The **Provider Guide** covers all 18 built-in providers in detail, including exactly what each one checks and returns.
- The **AI Guide** and **Threat Scoring** guide go deep on, respectively, how the AI layer is grounded against fabrication and the exact math behind the Threat Score and Confidence numbers introduced in Step 10.
- The **Admin Guide** covers creating accounts for colleagues, choosing their roles, and everything else an administrator does beyond first-run setup.
