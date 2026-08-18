"""Registry of security-assessment tools -- mirrors app/providers/registry.py's
shape (a flat list built by import) but is DELIBERATELY separate from it:
these tools must never be picked up by the automatic per-investigation
orchestrator fan-out. Adding a tool here is a two-line change (import +
append), same as app/providers/registry.py.

vuln_intel.py is not listed here -- it's an internal enrichment helper
nmap_tool.py calls directly, not a standalone user-selectable tool.
"""
from app.security_assessment.base import SecurityAssessmentTool
from app.security_assessment.dns_tool import dns_tool
from app.security_assessment.hash_tool import hash_tool
from app.security_assessment.http_headers_tool import http_headers_tool
from app.security_assessment.nmap_tool import nmap_tool
from app.security_assessment.tls_tool import tls_tool

_ALL_TOOLS: list[SecurityAssessmentTool] = [
    nmap_tool,
    dns_tool,
    tls_tool,
    http_headers_tool,
    hash_tool,
]


def get_all_tools() -> list[SecurityAssessmentTool]:
    return _ALL_TOOLS


def get_tool(tool_id: str) -> SecurityAssessmentTool | None:
    return next((t for t in _ALL_TOOLS if t.tool_id == tool_id), None)
