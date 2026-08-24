"""Unit test for MsfRpcClient's bytes->str normalization -- regression test
for a real bug found during live verification against an actual msfrpcd:
Metasploit's Ruby msgpack encoder emits old-spec "raw" strings, which
Python's msgpack library (even with raw=False, the correct setting) decodes
as bytes rather than str, since raw=False only affects the newer str8/16/32
formats. Without _decode_bytes(), every key/value coming back from a real
msfrpcd call (including auth.login's own "token" field) is bytes, and the
rest of this module's code (which does `result.get("token")`,
`chunk.get("data")`, etc.) silently never matches, permanently reporting
Metasploit as unavailable."""
from app.pentest.msf_client import _decode_bytes


def test_decode_bytes_converts_a_flat_dict():
    assert _decode_bytes({b"result": b"success", b"token": b"abc123"}) == {"result": "success", "token": "abc123"}


def test_decode_bytes_converts_nested_lists_and_dicts():
    raw = {b"data": b"some output\n", b"busy": False, b"refs": [[b"CVE", b"2017-0144"]]}
    assert _decode_bytes(raw) == {"data": "some output\n", "busy": False, "refs": [["CVE", "2017-0144"]]}


def test_decode_bytes_leaves_non_bytes_scalars_untouched():
    assert _decode_bytes({b"count": 5, b"ok": True, b"score": None}) == {"count": 5, "ok": True, "score": None}


def test_decode_bytes_falls_back_to_raw_bytes_on_invalid_utf8():
    invalid = b"\xff\xfe"
    assert _decode_bytes(invalid) is invalid
