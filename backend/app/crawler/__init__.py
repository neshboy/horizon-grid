"""Internet Intelligence Collector (OSINT crawler) package.

Exposes `internet_intelligence_provider`, the module-level singleton
BaseProvider instance, matching the same pattern every other connector uses
(see app/providers/virustotal.py). Import this into
app/providers/registry.py to wire it into the orchestrator.
"""
from app.crawler.collector import internet_intelligence_provider

__all__ = ["internet_intelligence_provider"]
