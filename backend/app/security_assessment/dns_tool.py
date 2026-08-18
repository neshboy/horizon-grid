"""DNS record enumeration tool adapter.

Standard, non-recursive record lookups only (A/AAAA/MX/TXT/NS/CAA/SOA) --
deliberately no AXFR zone-transfer attempt (an intrusive technique, not a
normal client query) and no subdomain brute-forcing (explicitly out of
scope, see docs/SECURITY_ASSESSMENT_TOOLKIT.md).

Severity rules (deterministic): resolved records themselves are
informational (`info`) -- DNS enumeration is inherently passive/normal
client behavior, not a vulnerability by itself. The one evidence-based
exception: a domain with no CAA record at all is `low` severity (any
publicly-trusted CA can issue a certificate for it -- a real, narrow,
well-established weakness, not a speculative one).

A/AAAA results are written into ProviderResult.data["resolved_ips"] using
the exact key app/correlation/engine.py's existing extractor table already
recognizes, so a resolved IP becomes a real correlation-graph edge with
zero engine changes.
"""
import dns.asyncresolver
import dns.exception
import dns.resolver

from app.ioc.types import IOCType
from app.security_assessment.base import Finding, ScanProfile, SecurityAssessmentTool, ToolRunResult
from app.providers.base import ProviderStatus

_RECORD_TYPES = ["A", "AAAA", "MX", "TXT", "NS", "CAA", "SOA"]

PROFILES: dict[str, ScanProfile] = {
    "standard": ScanProfile(
        id="standard",
        name="Standard record enumeration",
        description="Looks up A, AAAA, MX, TXT, NS, CAA, and SOA records via ordinary DNS queries.",
    ),
}


class DNSTool(SecurityAssessmentTool):
    tool_id = "dns"
    tool_name = "DNS Record Enumeration"
    supported_types = {IOCType.DOMAIN, IOCType.HOSTNAME}
    profiles = PROFILES

    async def run(self, target: str, ioc_type: IOCType, profile_id: str) -> ToolRunResult:
        if profile_id not in PROFILES:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Unknown scan profile: {profile_id!r}")

        resolver = dns.asyncresolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 10

        records: dict[str, list[str]] = {}
        for record_type in _RECORD_TYPES:
            try:
                answer = await resolver.resolve(target, record_type)
                records[record_type] = [rdata.to_text() for rdata in answer]
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.Timeout, dns.resolver.NoNameservers):
                records[record_type] = []
            except Exception as exc:  # noqa: BLE001 -- normalize any unexpected resolver failure
                return self._error(target, ioc_type, ProviderStatus.ERROR, f"DNS lookup failed: {exc}")

        if not any(records.values()):
            return ToolRunResult(
                provider_result=self._result(target, ioc_type, ProviderStatus.NO_DATA), findings=[]
            )

        findings: list[Finding] = []
        for record_type, values in records.items():
            if not values:
                continue
            findings.append(
                Finding(
                    tool_id=self.tool_id,
                    finding_type="dns_record",
                    severity="info",
                    title=f"{record_type} record(s) found",
                    description=f"{target} has {len(values)} {record_type} record(s): {', '.join(values[:10])}",
                    target_detail=record_type,
                    evidence={"record_type": record_type, "values": values},
                )
            )

        if not records.get("CAA"):
            findings.append(
                Finding(
                    tool_id=self.tool_id,
                    finding_type="dns_record",
                    severity="low",
                    title="No CAA record configured",
                    description=(
                        f"{target} has no CAA (Certification Authority Authorization) record, "
                        "meaning any publicly-trusted certificate authority can issue a certificate "
                        "for this domain without restriction."
                    ),
                    target_detail="CAA",
                    evidence={"record_type": "CAA", "values": []},
                )
            )

        resolved_ips = [ip for ip in records.get("A", []) + records.get("AAAA", [])]
        provider_result = self._result(
            target,
            ioc_type,
            ProviderStatus.OK,
            data={"dns_records": records, "resolved_ips": resolved_ips},
            raw=records,
        )
        return ToolRunResult(provider_result=provider_result, findings=findings)


dns_tool = DNSTool()
