"""Regression guard for a real bug: k8s/base/secret.example.yaml and
k8s/base/configmap.yaml were stale relative to backend/app/core/config.py's
current AI-provider surface. AI_BACKEND, OLLAMA_BASE_URL/OLLAMA_MODEL,
ENCRYPTION_MASTER_KEY, MSF_RPC_PASSWORD, and the API keys/model IDs for 9 of
the platform's 11 supported AI backends (Bedrock's bearer-token key, Gemini,
Anthropic, Groq, OpenAI, Kimi, DeepSeek, xAI, Mistral, OpenRouter) were
entirely absent from both files, despite k8s/README.md explicitly claiming
the Secret holds "every provider API key from .env.example." A kubectl
deployment built strictly from these manifests (per the documented
`--from-env-file=.env` / secret.example.yaml workflow) had no way to select
or configure any AI backend at all, and would silently fall back to
`ai_backend="ollama"` with `ollama_base_url="http://host.docker.internal:11434"`
-- a hostname with no k8s equivalent of docker-compose.yml's
`extra_hosts: host.docker.internal:host-gateway`, so it resolves nowhere
inside a pod.
"""
import re
from pathlib import Path

import pytest
import yaml

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern -- see
# test_k8s_frontend_deployment_build.py): the backend container only ever
# bind-mounts ./backend as /app -- k8s/ and .env.example are siblings of
# backend/ in the real repo, but simply do not exist inside the container's
# filesystem at all. Skipping loudly (not silently) when they're not found,
# rather than assuming a container-relative path that would never resolve
# there, so this only ever runs (and only ever matters) from a host-side run
# against the full repo checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SECRET_EXAMPLE = _REPO_ROOT / "k8s" / "base" / "secret.example.yaml"
_CONFIGMAP = _REPO_ROOT / "k8s" / "base" / "configmap.yaml"
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"
_README = _REPO_ROOT / "k8s" / "README.md"

_SKIP_REASON = "k8s/.env.example files not mounted in this environment (host-only check)"

# Non-*_API_KEY secret settings the AI backends/pentest suite need that
# backend/app/core/config.py's Settings reads with no default (or a
# clearly-placeholder default) -- see encryption_master_key/msf_rpc_password.
_OTHER_AI_RELATED_SECRET_KEYS = ["ENCRYPTION_MASTER_KEY", "MSF_RPC_PASSWORD"]

# Non-secret AI-backend selector + Ollama connection info + the model-ID
# settings for every alternative backend (backend/app/core/config.py's
# ai_backend/ollama_*/​*_model_id fields) -- these belong in the ConfigMap,
# mirroring the existing BEDROCK_MODEL_ID/BEDROCK_MAX_TOKENS entries there.
_AI_BACKEND_CONFIGMAP_KEYS = [
    "AI_BACKEND",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "GEMINI_MODEL_ID",
    "ANTHROPIC_MODEL_ID",
    "GROQ_MODEL_ID",
    "OPENAI_MODEL_ID",
    "KIMI_MODEL_ID",
    "DEEPSEEK_MODEL_ID",
    "XAI_MODEL_ID",
    "MISTRAL_MODEL_ID",
    "OPENROUTER_MODEL_ID",
]

_API_KEY_LINE_RE = re.compile(r"^([A-Z0-9_]+_API_KEY)=", re.MULTILINE)


def _stringdata_keys(path: Path) -> set:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return set((doc.get("stringData") or {}).keys())


def _data_keys(path: Path) -> set:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return set((doc.get("data") or {}).keys())


@pytest.mark.skipif(
    not (_SECRET_EXAMPLE.exists() and _ENV_EXAMPLE.exists()), reason=_SKIP_REASON
)
def test_secret_example_contains_every_api_key_from_env_example():
    # This is the literal claim k8s/README.md makes ("every provider API key
    # from .env.example") -- derived dynamically from the current
    # .env.example content (not a hardcoded list) so it also catches any
    # *future* API key added to .env.example without a matching k8s update.
    env_example_text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    expected_api_keys = sorted(set(_API_KEY_LINE_RE.findall(env_example_text)))
    assert expected_api_keys, "test assumption stale: no *_API_KEY= lines found in .env.example"

    secret_keys = _stringdata_keys(_SECRET_EXAMPLE)
    missing = [k for k in expected_api_keys if k not in secret_keys]
    assert not missing, (
        "k8s/base/secret.example.yaml is missing API keys that .env.example "
        f"documents: {missing!r}. k8s/README.md claims the Secret holds "
        "'every provider API key from .env.example' -- an operator following "
        "that doc has no way to configure the corresponding AI backend(s)."
    )


@pytest.mark.skipif(not _SECRET_EXAMPLE.exists(), reason=_SKIP_REASON)
def test_secret_example_contains_encryption_and_msf_rpc_settings():
    secret_keys = _stringdata_keys(_SECRET_EXAMPLE)
    missing = [k for k in _OTHER_AI_RELATED_SECRET_KEYS if k not in secret_keys]
    assert not missing, (
        "k8s/base/secret.example.yaml is missing secret settings that "
        f"backend/app/core/config.py's Settings requires: {missing!r}"
    )


@pytest.mark.skipif(not _CONFIGMAP.exists(), reason=_SKIP_REASON)
def test_configmap_contains_ai_backend_selector_and_model_ids():
    configmap_keys = _data_keys(_CONFIGMAP)
    missing = [k for k in _AI_BACKEND_CONFIGMAP_KEYS if k not in configmap_keys]
    assert not missing, (
        "k8s/base/configmap.yaml is missing AI-backend selector/model-id keys "
        f"that backend/app/core/config.py's Settings requires: {missing!r}. "
        "Without AI_BACKEND/OLLAMA_BASE_URL set explicitly, a k8s deployment "
        "silently defaults to ollama_base_url=http://host.docker.internal:11434, "
        "which does not resolve inside a pod (no k8s equivalent of "
        "docker-compose.yml's `extra_hosts: host.docker.internal:host-gateway` "
        "exists in k8s/base/*.yaml)."
    )


@pytest.mark.skipif(not _README.exists(), reason=_SKIP_REASON)
def test_readme_ai_backend_note_mentions_host_docker_internal_gap():
    # The finding's other half: the README's own "Notes / things to adjust"
    # section should call out that the default Ollama URL can't resolve from
    # inside a pod, so this isn't a silent gap for anyone who reads it.
    readme_text = _README.read_text(encoding="utf-8")
    assert "host.docker.internal" in readme_text and "hostAliases" in readme_text, (
        "k8s/README.md's Notes section should explicitly call out that the "
        "default OLLAMA_BASE_URL (host.docker.internal) has no k8s "
        "hostAliases equivalent configured, so it won't resolve from inside "
        "a pod as shipped."
    )
