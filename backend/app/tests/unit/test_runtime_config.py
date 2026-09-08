"""Unit tests for app.core.runtime_config's credential-merge logic.

Regression tests for a real, live-reproduced bug: saving a provider's
settings with an empty or partial `credentials` dict used to REPLACE the
whole stored credential set rather than leave untouched fields alone. The
settings UI's per-field inputs start blank and only populate for a field
the operator actually retypes this session (an already-saved value is only
ever shown as a placeholder hint, never as the real input value), so
clicking Save without retyping every field silently wiped a fully working,
already-tested provider credential -- confirmed live: `configured` flipped
from true to false, and the next real investigation failed with "not
configured" despite the UI still showing a stale "Last test: OK."
"""
import json
from types import SimpleNamespace

import pytest

from app.core.crypto import encrypt_secret
from app.core.runtime_config import IOC_PROVIDER_CREDENTIAL_FIELDS, _merge_credentials


def _row_with_credentials(creds: dict) -> SimpleNamespace:
    return SimpleNamespace(encrypted_credentials=encrypt_secret(json.dumps(creds)) if creds else "")


def test_empty_incoming_credentials_preserves_existing():
    row = _row_with_credentials({"api_key": "existing-key-value"})
    merged = _merge_credentials(row, {})
    assert merged == {"api_key": "existing-key-value"}


def test_partial_incoming_credentials_preserves_untouched_fields():
    # Censys needs both personal_access_token and organization_id; saving
    # only one (e.g. rotating the token) must not drop the other.
    row = _row_with_credentials({"personal_access_token": "old-token", "organization_id": "org-123"})
    merged = _merge_credentials(row, {"personal_access_token": "new-token"})
    assert merged == {"personal_access_token": "new-token", "organization_id": "org-123"}


def test_new_field_is_added_to_empty_existing_credentials():
    row = _row_with_credentials({})
    merged = _merge_credentials(row, {"api_key": "brand-new-key"})
    assert merged == {"api_key": "brand-new-key"}


def test_full_replacement_still_works_when_all_fields_sent():
    row = _row_with_credentials({"api_key": "old-key"})
    merged = _merge_credentials(row, {"api_key": "new-key"})
    assert merged == {"api_key": "new-key"}


# --- Real bug found live during overnight QA, a second variant of the
# class the module docstring above already describes: this time the field
# IS present in `incoming`, but with an explicit empty string -- reachable
# through completely ordinary UI use (click into a masked field to retype
# it, select-all+delete to reconsider, then Save without retyping). Live-
# reproduced via both raw API calls and a real browser walkthrough on two
# separate providers (urlhaus, groq) sharing this same merge code path. ---


def test_explicit_blank_value_for_an_existing_field_does_not_wipe_it():
    row = _row_with_credentials({"auth_key": "existing-working-key"})
    merged = _merge_credentials(row, {"auth_key": ""})
    assert merged == {"auth_key": "existing-working-key"}


def test_explicit_blank_value_alongside_a_real_update_to_a_sibling_field():
    # Censys-shaped: two fields, one legitimately updated, the other
    # accidentally cleared in the same save -- the real update must still
    # go through while the blanked sibling is preserved, not lost too.
    row = _row_with_credentials({"personal_access_token": "old-token", "organization_id": "org-123"})
    merged = _merge_credentials(row, {"personal_access_token": "new-token", "organization_id": ""})
    assert merged == {"personal_access_token": "new-token", "organization_id": "org-123"}


def test_explicit_blank_value_on_a_never_configured_field_stays_absent():
    row = _row_with_credentials({})
    merged = _merge_credentials(row, {"api_key": ""})
    assert merged == {}


# --- Real bug found live during overnight QA (independently, by 4 separate
# test passes tonight): when the encryption key changes (e.g. JWT_SECRET_KEY
# rotated with no separate ENCRYPTION_MASTER_KEY set -- see crypto.py),
# every previously-saved credential becomes permanently undecryptable, but
# the admin-facing API/UI kept showing a stale prior "Connected. Key is
# valid." test result for a provider that had just silently stopped
# working -- indistinguishable from "never configured" at a glance, and
# directly contradicting `configured: false` on the very same response. ---


