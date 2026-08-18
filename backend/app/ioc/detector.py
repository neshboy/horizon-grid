"""IOC auto-detection: given a raw user-entered string, determine its IOCType.

Order matters -- more specific patterns (hashes, CVEs, IPs) are checked before
generic fallbacks (hostname/file_name) so ambiguous strings resolve correctly.
"""
import ipaddress
import re

from app.ioc.types import IOCType

_MD5_RE = re.compile(r"^[a-fA-F0-9]{32}$")
_SHA1_RE = re.compile(r"^[a-fA-F0-9]{40}$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_SHA512_RE = re.compile(r"^[a-fA-F0-9]{128}$")
_JA3_RE = re.compile(r"^[a-fA-F0-9]{32}$")  # identical shape to MD5; disambiguated by caller hint
# JA4_a prefix is 10 chars: protocol(1) + version(2) + SNI(1) + cipher_count(2)
# + ext_count(2) + ALPN(2), e.g. "q13i0207h3_55b375c5d22e_cd85d2d88918".
_JA4_RE = re.compile(r"^[a-z0-9]{10}_[a-fA-F0-9]{12}_[a-fA-F0-9]{12}$", re.IGNORECASE)
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,7}$", re.IGNORECASE)
_CWE_RE = re.compile(r"^CWE-\d{1,5}$", re.IGNORECASE)
_CAPEC_RE = re.compile(r"^CAPEC-\d{1,5}$", re.IGNORECASE)
_MITRE_TECHNIQUE_RE = re.compile(r"^T\d{4}(\.\d{3})?$", re.IGNORECASE)
# Requires an explicit AS/ASN prefix -- a bare leading letter (e.g. the "a" in
# a 32-char hex hash) must never satisfy this, or hex hashes starting with a
# letter get misclassified as ASN before the hash regexes below run.
_ASN_RE = re.compile(r"^(?:AS|ASN)\s?(\d+)$", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)
_MUTEX_HINT_RE = re.compile(r"^(Global\\|Local\\)?[A-Za-z0-9_\-\.]{2,}$")
_REGISTRY_KEY_RE = re.compile(
    r"^(HKLM|HKCU|HKCR|HKU|HKCC|HKEY_[A-Z_]+)\\", re.IGNORECASE
)
_WINDOWS_PATH_RE = re.compile(r"^[a-zA-Z]:\\|^\\\\")
_UNIX_PATH_RE = re.compile(r"^/[\w\-./]+$")
_USER_AGENT_HINT_RE = re.compile(
    r"(Mozilla/|AppleWebKit/|Gecko/|Chrome/|Safari/|Edg/|curl/|python-requests/)", re.IGNORECASE
)
_BTC_RE = re.compile(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}$")
_ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_XMR_RE = re.compile(r"^4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}$")
_SIGMA_HINT_RE = re.compile(r"\bdetection:\s*\n", re.IGNORECASE)
_YARA_HINT_RE = re.compile(r"\brule\s+\w+\s*\{", re.IGNORECASE)

# Checked before the domain regex so common document/script/archive filenames
# (a webshell like "shell.php", a lure like "invoice.doc") aren't misread as
# domains just because they match "word.word" -- the domain regex alone can't
# tell "shell.php" from "shell.pl" (a real ccTLD), so extension wins on match.
_FILE_NAME_EXTENSIONS = frozenset(
    {
        "exe", "dll", "sys", "scr", "bat", "ps1", "vbs", "js", "jar", "bin", "elf", "apk", "docm", "xlsm",
        "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf", "txt", "rtf", "csv", "log", "ini", "cfg", "conf",
        "php", "php3", "php4", "php5", "phtml", "asp", "aspx", "jsp", "jspx", "cgi",
        "zip", "rar", "7z", "tar", "gz", "iso", "msi", "dmg", "dat", "tmp", "bak",
        "md", "py", "json", "xml", "yaml", "yml",
    }
)


