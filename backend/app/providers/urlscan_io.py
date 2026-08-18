"""urlscan.io connector -- submits a URL/domain for a live sandbox scan and
polls for the result. See app/providers/base.py for the BaseProvider
contract and app/providers/virustotal.py / app/providers/stubs/
hybrid_analysis.py for the reference connector style this follows.

API reference: https://urlscan.io/docs/api/ (auth via the `API-Key` header;
submit via POST /api/v1/scan/, then poll GET /api/v1/result/{uuid}/, which
returns HTTP 404 while the scan is still processing and HTTP 200 with the
full result once it's ready).

Status-code handling deliberately does NOT rely on BaseProvider.run()'s
generic HTTPStatusError mapping (app/providers/base.py maps HTTP 403 to
ProviderStatus.RATE_LIMITED for every connector, matching PhishTank's
documented over-limit behavior) -- for urlscan.io, 401/403 mean "bad API
key," not "rate limited." Both submit and poll requests check status codes
explicitly and return early, the same pattern app/providers/virustotal.py
already uses for its pre-`raise_for_status()` 404 check.

The poll loop is wall-clock timeboxed by `_TIMEOUT_SECONDS`, mirroring
app/security_assessment/nmap_tool.py's `_TIMEOUT_SECONDS` pattern for
capping a wait loop -- if the scan isn't ready by the deadline, this returns
ProviderStatus.TIMEOUT rather than fabricating a result from an incomplete
scan.
"""
import asyncio
import time

import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus

_TIMEOUT_SECONDS = 60  # wall-clock cap for submit + poll-until-ready
_POLL_INTERVAL_SECONDS = 3


