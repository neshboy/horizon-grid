"""Hash metadata analysis tool adapter.

Scoped deliberately narrowly, per explicit direction: given a hash VALUE
(MD5/SHA1/SHA256/SHA512), identifies which algorithm it is and confirms
it's well-formed hex of the expected length. Nothing here uploads,
downloads, executes, or sandboxes any file -- there is no file involved at
all, only the hash string itself. Real hash-*reputation* lookups (is this
hash known-malicious) already exist via the platform's normal threat-intel
providers (VirusTotal, MalwareBazaar, Hybrid Analysis) when a hash-type IOC
is investigated normally; this tool's only value-add is the format/algorithm
identification itself, exposed through the same toolkit UI/audit trail as
every other security-assessment tool for consistency.

Severity: always `info` -- format identification is never itself a finding
of concern, only a factual note.
"""
from app.ioc.types import HASH_TYPES, IOCType
from app.security_assessment.base import Finding, ScanProfile, SecurityAssessmentTool, ToolRunResult
from app.providers.base import ProviderStatus

_ALGORITHM_BY_TYPE = {
    IOCType.MD5: "MD5",
    IOCType.SHA1: "SHA-1",
    IOCType.SHA256: "SHA-256",
    IOCType.SHA512: "SHA-512",
}

PROFILES: dict[str, ScanProfile] = {
    "standard": ScanProfile(
        id="standard",
        name="Hash format identification",
        description="Identifies the hash algorithm and confirms the value is well-formed. No file involved -- metadata only.",
    ),
}


class HashTool(SecurityAssessmentTool):
    tool_id = "hash_analysis"
    tool_name = "Hash Metadata Analysis"
    supported_types = HASH_TYPES
    profiles = PROFILES

    async def run(self, target: str, ioc_type: IOCType, profile_id: str) -> ToolRunResult:
        if profile_id not in PROFILES:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Unknown scan profile: {profile_id!r}")

        algorithm = _ALGORITHM_BY_TYPE.get(ioc_type)
        if algorithm is None:
            return self._error(target, ioc_type, ProviderStatus.UNSUPPORTED_IOC, f"Not a supported hash type: {ioc_type.value}")

        well_formed = all(c in "0123456789abcdefABCDEF" for c in target)
        finding = Finding(
            tool_id=self.tool_id,
            finding_type="hash_info",
            severity="info",
            title=f"{algorithm} hash",
            description=(
                f"{target} is a well-formed {algorithm} hash ({len(target)} hex characters)."
                if well_formed
                else f"{target} has the expected length for {algorithm} but contains non-hex characters."
            ),
            evidence={"algorithm": algorithm, "length": len(target), "well_formed_hex": well_formed},
        )

        provider_result = self._result(
            target, ioc_type, ProviderStatus.OK,
            data={"algorithm": algorithm, "well_formed_hex": well_formed},
        )
        return ToolRunResult(provider_result=provider_result, findings=[finding])


hash_tool = HashTool()
