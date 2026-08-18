"""Unit tests for app.ioc.detector.detect_ioc_type.

These tests pin down the documented contract of detect_ioc_type(): given a raw,
untyped string, it must resolve to the IOCType an analyst would expect. See
app/ioc/detector.py for the ordering rules (more specific patterns like hashes/
CVEs/IPs are checked before generic hostname/file_name fallbacks).
"""
import pytest

from app.ioc.detector import detect_ioc_type
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
