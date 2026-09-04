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
import asyncio

import httpx

from app.core.url_safety import assert_globally_routable_target
from app.ioc.types import IOCType
from app.security_assessment.base import Finding, ScanProfile, SecurityAssessmentTool, ToolRunResult
from app.providers.base import ProviderStatus

_TIMEOUT_SECONDS = 15
_MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)

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
            response, url = await self._get_with_validated_redirects(url)
        except httpx.ConnectError:
            if url.startswith("https://"):
                try:
                    response, url = await self._get_with_validated_redirects(f"http://{target}")
                except httpx.HTTPError as exc:
                    return self._error(target, ioc_type, ProviderStatus.ERROR, f"Could not reach {target} over HTTP or HTTPS: {exc}")
                except ValueError as exc:
                    return self._error(target, ioc_type, ProviderStatus.ERROR, f"Refusing to follow a redirect for {target}: {exc}")
            else:
                return self._error(target, ioc_type, ProviderStatus.ERROR, f"Could not reach {target}.")
        except httpx.TimeoutException:
            return self._error(target, ioc_type, ProviderStatus.TIMEOUT, f"Request to {url} timed out.")
        except ValueError as exc:
            # Real SSRF-via-redirect gap found live during overnight QA:
            # follow_redirects=True used to follow a redirect chain with
            # zero re-validation of each hop against the globally-routable-
            # target check the caller already ran against the ORIGINAL
            # target -- a target that redirected to e.g. a cloud metadata
            # address or another docker-compose service's real internal IP
            # would be fetched for real. Every hop is now checked the same
            # way the original target was (see _get_with_validated_redirects).
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Refusing to follow a redirect for {target}: {exc}")
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

    async def _get_with_validated_redirects(self, url: str) -> tuple[httpx.Response, str]:
        """Manually follows redirects -- httpx's own follow_redirects=True
        does this with zero re-validation of each hop. Real SSRF-via-
        redirect gap found live during overnight QA: a target that
        redirected to a cloud metadata address or another docker-compose
        service's real internal IP would be fetched for real, completely
        bypassing the globally-routable-target check the caller already ran
        against the ORIGINAL target before this tool was ever invoked. Every
        hop gets that exact same check now, not just the first one."""
        async with httpx.AsyncClient(follow_redirects=False, timeout=_TIMEOUT_SECONDS) as client:
            current_url = url
            for _ in range(_MAX_REDIRECTS + 1):
                response = await client.get(current_url)
                if response.status_code not in _REDIRECT_STATUS_CODES or "location" not in response.headers:
                    return response, current_url
                next_url = str(httpx.URL(current_url).join(response.headers["location"]))
                # assert_globally_routable_target does a real (blocking) DNS
                # lookup -- off-loaded to a thread so this new redirect-
                # validation call doesn't introduce the same event-loop-
                # blocking class of bug just fixed in
                # app/pentest/orchestrator.py's _is_in_scope.
                await asyncio.to_thread(assert_globally_routable_target, IOCType.URL.value, next_url)
                current_url = next_url
        raise httpx.TooManyRedirects(f"Exceeded {_MAX_REDIRECTS} redirects while fetching {url}")

    def _finding(self, finding_type: str, severity: str, title: str, description: str, evidence_extra: dict | None = None) -> Finding:
        return Finding(
            tool_id=self.tool_id, finding_type=finding_type, severity=severity, title=title,
            description=description, evidence=evidence_extra or {},
        )


http_headers_tool = HTTPHeadersTool()