class UrlscanProvider(BaseProvider):
    provider_id = "urlscan"
    provider_name = "urlscan.io"
    category = ProviderCategory.SANDBOX
    supported_types = {IOCType.URL, IOCType.DOMAIN}
    requires_key = True
    base_url = "https://urlscan.io/api/v1"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().urlscan_api_key)

    @staticmethod
    def _target_url(ioc_value: str, ioc_type: IOCType) -> str:
        # urlscan.io's scan endpoint requires a full URL. IOCType.DOMAIN
        # values are bare hostnames (see app/ioc/types.py), so a scheme has
        # to be added; IOCType.URL values already have one.
        if ioc_type == IOCType.DOMAIN:
            return f"http://{ioc_value}"
        return ioc_value

    def _error(self, ioc_value: str, ioc_type: IOCType, status: ProviderStatus, message: str) -> ProviderResult:
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=status,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            error_message=message,
        )

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        api_key = get_credential("urlscan", "api_key", settings.urlscan_api_key) or ""
        headers = {"API-Key": api_key, "Content-Type": "application/json"}
        target = self._target_url(ioc_value, ioc_type)

        try:
            submit_response = await client.post(
                f"{self.base_url}/scan/",
                headers=headers,
                json={"url": target, "visibility": "unlisted"},
            )
        except httpx.TimeoutException as exc:
            return self._error(ioc_value, ioc_type, ProviderStatus.TIMEOUT, f"urlscan.io submission timed out: {exc}")
        except httpx.HTTPError as exc:
            return self._error(ioc_value, ioc_type, ProviderStatus.ERROR, f"urlscan.io submission network error: {exc}")

        if submit_response.status_code in (401, 403):
            return self._error(
                ioc_value, ioc_type, ProviderStatus.ERROR,
                f"urlscan.io rejected the API key (HTTP {submit_response.status_code}) on submission.",
            )
        if submit_response.status_code == 429:
            return self._error(
                ioc_value, ioc_type, ProviderStatus.RATE_LIMITED, "urlscan.io rate limit exceeded on submission."
            )
        submit_response.raise_for_status()

        try:
            submission = submit_response.json()
        except ValueError as exc:
            return self._error(
                ioc_value, ioc_type, ProviderStatus.ERROR, f"urlscan.io returned a malformed submission response: {exc}"
            )
        if not isinstance(submission, dict) or not submission.get("uuid"):
            return self._error(
                ioc_value, ioc_type, ProviderStatus.ERROR, "urlscan.io submission response did not include a scan uuid."
            )
        uuid = submission["uuid"]

        payload = await self._poll_for_result(ioc_value, ioc_type, uuid, headers, client)
        if isinstance(payload, ProviderResult):
            return payload

        data = self._map_result(payload)
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url=f"https://urlscan.io/result/{uuid}/",
        )

    async def _poll_for_result(
        self, ioc_value: str, ioc_type: IOCType, uuid: str, headers: dict, client: httpx.AsyncClient
    ):
        """Polls GET /api/v1/result/{uuid}/ until ready, erroring, or the
        `_TIMEOUT_SECONDS` wall-clock budget runs out. Returns the parsed
        result payload (dict) on success, or a ProviderResult directly for
        any error/timeout path -- never fabricates a result for an
        incomplete scan."""
        result_url = f"{self.base_url}/result/{uuid}/"
        deadline = time.monotonic() + _TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            try:
                response = await client.get(result_url, headers=headers)
            except httpx.TimeoutException as exc:
                return self._error(ioc_value, ioc_type, ProviderStatus.TIMEOUT, f"urlscan.io poll request timed out: {exc}")
            except httpx.HTTPError as exc:
                return self._error(ioc_value, ioc_type, ProviderStatus.ERROR, f"urlscan.io poll network error: {exc}")

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    return self._error(
                        ioc_value, ioc_type, ProviderStatus.ERROR, f"urlscan.io returned a malformed result response: {exc}"
                    )
                if not isinstance(payload, dict):
                    return self._error(
                        ioc_value, ioc_type, ProviderStatus.ERROR,
                        "urlscan.io returned an unexpected (non-object) result payload.",
                    )
                return payload
            if response.status_code == 404:
                # Scan still processing -- the documented "not ready yet" signal.
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                continue
            if response.status_code in (401, 403):
                return self._error(
                    ioc_value, ioc_type, ProviderStatus.ERROR,
                    f"urlscan.io rejected the API key (HTTP {response.status_code}) while polling for results.",
                )
            if response.status_code == 429:
                return self._error(
                    ioc_value, ioc_type, ProviderStatus.RATE_LIMITED, "urlscan.io rate limit exceeded while polling for results."
                )
            response.raise_for_status()

        return self._error(
            ioc_value, ioc_type, ProviderStatus.TIMEOUT,
            f"urlscan.io scan for {ioc_value!r} did not complete within {_TIMEOUT_SECONDS}s.",
        )

    @staticmethod
    def _map_result(payload: dict) -> dict:
        verdicts = payload.get("verdicts") or {}
        overall = verdicts.get("overall") or {}
        urlscan_verdict = verdicts.get("urlscan") or {}

        # Trust the API's own boolean verdict field when present -- overall
        # falls back to the urlscan engine's own verdict sub-object.
        # Deliberately does NOT infer "malicious" from a numeric score: the
        # score scale/direction differs across verdict sub-objects (see
        # https://urlscan.io/docs/result/), and guessing a threshold would
        # risk fabricating a verdict the API never actually asserted.
        malicious_flag = overall.get("malicious")
        if malicious_flag is None:
            malicious_flag = urlscan_verdict.get("malicious")

        if malicious_flag is True:
            verdict = "malicious"
        elif malicious_flag is False:
            verdict = "clean"
        else:
            verdict = "unknown"

        score = overall.get("score", urlscan_verdict.get("score"))
        categories = overall.get("categories") or urlscan_verdict.get("categories") or []
        brands = overall.get("brands") or urlscan_verdict.get("brands") or []

        page = payload.get("page") or {}
        task = payload.get("task") or {}
        lists = payload.get("lists") or {}

        return {
            "verdict": verdict,
            "malicious": malicious_flag,
            "score": score,
            "categories": categories,
            "brands": brands,
            "final_url": page.get("url"),
            "domain": page.get("domain"),
            "ip": page.get("ip"),
            "country": page.get("country"),
            "asn": page.get("asn"),
            "server": page.get("server"),
            "resolved_ips": lists.get("ips") or [],
            "domains_contacted": lists.get("domains") or [],
            "screenshot_url": f"https://urlscan.io/screenshots/{task.get('uuid')}.png" if task.get("uuid") else None,
            "scan_date": task.get("time"),
        }


urlscan_provider = UrlscanProvider()
