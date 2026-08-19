"""Unit tests for app.core.security_assessment's scope/authorization gate
(_validate_scope) -- the mandatory safety check every run must pass BEFORE
any tool is ever invoked. Tested directly against SimpleNamespace fakes,
mirroring this session's established pattern for testing a mechanism
directly rather than through incidental side effects."""
from types import SimpleNamespace

import pytest

from app.core.security_assessment import (
    AuthorizationNotConfirmedError,
    CIDRTooLargeError,
    InvalidTargetError,
    TargetMismatchError,
    UnscannableIOCTypeError,
    _validate_scope,
)
from app.ioc.types import IOCType


def _lookup(ioc_value: str, ioc_type: str):
    return SimpleNamespace(ioc_value=ioc_value, ioc_type=ioc_type)


def test_rejects_when_authorization_not_confirmed():
    lookup = _lookup("1.2.3.4", "ipv4")
    with pytest.raises(AuthorizationNotConfirmedError):
        _validate_scope(lookup, "1.2.3.4", False)


def test_rejects_when_target_confirmation_does_not_match():
    lookup = _lookup("1.2.3.4", "ipv4")
    with pytest.raises(TargetMismatchError):
        _validate_scope(lookup, "5.6.7.8", True)


def test_rejects_unscannable_ioc_type():
    lookup = _lookup("CVE-2021-44228", "cve")
    with pytest.raises(UnscannableIOCTypeError):
        _validate_scope(lookup, "CVE-2021-44228", True)


def test_accepts_matching_confirmation_for_a_scannable_type():
    lookup = _lookup("1.2.3.4", "ipv4")
    assert _validate_scope(lookup, "1.2.3.4", True) == IOCType.IPV4


def test_accepts_a_small_cidr_at_exactly_the_cap():
    lookup = _lookup("10.0.0.0/28", "cidr")  # exactly 16 addresses
    assert _validate_scope(lookup, "10.0.0.0/28", True) == IOCType.CIDR


def test_rejects_a_cidr_larger_than_the_cap():
    lookup = _lookup("10.0.0.0/27", "cidr")  # 32 addresses -- over the /28 cap
    with pytest.raises(CIDRTooLargeError):
        _validate_scope(lookup, "10.0.0.0/27", True)


def test_authorization_is_checked_before_target_mismatch():
    """Order matters for a clear error message: an unconfirmed request
    should say so, not report a target mismatch that may not even be true."""
    lookup = _lookup("1.2.3.4", "ipv4")
    with pytest.raises(AuthorizationNotConfirmedError):
        _validate_scope(lookup, "wrong-target", False)


def test_malformed_cidr_value_raises_a_clean_error_not_a_raw_valueerror():
    """A lookup can only reach ioc_type=cidr with a malformed ioc_value via
    the pre-existing lookup-creation ioc_type_hint override (which doesn't
    itself validate value-matches-hint) -- confirmed live to otherwise raise
    an uncaught ValueError here, surfacing as a raw 500 instead of the clean
    400 every other validation failure in this function produces."""
    lookup = _lookup("not-a-real-network; touch /tmp/pwned", "cidr")
    with pytest.raises(InvalidTargetError):
        _validate_scope(lookup, "not-a-real-network; touch /tmp/pwned", True)
