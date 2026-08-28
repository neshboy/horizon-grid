# IOC Investigation

This is the core of the product: you give it one IOC, and it tells you — with receipts — what dozens of threat-intelligence sources and an AI model think about it.

## Table of Contents

- [❓ What Is an IOC?](#-what-is-an-ioc)
- [🔎 Starting an Investigation](#-starting-an-investigation)
- [🧬 Anatomy of a Real Investigation: 8.8.8.8](#-anatomy-of-a-real-investigation-8888)
  - [The First Few Seconds](#the-first-few-seconds)
  - [The Full Picture](#the-full-picture)
- [⚠️ Why You Must Read the Evidence, Not Just the Score](#️-why-you-must-read-the-evidence-not-just-the-score)
- [📋 Supported IOC Types](#-supported-ioc-types)
- [🛡️ Security Assessment: Active Checks Against the Target](#️-security-assessment-active-checks-against-the-target)
  - [What a port scan actually does](#what-a-port-scan-actually-does)
  - [Scan statuses](#scan-statuses)
  - [Cancelling a scan](#cancelling-a-scan)
  - [If a tool shows as "unavailable"](#if-a-tool-shows-as-unavailable)

## ❓ What Is an IOC?

**IOC (Indicator of Compromise)** — a piece of evidence such as an IP address, a domain name, a URL, a file hash, or a **CVE** (Common Vulnerabilities and Exposures — a public catalog ID for a known software vulnerability, e.g. `CVE-2021-44228`) that a security analyst wants to investigate. An IOC by itself doesn't prove anything is wrong; it's a lead. Maybe it showed up in a firewall log, an email attachment, or a colleague's incident notes. The question an analyst always has to answer is: *is this thing actually dangerous, and what do I know about it?*

HORIZON GRID exists to answer that question fast, by querying many independent, real third-party sources at once, correlating what they say, and having an AI model summarize the result — while still giving you everything you need to check the AI's work yourself.

## 🔎 Starting an Investigation

There are two ways to kick off a lookup:

- **Type the IOC into the search box** on the platform's home page and submit it. You can paste in an IP address, a domain, a URL, a file hash, a CVE ID, or any of the other supported types (see the list at the end of this section) — the platform automatically detects what kind of IOC you gave it before it decides which providers to query.
- **Click one of the suggested example IOCs** offered on the same page. This drops that value straight into the search box for you — submit it the same way you would your own IOC. It's the fastest way to see the platform in action before you commit a real indicator from your own environment, and once submitted it runs an actual, live lookup, not a canned demo.

[FIGURE: 40-ioc-input-typed-ollama-selected.png | An IP address typed into the home page search box, ready to submit — the "AI:" selector alongside it shows which backend will analyze this investigation once submitted.]

Once you submit an IOC, the platform fans out to every configured provider that supports that IOC type at the same time (not one after another), so results stream back into the page within seconds rather than making you wait for the slowest source.

## 🧬 Anatomy of a Real Investigation: 8.8.8.8

To show what an investigation actually looks like, walk through a real one: the IOC `8.8.8.8` — the IPv4 address of Google's Public DNS resolver, a well-known, legitimate internet service used by billions of devices. It's a genuinely interesting example, because the sources don't fully agree with each other — and that disagreement is exactly the kind of thing an analyst needs to know how to read.

### The First Few Seconds

[FIGURE: 17-investigation-benign-ip-result.png | Seconds after submitting 8.8.8.8, the investigation page fills in live: a Threat Score gauge, a Provider Progress list, and individual result cards from Spamhaus, AbuseIPDB, and WHOIS/RDAP.]

This compact view appears almost immediately and updates as more providers respond:

- **Threat Score gauge** — a single 0–100 number with a plain-language severity label. In this investigation it reads **87/100, "High."** This number is the platform's aggregated read on the IOC once results start coming in; it is a starting signal, not a final judgment — hold that thought, because this exact example is about to show why.
- **Provider Progress list** — a running checklist of every provider the platform queried for this IOC type, ticking off as each one finishes. Because providers are queried concurrently, you see them complete in whatever order they actually respond, not a fixed sequence.
- **Per-provider result cards** — one card per source, each showing that provider's own verdict and supporting detail:
  - **Spamhaus DBL/ZEN** shows verdict **malicious**, with a reason string attached: *"query error – public/open resolver not permitted to query Spamhaus."*
  - **AbuseIPDB** shows verdict **clean**, with **0 abuse reports** on file.
  - **WHOIS/RDAP** shows registration/network ownership data for the address (who the IP block is allocated to).

Already, two cards disagree with each other. Keep reading — the full page explains why, and it isn't a bug.

### The Full Picture

[FIGURE: 18-investigation-benign-ip-full.png | The complete 8.8.8.8 investigation page: additional provider cards, Final Assessment tabs, a two-node Relationship Graph, MITRE ATT&CK Matrix, Detection Rules, Recommended Actions, Verdict Analysis tools, an 11-item Evidence Ledger, Pivot, Threat Hunting Center, and an Investigation Copilot chat box.]

Scroll down (or wait for later providers to finish) and the rest of the investigation appears:

- **More provider cards**: **VirusTotal** reports **clean**; the **Internet Intelligence Collector** (the platform's own OSINT — open-source intelligence, meaning publicly available, non-classified sources — crawler, pulling from sources like GitHub, Reddit, RSS feeds, and paste sites) reports its findings; **Censys** shows **"Not Configured"** — meaning that particular provider needs API credentials entered before it will run at all, not that it looked and found nothing.
- **Final Assessment tabs** — the AI's consolidated read on the whole investigation, written only after every provider has reported back. For 8.8.8.8, the **Executive Summary** tab states, in effect, that the IP "is considered malicious by Spamhaus, but its reputation as a clean and safe IP address is supported by AbuseIPDB and VirusTotal." The AI is not hiding the disagreement — it's telling you about it directly.
- **Relationship Graph** — a visual map of what this IOC connects to. Here it's simple: two nodes, `8.8.8.8` and its owning network, **ASN 15169** (Google's autonomous system number). On IOCs with more history, this graph can grow to show shared infrastructure, related files, or campaigns.
- **MITRE ATT&CK Matrix** — MITRE ATT&CK is an industry-standard catalog of known attacker tactics and techniques. This tab highlights any techniques the investigation's evidence actually supports. For 8.8.8.8 it correctly reads **"No MITRE ATT&CK techniques identified"** — there's nothing here to map to attacker behavior.
- **Detection Rules** — a tab that can generate ready-to-use detection logic (for a SIEM — Security Information and Event Management system, the kind of tool a SOC uses to watch for threats — or similar tool) when the evidence supports it. For this IOC it reads **"No detection logic generated for this IOC type"** — again, appropriately, since there's no malicious behavior to write a detection rule against.
- **Recommended Actions** — AI-suggested next steps for the analyst, grounded in what was actually found.
- **Verdict Analysis tools** — this is the toolbox that exists specifically so you don't have to just trust the Threat Score number. Each tab lets you interrogate the AI's own conclusion:
  - **Why?** — asks the AI to justify its verdict, citing the actual evidence behind it.
  - **What's this?** — a plain-language explanation of what the IOC is.
  - **Score Explanation** — breaks down how the numeric score was arrived at.
  - **Intelligence Conflicts** — specifically surfaces where providers disagree with each other (exactly the Spamhaus-vs-AbuseIPDB/VirusTotal situation in this example).
  - **False Positive Check** — asks the AI to assess how likely it is that the flagged verdict is wrong.
  - **Challenge This Verdict** — a deliberate red-team tool: it asks the AI to argue *against* its own conclusion, rather than defend it.
- **Evidence Ledger** — for this investigation, **11 items**, each with its own confidence percentage. This list is built directly and deterministically from the real provider data and correlation results — it is explicitly not itself written by the AI. That's the point: it exists so every claim the AI makes elsewhere on the page can be checked against a real, traceable record rather than taken on faith.
- **Pivot** — lets you jump from this IOC to a related one (for example, the ASN) to start a fresh investigation from something this one turned up.
- **Threat Hunting Center** — generates hunting queries or leads an analyst could run in their own environment, built only from indicators actually present in this investigation's evidence.
- **Investigation Copilot** — a chat box for asking follow-up questions about this specific investigation. Its answers are grounded in this lookup's own evidence rather than general knowledge, and unsupported citations get filtered out before you see them.

## ⚠️ Why You Must Read the Evidence, Not Just the Score

This 8.8.8.8 example is worth sitting with, because it's a genuine, non-staged illustration of the platform's most important lesson: **a single verdict number is a summary, not a substitute for reading the evidence.**

Here's what actually happened. Spamhaus operates a DNSBL (a DNS-based block list) — a lookup service you query to ask "is this IP known to be bad?" That service refuses to answer queries that come from public, open DNS resolvers, as an anti-abuse measure protecting its own infrastructure. 8.8.8.8 *is* exactly that kind of public resolver — it's Google's own open DNS service. So when the platform queried Spamhaus about it, Spamhaus didn't report finding malicious activity at all; it rejected the query itself, with the reason "query error – public/open resolver not permitted to query Spamhaus." The platform recorded that rejection as a **malicious** verdict card, because that's the status Spamhaus returned — but the underlying reason has nothing to do with 8.8.8.8 doing anything harmful.

Meanwhile, AbuseIPDB checked its abuse-report database and found zero reports. VirusTotal checked its own reputation data and came back clean. Two independent, purpose-built sources say this address is clean; one source's result is actually a permission error dressed up as a verdict.

Notice, too, that the Threat Score gauge on the first screen still read **87/100, "High"** — pulled up by that one Spamhaus flag — even though the fuller picture tells a different story. That's not a flaw the product is hiding: it's precisely why the Executive Summary text spells out the disagreement in plain words rather than quietly averaging it away, and why tools like **Intelligence Conflicts** and **Challenge This Verdict** exist on the same page. The AI's output here is analytical assistance — a fast, well-organized starting point — not an unquestionable ruling. An analyst who stopped at the gauge would walk away thinking Google's DNS resolver is a threat. An analyst who reads the provider cards, the Executive Summary, and the Evidence Ledger sees the real picture in under a minute.

## 📋 Supported IOC Types

The platform automatically detects what kind of IOC you've submitted and routes it only to the providers that support that type. Types with dedicated provider coverage include:

- **IP addresses** (IPv4 and IPv6)
- **Domains** and **hostnames**
- **URLs**
- **File hashes** (MD5, SHA-1, SHA-256, SHA-512)
- **CVE identifiers** (e.g. `CVE-2021-44228`)
- **MITRE ATT&CK techniques**
- **TLS/SSL certificates**
- **Autonomous System Numbers (ASN)**
- **Malware family names**
- **Threat actor names**
- **Campaign names**
- **File names**

This is not an exhaustive list of every type the platform can classify internally, but it covers the types you'll actually get provider results back for.

## 🛡️ Security Assessment: Active Checks Against the Target

Every provider covered so far is **passive** — it asks a third party what they already know about your indicator. Once an investigation completes for an IP, domain, hostname, or URL, a **Security Assessment** panel appears further down the page offering a genuinely different kind of check: sending real traffic to the target itself. Four checks are available — a Nmap port/service scan, a DNS record lookup, a TLS certificate inspection, and an HTTP security-header check — each described in plain language when you select it.

> [!WARNING]
> This never happens automatically. Unlike every passive provider, a security assessment is something you must deliberately start, and the platform requires two explicit confirmations before it will run anything:
>
> 1. **Retype the exact target** in the confirmation box — this is a safeguard against accidentally scanning the wrong thing.
> 2. **Check the authorization box**, confirming you're actually allowed to run active checks against this target. Only scan systems you own or have explicit permission to test.

[FIGURE: 45-security-assessment-panel.png | The Security Assessment panel: tool selection, the target-confirmation box, and the authorization checkbox.]

Once you start a run, results appear in a findings table with a severity badge on each row (from informational up to critical) — severities are assigned by fixed, documented rules based on what was actually found (e.g. an expired certificate, or an open port running software with a known vulnerability), never guessed. Click any finding to see exactly what was observed.

[FIGURE: 46-security-assessment-run-completed.png | A completed run's findings table, including a real port-scan result with a matched CVE.]

[FIGURE: 47-security-assessment-finding-drilldown.png | Clicking a finding opens its full detail: the matched CVEs and the raw evidence the severity was based on.]

A completed run's findings feed back into the same investigation — the AI-generated assessment, risk score, and verdict at the top of the page are refreshed to account for what the security assessment found, exactly as if a new provider had reported in.

### What a port scan actually does

The Nmap port/service scan is the only one of the four checks that has more than one option — a **profile** you pick before running it:

- **Quick scan** — the 100 most common ports, no service/version detection. Fastest, lowest footprint.
- **Standard scan** (the default) — the 1,000 most common ports, *with* service/version detection (identifying what software is actually answering on an open port, e.g. "Uvicorn" or "nginx"). Slower than Quick, but far more informative — a service/version match is what lets the platform cross-reference known CVEs against it.
- **Web service scan** — only the common web ports (80, 443, 8080, 8443), with service/version detection. The fastest way to check specifically web-facing exposure.

A port only ever shows up in the findings table if it's genuinely **open**. Closed and filtered ports are not reported as findings at all — they're the expected, uninteresting majority of any scan, not evidence of anything.

> [!NOTE]
> If a scan completes and the findings table is empty, that means every port it checked came back closed or filtered — a real, successful result, not a failure. A failed scan looks different: the run's status badge itself shows "failed" (in red) with an explanatory error message underneath, not an empty table with no explanation.

### Scan statuses

A run moves through a small set of statuses, shown as a colored badge:

| Status | Meaning |
|---|---|
| Pending | Accepted, waiting to start. Usually only visible for a moment. |
| Running | Actively in progress. The page checks for updates automatically every 2 seconds — no need to refresh. |
| Completed | Finished normally. Check the findings table (which may legitimately be empty — see above). |
| Failed | Something went wrong before a result could be produced (e.g. the scanner isn't installed on this deployment, or the target couldn't be reached). The specific reason is shown under the badge. |
| Cancelled | You (or another analyst — findings and runs are visible to your whole team, not private to whoever started them) stopped the scan before it finished. |

### Cancelling a scan

A **Cancel Scan** button appears next to any run that's still Pending or Running. Clicking it stops the scan immediately — including the real underlying scan process, not just the page's display of it — and the run's status changes to Cancelled. This is useful if you started the wrong profile by mistake, or a scan against a large/slow target is taking longer than you want to wait. A cancelled scan can simply be started again with different settings; nothing about the investigation itself is affected.

### If a tool shows as "unavailable"

Each tool button in the panel is disabled with an "(unavailable)" label if that specific check isn't currently usable on this deployment — hovering over it explains why. For the Nmap port scanner specifically, this means the `nmap` program isn't present on the machine actually running the backend. On the standard Windows and Linux installations of this platform, `nmap` is installed automatically as part of the backend container and should never need any manual setup; seeing "unavailable" on a standard install is itself worth reporting, not something to work around.
