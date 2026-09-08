"""TLS/certificate inspection tool adapter.

Performs one ordinary TLS client handshake to the target (the same thing
any browser does), then inspects the certificate chain and negotiated
protocol -- never an exploit, never a downgrade/fuzzing attempt. Certificate
verification is deliberately disabled for the connection itself (so a
self-signed or expired certificate can still be *inspected and reported*
rather than making the connection fail outright); trust/hostname validity
is independently checked and reported as its own finding.

Severity rules (deterministic):
- Certificate already expired -> `high`
- Certificate expires within 14 days -> `medium`
- Self-signed certificate (issuer == subject) -> `medium`
- Certificate valid but the connection didn't verify hostname/trust chain
  cleanly against the platform's default trust store -> `medium`
- Otherwise (valid, trusted, not expiring soon) -> `info`

Known scope limitation, disclosed rather than hidden: this reports the
protocol version negotiated with a normal modern TLS client context. It
does not deliberately attempt to negotiate deprecated protocols (TLS 1.0/
1.1/SSLv3) to test whether the server *would* still accept them if asked --
that would need multiple separate connection attempts with a lowered
`minimum_version`, which was judged out of scope for this pass (not a
"stealth" concern, just deliberately narrower to keep this tool a single,
ordinary-shaped client connection).
"""
import asyncio
import socket
import ssl
from datetime import datetime, timezone
from typing import Optional

from cryptography import x509
from cryptography.hazmat.backends import default_backend

from app.core.url_safety import resolve_safe_address
from app.ioc.types import IOCType
from app.security_assessment.base import Finding, ScanProfile, SecurityAssessmentTool, ToolRunResult
from app.providers.base import ProviderStatus

_TIMEOUT_SECONDS = 15
_EXPIRY_WARNING_DAYS = 14

PROFILES: dict[str, ScanProfile] = {
    "standard": ScanProfile(
        id="standard",
        name="Certificate inspection",
        description="One ordinary TLS handshake; inspects the certificate chain, expiry, and negotiated protocol.",
    ),
}


def _connect_sync(host: str, port: int, allow_private: bool = False) -> dict:
    # Resolve `host` to a single, just-validated address ONCE here, then
    # connect to THAT exact address for both handshakes below -- never let
    # socket.create_connection(host, port) resolve `host` itself, which
    # would be a second, independent, later DNS lookup of the same
    # (potentially attacker-controlled) hostname. That gap is the confirmed
    # DNS-rebinding TOCTOU this closes: app/core/security_assessment.py's
    # _validate_scope already checks `host` once, well before this function
    # ever runs (a separately-scheduled background task), and a caller who
    # controls this hostname's DNS (TTL=0 / rapid rebind) could otherwise
    # return a safe public address for that earlier check and an internal
    # address for the real connection performed here. Resolving once, right
    # before use, and pinning the connection to exactly that validated
    # result makes the check and the connection atomic. Raises ValueError
    # (caught by TLSTool.run below) if the resolved address is not safe to
    # connect to.
    #
    # allow_private is threaded through from TLSTool.run's own caller: the
    # Pentest Suite (app/pentest/orchestrator.py) passes True here, having
    # already authorized this exact target against its own operator-
    # declared scope (which legitimately includes RFC1918 targets -- see
    # resolve_safe_address's own docstring) -- the per-lookup Security
    # Assessment Toolkit never sets it, leaving the strict default in place.
    connect_ip = resolve_safe_address(host, allow_private=allow_private)

    permissive = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    permissive.check_hostname = False
    permissive.verify_mode = ssl.CERT_NONE

    with socket.create_connection((connect_ip, port), timeout=_TIMEOUT_SECONDS) as sock:
        with permissive.wrap_socket(sock, server_hostname=host) as ssock:
            der_cert = ssock.getpeercert(binary_form=True)
            protocol_version = ssock.version()
            cipher = ssock.cipher()

    trusted = False
    try:
        strict = ssl.create_default_context()
        with socket.create_connection((connect_ip, port), timeout=_TIMEOUT_SECONDS) as sock:
            with strict.wrap_socket(sock, server_hostname=host):
                trusted = True
    except ssl.SSLError:
        trusted = False
    except OSError:
        trusted = False

    return {"der_cert": der_cert, "protocol_version": protocol_version, "cipher": cipher, "trusted": trusted}