def detect_ioc_type(raw: str) -> IOCType:
    """Best-effort classification of a single IOC input string."""
    value = raw.strip()
    if not value:
        return IOCType.UNKNOWN

    # Multi-line structured rules first -- unambiguous once whitespace matters.
    if _YARA_HINT_RE.search(value):
        return IOCType.YARA_RULE
    if _SIGMA_HINT_RE.search(value):
        return IOCType.SIGMA_RULE

    stripped = value.strip('"').strip("'")

    if stripped.lower().startswith(("http://", "https://")):
        return IOCType.URL

    if _CVE_RE.match(stripped):
        return IOCType.CVE
    if _CAPEC_RE.match(stripped):
        return IOCType.CAPEC
    if _CWE_RE.match(stripped):
        return IOCType.CWE
    if _MITRE_TECHNIQUE_RE.match(stripped):
        return IOCType.MITRE_TECHNIQUE

    if "/" in stripped:
        try:
            ipaddress.ip_network(stripped, strict=False)
            return IOCType.CIDR
        except ValueError:
            pass

    try:
        ip = ipaddress.ip_address(stripped)
        return IOCType.IPV6 if ip.version == 6 else IOCType.IPV4
    except ValueError:
        pass

    if _ASN_RE.match(stripped):
        return IOCType.ASN

    if _EMAIL_RE.match(stripped):
        return IOCType.EMAIL

    if _SHA512_RE.match(stripped):
        return IOCType.SHA512
    if _SHA256_RE.match(stripped):
        return IOCType.SHA256
    if _SHA1_RE.match(stripped):
        return IOCType.SHA1
    if _JA4_RE.match(stripped):
        return IOCType.JA4
    if _MD5_RE.match(stripped):
        # MD5, JA3 and 32-char mutex-like tokens all look like 32 hex chars.
        # Default to MD5 -- callers with sandbox/TLS context can override via hint.
        return IOCType.MD5

    if _ETH_RE.match(stripped):
        return IOCType.CRYPTO_WALLET
    if _BTC_RE.match(stripped):
        return IOCType.CRYPTO_WALLET
    if _XMR_RE.match(stripped):
        return IOCType.CRYPTO_WALLET

    if _REGISTRY_KEY_RE.match(stripped):
        return IOCType.REGISTRY_KEY

    if _WINDOWS_PATH_RE.match(stripped):
        if re.search(r"\.(exe|dll|sys|scr|bat|ps1)$", stripped, re.IGNORECASE):
            return IOCType.FILE_PATH
        return IOCType.FILE_PATH
    if _UNIX_PATH_RE.match(stripped) and "." not in stripped.split("/")[-1]:
        return IOCType.FILE_PATH

    if _USER_AGENT_HINT_RE.search(stripped):
        return IOCType.USER_AGENT

    dotted_suffix = stripped.rsplit(".", 1)[-1].lower() if "." in stripped else ""
    if dotted_suffix in _FILE_NAME_EXTENSIONS:
        return IOCType.FILE_NAME

    if "." in stripped and " " not in stripped and _DOMAIN_RE.match(stripped):
        # Domain vs. hostname: a domain is a registrable name (has a public
        # suffix-like ending); a hostname often includes a subdomain of an
        # internal/service nature. Without a PSL we treat both as DOMAIN,
        # which is the more common analyst intent for a bare dotted string.
        return IOCType.DOMAIN

    if re.match(r"^[\w\-\.]+$", stripped) and "." not in stripped:
        # Single-token strings with no dots: could be malware family, threat
        # actor, campaign name, process name, mutex, or service name. These
        # are lexically indistinguishable -- default to UNKNOWN and let the
        # user's provider selection / context disambiguate, unless it strongly
        # resembles a process/service name.
        if re.search(r"\.(exe|dll|sys)$", stripped, re.IGNORECASE):
            return IOCType.PROCESS_NAME
        return IOCType.UNKNOWN

    return IOCType.UNKNOWN