def test_row_to_public_dict_flags_undecryptable_credentials_and_clears_stale_test_result():
    from datetime import datetime, timezone

    from app.core.runtime_config import _row_to_public_dict

    row = SimpleNamespace(
        provider_id="otx",
        provider_name="AlienVault OTX",
        kind=SimpleNamespace(value="ioc"),
        enabled=True,
        is_active=False,
        model_id=None,
        extra_config={},
        encrypted_credentials="not-a-real-fernet-token-so-decrypt-fails",
        last_test_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        last_test_ok=True,
        last_test_message="Connected. Key is valid.",
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    result = _row_to_public_dict(row)
    assert result["credentials_unreadable"] is True
    assert result["configured"] is False
    assert result["last_test_ok"] is None
    assert result["last_test_at"] is None
    assert "re-enter" in result["last_test_message"]


# --- Real bug found live: saving an IOC provider credential accepted and
# silently persisted ANY field name in `incoming`, not just the ones the
# provider actually declares in IOC_PROVIDER_CREDENTIAL_FIELDS. Reproduced
# live: POSTing {"credentials": {"totally_made_up_field": "junk"}} to
# virustotal (whose only declared field is api_key) returned 200 and
# permanently stored `totally_made_up_field` alongside the real api_key --
# a field the UI's ProviderConfigRow.tsx never renders (it only renders
# `credential_fields`), so it could never again be seen or removed. Callers
# now pass the provider's declared field list as `allowed_fields`, and an
# incoming key outside that list is rejected (ValueError) rather than
# silently merged in. ---


def test_unknown_credential_field_is_rejected_not_silently_persisted():
    row = _row_with_credentials({"api_key": "existing-key-value"})
    with pytest.raises(ValueError, match="totally_made_up_field"):
        _merge_credentials(row, {"totally_made_up_field": "junk"}, IOC_PROVIDER_CREDENTIAL_FIELDS["virustotal"])


def test_unknown_credential_field_does_not_get_merged_or_partially_applied():
    # A rejected save must not have side effects: the legitimate field in
    # the same payload must not have been merged in before the unknown
    # field was noticed either (all-or-nothing).
    row = _row_with_credentials({"api_key": "existing-key-value"})
    with pytest.raises(ValueError):
        _merge_credentials(
            row,
            {"api_key": "new-value", "totally_made_up_field": "junk"},
            IOC_PROVIDER_CREDENTIAL_FIELDS["virustotal"],
        )
    # The stored credentials are untouched by the failed attempt.
    assert _merge_credentials(row, {}) == {"api_key": "existing-key-value"}


def test_declared_credential_field_is_still_accepted_with_allow_list_enforced():
    row = _row_with_credentials({"api_key": "old-key"})
    merged = _merge_credentials(row, {"api_key": "new-key"}, IOC_PROVIDER_CREDENTIAL_FIELDS["virustotal"])
    assert merged == {"api_key": "new-key"}


def test_censys_partial_update_respects_allow_list_of_both_declared_fields():
    row = _row_with_credentials({"personal_access_token": "old-token", "organization_id": "org-123"})
    merged = _merge_credentials(
        row, {"personal_access_token": "new-token"}, IOC_PROVIDER_CREDENTIAL_FIELDS["censys"]
    )
    assert merged == {"personal_access_token": "new-token", "organization_id": "org-123"}


def test_empty_allow_list_rejects_any_field():
    # A caller passing an explicit empty allow-list (a provider declared to
    # need zero credential fields) must still reject any field, not treat
    # an empty list as "no restriction" (that's spelled `None`, tested
    # below).
    row = _row_with_credentials({})
    with pytest.raises(ValueError, match="api_key"):
        _merge_credentials(row, {"api_key": "nope"}, [])


def test_allow_list_not_enforced_when_caller_omits_it_ai_providers_unaffected():
    # AI providers (upsert_ai_provider) call _merge_credentials without an
    # `allowed_fields` argument -- this must keep behaving exactly as
    # before the fix, since AI providers have no equivalent declared-field
    # registry today.
    row = _row_with_credentials({"api_key": "existing-key-value"})
    merged = _merge_credentials(row, {"some_new_ai_field": "value"})
    assert merged == {"api_key": "existing-key-value", "some_new_ai_field": "value"}


def test_upsert_ioc_provider_only_enforces_allow_list_for_providers_that_declare_one():
    # upsert_ioc_provider() computes allowed_fields via
    # IOC_PROVIDER_CREDENTIAL_FIELDS.get(provider_id) (no default), which is
    # None -- not [] -- for a provider_id absent from the dict (a generic/
    # custom IOC provider, e.g. crtsh which needs no key, or a user-added
    # one). None must mean "no restriction" so those keep accepting
    # whatever fields they're given, exactly like before this fix and
    # exactly like _is_fully_configured's own identical fallback.
    row = _row_with_credentials({})
    assert IOC_PROVIDER_CREDENTIAL_FIELDS.get("crtsh") is None
    merged = _merge_credentials(row, {"anything": "value"}, IOC_PROVIDER_CREDENTIAL_FIELDS.get("crtsh"))
    assert merged == {"anything": "value"}


def test_row_to_public_dict_does_not_flag_a_genuinely_never_configured_provider():
    from app.core.runtime_config import _row_to_public_dict

    row = SimpleNamespace(
        provider_id="threatfox",
        provider_name="ThreatFox",
        kind=SimpleNamespace(value="ioc"),
        enabled=True,
        is_active=False,
        model_id=None,
        extra_config={},
        encrypted_credentials="",
        last_test_at=None,
        last_test_ok=None,
        last_test_message=None,
        updated_at=None,
    )
    result = _row_to_public_dict(row)
    assert result["credentials_unreadable"] is False
    assert result["configured"] is False
