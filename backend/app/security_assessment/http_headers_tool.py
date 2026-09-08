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
import ipaddress
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.url_safety import resolve_safe_address
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


def _pin_to_resolved_address(url: str, allow_private: bool = False) -> tuple[str, str, str]:
    """Resolves `url`'s host to a single, just-validated address ONCE (via
    resolve_safe_address, mirroring tls_tool.py's own _connect_sync) and
    returns (pinned_url, sni_hostname, host_header) -- pinned_url has its
    host replaced by that exact validated address, so the real outbound
    connection below is guaranteed to land on the same address that was
    just validated, never a second, independent, later DNS lookup of the
    same (potentially attacker-controlled) hostname performed by httpx
    itself. This is the same confirmed DNS-rebinding TOCTOU documented on
    resolve_safe_address's docstring: app/core/security_assessment.py's
    _validate_scope checks this hostname exactly once, well before this
    coroutine ever runs (a separately scheduled background task) -- a
    caller who controls this hostname's DNS (TTL=0 / rapid rebind) could
    otherwise return a safe public address for that earlier check and a
    private/internal address for httpx's own later resolution.

    sni_hostname/host_header preserve the ORIGINAL hostname for the TLS
    ClientHello + certificate-hostname verification (httpx/httpcore's
    "sni_hostname" request extension) and the HTTP Host header respectively
    -- the caller must pass both through on the actual request, never let
    httpx derive them from the pinned (IP-literal) URL, or a virtual-hosted
    target would silently receive the wrong site and any real TLS cert
    would fail to verify against the IP literal.

    Raises ValueError if the resolved address is not safe to connect to.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise ValueError("URL has no host.")
    host_header = parts.netloc
    # allow_private is threaded through from HTTPHeadersTool.run's own
    # caller: the Pentest Suite (app/pentest/orchestrator.py) passes True
    # here, having already authorized this exact target against its own
    # operator-declared scope (which legitimately includes RFC1918 targets
    # -- see resolve_safe_address's own docstring) -- the per-lookup
    # Security Assessment Toolkit never sets it, leaving the strict default
    # in place.
    connect_ip = resolve_safe_address(host, allow_private=allow_private)
    try:
        if ipaddress.ip_address(connect_ip).version == 6:
            connect_ip = f"[{connect_ip}]"
    except ValueError:
        pass
    pinned_netloc = connect_ip if parts.port is None else f"{connect_ip}:{parts.port}"
    pinned_url = urlunsplit((parts.scheme, pinned_netloc, parts.path, parts.query, parts.fragment))
    return pinned_url, host, host_header


class HTTPHeadersTool(SecurityAssessmentTool):
    tool_id = "http_headers"
    tool_name = "HTTP Security Headers"
    supported_types = {IOCType.IPV4, IOCType.IPV6, IOCType.DOMAIN, IOCType.HOSTNAME, IOCType.URL}
    profiles = PROFILES

    async def run(self, target: str, ioc_type: IOCType, profile_id: str, port: Optional[int] = None, allow_private: bool = False) -> ToolRunResult:
        """`port` is the caller-declared port to connect to (e.g.
        PentestTarget.port), if any. Only applied when `target` is a bare
        host (ipv4/ipv6/domain/hostname) -- a URL-typed target already
        carries its own explicit port in the string, which wins. Optional
        and defaulted to None so every existing caller (the per-lookup
        Security Assessment Toolkit never sets it) is unaffected.

        `allow_private`: see resolve_safe_address's own docstring. Only the
        Pentest Suite orchestrator sets this True, and only after its own
        scope-authorization check for this exact target -- the per-lookup
        Security Assessment Toolkit never sets it, so its behavior (reject
        any private/RFC1918 target) is completely unchanged.

        P1 fixed here: this used to always build `https://{target}` (or
        fall back to plain `http://{target}` on ConnectError, i.e. port 80)
        with no way for a caller to say otherwise, so a Pentest Suite
        target declared with an explicit port (e.g. 172.19.0.4:9200) was
        silently probed on 443/80 instead -- a connection failure against
        the wrong port, reported identically to a genuinely clean scan of
        the right one."""
        is_bare_host = not target.startswith(("http://", "https://"))
        if not is_bare_host:
            url = target
        elif port is not None:
            url = f"https://{target}:{port}"
        else:
            url = f"https://{target}"

        # Resolve+pin the connection to a single validated address ONCE
        # (see _pin_to_resolved_address's docstring) rather than handing
        # httpx the raw hostname and letting it perform its own,
        # independent, later DNS resolution -- the confirmed DNS-rebinding
        # TOCTOU app/core/url_safety.py's resolve_safe_address exists to
        # close, mirroring tls_tool.py's own _connect_sync.
        try:
            # resolve_safe_address (called inside _pin_to_resolved_address)
            # is a plain synchronous function -- a real blocking DNS lookup
            # -- run in a worker thread via asyncio.to_thread, exactly like
            # tls_tool.py's own _connect_sync, rather than calling it
            # directly on this coroutine's event loop thread.
            pinned_url, sni_host, host_header = await asyncio.to_thread(_pin_to_resolved_address, url, allow_private)
        except ValueError as exc:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Refusing to connect to {url}: {exc}")

        try:
            # Every hop (including this first one) is followed via
            # _get_with_validated_redirects, which re-validates AND re-pins
            # each redirect target exactly the same way this initial
            # pinned_url/sni_host/host_header were just produced -- see that
            # method's own docstring for the two distinct gaps (SSRF-via-
            # redirect, and this same DNS-rebinding TOCTOU on later hops)
            # this closes together.
            response, url, sni_host, host_header = await self._get_with_validated_redirects(
                pinned_url, url, sni_host, host_header, allow_private
            )
        except httpx.ConnectError:
            if url.startswith("https://"):
                try:
                    fallback_url = f"http://{target}:{port}" if (is_bare_host and port is not None) else f"http://{target}"
                    pinned_fallback, sni_host, host_header = await asyncio.to_thread(_pin_to_resolved_address, fallback_url, allow_private)
                    response, url, sni_host, host_header = await self._get_with_validated_redirects(
                        pinned_fallback, fallback_url, sni_host, host_header, allow_private
                    )
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

    async def _get_with_validated_redirects(
        self, pinned_url: str, url: str, sni_host: str, host_header: str, allow_private: bool
    ) -> tuple[httpx.Response, str, str, str]:
        """Manually follows redirects, re-validating AND re-pinning every
        hop -- httpx's own follow_redirects=True does neither. Two real gaps
        found live during overnight QA, closed here together:

        (1) SSRF-via-redirect: with follow_redirects=True, a target that
        redirected to a cloud metadata address or another docker-compose
        service's real internal IP would be fetched for real, completely
        bypassing the globally-routable-target check the caller already ran
        against the ORIGINAL target before this tool was ever invoked. Every
        hop gets that exact same check now, not just the first one.

        (2) The same DNS-rebinding TOCTOU _pin_to_resolved_address exists to
        close for the first hop (see its own docstring) applies equally to
        every redirect hop -- a `location` header names a hostname the
        target itself controls, exactly the "caller controls this
        hostname's DNS" shape that check exists for. Handing httpx a bare
        redirect URL would let it perform its own later, independent
        resolution of that hostname, defeating the check the same way an
        unpinned first request would.

        `pinned_url`/`sni_host`/`host_header` are the caller's own already-
        resolved-and-validated first hop (from _pin_to_resolved_address),
        passed in rather than re-resolved here so the caller's own initial
        ValueError handling (a distinct "refusing to connect" for the first
        hop vs this loop's "refusing to follow a redirect" for later ones)
        stays intact. `url` is the corresponding not-yet-pinned hostname
        URL, threaded through purely so the RETURNED url (used for
        `checked_url` and HSTS/CSP messages) is the human-readable hostname
        form, never a raw pinned IP literal."""
        async with httpx.AsyncClient(follow_redirects=False, timeout=_TIMEOUT_SECONDS) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                response = await client.get(pinned_url, headers={"Host": host_header}, extensions={"sni_hostname": sni_host})
                if response.status_code not in _REDIRECT_STATUS_CODES or "location" not in response.headers:
                    return response, url, sni_host, host_header
                url = str(httpx.URL(url).join(response.headers["location"]))
                # _pin_to_resolved_address (via resolve_safe_address) does a
                # real (blocking) DNS lookup -- off-loaded to a thread so
                # this redirect-validation call doesn't introduce the same
                # event-loop-blocking class of bug just fixed in
                # app/pentest/orchestrator.py's _is_in_scope. allow_private
                # is threaded through so a redirect hop is held to the exact
                # same policy (strict for the per-lookup Security Assessment
                # Toolkit, RFC1918-permitting for an already scope-
                # authorized Pentest Suite target) as the original request.
                pinned_url, sni_host, host_header = await asyncio.to_thread(_pin_to_resolved_address, url, allow_private)
        raise httpx.TooManyRedirects(f"Exceeded {_MAX_REDIRECTS} redirects while fetching {url}")

    def _finding(self, finding_type: str, severity: str, title: str, description: str, evidence_extra: dict | None = None) -> Finding:
        return Finding(
            tool_id=self.tool_id, finding_type=finding_type, severity=severity, title=title,
            description=description, evidence=evidence_extra or {},
        )


http_headers_tool = HTTPHeadersTool()
