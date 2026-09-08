"""Unit tests for app.ioc.detector.detect_ioc_type.

These tests pin down the documented contract of detect_ioc_type(): given a raw,
untyped string, it must resolve to the IOCType an analyst would expect. See
app/ioc/detector.py for the ordering rules (more specific patterns like hashes/
CVEs/IPs are checked before generic hostname/file_name fallbacks).
"""
import pytest

from app.ioc.detector import detect_ioc_type, value_matches_ioc_type
from app.ioc.types import IOCType

CASES: list[tuple[str, IOCType]] = [
    # Network observables
    ("8.8.8.8", IOCType.IPV4),
    ("2001:4860:4860::8888", IOCType.IPV6),
    ("192.168.0.0/24", IOCType.CIDR),
    ("example.com", IOCType.DOMAIN),
    ("http://example.com/path", IOCType.URL),
    ("https://example.com/path?q=1", IOCType.URL),
    ("user@example.com", IOCType.EMAIL),
    # Hashes, one per length
    ("826f75224ddb4979721c1240f5b423b5", IOCType.MD5),
    ("7053eba4b69b1898302218aae3a3a49982b319e4", IOCType.SHA1),
    (
        "71e88b019795fb624c5382163cba1e6bcea14d90713c6aedc2f9359d6a31af15",
        IOCType.SHA256,
    ),
    (
        "c52153a0a10bb13dfc184d8229a6f7b0d906279fa66a95eabf5c269dff6481f"
        "5d0ca52a673c4a254d00cc89c4f166b4b44d4a15853168a8a310ba9e64a70df58",
        IOCType.SHA512,
    ),
    # Vulnerability / ATT&CK taxonomy identifiers
    ("CVE-2021-44228", IOCType.CVE),
    ("CWE-79", IOCType.CWE),
    ("CAPEC-66", IOCType.CAPEC),
    ("T1059", IOCType.MITRE_TECHNIQUE),
    ("T1059.001", IOCType.MITRE_TECHNIQUE),
    # ASN
    ("AS15169", IOCType.ASN),
    # Crypto wallets
    ("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", IOCType.CRYPTO_WALLET),
    ("0xa1b2c3d4e5f60718293a4b5c6d7e8f9012345678", IOCType.CRYPTO_WALLET),
    # Windows filesystem / registry
    (r"C:\Windows\System32\evil.exe", IOCType.FILE_PATH),
    (r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run", IOCType.REGISTRY_KEY),
    # User agent
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        IOCType.USER_AGENT,
    ),
    # File name
    ("malware.exe", IOCType.FILE_NAME),
    ("shell.php", IOCType.FILE_NAME),
    ("invoice.doc", IOCType.FILE_NAME),
    ("readme.txt", IOCType.FILE_NAME),
    ("cmd.aspx", IOCType.FILE_NAME),
    ("notes.md", IOCType.FILE_NAME),
    # JA4 fingerprint (10-char prefix, not 8)
    ("q13i0207h3_55b375c5d22e_cd85d2d88918", IOCType.JA4),
    # A hex string starting with a letter followed by all digits must not be
    # misread as an ASN just because it superficially resembles "A<number>".
    ("a1111111111111111111111111111111", IOCType.MD5),
    # Empty input
    ("", IOCType.UNKNOWN),
]


@pytest.mark.parametrize("raw, expected", CASES, ids=[c[0] or "<empty>" for c in CASES])
def test_detect_ioc_type(raw: str, expected: IOCType) -> None:
    assert detect_ioc_type(raw) == expected


def test_detect_ioc_type_whitespace_only_is_unknown() -> None:
    assert detect_ioc_type("   ") == IOCType.UNKNOWN


def test_detect_ioc_type_asn_alternate_spelling() -> None:
    # The ASN regex accepts "ASN 12345" / "AS 12345" / "12345" style variants too.
    assert detect_ioc_type("ASN 15169") == IOCType.ASN


def test_detect_ioc_type_mitre_technique_bare_form_has_no_subtechnique() -> None:
    result = detect_ioc_type("T1059")
    assert result == IOCType.MITRE_TECHNIQUE


def test_detect_ioc_type_mitre_technique_subtechnique_form() -> None:
    result = detect_ioc_type("T1059.001")
    assert result == IOCType.MITRE_TECHNIQUE


