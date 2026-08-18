"""HTTP security-header inspection tool adapter.

Makes exactly one ordinary GET request to the target (the same request any
browser makes) and inspects the response headers -- never a fuzzer, never a
vulnerability-probing request sequence.

Severity rules (deterministic):
- Missing Strict-Transport-Security on an HTTPS response -> `low`
- Missing X-Frame-Options AND no CSP frame-ancestors directive -> `low`
  (clickjacking exposure)
- Missing X-Content-Type-Options -> `info`
- Missing Content-Security-Policy entirely -> `info` (a real gap, but CSP
  correctness varies enough by application that its absence alone doesn't
  warrant a higher severity than informational)
- A verbose `Server`/`X-Powered-By` header revealing a specific version ->
  `info` (a minor information-disclosure note, not a vulnerability by itself)
"""
import httpx

from app.ioc.types import IOCType
from app.security_assessment.base import Finding, ScanProfile, SecurityAssessmentTool, ToolRunResult
from app.providers.base import ProviderStatus

_TIMEOUT_SECONDS = 15

PROFILES: dict[str, ScanProfile] = {
    "standard": ScanProfile(
        id="standard",
        name="Security header check",
        description="One ordinary GET request; inspects the response for standard security headers.",
    ),
}


class HTTPHeadersTool(SecurityAssessmentTool):
    tool_id = "http_headers"
    tool_name = "HTTP Security Headers"
    supported_types = {IOCType.IPV4, IOCType.IPV6, IOCType.DOMAIN, IOCType.HOSTNAME, IOCType.URL}
    profiles = PROFILES

    async def run(self, target: str, ioc_type: IOCType, profile_id: str) -> ToolRunResult:
        if profile_id not in PROFILES:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Unknown scan profile: {profile_id!r}")

        url = target if target.startswith(("http://", "https://")) else f"https://{target}"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
        except httpx.ConnectError:
            if url.startswith("https://"):
                try:
                    async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT_SECONDS) as client:
                        response = await client.get(f"http://{target}")
                        url = f"http://{target}"
                except httpx.HTTPError as exc:
                    return self._error(target, ioc_type, ProviderStatus.ERROR, f"Could not reach {target} over HTTP or HTTPS: {exc}")
            else:
                return self._error(target, ioc_type, ProviderStatus.ERROR, f"Could not reach {target}.")
        except httpx.TimeoutException:
            return self._error(target, ioc_type, ProviderStatus.TIMEOUT, f"Request to {url} timed out.")
        except httpx.HTTPError as exc:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Request to {url} failed: {exc}")

        headers = {k.lower(): v for k, v in response.headers.items()}
        is_https = url.startswith("https://")
        findings: list[Finding] = []

        if is_https and "strict-transport-security" not in headers:
            findings.append(self._finding("missing_hsts", "low", "Missing Strict-Transport-Security header",
                f"{url} is served over HTTPS but does not send Strict-Transport-Security, so a browser will accept a downgraded HTTP connection on a future visit."))

        csp = headers.get("content-security-policy", "")
        if "x-frame-options" not in headers and "frame-ancestors" not in csp:
            findings.append(self._finding("missing_frame_protection", "low", "Missing clickjacking protection",
                f"{url} sends neither X-Frame-Options nor a CSP frame-ancestors directive, so the response can be framed by another site."))

        if "content-security-policy" not in headers:
            findings.append(self._finding("missing_csp", "info", "Missing Content-Security-Policy header",
                f"{url} does not send a Content-Security-Policy header."))

        if "x-content-type-options" not in headers:
            findings.append(self._finding("missing_content_type_options", "info", "Missing X-Content-Type-Options header",
                f"{url} does not send X-Content-Type-Options: nosniff."))

        server = headers.get("server") or headers.get("x-powered-by")
        if server and any(c.isdigit() for c in server):
            findings.append(self._finding("verbose_server_header", "info", "Server header reveals version information",
                f"{url} sent a Server/X-Powered-By header with version detail: {server!r}.", evidence_extra={"header_value": server}))

        if not findings:
            findings.append(self._finding("headers_ok", "info", "No missing security headers detected",
                f"{url} sent all the headers this check looks for."))

        provider_result = self._result(
            target, ioc_type, ProviderStatus.OK,
            data={"http_status": response.status_code, "checked_url": url, "headers_present": sorted(headers.keys())},
        )
        return ToolRunResult(provider_result=provider_result, findings=findings)

    def _finding(self, finding_type: str, severity: str, title: str, description: str, evidence_extra: dict | None = None) -> Finding:
        return Finding(
            tool_id=self.tool_id, finding_type=finding_type, severity=severity, title=title,
            description=description, evidence=evidence_extra or {},
        )


http_headers_tool = HTTPHeadersTool()
