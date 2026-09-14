"""Shared, pure geo-resolution helpers for turning a lookup's own
provider_results into a real (never-fabricated/never-guessed) country code.

Extracted from app/core/dashboard.py's get_geo_activity() implementation so
the exact same priority order/validity rule/otx-exclusion is reused, byte-
for-byte, by every consumer instead of being re-derived (and potentially
drifting) in more than one place:
  - GET /dashboard/geo-activity (aggregate across many lookups -- see
    app/core/dashboard.py::get_geo_activity, which still owns its own DB
    query and per-country aggregation; only country resolution itself lives
    here now).
  - GET /api/v1/lookup/{lookup_id}/geo (single lookup -- see
    app/api/routes/lookup.py::get_lookup_geo).

Nothing in this module touches the database -- resolve_lookup_country()
takes the same `{provider_id: [data dict, ...]}` shape callers already load
from ProviderResultRecord rows themselves.
"""

# Provider IDs consulted for country extraction, in the exact priority order
# documented on resolve_lookup_country() below (whois_rdap is checked via two
# different fields, hence the priority list there has 4 entries against only
# 3 provider_ids here).
GEO_PROVIDER_IDS = ("whois_rdap", "abuseipdb", "virustotal")


def valid_country_code(value) -> "str | None":
    """Returns the upper-cased 2-letter code if `value` is exactly 2 alpha
    characters once stripped (case-insensitive -- 'us' and 'US' both accepted
    and normalized to 'US'), else None.

    This is the single chokepoint every candidate field passed through this
    module is checked through, so this platform's hard rule -- never
    fabricate data, a missing data point always beats a guessed one -- is
    enforced in exactly one place: a full country name, an empty string,
    null, a 3-letter code, or any other non-2-alpha value is always treated
    as "no country from this field", never coerced or guessed at.
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if len(candidate) != 2 or not candidate.isalpha():
        return None
    return candidate.upper()


def resolve_lookup_country(provider_data: "dict[str, list[dict]]") -> "str | None":
    """Given one lookup's {provider_id: [data dict, ...]} (ideally already
    restricted to GEO_PROVIDER_IDS, though extra keys are simply ignored
    since only the 4 fields below are ever consulted), returns the
    ISO-3166-1 alpha-2 country code for that lookup, or None if it cannot be
    determined (i.e. this lookup is unmapped).

    Checked in this EXACT priority order -- the first field that yields a
    valid code (per valid_country_code() above) wins, and every lower
    priority is skipped entirely once that happens:
      1. whois_rdap  -> data['country']
      2. whois_rdap  -> data['registrant_country']
      3. abuseipdb   -> data['country_code']
      4. virustotal  -> data['country']

    otx is deliberately never consulted here even though it also returns a
    'country' field: OTX's is a free-text country NAME (e.g. "United
    States"), not an ISO code, and reliably normalizing names to codes needs
    a name table this function does not have -- skipping it entirely is the
    "never fabricate/guess" rule applied to a whole provider, not just to a
    single malformed value.

    A field that exists but fails valid_country_code() (full name, empty
    string, 3-letter code, null, wrong type) is indistinguishable here from a
    field that is simply absent -- both fall through to the next priority,
    never get coerced.
    """
    priorities = (
        ("whois_rdap", "country"),
        ("whois_rdap", "registrant_country"),
        ("abuseipdb", "country_code"),
        ("virustotal", "country"),
    )
    for provider_id, field in priorities:
        for data in provider_data.get(provider_id, ()):
            code = valid_country_code((data or {}).get(field))
            if code:
                return code
    return None
