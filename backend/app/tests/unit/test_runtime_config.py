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
