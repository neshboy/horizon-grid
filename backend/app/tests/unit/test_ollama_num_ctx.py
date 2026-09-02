"""Regression test for a real P1 bug found live during overnight QA:
app.ai.ollama_client's call_claude_json() never set num_ctx, so Ollama
0.33.0's default behavior sized the KV-cache to the MODEL's own trained
maximum context (131072 tokens for Llama 3.2) rather than the prompt --
confirmed live via `ollama ps` that one ordinary investigation turned a
2GB model into an 18GB resident allocation, with host free RAM dropping
into the 600MB-1.8GB range on a 16GB host. _estimate_num_ctx caps this to
something sane for a summarization-sized prompt.
"""
from app.ai.ollama_client import _MAX_NUM_CTX, _MIN_NUM_CTX, _estimate_num_ctx


def test_short_prompt_uses_the_minimum_not_the_models_full_context():
    result = _estimate_num_ctx("short system prompt", "IOC: 8.8.8.8", response_budget=512)
    assert result == _MIN_NUM_CTX
    assert result < 131072  # nowhere near a real model's trained max context


def test_long_prompt_scales_up_but_stays_bounded():
    huge_prompt = "x" * 100_000
    result = _estimate_num_ctx("system", huge_prompt, response_budget=512)
    assert result == _MAX_NUM_CTX  # capped, never unbounded


def test_medium_prompt_scales_between_the_bounds():
    medium_prompt = "x" * 9000  # ~3000 estimated tokens
    result = _estimate_num_ctx("system", medium_prompt, response_budget=1000)
    assert _MIN_NUM_CTX < result < _MAX_NUM_CTX
