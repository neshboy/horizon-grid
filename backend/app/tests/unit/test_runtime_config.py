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

from app.core.crypto import encrypt_secret
from app.core.runtime_config import _merge_credentials


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
