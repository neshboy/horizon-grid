"""Shared query_status handling for the three abuse.ch-backed connectors
(URLhaus, ThreatFox, MalwareBazaar) -- all three share the same Auth-Key
mechanism and the same query_status vocabulary in their JSON responses.

Auth/config failures (bad or missing Auth-Key) must not collapse into
ProviderStatus.NO_DATA -- that value is what the UI shows as "nothing
malicious found," so a misconfigured key would misrepresent a possibly
malicious IOC as clean. See app/providers/base.py for the ProviderStatus enum.
"""
from app.providers.base import ProviderStatus

# Documented per-endpoint by abuse.ch as the query_status value returned when
# the Auth-Key header is missing/invalid, distinct from a genuine empty result
# (e.g. "no_results", "hash_not_found", "illegal_hash", "no_urls_found").
_AUTH_FAILURE_STATUSES = frozenset({"no_api_key", "invalid_api_key", "unauthorized"})


def map_query_status(query_status: str | None) -> tuple[ProviderStatus, str | None]:
    """Maps an abuse.ch query_status string to (ProviderStatus, error_message).

    Returns (ProviderStatus.OK, None) for "ok" -- callers still need to check
    for empty result entries themselves, since "ok" with zero matches is a
    valid abuse.ch response for some endpoints.
    """
    if query_status == "ok":
        return ProviderStatus.OK, None
    if query_status in _AUTH_FAILURE_STATUSES:
        return ProviderStatus.ERROR, f"abuse.ch Auth-Key rejected (query_status={query_status!r})"
    return ProviderStatus.NO_DATA, None
