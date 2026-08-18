"""Security Assessment Toolkit -- active checks against a target itself
(Nmap port/service scan, DNS enumeration, TLS/certificate inspection, HTTP
security-header checks, vulnerability-intelligence enrichment, hash-metadata
analysis), as opposed to every existing provider under app/providers/, which
only ever queries a third party's already-collected data about the target.

Deliberately NOT registered in app/providers/registry.py and never run by
the automatic per-investigation orchestrator fan-out (app/providers/
orchestrator.py) -- every tool here is invoked only through an explicit,
authorization-gated call (app/api/routes/security_assessment.py), never
silently, and never against a target the caller hasn't just retyped to
confirm. See app/security_assessment/base.py for the tool contract and
docs/SECURITY_ASSESSMENT_TOOLKIT.md for the full safety/scope writeup.
"""
