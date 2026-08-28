# 🗂️ Case Management

## Why group IOCs together at all?

A single **IOC** (Indicator of Compromise — a piece of evidence such as an IP address, domain, URL, file hash, or CVE ID that a security analyst wants to investigate) rarely tells the whole story on its own. A real incident is usually made up of several related pieces of evidence: the CVE (Common Vulnerabilities and Exposures identifier — a public catalog number for a known software vulnerability) behind an exploit attempt, the malicious IP address that tried to use it, the file hash of a payload that was dropped, and the analyst's own observations along the way.

If a SOC (Security Operations Center) analyst investigates each of those as a separate, disconnected search, several problems show up quickly:

- **Context gets lost.** A week later, nobody remembers that the "8.8.8.8 lookup" and the "CVE-2021-44228 lookup" and the "note about the firewall log" were all part of the same incident.
- **Handoffs are painful.** A second analyst picking up the investigation has no single place to see everything that's already been found — they have to be told, or re-discover it themselves.
- **Nothing to report from.** When it's time to write up what happened, the evidence is scattered across a browser history of individual lookups instead of living in one record.

The platform's **Case** feature solves this by giving an analyst one container — a "case" — that IOCs and notes can all be attached to as an investigation grows. Instead of "three unrelated searches I happened to run this week," it becomes "one case, with three pieces of evidence attached to it."

## Walking through a real case

The screenshot below shows a case immediately after it was created:

[FIGURE: 24-case-created.png | A newly created case titled "Log4Shell Exposure Review," set to Critical severity and Open status, with a written description — an empty container ready to have IOCs and notes attached to it.]

At this point the case is just a title, a severity level (here, Critical), an Open status, and a description of what the analyst is tracking — no evidence has been linked to it yet.

From here, an analyst builds the case up over the course of the investigation:

- **Attaching an IOC:** every investigation page in the platform (the page that shows a lookup's results) has an **"Add to Case"** button. When an analyst is looking at the results for an IOC — for example, the CVE-2021-44228 (Log4Shell) investigation — clicking "Add to Case" links that IOC directly to the case, so it no longer has to be tracked as a separate, disconnected search.
- **Adding a note:** the case also supports freeform analyst notes — short written observations that don't belong inside an automated provider result, such as "confirmed this CVE affects our externally-facing logging service; escalating to patch team."

The second screenshot shows the same case after both of those actions have happened:

[FIGURE: 25-case-with-ioc-and-note.png | The same "Log4Shell Exposure Review" case after the CVE-2021-44228 IOC was attached via the investigation page's "Add to Case" button and an analyst note was added — the case now shows 1 attached IOC and 1 note.]

The case now shows one attached IOC (CVE-2021-44228) and one analyst note. As an investigation continues, more IOCs and more notes can be attached the same way, so that everything relevant to "Log4Shell Exposure Review" stays in one place rather than spread across separate, easily-forgotten lookups.

# 🧺 IOC Basket

## What it is (and what it isn't called)

While working an investigation, an analyst often wants to keep track of a handful of IOCs they're personally paying attention to — not necessarily a formal case yet, just a running list of "things I'm keeping an eye on." The platform's real name for this feature is the **IOC Basket** (or just "Basket"). It is a personal scratch-list: an analyst adds IOCs to it while they investigate, and the Basket holds onto them for later.

> [!NOTE]
> This feature is **not** called a "Watchlist" anywhere in the product — "Basket" is its actual name. It serves a purpose an analyst might informally think of in watchlist terms — a personal running list of IOCs to come back to — but the platform's own term for it is Basket, and that's the name used throughout its interface.

## Using the Basket

[FIGURE: 26-basket.png | The IOC Basket page, showing one collected IOC (8.8.8.8) with a status tag indicating its lookup has already completed, alongside "Investigate Selected," "Compare Selected," and "Clear Basket" buttons.]

In the screenshot above, the Basket holds one collected IOC, 8.8.8.8, tagged as having already completed a lookup — so the analyst can see at a glance which basket entries already have results waiting versus which still need to be investigated.

The Basket page offers a small set of actions for working with the IOCs an analyst has collected:

- **Investigate Selected** — run (or re-run) a lookup on the IOCs currently selected in the Basket, rather than having to re-enter each one manually on the search page.
- **Compare Selected** — look at more than one saved IOC side by side, useful when an analyst wants to check whether two or more indicators they've been tracking relate to each other or share characteristics.
- **Clear Basket** — remove everything from the personal scratch-list once it's no longer needed.

Because the Basket is a personal list rather than a shared case record, it's best suited for the everyday "let me keep track of these while I work" habit — when something in the Basket turns out to matter for a real incident, it can then be formally attached to a Case (see the Case Management section above) so the finding isn't lost once the Basket is cleared.
