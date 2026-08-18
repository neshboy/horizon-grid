"""Spamhaus DBL/ZEN DNSBL connector -- free public DNS-based blocklist lookups.

Unlike the other stub connectors, this one needs no API key: Spamhaus's ZEN
(combined SBL+XBL+PBL IP reputation list) and DBL (Domain Block List) are
queried via plain DNS A-record lookups against the public
`*.zen.spamhaus.org` / `*.dbl.spamhaus.org` zones. A listing is signalled by
an A-record answer in the 127.0.0.0/8 range whose last octet(s) encode the
listing reason (per Spamhaus's published return-code tables); NXDOMAIN (no
answer) means "not listed". See app/providers/base.py for the BaseProvider
contract this still implements even though it performs a DNS lookup instead
of an HTTP call.
"""
import asyncio
import ipaddress
import socket

import httpx

from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus

# Published Spamhaus ZEN (SBL + SBL CSS + XBL + PBL combined) return codes.
# https://www.spamhaus.org/zen/ -- best-effort mapping, Spamhaus may extend this.
_ZEN_CODES = {
    "127.0.0.2": "SBL - spam source (Spamhaus Block List)",
    "127.0.0.3": "SBL CSS - snowshoe spam source",
    "127.0.0.4": "XBL - CBL: compromised host (open proxy / worm / bot infection)",
    "127.0.0.5": "XBL - CBL: compromised host (open proxy / worm / bot infection)",
    "127.0.0.6": "XBL - CBL: compromised host (open proxy / worm / bot infection)",
    "127.0.0.7": "XBL - CBL: compromised host (open proxy / worm / bot infection)",
    "127.0.0.9": "SBL DROP/EDROP - hijacked or spammer-controlled netblock",
    "127.0.0.10": "PBL - ISP policy block list (end-user, not expected to send mail)",
    "127.0.0.11": "PBL - ISP policy block list (Spamhaus-maintained)",
    "127.255.255.254": "query error - public/open resolver not permitted to query Spamhaus",
    "127.255.255.255": "query error - excessive number of queries, temporarily blocked",
}

# Published Spamhaus DBL (Domain Block List) return codes.
_DBL_CODES = {
    "127.0.1.2": "spam domain",
    "127.0.1.4": "phishing domain",
    "127.0.1.5": "malware domain",
    "127.0.1.6": "botnet command-and-control domain",
    "127.0.1.102": "abused legit spam",
    "127.0.1.103": "abused legit spammed redirector",
    "127.0.1.104": "abused legit phish",
    "127.0.1.105": "abused legit malware",
    "127.0.1.106": "abused legit botnet C&C",
    "127.0.1.255": "query error - IP queries prohibited (misconfigured resolver)",
}


class SpamhausProvider(BaseProvider):
    provider_id = "spamhaus"
    provider_name = "Spamhaus DBL/ZEN"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.IPV4, IOCType.DOMAIN}
    requires_key = False
    configured = True

    @staticmethod
    def _query_name(ioc_value: str, ioc_type: IOCType) -> str:
        if ioc_type == IOCType.IPV4:
            reversed_octets = ".".join(reversed(str(ipaddress.ip_address(ioc_value)).split(".")))
            return f"{reversed_octets}.zen.spamhaus.org"
        return f"{ioc_value}.dbl.spamhaus.org"

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        query_name = self._query_name(ioc_value, ioc_type)
        codes = _ZEN_CODES if ioc_type == IOCType.IPV4 else _DBL_CODES
        list_name = "ZEN" if ioc_type == IOCType.IPV4 else "DBL"

        try:
            loop = asyncio.get_event_loop()
            infos = await loop.getaddrinfo(query_name, None)
            addresses = sorted({info[4][0] for info in infos if info[4]})
        except socket.gaierror:
            # NXDOMAIN / no answer -- not listed.
            addresses = []

        if not addresses:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.OK,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                data={
                    "verdict": "clean",
                    "listed": False,
                    "list": list_name,
                    "query": query_name,
                },
                source_url="https://www.spamhaus.org/lookup/",
            )

        reasons = [codes.get(addr, f"listed ({addr}) -- reason not in local code table") for addr in addresses]

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={
                "verdict": "malicious",
                "listed": True,
                "list": list_name,
                "query": query_name,
                "return_codes": addresses,
                "listing_reason": "; ".join(reasons),
            },
            raw={"query": query_name, "answers": addresses},
            source_url="https://www.spamhaus.org/lookup/",
        )


spamhaus_provider = SpamhausProvider()
