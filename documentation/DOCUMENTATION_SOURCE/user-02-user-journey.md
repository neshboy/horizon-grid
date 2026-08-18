# The User Journey

An orientation map, not a manual: what a session with HORIZON GRID looks like end to end, from one-time setup through a routine day of investigating indicators.

## Setup, Once

An admin installs the platform via the Windows installer, then runs a setup wizard collecting an administrator account, an AI backend choice, and API keys for whichever threat-intelligence providers are available. After that, day-to-day use is just opening a browser tab.

Signed in, an analyst sees the home page: a single search box, ready for the first IOC (Indicator of Compromise — an IP, domain, URL, file hash, or CVE ID — a Common Vulnerabilities and Exposures identifier for a known software vulnerability — worth investigating).

[FIGURE: 16-dashboard-logged-in.png | The platform's home page after signing in — a single search box ready to accept an IOC.]

From here, the new **Dashboard** entry in the global navigation is a natural first stop too, before diving into a specific IOC — an at-a-glance operational view of active investigations, case load, provider health, and AI reliability across the whole team.

## The Daily Loop: Submit an Indicator, Watch Evidence Arrive

This is the core workflow, repeated many times a day. The analyst types or pastes an IOC and submits it. The platform classifies the indicator type and queries every configured provider that supports it in parallel, not one after another — results stream in as each finishes. As each result arrives, the AI briefly summarizes that provider's own findings; once all providers report in, one consolidated AI call produces a Final Assessment: a verdict, a risk score, and a plain-language summary weighing everything together.

[FIGURE: 17-investigation-benign-ip-result.png | A lookup of 8.8.8.8 (Google's public DNS resolver) mid-flight, with provider verdict cards arriving in parallel — Spamhaus flags it malicious over an unrelated DNS-policy reason, while AbuseIPDB shows it clean with zero abuse reports.]

## Reading the AI's Summary — and Verifying It

The AI summary is a fast way to orient, not a verdict to accept blindly — providers genuinely disagree, and the AI's job is to weigh that disagreement, not hide it. The 8.8.8.8 case above is a real example: Spamhaus calls the address malicious (it rejects lookups from public resolvers, unrelated to actual malice), while AbuseIPDB and VirusTotal both call it clean, and the Final Assessment says so explicitly. This is why every investigation includes an Evidence Ledger — non-AI-generated facts with confidence scores. When a claim looks surprising, the analyst opens the ledger and checks it against the real provider data before trusting it.

[FIGURE: 18-investigation-benign-ip-full.png | The full 8.8.8.8 investigation page, with the Final Assessment's summary alongside the Evidence Ledger and Relationship Graph used to check any claim against the underlying evidence.]

## Following the Trail, Then Keeping Track

The Relationship Graph shows indicators connected to the one just searched — for 8.8.8.8, its parent ASN (Autonomous System Number) — letting the analyst pivot onward without a fresh search. Interesting IOCs go into the IOC Basket, a running list serving the purpose of a personal watchlist, or get attached to a Case with analyst notes when tied to a specific incident.

## Taking Findings Elsewhere

Investigations export cleanly as JSON or Markdown today. PDF and CSV buttons exist but return an honest "Export format not yet available" message — a known gap, not a hidden failure.
