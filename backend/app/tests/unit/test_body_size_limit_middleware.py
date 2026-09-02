"""Regression tests for app.main.request_body_size_limit_middleware's
chunked-Transfer-Encoding bypass, found live during overnight QA: the
middleware only ever checked the self-reported Content-Length header, which
chunked encoding omits entirely (standard HTTP/1.1 behavior, not a client
"lying") -- an ~11MB chunked body was fully read, buffered, and Pydantic-
validated with the documented 10MB cap never enforced at all.
"""
from types import SimpleNamespace

import pytest

from app.main import _MAX_REQUEST_BODY_BYTES, request_body_size_limit_middleware


class _FakeHeaders:
    def __init__(self, content_length=None):
        self._content_length = content_length

    def get(self, key):
        if key == "content-length":
            return self._content_length
        return None


def _fake_request(chunks, content_length=None):
    async def _stream():
        for chunk in chunks:
            yield chunk

    return SimpleNamespace(headers=_FakeHeaders(content_length), stream=_stream)


async def _call_next_ok(request):
    return SimpleNamespace(status_code=200)


@pytest.mark.asyncio
async def test_chunked_body_over_the_limit_with_no_content_length_header_is_rejected():
    """The exact bypass shape found live: no Content-Length header at all
    (as chunked Transfer-Encoding produces), body over the cap."""
    oversized_chunk = b"A" * (_MAX_REQUEST_BODY_BYTES + 1024)
    request = _fake_request([oversized_chunk], content_length=None)
    response = await request_body_size_limit_middleware(request, _call_next_ok)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_chunked_body_over_the_limit_split_across_many_small_chunks_is_rejected():
    """Confirms the byte-counting accumulates correctly across multiple
    stream chunks, not just a single big one."""
    chunk = b"A" * 1024
    num_chunks = (_MAX_REQUEST_BODY_BYTES // 1024) + 10
    request = _fake_request([chunk] * num_chunks, content_length=None)
    response = await request_body_size_limit_middleware(request, _call_next_ok)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_body_under_the_limit_with_no_content_length_header_passes_through():
    request = _fake_request([b"small body"], content_length=None)
    response = await request_body_size_limit_middleware(request, _call_next_ok)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_body_under_the_limit_populates_request_body_cache_for_downstream_use():
    request = _fake_request([b"hello", b" world"], content_length=None)
    await request_body_size_limit_middleware(request, _call_next_ok)
    assert request._body == b"hello world"
