"""Symmetric encryption for provider/AI credentials persisted at runtime.

Runtime-configurable providers can no longer live purely in `.env` -- that
would still require a process restart to change, defeating the entire point
of a live provider registry (see app/core/runtime_config.py). But persisting
raw API keys as plain DB text would be a straightforward downgrade from
"keys only in a root-owned .env file" to "keys visible to anyone who can
read a Postgres row." Fernet symmetric encryption bridges this: ciphertext
is what's actually persisted in provider_runtime_configs.encrypted_credentials,
and only a process holding the master key can ever recover a real credential.

Key material: `settings.encryption_master_key` if explicitly set (the
Windows wizard generates and writes one for new installs, exactly like
`jwt_secret_key` already is), otherwise deterministically derived from
`jwt_secret_key` via HKDF -- every existing install already has a real
`jwt_secret_key` (it's required for login to work at all), so this fallback
needs zero migration effort and never fails to produce a usable key. This is
a defense-in-depth tradeoff, not HSM-grade key separation: documented
honestly rather than overclaimed.
"""
import base64
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_HKDF_INFO = b"ioc-intel-platform:provider-credential-encryption:v1"


def _derive_key_from_jwt_secret(jwt_secret: str) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO)
    raw = hkdf.derive(jwt_secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_master_key:
        key = settings.encryption_master_key.encode("utf-8")
    else:
        key = _derive_key_from_jwt_secret(settings.jwt_secret_key)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Returns "" for falsy input so an unset credential round-trips as
    unset rather than as an encrypted empty string."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Returns "" on any decryption failure (corrupted row, master-key
    rotation) rather than raising -- callers already treat an empty
    credential as "not configured," which is the correct, safe behavior
    here rather than a 500.

    Real bug found live during overnight QA: this used to fail completely
    silently -- zero log line -- so a master-key rotation (e.g. JWT_SECRET_KEY
    changing, when ENCRYPTION_MASTER_KEY isn't set) orphaned every existing
    credential with no trace anywhere an operator would look, while the
    admin UI kept displaying a stale prior "Connected. Key is valid." test
    result for a credential that had just silently stopped working. Still
    never raises (the safe "not configured" behavior is unchanged) -- just
    stops being silent about it."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning(
            "Failed to decrypt a stored credential -- treating it as unconfigured. This usually "
            "means the encryption key changed since it was saved (e.g. JWT_SECRET_KEY rotated with "
            "no separate ENCRYPTION_MASTER_KEY set). The credential must be re-entered."
        )
        return ""


def mask_secret(plaintext: str, visible_suffix: int = 4) -> str:
    """"sk-abc123xyz" -> "*******3xyz" for display -- never round-trippable
    back to the real value, unlike returning a truncated real prefix."""
    if not plaintext:
        return ""
    if len(plaintext) <= visible_suffix:
        return "*" * len(plaintext)
    return "*" * (len(plaintext) - visible_suffix) + plaintext[-visible_suffix:]