# --- value_matches_ioc_type -------------------------------------------------
#
# Regression coverage for a real bug found via independent verification: a
# caller-supplied ioc_type_hint was trusted with zero validation in
# stream_lookup()/add_to_basket() (app/api/routes/lookup.py,
# app/api/routes/basket.py) -- detect_ioc_type('')'s own UNKNOWN result never
# even ran once a hint was present, so a whitespace-only value paired with
# ANY hint (or a value that plainly doesn't match the claimed type) sailed
# straight through to persistence and a full provider fan-out. These tests
# pin down the validation primitive both routes now call before trusting a
# hint.

MATCH_CASES: list[tuple[str, IOCType, bool]] = [
    # The core reported repro: an empty/whitespace-derived value must never
    # be considered valid for ANY claimed type.
    ("", IOCType.DOMAIN, False),
    ("", IOCType.IPV4, False),
    ("", IOCType.MALWARE_FAMILY, False),
    # The second reported repro: a value that plainly isn't the claimed
    # structured type.
    ("totally-not-an-ip", IOCType.IPV4, False),
    ("8.8.8.8", IOCType.IPV4, True),
    ("2001:4860:4860::8888", IOCType.IPV6, True),
    ("8.8.8.8", IOCType.IPV6, False),
    ("192.168.0.0/24", IOCType.CIDR, True),
    ("192.168.0.0", IOCType.CIDR, False),  # no "/" -- not a CIDR block
    ("example.com", IOCType.DOMAIN, True),
    ("not a domain!!", IOCType.DOMAIN, False),
    ("http://example.com/path", IOCType.URL, True),
    ("example.com", IOCType.URL, False),  # no scheme
    ("user@example.com", IOCType.EMAIL, True),
    ("not-an-email", IOCType.EMAIL, False),
    ("826f75224ddb4979721c1240f5b423b5", IOCType.MD5, True),
    ("not-a-hash", IOCType.MD5, False),
    ("7053eba4b69b1898302218aae3a3a49982b319e4", IOCType.SHA1, True),
    (
        "71e88b019795fb624c5382163cba1e6bcea14d90713c6aedc2f9359d6a31af15",
        IOCType.SHA256,
        True,
    ),
    ("CVE-2021-44228", IOCType.CVE, True),
    ("CVE-2021", IOCType.CVE, False),
    ("AS15169", IOCType.ASN, True),
    ("15169", IOCType.ASN, True),  # bare digits also accepted (see whois_rdap.py)
    ("not-an-asn", IOCType.ASN, False),
    ("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", IOCType.CRYPTO_WALLET, True),
    ("0xa1b2c3d4e5f60718293a4b5c6d7e8f9012345678", IOCType.CRYPTO_WALLET, True),
    ("not-a-wallet", IOCType.CRYPTO_WALLET, False),
    (r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run", IOCType.REGISTRY_KEY, True),
    ("not-a-registry-key", IOCType.REGISTRY_KEY, False),
    # Free-text types (no fixed syntax) -- any non-empty value is accepted,
    # since ioc_type_hint exists specifically to label this kind of
    # observable (malware family names, threat actor aliases, etc).
    ("Emotet", IOCType.MALWARE_FAMILY, True),
    ("APT28", IOCType.THREAT_ACTOR, True),
    ("SolarWinds Compromise", IOCType.CAMPAIGN, True),
]


@pytest.mark.parametrize(
    "value, ioc_type, expected",
    MATCH_CASES,
    ids=[f"{c[0] or '<empty>'}-as-{c[1].value}" for c in MATCH_CASES],
)
def test_value_matches_ioc_type(value: str, ioc_type: IOCType, expected: bool) -> None:
    assert value_matches_ioc_type(value, ioc_type) is expected


def test_value_matches_ioc_type_whitespace_only_value_is_rejected_for_every_type() -> None:
    """The exact live repro: a whitespace-only value (still non-empty, so
    Pydantic's Field(min_length=1) on the raw payload never catches it) must
    be rejected regardless of which type is claimed for it -- callers are
    expected to .strip() first and pass the result here, but this must not
    silently accept a stripped-to-empty value for any type."""
    for ioc_type in IOCType:
        assert value_matches_ioc_type("", ioc_type) is False
