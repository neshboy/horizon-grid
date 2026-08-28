# 🧾 Evidence and Receipts

## Every AI claim comes with a receipt

When the platform finishes investigating an IOC (Indicator of Compromise -- a piece of evidence such as an IP address, domain, URL, file hash, or CVE ID that a security analyst wants to investigate), it doesn't just hand you a paragraph of AI-written analysis and expect you to take it on faith. Underneath every AI explanation sits an **Evidence Ledger**: a list of individual, checkable evidence records, each one built directly from what a specific provider (one of the many third-party threat-intelligence services the platform queries, such as VirusTotal or AbuseIPDB) actually returned, or from a connection the platform's correlation step found between two providers' results.

The Evidence Ledger itself is not written by the AI. It is assembled deterministically from the real provider data and the real correlation output, precisely so that when the AI *does* write a summary, a verdict, or an answer to a question, every meaningful claim in that text can point back to one of these real records instead of being a bare assertion. Each item carries its own source, its own confidence score, and the underlying data it came from -- nothing in the ledger is invented after the fact to make an AI claim look more supported than it is.

On top of the ledger sit several different views an analyst can open on the same evidence -- for example, "Why?", "What's this?", "Score Explanation," "Intelligence Conflicts," "False Positive Check," and "Challenge This Verdict." These are different lenses on the same underlying evidence, not separate, independent opinions. Where an AI explanation cites specific evidence for a specific sentence, "Show receipts" takes you straight from that sentence to the exact evidence record(s) it's based on, instead of leaving you to wonder where a number or a claim came from.

## ⚠️ Why this matters: never take the AI's word for it

This design exists for one reason: an analyst should never have to simply trust an AI's conclusion. The AI is analytical assistance -- it reads, summarizes, and correlates a lot of provider data quickly -- but the underlying evidence, not the AI's prose, is the actual source of truth.

> [!TIP]
> If a claim in a summary can't be traced to a real evidence record, that's a signal to question it, not accept it.

A genuine example from this platform makes the point well. Looking up `8.8.8.8` (Google's Public DNS server, a benign, well-known service) produces a Threat Score of 87 out of 100, rated "High" -- because the Spamhaus provider marked it malicious. But the actual reason string behind that verdict, visible in the evidence itself, is "query error -- public/open resolver not permitted to query Spamhaus" -- a policy rejection from Spamhaus's own lookup service, not a detection of malicious behavior. Meanwhile AbuseIPDB reports zero abuse reports and VirusTotal calls the address clean. The platform's own AI-written Executive Summary is honest about this: it describes the IP as "considered malicious by Spamhaus, but its reputation as a clean and safe IP address is supported by AbuseIPDB and VirusTotal" -- disagreement and all.

This isn't a bug to hide -- it's exactly the kind of case the Evidence Ledger exists for. An analyst who opens the underlying evidence record can read the literal reason for the Spamhaus verdict, recognize it as a lookup-policy quirk rather than a real threat finding, and decide for themselves whether the high score is warranted. That is the whole point: the platform surfaces disagreement and lets you check it, rather than smoothing it over into a single unquestionable number.

[FIGURE: 18-investigation-benign-ip-full.png | For the IOC 8.8.8.8 (Google's public DNS resolver), the Evidence Ledger lists individual, checkable evidence records with confidence scores, alongside the Verdict Analysis tabs (including "Why?" and "Challenge This Verdict") an analyst can use to trace exactly which evidence backs the Executive Summary's statement that Spamhaus flagged the IP while AbuseIPDB and VirusTotal call it clean.]

# 🕸️ Correlation and the Relationship Graph

## What "correlation" means here

Every provider the platform queries only knows about its own narrow slice of the picture. AbuseIPDB knows abuse reports. WHOIS/RDAP knows registration and network-ownership details. VirusTotal knows antivirus-engine detections. On their own, these are just separate lists of facts from separate sources.

**Correlation** is the step where the platform automatically looks across everything the providers returned and notices when two separate findings are actually pointing at the same related fact. A common example: an IP address and the ASN (Autonomous System Number -- an identifier for the network block or organization that owns a range of IP addresses) it belongs to. If one provider reports the IP address and another (or the same provider's WHOIS/RDAP data) reports which network owns it, the platform draws that as a connection rather than leaving you to notice the overlap yourself while reading two separate provider write-ups.

This happens automatically after every provider has finished responding, before the platform writes its final consolidated assessment -- so the AI's overall summary is correlation-aware, not just a stitched-together list of per-provider opinions. When more than one provider corroborates the same underlying fact, the platform's confidence in that connection increases accordingly, since agreement across independent sources is more meaningful than a single provider's claim alone.

## 🔗 The Relationship Graph: seeing connections instead of reading walls of text

The **Relationship Graph** is where these correlated connections become visible. Instead of an analyst reading through several separate provider cards and mentally cross-referencing which facts relate to which, the graph draws each fact as a node and each discovered connection as a line between nodes -- so relationships that would otherwise be buried across multiple paragraphs of provider text are visible at a glance.

In the simplest case, this might be no more than two connected nodes -- for example, an IP address and the single ASN it belongs to. In a richer investigation involving more providers and more shared facts -- such as a vulnerability with related findings pulled together from several sources -- the same graph grows to reflect however many real, corroborated connections the correlation step actually found. In every case, the graph is a visualization of the same underlying evidence discussed above, not a separate or less-verified layer -- it shows relationships the platform can already point to specific evidence for.

[FIGURE: 23-investigation-cve-full.png | For the Log4Shell vulnerability (CVE-2021-44228), the investigation view's Relationship Graph visualizes the correlated connections the platform found around the CVE, letting an analyst see how findings relate to one another at a glance instead of reading each provider's write-up separately to piece the picture together.]
