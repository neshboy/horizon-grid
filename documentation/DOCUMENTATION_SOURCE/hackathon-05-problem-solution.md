# The Problem and The Solution

## The Problem: Fragmented, Manual Threat Triage

Every individual threat-intelligence source is narrow by design — a multi-engine reputation scanner, a malware sandbox, a certificate-transparency search, a government vulnerability catalog, a DNS blocklist — and none of them sees the full picture alone. In practice, investigating one indicator means an analyst opens a reputation lookup site, then a sandbox or sample database, then a certificate search, then a vulnerability database, then a blocklist, pasting the same value into each one and reading each result in its own format. Cross-referencing those results by hand — noticing that an IP tied to a malware family is also tied to a MITRE ATT&CK technique that matches a hash flagged somewhere else — is the actual cost of triage, and it is the first thing that gets skipped when the indicator queue is long.

A second, quieter problem sits underneath the first: once AI entered this workflow, it became tempting to let a language model produce the whole verdict from a prompt. That's fast, but it trades a real problem (manual cross-referencing is slow) for a worse one — an analyst now has to trust a paragraph that might be internally inconsistent, might invent a source that was never checked, and offers no fixed, reproducible number to audit later.

## The Solution: One Submission, One Verifiable Operational Picture

HORIZON GRID's actual processing pipeline, in the order it really executes:

1. **IOC submission and classification** — the analyst submits one value; the platform validates and classifies it (IPv4/IPv6, domain, URL, file hash, CVE ID, and the other IOC types the app recognizes).
2. **Parallel provider queries** — every one of the 18 built-in providers relevant to that IOC type is queried at once (a file hash is never sent to a domain-registration lookup), and results stream into the page live over Server-Sent Events as each provider responds, rather than waiting for the slowest one.
3. **Per-provider AI summaries** — as each provider's result arrives, a short AI-written summary of that one result is generated, grounded only in that provider's own data.
4. **Correlation** — once providers have reported in, a correlation engine extracts relationships between what different sources said (shared infrastructure, related hashes, malware families, MITRE ATT&CK techniques, exploited CVEs) and boosts confidence when independent providers corroborate the same fact.
5. **Deterministic threat scoring — before the AI's final verdict, not after.** A fixed, versioned scoring engine computes `overall_risk_score`, `confidence_score`, `malicious_probability`, and a severity band from provider-verdict consensus and correlation evidence, using a documented, weighted formula (see the Threat Scoring guide). This step deliberately happens *before* the AI's consolidated assessment.
6. **AI Final Assessment, conditioned on the score** — one consolidated AI pass reasons over every per-provider summary plus the correlation output, and is handed the already-computed score as a fixed input to narrate. The platform validates that the AI's own stated verdict agrees with that number before saving anything, rather than trusting the AI to have applied the number correctly.
7. **Operational presentation** — the result renders as an investigation page with an Evidence Ledger and verdict-interrogation tools, rolls up into the Executive Dashboard's live KPIs, and can be exported (JSON/Markdown/CSV/PDF) with the platform's branding, a generation timestamp, and an Investigation ID on every export.

[FIGURE: ioc-investigation-results.png | A completed investigation — provider results, threat score, and severity all visible on one page, each traceable back to the specific source that produced it.]

The order in step 5 and step 6 is the load-bearing design decision in this whole pipeline: the AI is never the source of the threat score. It receives a number that was already computed by a fixed formula and is only permitted to explain it — which is what makes the score reproducible and auditable in a way a single AI-generated verdict never can be.

## Why This Design, Specifically

An earlier, simpler version of this idea would have let the AI produce `risk_score`, `malicious_probability`, and the verdict directly from a prompt in one call. That's a real, common pattern, and it's exactly the pattern this project moved away from once a deterministic scoring engine was built: prompt wording alone cannot reliably stop a model — particularly a local model — from overriding a "do not fill in, this is provided" instruction. Computing the score first and feeding it into the AI prompt as a fixed input, then validating the AI's verdict against it, closes that gap structurally instead of relying on the AI to behave. It is also the only design that makes an "average threat score" KPI on the Executive Dashboard mean anything consistent over time, since the AI backend an analyst has selected (of eleven interchangeable options) no longer changes what the score *is* — only how it's explained.
