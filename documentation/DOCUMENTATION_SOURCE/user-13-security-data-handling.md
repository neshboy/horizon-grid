# Security and Data Handling

This section explains, in plain language, how HORIZON GRID handles your sign-in, your provider credentials, and — most importantly — the actual indicator data you investigate. It is meant to be read by anyone using the tool, not just engineers. A far more detailed, code-level Security Architecture appendix exists later in this document for readers who want the full technical picture; this section is its beginner-friendly companion.

## Signing In, and Who Becomes the Administrator

The platform is a normal sign-in-protected web application: you register an account with an email and password, then sign in from the same page each time.

[FIGURE: 15-login.png | The web app's Sign in page, where an existing user enters their email and password to access the platform.]

A few things worth knowing about how this works:

- **Your password is never stored in plain text.** The platform keeps only a one-way scrambled (hashed) version of it, so nobody — not even someone with direct database access — can read your actual password back out.
- **Signing in issues a temporary digital pass, not a permanent one.** After you sign in, the platform gives your browser a short-lived access token that expires automatically after about 30 minutes, plus a longer-lived one (good for about 7 days) that quietly renews your session in the background so you aren't forced to re-enter your password constantly.
- **The very first account created on a fresh install automatically becomes the administrator.** There is no separate "make someone an admin" step to remember. When the Setup Wizard runs during installation, the account you create on its Administrator Account page is that very first account — and because it's first, the platform automatically grants it administrator-level access. Once that administrator exists, the public sign-up page closes itself: anyone who tries to register through it afterward is turned away with a message pointing them at an administrator instead. Every account after the first one has to be created by an administrator from the Administration page (see below), who chooses its role — analyst or viewer, or another administrator — up front.
- **Administrators manage every other account from an Administration page**, not by editing anything by hand. Once signed in as an administrator, an "Administration" link appears in the top navigation (it's invisible to non-administrators). From there you can create a new account with a specific role from the start, promote or demote an existing analyst or viewer, disable an account instantly (their access stops working on their very next click, even if they're mid-session), re-enable one, and reset anyone's password — which also signs that person out of every device they were already signed into, so they can't keep using the old password's session. Every one of these actions is recorded in the same Audit Log a provider-configuration change would be, so there's always a record of who did what and when — never including the actual password.
- **There is always at least one administrator, and the platform won't let you accidentally remove the last one.** Trying to disable the sole remaining administrator, or demote them to analyst/viewer, is refused with a clear error rather than silently locking everyone out of account management. An administrator also can't change their own role (another administrator has to do it) — this just prevents someone from accidentally locking themselves out of the very screen they're using.

[FIGURE: 07-wizard-admin-filled.png | The Setup Wizard's Administrator Account page during installation, where the first account on a new install is created — this account automatically becomes the administrator.]

[FIGURE: 41-admin-users-tab.png | The Administration page's Users tab: search, filters, and the create/edit/reset-password/enable-disable actions available to an administrator.]

[FIGURE: 43-admin-roles-permissions-tab.png | The Administration page's Roles & Permissions tab: a read-only view of exactly what each role can do.]

[FIGURE: 44-admin-audit-log-tab.png | The Administration page's Audit Log tab, showing account changes and provider-configuration changes together in one timeline.]

## Your Provider API Keys: Entered Once, Locked Away

To query the various third-party threat-intelligence services this platform aggregates (VirusTotal, AbuseIPDB, AlienVault OTX, and others), several of them require you to supply your own API key for that service. You provide these once, during installation, on the Setup Wizard's provider configuration page — not somewhere buried in a settings menu you have to hunt for.

[FIGURE: 12-wizard-providers-configured.png | The Setup Wizard's Threat Intelligence Providers page with several provider API keys entered; each key box shows masked dots on screen rather than the real characters.]

A few practical points:

- **Keys are masked as you type them**, the same way a password field is — so nothing sensitive is visible on your screen by accident, including in screenshots or over someone's shoulder.
- **Keys are stored in a single configuration file, kept in a protected system folder on the machine running the platform** — not inside the web application's database, and not anywhere a regular file browse would stumble across. That folder is locked down at the operating-system level so that only Administrator-level Windows accounts (and the system itself) can open it; a standard, non-administrator user account on the same computer cannot read it.
- **You can revisit and change your keys later** using the "Configuration" shortcut the installer creates, which simply re-runs the same wizard against your existing setup.

## What Happens to an IOC You Investigate

This is the part worth reading carefully, because it's central to how the platform works and it deserves an honest explanation rather than a reassuring gloss.

When you submit an IOC (Indicator of Compromise — an IP address, domain, URL, file hash, or CVE ID, i.e. a standardized identifier for a publicly known software vulnerability, that you want to investigate) for a lookup, the platform does not just search its own local database. For every configured provider that supports that type of indicator, the platform sends the literal value you entered — the actual IP address, the actual domain name, the actual file hash — out to that provider's own service, because that is the only way those services can check it against their own intelligence. This is true across essentially the whole provider lineup: threat-intelligence services like VirusTotal, AbuseIPDB, and AlienVault OTX; public lookups like WHOIS/RDAP and Certificate Transparency; and everything in between. If a provider isn't configured (no key entered, or not applicable to that indicator type), it simply isn't contacted and contributes nothing — but any provider that is configured and supports that IOC type will see the value you're investigating.

Practically, that means: **be mindful before investigating something genuinely sensitive.** If you're looking up an internal hostname, an internal IP address, or a file hash tied to an active, confidential incident, remember that value is being transmitted to whichever external providers you've enabled — the same way it would be if you pasted it into any of those providers' own websites. That's simply how multi-provider IOC lookups work, not a flaw specific to this platform, but it's a habit worth having regardless of which tool you're using.

## AI Analysis: Local by Default, Cloud if You Choose

Once provider results come back, the platform uses an AI model to summarize individual provider findings and produce a consolidated assessment. You choose which AI model does that work during setup.

[FIGURE: 08-wizard-aiconfig.png | The Setup Wizard's AI Configuration page, where you choose between a local AI model running on your own machine or a cloud AI provider.]

- **By default, the AI runs entirely on a local model on the same machine as the rest of the platform.** In this mode, no analysis data leaves your machine at all — the model that reads the provider findings and writes the summaries and verdicts is running locally, alongside everything else.
- **Optionally, you can configure a cloud AI provider instead.** If you choose this, the provider findings gathered during your investigation are sent to that external AI service so it can generate the write-up. This is a deliberate trade-off some readers may want (for a more capable model) and others may not — it's your choice to make during setup, and it's separate from the provider-lookup data flow described above.

Either way, choosing the local model versus a cloud AI provider only affects where the *AI writing* happens — it does not change the fact, described above, that the IOC value itself is still sent to whichever threat-intelligence providers are configured, since that step happens before the AI is ever involved.

## Checking the AI's Work Instead of Just Trusting It

AI-generated verdicts, summaries, and explanations in this platform are analytical assistance — a well-informed second opinion — not an unquestionable ground truth, and the platform itself is built around that idea rather than around asking you to simply trust a score.

A genuine, honest example of why this matters: a lookup on 8.8.8.8 (Google's well-known public DNS server) shows Spamhaus returning a "malicious" verdict, but for an unusual reason — its own card explains this is because open public resolvers aren't permitted to query Spamhaus directly, not because 8.8.8.8 is actually malicious. Meanwhile AbuseIPDB and VirusTotal both call it clean. The platform's own executive summary is upfront about this disagreement rather than quietly blending it into one number.

[FIGURE: 17-investigation-benign-ip-result.png | An investigation of the IOC 8.8.8.8 (Google Public DNS) showing a high Threat Score alongside individual provider cards — including Spamhaus's "malicious" verdict, whose stated reason is a query error rather than an actual detection.]

[FIGURE: 18-investigation-benign-ip-full.png | The same 8.8.8.8 investigation's full results page, where the Executive Summary explicitly notes the IP is flagged malicious by Spamhaus while AbuseIPDB and VirusTotal support a clean reputation, alongside the Evidence Ledger and Verdict Analysis tabs an analyst can use to dig into why.]

This is exactly the kind of AI verdict worth double-checking rather than accepting at face value — and the platform gives you the means to do that:

- The **Evidence Ledger** is a list of the underlying facts behind a verdict, each with its own confidence level. Unlike the AI's prose summaries, evidence-ledger entries are built directly and deterministically from the provider results themselves — they are not written by the AI — so they exist specifically to give you something concrete to check the AI's claims against.
- The **Verdict Analysis tabs** (including "Why?", "What's this?", "Score Explanation", "Intelligence Conflicts", "False Positive Check", and "Challenge This Verdict") let you interrogate a verdict rather than just read it, and are designed to surface disagreements between providers — like the Spamhaus/AbuseIPDB/VirusTotal split above — instead of hiding them.
- Behind the scenes, the platform also cross-checks the AI's own output against the underlying data it was given: if the AI cites something (for example, a specific MITRE ATT&CK technique) that isn't actually backed by the real evidence collected for that IOC, the platform flags it rather than presenting it as confirmed.

The takeaway: treat AI-generated verdicts as a starting point for your own analysis, and use the Evidence Ledger and Verdict Analysis tools when a result seems surprising, high-stakes, or — as with 8.8.8.8 — genuinely contested between providers.
