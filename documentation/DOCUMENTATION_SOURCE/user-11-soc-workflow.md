# 🕵️ A Real-World SOC Workflow

Every feature described so far is easier to trust once you see it used the way a SOC (Security Operations Center) analyst actually works: not by opening one tool at a time, but by following a single lead wherever it goes. The walkthrough below is not a hypothetical — it is the exact sequence an analyst followed in the platform, start to finish, while triaging a routine batch of indicators.

## The lead: a CVE turns up in a routine sweep

It starts the way most real investigations do — unglamorously. The analyst is working through a list of IOCs (Indicators of Compromise: IP addresses, domains, hashes, and CVE IDs pulled from recent alerts and vendor advisories) that need to be checked against threat intelligence before the shift ends. Most will turn out to be noise. One entry in the list is `CVE-2021-44228` — a CVE (Common Vulnerabilities and Exposures) identifier, the standard way the industry names a specific, publicly tracked software vulnerability. The analyst doesn't recognize the number offhand, so they submit it to the platform the same way they would any other IOC.

The results come back aggregated from multiple authoritative sources in one view. This is the payoff of an IOC lookup platform in the first place: instead of opening a CISA advisory in one tab, a NIST database in another, and a search engine in a third, the analyst gets all of it side by side, in the time it takes the providers to respond.

[FIGURE: 22-investigation-cve-result.png | Looking up CVE-2021-44228 returns a CISA Known Exploited Vulnerabilities card confirming active exploitation with real CVSS, vendor, and product data; a NIST NVD card showing a CVSS score of 10 and CRITICAL severity with the full vulnerability description; and an Internet Intelligence Collector card of live, freshly-fetched OSINT (Open Source Intelligence) findings from public GitHub repositories discussing this exact CVE.]

The CISA (Cybersecurity and Infrastructure Security Agency) Known Exploited Vulnerabilities card is the first thing that raises the stakes: CISA doesn't list a CVE unless it has confirmed real-world exploitation, and here the verdict is unambiguous — malicious, with the vendor, affected product, and remediation guidance pulled directly from that catalog. The NIST NVD (National Vulnerability Database) card independently corroborates the severity: a CVSS (Common Vulnerability Scoring System) score of 10 out of 10, rated CRITICAL, with the full official vulnerability description. Underneath both, the Internet Intelligence Collector — the platform's own OSINT crawler — has pulled in live findings from GitHub repositories actively discussing this CVE, showing the analyst that it isn't just historically significant, it's still a live topic. The analyst recognizes the number now: this is Log4Shell, the Log4j remote-code-execution vulnerability. Two independent, authoritative government-maintained sources agreeing on maximum severity is exactly the kind of signal that turns a routine sweep item into a priority.

Scrolling further confirms there's substance behind the verdict, not just a score:

[FIGURE: 23-investigation-cve-full.png | The full Log4Shell investigation page adds a Final Assessment, a Relationship Graph, a MITRE ATT&CK Matrix, an Evidence Ledger, and a generated Detection Rule titled "Direct Class Unloader EJP Proxy Vulnerability" that gives the analyst a concrete starting draft to bring to a detection engineering team.]

The Detection Rules panel is a concrete, useful artifact: a real generated rule that gives the analyst a working draft to review and adapt rather than having to write one from scratch. As with any AI-assisted output in the platform, this rule and the Final Assessment above it are analytical assistance, not a verdict to take on faith — every claim on this page can be traced back to a real provider record or correlation edge in the Evidence Ledger below, so the analyst (or a teammate reviewing the case later) can check exactly where a specific statement came from rather than just trusting the summary text. It's a head start for the detection engineering team, not a substitute for their review before it ships to production.

## Escalating: opening a case

A CVSS 10, confirmed-exploited, still-actively-discussed vulnerability isn't a one-off lookup to close and forget — it needs to be tracked, assigned a severity, and worked as its own investigation. The analyst opens the platform's Cases feature and creates a new case.

[FIGURE: 24-case-created.png | A new case titled "Log4Shell Exposure Review" is created with Critical severity and Open status, giving the investigation a home separate from the one-off IOC lookup that started it.]

Naming the case, setting its severity to Critical, and leaving it Open turns a single search result into a tracked piece of work — something that can be picked up again tomorrow, handed to another analyst, or referenced from a ticketing system, instead of living only in the analyst's memory or a screenshot.

## Attaching evidence and recording the next step

From the CVE-2021-44228 investigation page, the analyst attaches the CVE directly to the new case using the "Add to Case" button, then records what they're doing about it as an analyst note before moving on.

[FIGURE: 25-case-with-ioc-and-note.png | The "Log4Shell Exposure Review" case now shows one attached IOC, CVE-2021-44228, and one analyst note documenting the next investigative step.]

The note reads, in full: *"Confirmed CVE-2021-44228 (Log4Shell) via the platform's NVD-backed lookup. Cross-checking internal asset inventory for vulnerable Log4j versions next."* This is a small thing, but it is the difference between institutional knowledge and a Slack message that scrolls away: the case now carries a permanent record of what was confirmed, from where, and what happens next — reviewable by a teammate, a manager, or the analyst's own future self without anyone having to reconstruct it from memory.

## Handing it off

The investigation still needs to leave the platform and land in wherever the team tracks incident tickets. The analyst exports the findings as Markdown, which attaches cleanly to a ticket or incident-report document as readable, formatted text. JSON, PDF, and CSV export are also available, for anyone downstream who wants to parse the findings programmatically, attach a formatted document, or import into a spreadsheet.

## Why this is faster than doing it by hand

The same investigation done manually would mean separately visiting CISA's KEV catalog, querying NVD, running a search for current OSINT chatter, writing a detection rule from scratch, and then remembering to document all of it somewhere durable — five or six separate tools and a self-imposed discipline to write anything down at all. Here, one search surfaced every authoritative source at once, the platform's own evidence trail let the analyst verify the severity claim instead of just trusting a score, and opening a case took the finding from "something I noticed" to "something the team can act on" in the same sitting. Search, correlate, verify, document, escalate — collapsing those five steps into one continuous flow is what keeps a real Log4Shell-caliber finding from getting lost in a routine sweep.
