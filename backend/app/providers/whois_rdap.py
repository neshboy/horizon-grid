"""WHOIS (domains) + RDAP (IP/ASN) connector -- no API key required.

Domains are looked up via the blocking `python-whois` library (run off the
event loop with asyncio.to_thread since it opens a raw socket to port 43).
IPv4/IPv6/ASN are looked up via RDAP against https://rdap.org, which
bootstraps to whichever RIR (ARIN/RIPE/APNIC/LACNIC/AFRINIC) actually holds
the record, so a single endpoint covers all of them. See app/providers/base.py
for the BaseProvider contract and app/providers/virustotal.py for the
reference connector style.

Many TLDs have whois servers that return non-standard text python-whois
cannot parse, raising on `.parse()`; those failures are mapped to
ProviderStatus.NO_DATA with the exception message in error_message rather
than propagating, per the WHOIS connector contract.
"""
import asyncio
import re
import socket
from typing import Any, Optional

import httpx
import whois as pywhois
from whois.exceptions import PywhoisError

from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus

# pywhois.whois() defaults to ignore_socket_errors=True, which swallows a
# socket timeout/refused-connection into the response TEXT instead of
# raising -- that text then fails to parse into a domain_name, so it was
# silently reaching the same "no domain_name" NO_DATA branch as a genuine
# unregistered domain. Passing False makes a socket-level failure raise a
# real exception we can map to TIMEOUT/ERROR instead. NICClient's own
# get_socket() already calls settimeout(_WHOIS_SOCKET_TIMEOUT_SECONDS), so
# this can't hang the to_thread executor slot indefinitely either way.
_WHOIS_SOCKET_TIMEOUT_SECONDS = 10

_RDAP_BASE = "https://rdap.org"
_ASN_DIGITS_RE = re.compile(r"(\d+)")


class WhoisRdapProvider(BaseProvider):
    provider_id = "whois_rdap"
    provider_name = "WHOIS/RDAP"
    category = ProviderCategory.WHOIS
    supported_types = {IOCType.DOMAIN, IOCType.IPV4, IOCType.IPV6, IOCType.ASN}
    requires_key = False

    def __init__(self) -> None:
        super().__init__()
        self.configured = True

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        if ioc_type == IOCType.DOMAIN:
            return await self._fetch_whois(ioc_value, ioc_type)
        return await self._fetch_rdap(ioc_value, ioc_type, client)

    # --- Domain WHOIS -----------------------------------------------------

    async def _fetch_whois(self, ioc_value: str, ioc_type: IOCType) -> ProviderResult:
        source_url = f"https://www.whois.com/whois/{ioc_value}"
        try:
            entry = await asyncio.to_thread(
                pywhois.whois,
                ioc_value,
                ignore_socket_errors=False,
                timeout=_WHOIS_SOCKET_TIMEOUT_SECONDS,
            )
        except (socket.timeout, socket.gaierror, ConnectionRefusedError, ConnectionResetError, socket.error) as exc:
            # The TLD's port-43 WHOIS server is unreachable/hung -- a real
            # infrastructure failure, not "this domain has no WHOIS record".
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.TIMEOUT if isinstance(exc, socket.timeout) else ProviderStatus.ERROR,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                error_message=str(exc),
                source_url=source_url,
            )
        except PywhoisError as exc:
            # The WHOIS server responded but python-whois couldn't parse this
            # TLD's non-standard response format -- genuinely "no usable data".
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                error_message=str(exc),
                source_url=source_url,
            )

        if not entry or not entry.get("domain_name"):
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url=source_url,
            )

        name_servers = entry.get("name_servers")
        if isinstance(name_servers, str):
            name_servers = [name_servers]

        registrant = entry.get("org") or entry.get("name")

        data: dict[str, Any] = {
            "registrar": entry.get("registrar"),
            "creation_date": _stringify(entry.get("creation_date")),
            "expiration_date": _stringify(entry.get("expiration_date")),
            "updated_date": _stringify(entry.get("updated_date")),
            "name_servers": sorted({str(ns).lower() for ns in name_servers}) if name_servers else [],
            "registrant": registrant,
            "registrant_country": entry.get("country"),
            "status": entry.get("status"),
            "emails": entry.get("emails"),
            "first_seen": _stringify(entry.get("creation_date")),
            "last_seen": _stringify(entry.get("updated_date")),
        }

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=dict(entry),
            source_url=source_url,
        )

    # --- IP / ASN RDAP ------------------------------------------------------

    async def _fetch_rdap(
        self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient
    ) -> ProviderResult:
        if ioc_type == IOCType.ASN:
            match = _ASN_DIGITS_RE.search(ioc_value)
            asn_number = match.group(1) if match else ioc_value
            url = f"{_RDAP_BASE}/autnum/{asn_number}"
            source_url = url
        else:  # IPV4 / IPV6
            url = f"{_RDAP_BASE}/ip/{ioc_value}"
            source_url = url

        response = await client.get(url, headers={"Accept": "application/rdap+json"})
        if response.status_code == 404:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url=source_url,
            )
        response.raise_for_status()
        payload = response.json()

        entities = payload.get("entities") or []
        mapped_entities = [_map_entity(e) for e in entities]

        registrant = next((e for e in mapped_entities if "registrant" in (e.get("roles") or [])), None)

        # ARIN's RDAP extension exposes originating ASNs for an IP block; other
        # RIRs may omit this field entirely, hence the best-effort .get().
        origin_asns = payload.get("arin_originas0_originautnums") or []

        data: dict[str, Any] = {
            "handle": payload.get("handle"),
            "name": payload.get("name"),
            "country": payload.get("country"),
            "start_address": payload.get("startAddress"),
            "end_address": payload.get("endAddress"),
            "start_autnum": payload.get("startAutnum"),
            "end_autnum": payload.get("endAutnum"),
            "ip_version": payload.get("ipVersion"),
            "type": payload.get("type"),
            "status": payload.get("status"),
            "entities": mapped_entities,
            "registrant": registrant.get("name") if registrant else payload.get("name"),
        }
        if ioc_type == IOCType.ASN:
            data["asn"] = payload.get("handle")
        elif origin_asns:
            data["asn"] = [f"AS{n}" for n in origin_asns]

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url=source_url,
        )


def _stringify(value: Any) -> Optional[Any]:
    """Datetime (or list of datetimes) -> ISO string(s); anything else passes through."""
    if value is None:
        return None
    if isinstance(value, list):
        stringified = [_stringify(v) for v in value]
        return stringified[0] if len(stringified) == 1 else stringified
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _map_entity(entity: dict) -> dict:
    name = None
    for item in (entity.get("vcardArray") or [None, []])[1]:
        if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
            name = item[3]
            break
    return {
        "handle": entity.get("handle"),
        "roles": entity.get("roles"),
        "name": name,
    }


whois_provider = WhoisRdapProvider()
