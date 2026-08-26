"""Unit tests for parse_ollama_tags_response -- extracted from the
/api/v1/ai/{backend}/models endpoint specifically to close a real bug found
via a user's failed self-hosted install: Ollama's GET /api/tags returning a
literal `{"models": null}` (not a missing key, not an empty array) crashed
the model-listing endpoint with an uncaught TypeError instead of falling
back to the static model list.
"""
from app.api.routes.ai_config import parse_ollama_tags_response


def test_literal_null_models_field_does_not_crash():
    assert parse_ollama_tags_response({"models": None}) == []


def test_missing_models_key_does_not_crash():
    assert parse_ollama_tags_response({}) == []


def test_empty_models_array_is_empty_result():
    assert parse_ollama_tags_response({"models": []}) == []


def test_normal_response_extracts_names():
    payload = {"models": [{"name": "llama3.2:3b"}, {"name": "llama3.1:8b"}]}
    assert parse_ollama_tags_response(payload) == ["llama3.2:3b", "llama3.1:8b"]


def test_entry_using_model_key_instead_of_name_is_still_extracted():
    # Some Ollama API versions/proxies use "model" instead of "name".
    payload = {"models": [{"model": "llama3.2:3b"}]}
    assert parse_ollama_tags_response(payload) == ["llama3.2:3b"]


def test_entry_missing_both_name_and_model_keys_is_skipped_not_crashed():
    payload = {"models": [{"name": "llama3.2:3b"}, {"size": 12345}]}
    assert parse_ollama_tags_response(payload) == ["llama3.2:3b"]


def test_non_dict_entry_in_models_array_is_skipped_not_crashed():
    payload = {"models": [{"name": "llama3.2:3b"}, "unexpected-string-entry", None]}
    assert parse_ollama_tags_response(payload) == ["llama3.2:3b"]
