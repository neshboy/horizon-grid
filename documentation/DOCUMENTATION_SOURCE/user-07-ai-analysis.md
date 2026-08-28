# AI-Assisted Analysis

When you look up an **IOC** (Indicator of Compromise — a piece of evidence such as an IP address, domain, URL, file hash, or CVE ID that a security analyst wants to investigate) in HORIZON GRID, the platform doesn't just show you a pile of raw results from a dozen different sources and leave you to make sense of them yourself. It also uses an AI model to read that data and write a plain-language summary of what it means.

This section explains, honestly, what that AI layer actually does, what it deliberately does **not** do, and — most importantly — how you as an analyst can check any AI-written claim against the real evidence behind it rather than simply trusting it.

## 🤖 What the AI Actually Does

The platform's AI analysis happens in two distinct passes over the same investigation:

1. **A per-provider summary.** After each individual data source (VirusTotal, AbuseIPDB, Spamhaus, WHOIS, and so on) returns its result, the AI writes a short summary of *that one provider's findings* — nothing else. It is only shown that provider's own data when writing this summary, so a per-provider summary can never blend in information from a different source by mistake.
2. **One consolidated final assessment.** Once every provider has finished responding, the AI makes a second, separate call — this time it is given all of the per-provider summaries together, plus a correlation step that has already mechanically compared the providers against each other (looking for things they agree on, disagree on, or both independently point to, such as a shared malware family or IP relationship). From that combined picture, the AI writes one overall assessment: a verdict, a risk score, and prose explaining how the providers relate to and support (or contradict) one another.

Both passes run on whichever AI backend the platform has been configured to use. The platform supports eleven interchangeable backends: Ollama (a locally-hosted model with no external API calls), Anthropic, Amazon Bedrock, Google Gemini, Groq (a fast-inference provider with an OpenAI-compatible API, defaulting to the `llama-3.3-70b-versatile` model), OpenAI, Kimi (Moonshot AI), DeepSeek, xAI (the company behind Grok — a different product from Groq above, despite the similar name), Mistral AI, and OpenRouter (a meta-router that gives access to hundreds of underlying models from many different companies through one API). Whichever backend is selected on the AI Configuration page of the setup wizard is the one actually used for both the per-provider summaries and the final assessment; the platform never silently mixes or falls back to a different provider mid-investigation. See `standalone-ai-guide.md` for how each backend is actually configured, credentialed, tested, and switched.

Both of these appear on the investigation page, and they answer different questions. A per-provider AI summary answers "what did this one source say?" The final assessment answers "now that I've seen everything, what's the overall picture?" You'll see one summary box per provider card, and then a single Final Assessment section (with its own Executive Summary) further down the page that speaks for the investigation as a whole.

[FIGURE: 17-investigation-benign-ip-result.png | An investigation of the IOC 8.8.8.8 (Google Public DNS) shown moments after submission, with a Threat Score gauge and individual provider result cards (Spamhaus, AbuseIPDB, WHOIS/RDAP) displayed side by side as each provider finishes responding.]

## 🚫 What the AI Does NOT Do

It's just as important to understand the boundaries of this feature as it is to understand what it produces:

- **The AI does not scan any files itself.** It has no antivirus engine, no sandbox, and no ability to independently examine a file, URL, or IP. Every fact it summarizes came from one of the third-party providers the platform queried — VirusTotal, AbuseIPDB, Spamhaus, NIST NVD, and so on.
- **The AI has no threat feed or knowledge base of its own that it consults for a verdict.** It doesn't maintain a private list of known-bad indicators. Its job is strictly to read and reason over the results the providers already returned for *this specific lookup* — never to supply new "knowledge" of its own about whether something is malicious.

