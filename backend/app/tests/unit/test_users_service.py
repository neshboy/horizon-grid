"""Pure-logic unit tests for app.core.users's last-admin-protection counting
helper -- the actual security invariant behind "cannot disable/demote the
last administrator" -- exercised directly against SimpleNamespace fakes
rather than a real database, mirroring app/tests/unit/test_runtime_config.py's
established pattern for _merge_credentials.
"""
import uuid
from types import SimpleNamespace

from app.core.users import _remaining_active_admins


def _admin(active: bool = True):
    return SimpleNamespace(id=uuid.uuid4(), is_active=active)


def test_remaining_active_admins_excludes_the_target():
    a, b = _admin(), _admin()
    assert _remaining_active_admins([a, b], excluding=a.id) == 1


def test_remaining_active_admins_is_zero_when_target_is_the_only_active_one():
    a = _admin(active=True)
    b = _admin(active=False)  # already disabled -- shouldn't count as "remaining"
    assert _remaining_active_admins([a, b], excluding=a.id) == 0


def test_remaining_active_admins_counts_only_active_rows():
    a = _admin(active=True)
    b = _admin(active=True)
    c = _admin(active=False)
    assert _remaining_active_admins([a, b, c], excluding=a.id) == 1


def test_remaining_active_admins_empty_list():
    target_id = uuid.uuid4()
    assert _remaining_active_admins([], excluding=target_id) == 0
