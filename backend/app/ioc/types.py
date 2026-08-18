"""Canonical IOC type enum shared by detection, providers, correlation, and API schemas."""
from enum import Enum


class IOCType(str, Enum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    DOMAIN = "domain"
    URL = "url"
    HOSTNAME = "hostname"
    EMAIL = "email"
    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    SHA512 = "sha512"
    TLS_CERTIFICATE = "tls_certificate"
    JA3 = "ja3"
    JA4 = "ja4"
    ASN = "asn"
    CIDR = "cidr"
    MALWARE_FAMILY = "malware_family"
    THREAT_ACTOR = "threat_actor"
    CAMPAIGN = "campaign"
    CVE = "cve"
    CWE = "cwe"
    CAPEC = "capec"
    MITRE_TECHNIQUE = "mitre_technique"
    FILE_NAME = "file_name"
    REGISTRY_KEY = "registry_key"
    PROCESS_NAME = "process_name"
    MUTEX = "mutex"
    WINDOWS_SERVICE = "windows_service"
    FILE_PATH = "file_path"
    USER_AGENT = "user_agent"
    CRYPTO_WALLET = "crypto_wallet"
    YARA_RULE = "yara_rule"
    SIGMA_RULE = "sigma_rule"
    UNKNOWN = "unknown"


# IOC types that describe "hash" family, used by connectors that accept any hash.
HASH_TYPES = {IOCType.MD5, IOCType.SHA1, IOCType.SHA256, IOCType.SHA512}

# IOC types considered "network" observables for correlation graph seeding.
NETWORK_TYPES = {
    IOCType.IPV4,
    IOCType.IPV6,
    IOCType.DOMAIN,
    IOCType.URL,
    IOCType.HOSTNAME,
    IOCType.ASN,
    IOCType.CIDR,
}
