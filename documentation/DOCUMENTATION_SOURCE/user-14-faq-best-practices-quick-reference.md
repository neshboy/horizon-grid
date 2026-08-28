# ❓ Frequently Asked Questions

**Do I need every provider configured to use the platform?**
No. Every provider that needs an API key is optional -- the platform works with any subset configured, including none. Providers that need no key at all (WHOIS/RDAP, Spamhaus, crt.sh, NIST NVD, CISA KEV, MITRE ATT&CK, PhishTank, the Internet Intelligence Collector) always run regardless. An investigation with zero paid providers configured still produces a real result from whichever free sources apply to that IOC type.

**Does the AI's verdict override the provider data?**
No, and the platform is deliberately built so you never have to take the AI's word for it. Every AI-written summary is grounded in the Evidence Ledger -- a deterministic, AI-independent record built directly from what the providers actually returned. If an AI conclusion doesn't match the underlying evidence, the Verdict Analysis tools ("Why?", "Challenge This Verdict", "False Positive Check") exist specifically so you can check.

**What happens if a provider fails or isn't configured?**
The investigation continues with whichever providers succeeded. A failed, rate-limited, not-configured, or disabled provider is reported with a specific status (never a generic "error"), and the AI is explicitly told that provider's data is *unavailable* -- which is treated differently from "the provider ran and found nothing." A missing data point is never silently read as a clean bill of health.

**Can I switch AI providers without losing my current investigation?**
Yes. Switching the active AI backend (via the "AI:" selector on the home page, or the AI Providers tab in Manage Providers) takes effect on the *next* investigation immediately -- no restart. For an investigation you've already run, the "AI Comparison" panel lets you re-run just the AI analysis step against a different backend, using the same already-collected evidence, without re-querying any provider.

**Why does the same IOC sometimes get a slightly different AI write-up if I re-analyze it?**
AI-generated text is not perfectly deterministic between calls, and different backends/models can reasonably read the same evidence differently (which is exactly what the AI Comparison feature is for). The underlying facts -- provider data, correlation, Evidence Ledger -- do not change between reruns; only the AI's synthesis of them can.

**Is my data sent to the third-party providers?**
Only the specific IOC value you investigate is sent to whichever providers are enabled and support that IOC type -- normal behavior for any threat-intelligence lookup tool. Nothing else about your environment is sent. See the Security & Data Handling chapter for the full picture.

**Where do I go to change a provider's API key later?**
The "Providers" link in the workspace navigation opens Manage Providers, with separate tabs for AI Providers and IOC (threat-intelligence) Providers. Changes there take effect immediately -- no restart, no reinstall, no editing configuration files.

# ✅ Best Practices

- **Start with the free providers, add paid ones as you need them.** Because every provider is optional, there's no reason to hold off using the platform while waiting on API key approvals -- WHOIS/RDAP, Spamhaus, and the OSINT collector already provide real signal with zero configuration.
- **Use Test Connection before relying on a newly-entered key.** It makes one real, minimal request to the provider and reports a genuine result (authenticated, invalid key, rate-limited, unavailable) -- never just "the field is non-empty."
- **Treat a disagreement between providers as a prompt to look closer, not a tie-breaker to ignore.** The correlation engine and the AI's threat assessment both explicitly track agreeing vs. disagreeing providers -- when they disagree, that is itself useful signal, not noise to average away.
- **Use the Evidence Ledger and "Why?" tools before escalating a verdict.** A high-severity verdict backed by thin evidence is exactly what these tools are designed to catch before it turns into an unnecessary incident response action.
- **Add an IOC to a Case as soon as it's part of a real investigation, not after.** Cases keep the analyst's notes, IOCs, and reasoning together as the investigation develops, rather than requiring reconstruction later.
- **If comparing AI backends, compare on the same evidence, not a fresh lookup.** The AI Comparison panel's whole point is holding the evidence constant so the only variable is which AI produced the read -- re-running a brand-new investigation instead would also change the provider data and defeat the comparison.

# 📌 Quick Reference

| I want to... | Where |
|---|---|
| Investigate an IOC | Home page search box, or the search bar on any page |
| See which AI is currently active | "AI:" selector, home page, next to the search box |
| Switch which AI analyzes the next investigation | Same "AI:" selector, or Manage Providers → AI Providers → Set Active |
| Configure or change a provider's API key | Manage Providers (workspace nav) → AI Providers or IOC Providers tab |
| Test a provider or AI key before trusting it | Expand its row in Manage Providers → Test Connection |
| Enable/disable a provider | Manage Providers → IOC Providers tab → Enable/Disable |
| Compare AI backends on one investigation | Completed investigation page → AI Comparison panel |
| See every configuration change ever made | Manage Providers → Audit Log tab |
| Check why a verdict was reached | Investigation page → Verdict Analysis → "Why?" |
| Check the platform is actually running | System Health page |
| Save an IOC for later without a full case | Add to Basket |
| Track a multi-IOC investigation with notes | Cases |
| Export an investigation's findings | Export menu (PDF / Markdown / CSV / JSON) on the investigation page |