> [!IMPORTANT]
> The AI is explicitly prevented from inventing a verdict when there is no real evidence. This is a hard, code-level safeguard, not just a polite instruction to the model, and it exists precisely because the alternative was tested and failed. During validation, the platform's real EICAR test file was looked up by its actual MD5 hash (EICAR is a standard, harmless, industry-wide test file used to safely trigger antivirus and threat-intelligence detections without touching real malware). In that specific test, none of the configured providers were actually turned on for that lookup, so there was zero real evidence of any kind — no provider data, no correlation between sources. Despite that, the AI model still produced a verdict of "highly malicious," a fabricated 92% probability of maliciousness, and invented prose claiming an "association with ransomware and trojans" — none of it grounded in anything that had actually been returned. This was caught, and the platform now includes a deterministic check that runs *before* the AI is ever asked to weigh in: if there are no per-provider findings and no correlated relationships between providers, the platform skips the AI call entirely and returns a fixed, honest result — a verdict of "unknown," a message explaining that no provider returned usable data for the indicator, and the risk fields left at zero — rather than letting a model guess from its own general training data. In other words, when there's nothing to go on, the platform says so, instead of making something up.

## ⚖️ How the AI Handles Disagreement Between Providers

Threat intelligence sources don't always agree, and the platform doesn't hide that when it happens — it says so directly. A good real example is the IOC `8.8.8.8` (Google's public DNS resolver): Spamhaus flagged it as malicious, but the actual reason given was a query-permission error ("public/open resolver not permitted to query Spamhaus"), not a genuine detection — while AbuseIPDB reported zero abuse reports and VirusTotal returned a clean result. The AI's Executive Summary for that investigation says so plainly: the IP "is considered malicious by Spamhaus, but its reputation as a clean and safe IP address is supported by AbuseIPDB and VirusTotal."

That's not a bug in the product — it's the AI doing exactly what it's supposed to do: surfacing a genuine conflict between sources instead of quietly picking one side, so the analyst can see the disagreement and judge it for themselves (in this case, a known, benign, heavily-used public DNS server being caught by a resolver-permission rule rather than an actual threat detection).

[FIGURE: 18-investigation-benign-ip-full.png | The same 8.8.8.8 investigation, scrolled further, showing the Final Assessment's Executive Summary describing the disagreement between Spamhaus (malicious) and AbuseIPDB/VirusTotal (clean), alongside the Evidence Ledger, Verdict Analysis tabs, and Relationship Graph.]

## 🧾 Verifying an AI Claim Instead of Trusting It Blindly

Every investigation gives you concrete ways to check an AI-written statement against the real underlying evidence, rather than asking you to just take its word for it:

- **The Evidence Ledger.** Every investigation includes a running list of individual, numbered evidence items — each one tied to a real source and carrying its own confidence percentage. This is the platform's version of "show receipts": any specific claim the AI makes should be traceable back to one or more of these concrete, checkable entries rather than floating free as an unsupported assertion.
- **Verdict Analysis tools.** Alongside the Final Assessment, the investigation page offers a set of tabs specifically for interrogating the verdict rather than passively reading it, including **"Why?"** (asks the AI to justify the verdict by pointing at specific evidence), **"Challenge This Verdict"** (deliberately pushes back on the AI's own conclusion to see if it holds up), and **"False Positive Check"** (asks the AI to reason about whether this could be a benign result mislabeled as a threat). These exist so that an analyst's natural next question — "why should I believe this?" — has a direct, built-in answer instead of requiring you to take the summary on faith.
- **The AI provenance badge.** Every AI-generated Final Assessment carries a small badge naming exactly which AI backend and model produced it — for example, `groq / llama-3.3-70b-versatile` or `ollama / llama3.2:3b`. This matters because, as noted above, the platform never silently switches or falls back between backends mid-investigation, so the badge is a dependable record rather than a guess: an analyst can always see precisely which AI generated a given conclusion, and can factor that into how much weight to give it (a larger hosted model and a small local model won't necessarily reason about the same evidence with the same thoroughness).

[FIGURE: 18-investigation-benign-ip-full.png | The Evidence Ledger and Verdict Analysis tabs (Why?, What's this?, Score Explanation, Intelligence Conflicts, False Positive Check, Challenge This Verdict) on the 8.8.8.8 investigation, giving an analyst tools to check the AI's verdict against the underlying evidence.]

## 🔀 Switching AI Backends and Getting a Second Opinion

Because the platform supports several interchangeable AI backends, changing which one analyzes your work is a day-to-day action, not an administrator task. A compact **"AI: [dropdown]"** control sits right next to the search bar on the home page, showing whichever backend is currently selected along with a colored dot — green if that backend is actually configured with working credentials, gray if it isn't — and a **Manage** link through to the full provider configuration page. Picking a different backend from the dropdown changes which AI analyzes your next investigation immediately: no restart, no editing configuration files, no detour through a separate settings page.

[FIGURE: 31-home-ai-quickswitch.png | The home page showing the compact "AI:" dropdown (currently "Ollama (local)") and "Manage" control next to the search bar, used to switch which AI backend analyzes the next investigation without leaving the page.]

After picking a different entry from the dropdown, the control immediately reflects the new selection and its real configured status — here, switched to Groq:

[FIGURE: 39-ai-selector-groq-selected.png | The same "AI:" control after switching to Groq — the dropdown and its green configured-status dot update immediately, and this backend is what the next investigation will use.]

This connects directly to the point above about not trusting an AI claim blindly: if you want to check whether a verdict reflects the evidence itself rather than one particular model's read of it, you can ask a second AI to look at the same evidence and see whether it agrees. On a completed investigation's page, the **AI Comparison** panel lets you pick a different backend and click **"Analyze with [backend]"**; the platform re-runs only the final-assessment step against the evidence already collected — it does not re-query any provider — and appends that backend's independent result below the original, with each result clearly labeled by exactly which AI and model produced it. Neither result is presented as more correct than the other; the value is in having a second opinion to weigh against the first, which is especially useful for sanity-checking a verdict, or for spotting cases where two backends actually disagree.

[FIGURE: 36-ai-comparison-panel.png | A completed investigation's AI Comparison panel, showing the original Ollama-generated assessment (verdict, risk score, executive summary) with a ready "Analyze with anthropic" control to append an independent second opinion from a different backend.]

### Ask AI (Gemini Second Opinion) -- a separate, manual escalation path

Alongside AI Comparison, every investigation page (both while it is still running and afterward) shows a smaller **"Ask AI (Gemini second opinion)"** panel in the sidebar. This is a distinct feature, not another view of AI Comparison, and works differently: clicking **"Copy prompt & open Gemini box"** builds a single, detailed analyst-escalation prompt from everything pulled for this IOC so far (provider results, per-provider summaries, and correlation), copies that prompt to your clipboard, and opens a small popup window pointed at `gemini.google.com`. You then paste the prompt into that popup yourself and read Gemini's answer there, signed in with your own personal Google account.

This matters for two reasons an analyst should know before using it. First, it is entirely manual and entirely outside the platform: the platform never sends your IOC data to Gemini itself, has no API credential or integration with Gemini for this feature, and never sees or stores whatever Gemini replies with in the popup -- unlike AI Comparison's result, a Gemini second opinion obtained this way is not saved to the investigation record. Second, because the copied prompt includes the IOC value and every provider result pulled so far, treat it the same way you would treat pasting investigation data into any other outside AI chat tool -- follow your organization's policy on what may leave the platform this way before using it on sensitive investigations.

[FIGURE: 18-investigation-benign-ip-full.png | The full investigation page for 8.8.8.8, with the "Ask AI (Gemini second opinion)" panel and its "Copy prompt & open Gemini box" button visible in the top-right sidebar, below Export and Investigation Actions.]

---

> [!IMPORTANT]
> AI analysis in this product is intended as analytical assistance, not unquestionable truth, and every AI-generated claim is designed to be traceable back to real evidence an analyst can independently check.
