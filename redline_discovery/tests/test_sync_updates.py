"""
Regression test for sync_updates.py's Pass 2 false-success bug: a failed
change-detection pass (the bulk fetch itself, or any individual request)
used to still advance the watermark and report "success" — permanently
skipping that window's changes, since the next run starts from wherever the
watermark says, not from what was actually synced. Fixed version must keep
the old watermark and report a non-"success" status whenever Pass 2 fails.

Mocks db/config/request_api via sys.modules so this never touches Postgres
or the live CobbleStone API — sync_updates.py only ever calls them through
module-level names, so swapping the modules before import/reload is enough.
data_refresh_lock is faked for the same reason: the real one is a PID lock
file shared with every other data-writing script, so without this a unit
test would silently no-op (and falsely "pass" as a KeyError) whenever a real
backfill/repair/scan happened to be running on the machine.
"""

import importlib
import sys
import types
from datetime import datetime

import pytest


def _install_fakes(monkeypatch, tmp_path, pass2_should_fail: bool, old_watermark):
    updates = {}

    fake_config = types.ModuleType("config")
    fake_config.OUTPUT_DIR = tmp_path

    fake_db = types.ModuleType("db")
    fake_db.get_connection = lambda: types.SimpleNamespace(commit=lambda: None, close=lambda: None, rollback=lambda: None)
    fake_db.max_request_id = lambda conn: 100
    fake_db.get_requests = lambda conn, active_only=False: []
    fake_db.get_sync_state = lambda conn: {
        "last_incremental_watermark": old_watermark, "last_run_at": None, "last_run_status": "success"
    }
    fake_db.upsert_request = lambda conn, r: None
    fake_db.upsert_file = lambda conn, f, rid: None
    fake_db.update_sync_state = lambda conn, **fields: updates.update(fields)

    fake_request_api = types.ModuleType("request_api")
    fake_request_api.get_bearer_token = lambda force_refresh=False: "tok"
    fake_request_api.fetch_all_requests = lambda token, start_after_id=0: []
    fake_request_api.fetch_request_file_list = lambda rid, token: []

    def fake_fetch_requests_updated_since(token, since):
        if pass2_should_fail:
            raise RuntimeError("simulated 401")
        return [{"RequestID": 555}]
    fake_request_api.fetch_requests_updated_since = fake_fetch_requests_updated_since

    class _NoOpLock:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake_lock_module = types.ModuleType("data_refresh_lock")
    fake_lock_module.DataRefreshLock = _NoOpLock

    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "db", fake_db)
    monkeypatch.setitem(sys.modules, "request_api", fake_request_api)
    monkeypatch.setitem(sys.modules, "data_refresh_lock", fake_lock_module)

    if "sync_updates" in sys.modules:
        importlib.reload(sys.modules["sync_updates"])
    else:
        import sync_updates  # noqa: F401
    return sys.modules["sync_updates"], updates


@pytest.fixture(autouse=True)
def _clear_sync_updates_module():
    # Force a fresh import against each test's fakes rather than reusing a
    # previously-imported module bound to a prior test's fake dependencies.
    sys.modules.pop("sync_updates", None)
    yield
    sys.modules.pop("sync_updates", None)


def test_pass2_failure_does_not_advance_watermark(monkeypatch, tmp_path):
    old_wm = datetime(2026, 1, 1)
    sync_updates, updates = _install_fakes(monkeypatch, tmp_path, pass2_should_fail=True, old_watermark=old_wm)

    sync_updates.main()

    assert updates["last_incremental_watermark"] == old_wm
    assert updates["last_run_status"] == "pass2_failed"


def test_pass2_success_advances_watermark(monkeypatch, tmp_path):
    old_wm = datetime(2026, 1, 1)
    sync_updates, updates = _install_fakes(monkeypatch, tmp_path, pass2_should_fail=False, old_watermark=old_wm)

    sync_updates.main()

    assert updates["last_incremental_watermark"] != old_wm
    assert updates["last_run_status"] == "success"


def test_first_run_with_no_prior_watermark_still_succeeds(monkeypatch, tmp_path):
    sync_updates, updates = _install_fakes(monkeypatch, tmp_path, pass2_should_fail=False, old_watermark=None)

    sync_updates.main()

    assert updates["last_incremental_watermark"] is not None
    assert updates["last_run_status"] == "success"
