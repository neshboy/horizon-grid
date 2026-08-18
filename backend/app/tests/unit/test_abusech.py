"""Tests for the shared abuse.ch query_status mapping used by URLhaus,
ThreatFox, and MalwareBazaar -- see app/providers/abusech.py. Pins down the
fix for auth/config failures being indistinguishable from a genuine clean
result (both used to collapse into ProviderStatus.NO_DATA).
"""
from app.providers.abusech import map_query_status
from app.providers.base import ProviderStatus


def test_ok_status_maps_to_ok():
    status, error_message = map_query_status("ok")
    assert status == ProviderStatus.OK
    assert error_message is None


def test_missing_api_key_maps_to_error_not_no_data():
    status, error_message = map_query_status("no_api_key")
    assert status == ProviderStatus.ERROR
    assert "Auth-Key" in error_message


def test_invalid_api_key_maps_to_error():
    status, error_message = map_query_status("invalid_api_key")
    assert status == ProviderStatus.ERROR


def test_genuine_empty_result_maps_to_no_data():
    status, error_message = map_query_status("no_results")
    assert status == ProviderStatus.NO_DATA
    assert error_message is None


def test_hash_not_found_maps_to_no_data():
    status, error_message = map_query_status("hash_not_found")
    assert status == ProviderStatus.NO_DATA