class TLSTool(SecurityAssessmentTool):
    tool_id = "tls"
    tool_name = "TLS Certificate Inspection"
    supported_types = {IOCType.IPV4, IOCType.IPV6, IOCType.DOMAIN, IOCType.HOSTNAME, IOCType.URL}
    profiles = PROFILES

    async def run(self, target: str, ioc_type: IOCType, profile_id: str, port: Optional[int] = None, allow_private: bool = False) -> ToolRunResult:
        """`port` is the caller-declared port to connect to (e.g.
        PentestTarget.port), if any -- see _host_and_port below for exactly
        how it interacts with a port already embedded in a URL-typed
        target. Optional and defaulted to None so every existing caller
        (the per-lookup Security Assessment Toolkit never sets it) is
        unaffected.

        `allow_private`: see resolve_safe_address's own docstring. Only the
        Pentest Suite orchestrator sets this True, and only after its own
        scope-authorization check for this exact target -- the per-lookup
        Security Assessment Toolkit never sets it, so its behavior (reject
        any private/RFC1918 target) is completely unchanged."""
        if profile_id not in PROFILES:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Unknown scan profile: {profile_id!r}")

        host, port = self._host_and_port(target, ioc_type, port)

        try:
            conn = await asyncio.wait_for(asyncio.to_thread(_connect_sync, host, port, allow_private), timeout=_TIMEOUT_SECONDS + 5)
        except asyncio.TimeoutError:
            return self._error(target, ioc_type, ProviderStatus.TIMEOUT, f"TLS handshake to {host}:{port} timed out.")
        except ValueError as exc:
            # Raised by resolve_safe_address inside _connect_sync when the
            # address `host` resolves to right now is not safe to connect
            # to (private/link-local/reserved) -- see that function's
            # docstring for the DNS-rebinding TOCTOU this closes.
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Refusing to connect to {host}:{port}: {exc}")
        except (ssl.SSLError, OSError) as exc:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Could not establish a TLS connection to {host}:{port}: {exc}")

        if conn["der_cert"] is None:
            return self._error(target, ioc_type, ProviderStatus.NO_DATA, "Server presented no certificate.")

        cert = x509.load_der_x509_certificate(conn["der_cert"], default_backend())
        not_after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_until_expiry = (not_after - now).days
        self_signed = cert.issuer == cert.subject
        subject = cert.subject.rfc4514_string()
        issuer = cert.issuer.rfc4514_string()

        findings: list[Finding] = []
        if days_until_expiry < 0:
            findings.append(
                Finding(
                    tool_id=self.tool_id, finding_type="tls_issue", severity="high",
                    title="TLS certificate has expired",
                    description=f"The certificate for {host} expired {-days_until_expiry} day(s) ago (on {not_after.date()}).",
                    target_detail=f"{host}:{port}", evidence={"not_after": not_after.isoformat(), "subject": subject},
                )
            )
        elif days_until_expiry <= _EXPIRY_WARNING_DAYS:
            findings.append(
                Finding(
                    tool_id=self.tool_id, finding_type="tls_issue", severity="medium",
                    title="TLS certificate expires soon",
                    description=f"The certificate for {host} expires in {days_until_expiry} day(s) (on {not_after.date()}).",
                    target_detail=f"{host}:{port}", evidence={"not_after": not_after.isoformat(), "subject": subject},
                )
            )
        else:
            findings.append(
                Finding(
                    tool_id=self.tool_id, finding_type="tls_issue", severity="info",
                    title="TLS certificate validity",
                    description=f"The certificate for {host} is valid until {not_after.date()} ({days_until_expiry} days).",
                    target_detail=f"{host}:{port}", evidence={"not_after": not_after.isoformat(), "subject": subject},
                )
            )

        if self_signed:
            findings.append(
                Finding(
                    tool_id=self.tool_id, finding_type="tls_issue", severity="medium",
                    title="Self-signed certificate",
                    description=f"The certificate presented by {host} is self-signed (issuer == subject: {issuer}).",
                    target_detail=f"{host}:{port}", evidence={"issuer": issuer, "subject": subject},
                )
            )

        if not conn["trusted"] and not self_signed:
            findings.append(
                Finding(
                    tool_id=self.tool_id, finding_type="tls_issue", severity="medium",
                    title="Certificate did not verify against the trust store",
                    description=f"The certificate chain for {host} did not verify cleanly (not a simple self-signed case) -- possible hostname mismatch or missing intermediate certificate.",
                    target_detail=f"{host}:{port}", evidence={"subject": subject, "issuer": issuer},
                )
            )

        provider_result = self._result(
            target, ioc_type, ProviderStatus.OK,
            data={
                "certificates": [subject],
                "tls_protocol": conn["protocol_version"],
                "tls_cipher": conn["cipher"][0] if conn["cipher"] else None,
                "certificate_subject": subject,
                "certificate_issuer": issuer,
                "certificate_not_after": not_after.isoformat(),
                "self_signed": self_signed,
                "trusted": conn["trusted"],
            },
        )
        return ToolRunResult(provider_result=provider_result, findings=findings)

    @staticmethod
    def _host_and_port(target: str, ioc_type: IOCType, port_override: Optional[int] = None) -> tuple[str, int]:
        """`port_override` (a caller-declared port, e.g. PentestTarget.port)
        wins over this method's own hardcoded defaults, but a port already
        embedded in a URL-typed target string wins over even that -- the
        most specific source of the port (parsed straight out of the target
        the caller gave us) always beats a separately-supplied override.

        P1 fixed here: this used to hardcode 443 for every non-URL target
        (ipv4/ipv6/domain/hostname) with no way for a caller to say
        otherwise, so a Pentest Suite target declared with an explicit port
        (e.g. 172.19.0.4:9200) was silently probed on 443 instead -- a
        connection failure against the wrong port, reported identically to
        a genuinely clean scan of the right one."""
        default_port = port_override if port_override is not None else 443
        if ioc_type == IOCType.URL:
            from urllib.parse import urlsplit

            parts = urlsplit(target if "//" in target else f"//{target}")
            url_default = port_override if port_override is not None else (443 if parts.scheme != "http" else 80)
            return parts.hostname or target, parts.port or url_default
        return target, default_port


tls_tool = TLSTool()
