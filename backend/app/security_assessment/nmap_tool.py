"""Nmap port/service-scan tool adapter.

Safety boundaries (see docs/SECURITY_ASSESSMENT_TOOLKIT.md for the full
writeup, restated briefly here since this is the one tool in this package
that executes an external binary):

- Every profile below is a HARDCODED argv list. There is no code path from
  caller input to a raw flag or raw command string -- the caller only ever
  selects a profile `id` from `PROFILES`, checked by app/api/routes/
  security_assessment.py against this exact dict before this module is
  ever invoked.
- Invoked via asyncio.create_subprocess_exec with an explicit argument
  LIST, never create_subprocess_shell and never string concatenation of
  the target into a command line -- the target is one argv element,
  passed to the subprocess API directly, never interpolated into a string
  Nmap or a shell then re-parses.
- No profile includes: `--script` (NSE = arbitrary code execution), `-O`
  (OS fingerprinting, needs raw sockets), `-sS`/`-sU` (raw-socket SYN/UDP
  scans -- more intrusive and typically require elevated capabilities),
  or any timing/decoy/spoofing evasion flag (`-D`, `-f`, `--source-port`,
  sneaky `-T0`/`-T1`). This tool never behaves differently to avoid
  detection.
- Every run is wall-clock timeboxed (`_TIMEOUT_SECONDS`); the subprocess is
  killed, not left running, on timeout.
- A CIDR target is capped at 16 addresses (/28) by the caller
  (app/api/routes/security_assessment.py) before this module ever runs --
  Nmap natively understands CIDR notation, so the whole network string is
  passed as one target argument, no per-host loop needed.

Severity rules (deterministic, evidence-based -- never "ask the AI"):
- Open port, no identified service/version -> INFO
- Open port with an identified service/version, no CVE match -> LOW
- Open port whose service/version matches a CVE (found via
  app/security_assessment/vuln_intel.py) with CVSS < 7.0 -> MEDIUM
- ... with CVSS 7.0-8.9 or severity HIGH -> HIGH
- ... with CVSS >= 9.0 or severity CRITICAL -> CRITICAL
"""
import asyncio
import ipaddress
import shutil
import xml.etree.ElementTree as ET

import httpx

from app.ioc.types import IOCType
from app.security_assessment.base import Finding, ScanProfile, SecurityAssessmentTool, ToolRunResult
from app.security_assessment.vuln_intel import search_cves_by_service
from app.providers.base import ProviderStatus

_TIMEOUT_SECONDS = 120


def _timeout_for(target: str, ioc_type: IOCType) -> int:
    """Real gap fixed: _TIMEOUT_SECONDS was a single flat constant applied
    identically to a single host and to a full /28 CIDR (up to 16 addresses,
    the cap enforced in app/core/security_assessment.py's _validate_scope)
    -- the same wall-clock budget for up to 16x the scan work, risking a
    spurious timeout on the largest permitted target with no slack margin.
    Scales linearly with host count for a CIDR target, capped at 8x (not a
    full 16x) since nmap parallelizes host probing rather than scanning
    each address in strict serial -- a full 16x budget would be overly
    generous, not just safe."""
    if ioc_type != IOCType.CIDR:
        return _TIMEOUT_SECONDS
    try:
        num_addresses = ipaddress.ip_network(target, strict=False).num_addresses
    except ValueError:
        return _TIMEOUT_SECONDS
    scale = min(max(num_addresses, 1), 8)
    return _TIMEOUT_SECONDS * scale

PROFILES: dict[str, ScanProfile] = {
    "quick": ScanProfile(
        id="quick",
        name="Quick scan",
        description="The 100 most common ports, service detection off. Fastest, lowest-footprint option.",
    ),
    "standard": ScanProfile(
        id="standard",
        name="Standard scan",
        description="The 1000 most common ports with service/version detection. The default recommended profile.",
    ),
    "web": ScanProfile(
        id="web",
        name="Web service scan",
        description="Only the common web ports (80, 443, 8080, 8443) with service/version detection.",
    ),
}

