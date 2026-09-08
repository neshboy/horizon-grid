"""Thin async wrapper around a locally-hosted Ollama server, used as the
primary AI backend when no cloud AI vendor has a working key/quota (Bedrock
needs IAM + model access, Gemini/OpenAI need billing). Ollama runs entirely
on the user's own machine -- no API key, no quota, no per-token cost.

Uses Ollama's /api/chat structured-output mode (`format: <json schema>`,
supported since Ollama 0.5+): the server grammar-constrains decoding so the
response text is valid JSON matching the schema, without needing the model
to have been trained on tool-calling. This works with any local model,
including ones like Gemma that have no native tool-use format.

Networking note: this backend process runs inside Docker (see
docker-compose.yml), while Ollama runs directly on the host -- so
"localhost" from inside the container is the container itself, not the
host's Ollama server. OLLAMA_BASE_URL defaults to
http://host.docker.internal:11434, which Docker Desktop (Windows/Mac)
resolves to the host automatically.

Schema note: same as Gemini (app/ai/gemini_client.py) -- llama.cpp's
grammar-based structured output (which Ollama's `format` parameter compiles
to) has inconsistent support for JSON Schema `$ref`/`$defs` depending on
model/version, so inline_refs() flattens them defensively before sending.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Fallback only -- used if a caller ever constructs OllamaClient against a
# Settings-like object that doesn't define ollama_timeout_seconds (the real
# app/core/config.py Settings always does; see its own comment for the
# reasoning). Confirmed real P1 bug: this used to be a hardcoded 120,
# justified by a now-disproven assumption that "a model sized to fit fully
# in VRAM responds in seconds" -- but this backend's own default model
# (llama3.2:3b) runs CPU-only on a real dev/QA host (confirmed via
# `size_vram: 0` in Ollama's own /api/ps), and Ollama's default idle-unload
# behavior means the FIRST call after any idle period pays a full model
# reload (measured live at 62.8s and 78.8s on two separate cold loads) on
# top of CPU-speed generation (measured live at ~4.7 tokens/sec). The exact
# request generate_final_assessment() sends (app/ai/service.py) was
# confirmed live to complete successfully with valid JSON in 187s when not
# artificially cut off at 120s -- so 120s was aborting ordinary, working
# requests, not just genuinely hung ones. 300s leaves real headroom above
# that measured 187s baseline for slightly larger prompts/outputs.
_TIMEOUT_SECONDS = 300

# Real P1 bug found live during overnight QA: with no num_ctx set at all,
# Ollama 0.33.0 defaults the KV-cache to the MODEL's own trained maximum
# context length (131072 for Llama 3.2), not the prompt -- confirmed live
# via `ollama ps` that one ordinary investigation call turned a 2GB model
# into an 18GB resident allocation, and independently corroborated by host
# free RAM dropping into the 600MB-1.8GB range on this 16GB host during
# testing (a real host-stability risk, not a performance nit, on exactly
# the RAM-constrained self-hosted deployments this local/no-cost backend
# targets). These bounds are a rough, conservative estimate (~3 chars/token
# is deliberately pessimistic for English text to leave headroom for
# structured-JSON/schema density) rather than an exact tokenizer count --
# the goal is capping the KV-cache to something sane for a summarization-
# sized prompt, not exact sizing.
_MIN_NUM_CTX = 2048
_MAX_NUM_CTX = 8192


def _estimate_num_ctx(system_prompt: str, user_prompt: str, response_budget: int) -> int:
    estimated_prompt_tokens = (len(system_prompt) + len(user_prompt)) // 3
    return max(_MIN_NUM_CTX, min(_MAX_NUM_CTX, estimated_prompt_tokens + response_budget + 512))


class OllamaClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        *,
        _ssrf_checked: bool = False,
    ) -> None:
        # Optional overrides let app/core/runtime_config.py construct a
        # client from the currently-active runtime configuration instead of
        # the frozen .env-derived Settings singleton -- defaults preserve
        # the original settings-only behavior for any other caller.
        #
        # _ssrf_checked is deliberately keyword-only, private (leading
        # underscore), and defaults to False: the ONLY supported way to
        # construct a real OllamaClient is `await OllamaClient.create(...)`
        # (or the get_ollama_client() singleton below, which itself goes
        # through create()) -- never this constructor directly. That is
        # enforced here, not just documented, because a validation call
        # (app/core/url_safety.py's assert_safe_outbound_url, blocking
        # link-local addresses including the 169.254.169.254 cloud
        # instance-metadata address) used to live directly in this
        # constructor -- which meant every caller got it "for free" by
        # construction, but that check does a real DNS resolution, and
        # __init__ cannot be async. That forced the resolution through the
        # synchronous, un-timeboxed socket.getaddrinfo() called directly on
        # the shared asyncio event loop -- freezing the ENTIRE backend
        # process (every route, every other in-flight request, not just
        # this one) for however long resolution took, on every single
        # Ollama-backed AI call once runtime-config was seeded. Measured
        # live: a background asyncio ticker task ticking every 50ms recorded
        # ZERO ticks during a 0.567s synchronous getaddrinfo() call for an
        # unresolvable host, vs. the ~11 ticks expected if the loop had
        # stayed responsive. assert_safe_outbound_url() is now async (awaits
        # the event loop's own non-blocking resolver instead of calling
        # socket.getaddrinfo() directly) -- which an __init__ can never
        # await -- so the check now lives in create() below. Raising here
        # if some future caller reintroduces a direct `OllamaClient(...)`
        # call is what keeps that check from silently being skipped again.
        if not _ssrf_checked:
            raise RuntimeError(
                "OllamaClient must not be constructed directly -- use "
                "`await OllamaClient.create(...)` (or get_ollama_client()) so the "
                "SSRF/DNS-resolution safety check runs without blocking the event loop."
            )
        settings = get_settings()
        resolved_base_url = (base_url if base_url is not None else settings.ollama_base_url).rstrip("/")
        self._base_url = resolved_base_url
        self._model = model if model is not None else settings.ollama_model
        self._max_tokens = max_tokens if max_tokens is not None else settings.ollama_max_tokens
        # getattr fallback: some tests construct a minimal Settings stand-in
        # that predates this field; real app/core/config.py Settings always
        # defines ollama_timeout_seconds.
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "ollama_timeout_seconds", _TIMEOUT_SECONDS)
        )

    @classmethod
    async def create(
        cls,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ) -> "OllamaClient":
        """The one real construction choke point for OllamaClient -- awaits
        the SSRF/link-local check (app/core/url_safety.py's
        assert_safe_outbound_url) before constructing, so both the
        runtime-config override path (app/ai/service.py's _build_client)
        and the settings-only singleton path (get_ollama_client() below)
        are covered by construction, exactly like the previous __init__-
        based check was -- just async-safe now, so a slow/hanging DNS
        resolution for the configured host delays only this call, not every
        other concurrent request this process is serving."""
        settings = get_settings()
        resolved_base_url = (base_url if base_url is not None else settings.ollama_base_url).rstrip("/")

        from app.core.url_safety import assert_safe_outbound_url

        await assert_safe_outbound_url(resolved_base_url)
        return cls(
            base_url=resolved_base_url,
            model=model,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            _ssrf_checked=True,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._model)

    async def call_claude_json(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        tool_name: str = "emit_result",
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Named call_claude_json to match the Bedrock/Gemini/Anthropic
        clients' method name -- app/ai/service.py calls whichever backend is
        configured through this identical signature.
        """
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": inline_refs(json_schema),
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": max_tokens or self._max_tokens,
                "num_ctx": _estimate_num_ctx(system_prompt, user_prompt, max_tokens or self._max_tokens),
            },
        }

        # self._timeout_seconds (settings.ollama_timeout_seconds, default
        # 300) intentionally assumes CPU-only inference plus a possible cold
        # model reload, NOT "a model sized to fit fully in VRAM" -- this
        # backend's own default model/config runs CPU-only on an ordinary
        # dev/QA host, and Ollama's default idle-unload behavior means the
        # first call after any idle period pays a full reload (measured live
        # at 60-80s) on top of generation. See the module-level
        # _TIMEOUT_SECONDS comment for the live measurements this default is
        # based on. Operators running an even slower/larger model can raise
        # OLLAMA_TIMEOUT_SECONDS further without a code change.
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                response = await client.post(f"{self._base_url}/api/chat", json=body)
            except httpx.ConnectError as exc:
                raise RuntimeError(
                    f"Could not reach Ollama at {self._base_url} -- is it running? ({exc})"
                ) from exc
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"Ollama did not respond within {self._timeout_seconds}s (model={self._model}) -- "
                    "likely too slow for available hardware"
                ) from exc
            except httpx.HTTPError as exc:
                # Anything else httpx can raise once a connection is
                # established (reset mid-response, protocol error, etc).
                logger.error("Ollama request failed for model=%s: %r", self._model, exc)
                raise RuntimeError(f"Ollama request failed (model={self._model}): {exc!r}") from exc

        if response.status_code >= 400:
            logger.error("Ollama chat call failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Ollama invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        content = payload.get("message", {}).get("content", "")
        if not content:
            logger.error("Ollama response had no message content (model=%s): %r", self._model, payload)
            raise RuntimeError(f"Ollama response had no message content: {payload}")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Ollama response was not valid JSON (model=%s): %r", self._model, content)
            raise RuntimeError(f"Ollama response was not valid JSON: {content}") from exc

        if not isinstance(parsed, dict):
            logger.error("Ollama response JSON was not an object (model=%s): %r", self._model, parsed)
            raise RuntimeError(f"Ollama response was valid JSON but not an object: {parsed!r}")
        return parsed


_singleton: Optional[OllamaClient] = None


async def get_ollama_client() -> OllamaClient:
    global _singleton
    if _singleton is None:
        _singleton = await OllamaClient.create()
    return _singleton
