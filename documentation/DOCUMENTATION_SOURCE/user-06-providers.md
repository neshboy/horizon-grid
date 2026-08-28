# 🔌 Intelligence Providers

## Table of Contents

- [❓ What Is a "Provider," Exactly?](#-what-is-a-provider-exactly)
- [🦠 Malware, IP, and URL Reputation Providers](#-malware-ip-and-url-reputation-providers)
- [🩹 Vulnerability Intelligence Providers](#-vulnerability-intelligence-providers)
- [🌐 Live Web / OSINT Intelligence](#-live-web--osint-intelligence)
- [⚔️ Attack Technique Reference](#️-attack-technique-reference)
- [📜 Domain, IP, and Certificate Registration Providers](#-domain-ip-and-certificate-registration-providers)
- [📋 All 18 Providers at a Glance](#-all-18-providers-at-a-glance)
- [🧮 Why the Setup Wizard Only Shows 8 Providers, Not 18](#-why-the-setup-wizard-only-shows-8-providers-not-18)
- [⚙️ Managing Providers From the App (No Restart)](#️-managing-providers-from-the-app-no-restart)
- [💬 A Note on Provider Disagreement](#-a-note-on-provider-disagreement)

## ❓ What Is a "Provider," Exactly?

Every time you look up an IOC (Indicator of Compromise — a piece of evidence such as an IP address, domain, URL, file hash, or CVE ID that a security analyst wants to investigate) in HORIZON GRID, the tool doesn't ask one source what it thinks. It asks many.

Each of those outside sources — a malware database, a government vulnerability catalog, a domain registration lookup, a live web crawler — is called a **provider**. A provider is simply a specialized service, database, or feed that knows something specific about the internet: who owns this IP address, has this file hash been seen in malware before, is this CVE (Common Vulnerabilities and Exposures — a standardized ID number for a publicly known security flaw, e.g. "CVE-2021-44228") actively being exploited right now, and so on.

The platform has **18 providers built in**. When you submit an IOC, it queries every provider that's relevant to that IOC's type — for example, a file hash won't be sent to a domain-registration lookup, but it will be sent to a malware-sample database — and streams each provider's answer back to you as it arrives, before combining everything into one assessment.

This section walks through what each of the 18 real providers is, in plain language: what it is, what kind of intelligence it supplies, why a SOC (Security Operations Center) analyst would care, and roughly what comes back.

## 🦠 Malware, IP, and URL Reputation Providers

These are the "has anyone seen this before, and was it bad?" sources — the closest thing to a criminal record check for an IP, domain, URL, or file.

- **VirusTotal** — A well-known, multi-engine file/URL scanning service: when you submit a hash, domain, IP, or URL, VirusTotal reports back what dozens of antivirus engines and URL scanners think of it. For a SOC analyst, this is one of the fastest ways to get a broad consensus opinion. What it returns: a detection ratio (e.g. how many engines out of how many flagged it as malicious), plus a verdict.

- **AbuseIPDB** — A community-driven database where network administrators and analysts report IP addresses that have attacked or abused them (brute-force logins, spam, port scanning, etc.). It only covers IP addresses. This is useful because it reflects real-world abuse reports rather than automated scanning alone. What it returns: an abuse-report count and a verdict (e.g. "clean, 0 reports").

- **AlienVault OTX (Open Threat Exchange)** — A large, community-contributed threat-intelligence exchange covering IPs, domains, hostnames, URLs, and file hashes. Analysts and vendors publish "pulses" describing malware campaigns, and OTX links IOCs to them. This is valuable for context: OTX can name the actual malware family or threat actor associated with an indicator, not just say "bad." What it returns: a verdict plus, when available, malware family names and threat-actor attributions.

- **URLhaus** — An abuse.ch project that tracks URLs actively distributing malware. It checks URLs, domains, and IPs. This is useful for catching live malware-hosting infrastructure specifically, rather than general reputation. What it returns: whether the URL/domain/IP appears in the malware-distribution database.

- **ThreatFox** — Another abuse.ch project, a shared IOC (Indicator of Compromise) database contributed to by the security community, covering IPs, domains, URLs, and MD5/SHA256 hashes. It's a good complement to URLhaus because it's broader than just distribution URLs. What it returns: a verdict, and often the associated malware family.

- **MalwareBazaar** — The third abuse.ch project, a repository of actual malware sample hashes (MD5, SHA1, SHA256, SHA512). If a file hash you're investigating shows up here, someone has already submitted that exact malicious file to the community. What it returns: a verdict and malware family/tag information for known samples.

- **Hybrid Analysis** — An online malware sandbox: files are actually executed in an isolated environment and their behavior is recorded. In this platform, it's used to check SHA256 hashes only (the connector's own documentation notes that hash-search-by-MD5/SHA1 and URL search are no longer supported by the underlying service). This is useful because it can reflect actual observed behavior, not just static signatures. What it returns: a verdict and summary from a prior sandbox run of that exact file, if one exists.

- **Spamhaus** — A long-established DNSBL (DNS-based blocklist) — a reputation list checked via a plain DNS query rather than a web API — covering IPs and domains, widely used across the email and network security industry to flag spam sources and malicious infrastructure. It's a fast, no-configuration check. What it returns: a verdict (listed / not listed), and sometimes a specific reason string from the lookup itself.

- **PhishTank** — A community-reported database of phishing URLs. Since phishing pages are often short-lived, having a dedicated, frequently updated phishing list matters. What it returns: whether the URL has been reported and confirmed as phishing.

- **urlscan.io** — Submits a URL or domain for a real, live sandbox scan rather than checking it against a pre-built database, then polls for the result (capped at 60 seconds). This is useful when you want to see what a page actually does right now, not just whether it was flagged before. It checks URLs and domains only. What it returns: a scan verdict once the sandbox run completes; a scan that isn't ready by the timeout is reported honestly as timed out, never as clean.

- **Google Safe Browsing** — Google's own URL/domain reputation check (the same list of malware and phishing threat types your web browser itself would normally warn you about), covering malware, social engineering, unwanted software, and potentially harmful applications. It checks URLs and domains only. What it returns: a verdict based on whether Google's own threat lists have a match — and, by design, absolutely nothing else (a failed check, a network error, or an unexpected response is always reported as unknown/error, never mistaken for "safe," specifically so a broken or misconfigured key can never look like a clean scan).

## 🩹 Vulnerability Intelligence Providers

These answer a different question: not "is this indicator bad," but "how serious is this known software vulnerability, and is it actually being used in the wild?"

- **NIST NVD (National Vulnerability Database)** — The U.S. government's official, authoritative catalog of publicly disclosed software vulnerabilities. Given a CVE ID, it returns the full vulnerability description and its CVSS (Common Vulnerability Scoring System) severity score. This is often an analyst's starting point for understanding what a vulnerability actually is and how bad it could theoretically be. What it returns: description, CVSS score/severity (e.g. 10.0, CRITICAL), and related metadata.

- **CISA KEV (Known Exploited Vulnerabilities catalog)** — Also run by a U.S. government agency (CISA), but answering a much sharper question: is this vulnerability *actually* being exploited by attackers right now, not just theoretically dangerous? A CVE appearing here means it's confirmed to be actively used in real attacks — which is exactly the kind of finding that should jump a vulnerability to the top of a patching queue. What it returns: a verdict, plus vendor/product details and CISA's recommended remediation.

[FIGURE: 22-investigation-cve-result.png | Investigating CVE-2021-44228 (Log4Shell) returns cards from CISA Known Exploited Vulnerabilities, NIST NVD, and the Internet Intelligence Collector side by side — CISA KEV confirms real-world exploitation, NVD supplies the CVSS 10.0 "CRITICAL" score and full description, and the Internet Intelligence Collector adds live-fetched OSINT findings, all without any provider requiring a credential.]

## 🌐 Live Web / OSINT Intelligence

- **Internet Intelligence Collector** — This is the platform's own OSINT (Open-Source Intelligence — information gathered from publicly available sources rather than a paid feed) crawler. It actively searches public sources like GitHub, Reddit, RSS feeds, and paste sites for recent chatter about a domain, IP, malware family, threat actor, campaign, CVE, or filename. Unlike the other providers, which query a fixed, pre-built database, this one goes out and fetches live results at the moment you run the investigation. For an analyst, this is useful precisely because it can surface very recent, informal discussion — like a proof-of-concept exploit script just published on GitHub — that a slower-moving commercial feed hasn't caught up to yet. What it returns: a list of real, live-fetched findings (e.g. matching GitHub repositories) relevant to the IOC.

## ⚔️ Attack Technique Reference

- **MITRE ATT&CK** — MITRE ATT&CK is the industry-standard framework that catalogs known attacker tactics and techniques (for example, "T1055 — Process Injection"). This provider looks up a MITRE technique ID directly against the official ATT&CK knowledge base. It's mainly used behind the scenes to enrich technique references the platform's correlation engine has already identified, giving analysts the real, official name and description rather than a bare ID.

## 📜 Domain, IP, and Certificate Registration Providers

These answer "who owns this, and what else is tied to it?" — infrastructure-and-ownership questions rather than reputation questions.

- **WHOIS/RDAP** — WHOIS and RDAP (Registration Data Access Protocol, the modern successor to WHOIS) are the standard ways to look up who registered a domain, or who an IP address / ASN (Autonomous System Number — an ID assigned to a network operator) block belongs to. This is often the very first thing an analyst checks: is this a brand-new domain registered yesterday, or a major cloud provider's IP range? What it returns: registrar/owner details, registration dates, and organizational information.

- **crt.sh (Certificate Transparency)** — Every publicly trusted TLS certificate (the certificate that secures a website's HTTPS connection) gets logged in public, tamper-evident "Certificate Transparency" logs. crt.sh searches those logs by domain. This is a well-known technique for discovering other subdomains or infrastructure tied to the same certificate issuer or domain — useful for mapping out an attacker's broader infrastructure. What it returns: a list of matching certificates and the domains/subdomains they cover.

- **Censys** — An internet-wide scanning service that catalogs what's actually running on IP addresses across the internet (open ports, services, certificates) — sometimes described as passive DNS / internet asset intelligence. This is useful for understanding what an IP is actually hosting, beyond just a reputation score. Censys is the one provider in this platform that needs **two** separate credentials to work — a Personal Access Token *and* an Organization ID — both are required, and having only one leaves it not configured.

## 📋 All 18 Providers at a Glance

| Provider | What It Checks | Key Required? |
|---|---|---|
| VirusTotal | IPs, domains, URLs, file hashes — multi-engine scan verdicts | Yes |
| AbuseIPDB | IPs — community abuse reports | Yes |
| AlienVault OTX | IPs, domains, hostnames, URLs, hashes — community threat exchange | Yes |
| URLhaus | URLs, domains, IPs — malware-distribution tracking | Yes (shared abuse.ch key) |
| ThreatFox | IPs, domains, URLs, MD5/SHA256 hashes — shared IOC database | Yes (shared abuse.ch key) |
| MalwareBazaar | File hashes (MD5/SHA1/SHA256/SHA512) — known malware samples | Yes (shared abuse.ch key) |
| crt.sh | Domains, TLS certificates — Certificate Transparency logs | No |
| NIST NVD | CVE IDs — vulnerability description & CVSS score | No (optional key raises rate limit) |
| CISA KEV | CVE IDs — confirmed active exploitation | No |
| MITRE ATT&CK | MITRE technique IDs — official attack-technique reference | No |
| WHOIS/RDAP | Domains, IPs, ASNs — registration/ownership records | No |
| Hybrid Analysis | SHA256 file hashes — malware sandbox behavior | Yes |
| Spamhaus | IPs, domains — DNS-based blocklist | No |
| PhishTank | URLs — community-reported phishing | No (optional key raises rate limit) |
| Censys | IPs — internet-wide host/certificate scan data | Yes (Personal Access Token **and** Organization ID, both required) |
| Internet Intelligence Collector | Domains, IPs, malware families, threat actors, campaigns, CVEs, filenames — live OSINT crawl | No |
| urlscan.io | URLs, domains — live sandbox scan | Yes (no wizard entry — see below) |
| Google Safe Browsing | URLs, domains — Google's malware/phishing threat lists | Yes (no wizard entry — see below) |

## 🧮 Why the Setup Wizard Only Shows 8 Providers, Not 18

If you've been through the installation wizard, you may have noticed its provider page only lists 8 entries to fill in — not 18. This is a deliberate, verified design detail, not a missing feature.

[FIGURE: 12-wizard-providers-configured.png | The Setup Wizard's Threat Intelligence Providers page, where an administrator enters credentials (shown as masked dots, never real key text) for providers such as VirusTotal, AbuseIPDB, and AlienVault OTX.]

Here's the honest breakdown of why the numbers work out that way:

- **6 of the 18 providers need no credential at all and have no entry on the wizard's page**: crt.sh, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Spamhaus, and the Internet Intelligence Collector. Since there's nothing to type in, there's simply nothing for a setup screen to ask for — these providers are already active the moment the platform starts, with no setup step required. (NIST NVD and PhishTank also work with no credential, but the wizard still gives each of them an optional key field purely to raise their rate limit — so they're counted in the wizard's 8 entries below, not in this list of 6.)
- The remaining **10 providers with an actual credential requirement are covered by only 8 wizard entries**, because three of them — URLhaus, ThreatFox, and MalwareBazaar — all share a single abuse.ch "Auth-Key." Entering that one key on the wizard's single abuse.ch field activates all three providers at once.
- **2 providers need a credential but have no wizard entry at all: urlscan.io and Google Safe Browsing.** Both are configured exclusively after install, from the app's own Providers page (sign in → Providers) — the same runtime, database-backed, no-restart configuration described below. This isn't a Windows-versus-Linux gap; both installers' wizards omit these two identically, and both say so explicitly in their own setup-time messaging.

So the math is: 8 wizard entries → 10 providers with a wizard entry (7 individual + 3 sharing one abuse.ch key) + 6 always-on providers with nothing to configure + 2 providers that need a credential but are set up after install instead of during the wizard = **18 providers total**, all working once configured. Nothing is hidden or broken — the shorter wizard list is simply an accurate reflection of which providers actually have a setting on that specific page.

## ⚙️ Managing Providers From the App (No Restart)

The Setup Wizard's provider page is a **first-run bootstrap**, not the only place these settings live. Once the platform is up and running, every credential, model choice, and enabled/disabled state — for both IOC providers and AI backends — can be viewed and changed from inside the app itself, at any time, with no restart, no re-installation, and no editing of any configuration file by hand. This is the same underlying configuration the wizard wrote on first install; the wizard just gets you to a working starting point, and this page is where you go afterward whenever something needs to change.

You'll find it via the **Providers** link in the workspace navigation, which opens a dedicated page organized into four tabs.

**AI Providers.** This tab lists the platform's AI backends and their current status — for example, showing which ones are "Not configured," which are "Configured," and which one is currently "Active."

[FIGURE: 32-manage-providers-ai-tab.png | The /providers page, AI Providers tab, listing each AI backend with its live configured/active status.]

Expanding a backend's row lets you enter or update its credentials and model. An already-saved credential is never shown in plain text -- it displays as a row of masked dots followed by the last few characters, the same partial-reveal convention used by most login and payment forms, so you can recognize which key is saved without the full value ever being visible on screen or recoverable from it. From that same expanded row you can click **Test Connection** to confirm the credentials actually work before relying on them, and **Set Active** to make that backend the one the platform uses for new investigations — immediately, without restarting anything.

[FIGURE: 33-manage-providers-ai-edit-masked.png | An AI backend's row expanded for editing, showing the masked API key field, the model field, and the Test Connection / Save / Set Active controls.]

**IOC Providers.** This tab covers all 18 built-in providers described earlier in this section — each one configurable, testable, and individually enabled or disabled, right from this screen. Because each provider's row only asks for the exact fields that provider actually needs (a single credential for most, the shared abuse.ch key for URLhaus/ThreatFox/MalwareBazaar, or the Personal Access Token *and* Organization ID pair for Censys), there's no guesswork about what to fill in. Providers that need no credential at all still appear here with an enable/disable toggle, since "on or off" remains a setting worth controlling even when there's nothing to type in.

[FIGURE: 34-manage-providers-ioc-tab.png | The IOC Providers tab, listing all 18 registry providers with their real configured/enabled status.]

Expanding an IOC provider's row works the same way as an AI backend's: a masked credential field for exactly the input that provider needs, plus Test Connection, Save, and Enable/Disable controls. The screenshot below shows AbuseIPDB expanded with a key typed in, ready to test or save — the same flow used whether you're setting up a provider for the first time or changing an existing key.

[FIGURE: 37-add-ioc-provider-form.png | An IOC provider's row expanded for editing (AbuseIPDB), with the masked API key field and Test Connection / Save / Disable controls.]

Test Connection always makes a real request to the provider rather than just checking that a field is non-empty, so an incorrect or revoked key is caught immediately with a specific reason, not a vague failure. The screenshot below shows a genuine failed test — a real "Authentication failed" response from the provider, not a placeholder message:

[FIGURE: 38-failed-test-connection.png | A real failed Test Connection result: "Failed: Authentication failed -- check your API key," shown in place, with the provider's exact response reflected back rather than a generic error.]

**Audit Log.** Every configuration change made through this page — configuring a provider, enabling or disabling one, switching the active AI backend, running a connection test — is recorded here in plain, human-readable language: who made the change and what it was.

> [!NOTE]
> Consistent with how the platform treats credentials everywhere else, the audit log never records the actual credential value — only that a credential was configured or updated, never what it is.

[FIGURE: 35-manage-providers-audit-log.png | The Audit Log tab, showing recorded configuration actions with human-readable detail text and no credential values.]

**Network Access.** This tab shows the address other devices on your local network can use to reach the platform (detected automatically during setup), the ports in use, and whether the local Windows Firewall rule needed for LAN access is in place — see "Accessing From Another Computer" for the full walkthrough.

## 💬 A Note on Provider Disagreement

Because the platform asks many independent providers at once, they won't always agree — and that's normal, useful behavior, not a malfunction. Reputation feeds, blocklists, and community-reported databases each have their own methodology, so it's entirely possible for one provider to flag an indicator as malicious while another calls the exact same indicator clean.

When that happens, the platform's AI-generated summary tries to explain the disagreement in plain language rather than silently picking a side. That AI output should be treated as **analytical assistance, not an unquestionable verdict** — it's a starting point for your own judgment, not a replacement for it. Every investigation includes an Evidence Ledger (and a "Show receipts"-style breakdown of how the score and verdict were reached) so you can trace any AI claim back to the specific, real provider data behind it, rather than just taking the summary's word for it.