_PROFILE_ARGS: dict[str, list[str]] = {
    "quick": ["-T4", "-F", "--top-ports", "100"],
    "standard": ["-sV", "-T4", "--top-ports", "1000"],
    "web": ["-p", "80,443,8080,8443", "-sV"],
}


def _severity_for_cves(cves: list[dict]) -> str:
    if not cves:
        return "low"
    best_score = max((c.get("cvss_score") or 0) for c in cves)
    best_severity = {(c.get("cvss_severity") or "").upper() for c in cves}
    if best_score >= 9.0 or "CRITICAL" in best_severity:
        return "critical"
    if best_score >= 7.0 or "HIGH" in best_severity:
        return "high"
    return "medium"


class NmapTool(SecurityAssessmentTool):
    tool_id = "nmap"
    tool_name = "Nmap Port/Service Scan"
    supported_types = {IOCType.IPV4, IOCType.IPV6, IOCType.DOMAIN, IOCType.HOSTNAME, IOCType.CIDR}
    profiles = PROFILES

    async def is_available(self) -> bool:
        return shutil.which("nmap") is not None

    async def run(self, target: str, ioc_type: IOCType, profile_id: str) -> ToolRunResult:
        if not await self.is_available():
            return self._error(target, ioc_type, ProviderStatus.ERROR, "nmap is not installed on this host.")
        if profile_id not in _PROFILE_ARGS:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Unknown scan profile: {profile_id!r}")
        if target.startswith("-"):
            # Confirmed live during overnight QA (CWE-88): nmap's own argv
            # parser -- not a shell -- treats a leading '-' as the start of
            # a flag, not part of a hostname/IP. A target of e.g.
            # "--script=vuln.example.com" (paired with ioc_type_hint=domain
            # to bypass app/ioc/detector.py's classification upstream) was
            # accepted here and successfully loaded nmap's real NSE "vuln"
            # script category -- exactly the "no code path to --script"
            # invariant this module's own docstring documents as guaranteed.
            # Upstream validation (app/core/security_assessment.py's
            # _validate_scope, app/pentest/orchestrator.py's _is_in_scope)
            # now also rejects this shape before it ever reaches here; this
            # is deliberate defense-in-depth at the actual argv boundary.
            return self._error(
                target, ioc_type, ProviderStatus.ERROR,
                f"Refusing to scan {target!r}: a target may never start with '-' "
                "(nmap's argument parser would treat it as a flag, not a hostname).",
            )

        # nmap requires an explicit "-6" flag for any IPv6 literal target --
        # without it, nmap treats the argument as malformed, prints a
        # warning to stderr, and exits 0 having scanned 0 hosts. Confirmed
        # live: this was previously silently reported as a normal
        # "completed, 0 findings" result, indistinguishable from a real
        # clean scan, even though supported_types above has always claimed
        # IPv6 support and no scan of any kind ever actually ran.
        ipv6_flag = ["-6"] if ioc_type == IOCType.IPV6 else []
        argv = ["nmap", "-oX", "-", *ipv6_flag, *_PROFILE_ARGS[profile_id], target]
        timeout_seconds = _timeout_for(target, ioc_type)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return self._error(
                    target, ioc_type, ProviderStatus.TIMEOUT, f"Scan exceeded {timeout_seconds}s and was stopped."
                )
            except asyncio.CancelledError:
                # A user-initiated cancel (app/core/security_assessment.py's
                # cancel_run()) cancels the asyncio.Task awaiting this
                # coroutine, which surfaces here as CancelledError at this
                # exact await point. Without killing the real OS process
                # explicitly, it would keep running as an orphan -- nmap
                # itself has no idea its caller stopped waiting on it.
                proc.kill()
                await proc.wait()
                raise
        except FileNotFoundError:
            return self._error(target, ioc_type, ProviderStatus.ERROR, "nmap is not installed on this host.")

        if proc.returncode != 0:
            return self._error(
                target, ioc_type, ProviderStatus.ERROR, f"nmap exited {proc.returncode}: {stderr.decode(errors='replace')[:500]}"
            )

        try:
            hosts = self._parse_xml(stdout.decode(errors="replace"))
        except ET.ParseError as exc:
            return self._error(target, ioc_type, ProviderStatus.ERROR, f"Could not parse nmap output: {exc}")

        findings: list[Finding] = []
        open_ports: list[dict] = []
        async with httpx.AsyncClient() as client:
            for host in hosts:
                for port in host["ports"]:
                    if port["state"] != "open":
                        continue
                    service = port.get("service") or {}
                    product, version = service.get("product"), service.get("version")
                    cves: list[dict] = []
                    if product:
                        cves = await search_cves_by_service(client, product, version)

                    target_detail = f"{port['protocol']}/{port['portid']}"
                    banner = " ".join(filter(None, [service.get("name"), product, version]))
                    open_ports.append(
                        {
                            "host": host["address"],
                            "port": port["portid"],
                            "protocol": port["protocol"],
                            "service": service.get("name"),
                            "product": product,
                            "version": version,
                            "cves": [c["cve_id"] for c in cves],
                        }
                    )

                    if not product:
                        severity, title = "info", f"Open port {target_detail}"
                        description = f"Port {target_detail} is open{f' ({banner})' if banner else ''}; no service/version identified."
                    elif not cves:
                        severity, title = "low", f"Open port {target_detail} running {banner}"
                        description = f"Port {target_detail} is open, running {banner}. No known CVEs matched this service/version."
                    else:
                        severity = _severity_for_cves(cves)
                        title = f"Open port {target_detail} running {banner} -- {len(cves)} possible CVE(s)"
                        description = (
                            f"Port {target_detail} is open, running {banner}, which matches "
                            f"{len(cves)} CVE(s) in NVD. Confirm applicability before treating as exploitable -- "
                            f"a keyword/CPE match is not a confirmed vulnerable configuration."
                        )

                    findings.append(
                        Finding(
                            tool_id=self.tool_id,
                            finding_type="open_port",
                            severity=severity,
                            title=title,
                            description=description,
                            target_detail=target_detail,
                            cve_ids=[c["cve_id"] for c in cves],
                            evidence={"host": host["address"], "port": port, "cves": cves},
                        )
                    )

        provider_result = self._result(
            target,
            ioc_type,
            ProviderStatus.OK if open_ports else ProviderStatus.NO_DATA,
            data={
                "open_ports": open_ports,
                "cves": sorted({cve for p in open_ports for cve in p["cves"]}),
            },
            raw=stdout.decode(errors="replace"),
        )
        return ToolRunResult(provider_result=provider_result, findings=findings)

    @staticmethod
    def _parse_xml(xml_text: str) -> list[dict]:
        root = ET.fromstring(xml_text)
        hosts = []
        for host_el in root.findall("host"):
            status = host_el.find("status")
            if status is not None and status.get("state") != "up":
                continue
            address_el = host_el.find("address")
            address = address_el.get("addr") if address_el is not None else None
            ports = []
            ports_el = host_el.find("ports")
            if ports_el is not None:
                for port_el in ports_el.findall("port"):
                    state_el = port_el.find("state")
                    service_el = port_el.find("service")
                    ports.append(
                        {
                            "protocol": port_el.get("protocol"),
                            "portid": port_el.get("portid"),
                            "state": state_el.get("state") if state_el is not None else "unknown",
                            "service": (
                                {
                                    "name": service_el.get("name"),
                                    "product": service_el.get("product"),
                                    "version": service_el.get("version"),
                                }
                                if service_el is not None
                                else None
                            ),
                        }
                    )
            hosts.append({"address": address, "ports": ports})
        return hosts


nmap_tool = NmapTool()
