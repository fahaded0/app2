"""Lifecycle unit tests for backend/server.py.

Proves MongoDB client is not created at import time and that the startup
failure path closes the client exactly once and resets module state.

No live MongoDB, no network, no FastAPI server, no production environment.
"""
from __future__ import annotations

import asyncio
import sys
import os
import types
import logging
from unittest.mock import AsyncMock, MagicMock, patch, call

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest

# Stub dotenv before any server import so tests work without the package installed
if "dotenv" not in sys.modules:
    _dotenv_stub = types.ModuleType("dotenv")
    _dotenv_stub.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = _dotenv_stub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_GOOD_ENV = {
    "APP_ENV": "development",
    "MONGO_URL": "mongodb://localhost:27017",
    "DB_NAME": "testdb",
    "JWT_SECRET": "a" * 32,
    "COOKIE_SECURE": "false",
    "COOKIE_SAMESITE": "lax",
    "CORS_ALLOWED_ORIGINS": "",
    "SEED_DATA_ENABLED": "false",
    "ADMIN_EMAIL": "",
    "ADMIN_PASSWORD": "",
}

_SEED_ENV = dict(
    _GOOD_ENV,
    SEED_DATA_ENABLED="true",
    ADMIN_EMAIL="admin@ex.com",
    ADMIN_PASSWORD="StrongPassword1!",
)


def _make_col():
    col = MagicMock()
    col.create_index = AsyncMock(return_value="idx")
    col.update_many = AsyncMock(return_value=None)
    return col


def _make_db():
    db = MagicMock()
    for name in ["users", "items", "departments", "stock_entries", "stock_transactions",
                 "item_department_thresholds", "escalation_recipients", "stock_requests",
                 "alerts", "audit_logs", "login_attempts"]:
        setattr(db, name, _make_col())
    return db


def _make_client(db):
    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=db)
    client.close = AsyncMock()
    return client


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _all_stubs():
    """Return sys.modules stubs dict for a clean server import."""
    _jwt = types.ModuleType("jwt")
    _jwt.encode = MagicMock(return_value="tok")
    _jwt.decode = MagicMock(return_value={})
    _jwt.ExpiredSignatureError = Exception
    _jwt.InvalidTokenError = Exception

    _bcrypt = types.ModuleType("bcrypt")
    _bcrypt.gensalt = MagicMock(return_value=b"salt")
    _bcrypt.hashpw = MagicMock(return_value=b"hash")
    _bcrypt.checkpw = MagicMock(return_value=True)

    _pymongo = types.ModuleType("pymongo")
    _pymongo.__path__ = []
    _pymongo.AsyncMongoClient = MagicMock

    _pymongo_async = types.ModuleType("pymongo.asynchronous")
    _pymongo_async.__path__ = []

    _pymongo_async_database = types.ModuleType(
        "pymongo.asynchronous.database"
    )
    _pymongo_async_database.AsyncDatabase = object

    _pymongo_errors = types.ModuleType("pymongo.errors")
    _pymongo_errors.DuplicateKeyError = Exception

    _pymongo.asynchronous = _pymongo_async
    _pymongo_async.database = _pymongo_async_database

    d = {
        "jwt": _jwt,
        "bcrypt": _bcrypt,
        "pymongo": _pymongo,
        "pymongo.asynchronous": _pymongo_async,
        "pymongo.asynchronous.database": _pymongo_async_database,
        "pymongo.errors": _pymongo_errors,
        "state_machine": types.ModuleType("state_machine"),
        "settings_store": types.ModuleType("settings_store"),
        "scheduler": types.ModuleType("scheduler"),
        "excel_import": types.ModuleType("excel_import"),
        "stock_issue": types.ModuleType("stock_issue"),
        "email_service": types.ModuleType("email_service"),
        "seed": types.ModuleType("seed"),
        "reports_export": types.ModuleType("reports_export"),
    }
    d["state_machine"].validate_request_transition = MagicMock()
    d["state_machine"].validate_alert_transition = MagicMock()
    d["settings_store"].get_settings = AsyncMock()
    d["settings_store"].update_settings = AsyncMock()
    d["scheduler"].scheduler_loop = AsyncMock()
    d["scheduler"]._reconciliation_loop = AsyncMock()
    d["seed"].seed = AsyncMock()
    d["reports_export"].build_excel = None
    d["reports_export"].build_pdf = None
    return d


# ---------------------------------------------------------------------------
# 1. Import safety
# ---------------------------------------------------------------------------
class TestImportSafety:
    def test_import_does_not_instantiate_mongo_client(self):
        call_count = 0

        class CountingClient:
            def __init__(self, *a, **kw):
                nonlocal call_count
                call_count += 1

        stubs = _all_stubs()
        stubs["pymongo"].AsyncMongoClient = CountingClient

        saved = {k: sys.modules.get(k) for k in stubs}
        sys.modules.update(stubs)
        sys.modules.pop("server", None)
        sys.modules.pop("auth", None)

        try:
            import server as srv
            assert call_count == 0, f"AsyncMongoClient called {call_count}x during import"
            assert srv.client is None
            assert srv.db is None
            print("IMPORT SAFETY: PASS")
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("server", None)
            sys.modules.pop("auth", None)


# ---------------------------------------------------------------------------
# Fixture: patched server module
# ---------------------------------------------------------------------------
@pytest.fixture()
def srv():
    """Return the server module with external deps monkeypatched."""
    import importlib

    stubs = _all_stubs()
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    sys.modules.pop("server", None)
    sys.modules.pop("auth", None)

    import server as srv_mod
    importlib.reload(srv_mod)

    srv_mod.client = None
    srv_mod.db = None

    yield srv_mod

    srv_mod.client = None
    srv_mod.db = None
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    sys.modules.pop("server", None)
    sys.modules.pop("auth", None)


# ---------------------------------------------------------------------------
# 2. Module-level client and db are None after import
# ---------------------------------------------------------------------------
def test_module_level_none(srv):
    assert srv.client is None
    assert srv.db is None


# ---------------------------------------------------------------------------
# 3. Config validation occurs before client construction
# ---------------------------------------------------------------------------
def test_config_validated_before_client_construction(srv):
    client_constructed = False

    class SpyClient:
        def __init__(self, *a, **kw):
            nonlocal client_constructed
            client_constructed = True

    with patch.object(srv, "load_runtime_config", side_effect=ValueError("bad config")):
        with patch.object(srv, "AsyncMongoClient", SpyClient):
            with pytest.raises(ValueError, match="bad config"):
                _run(srv.startup())

    assert not client_constructed, "Client was constructed despite config validation failure"
    assert srv.client is None
    assert srv.db is None


# ---------------------------------------------------------------------------
# 4. Index creation failure closes client exactly once
# ---------------------------------------------------------------------------
def test_index_failure_closes_client_once(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    db.users.create_index = AsyncMock(side_effect=RuntimeError("index boom"))
    client = _make_client(db)

    with patch.object(srv, "load_runtime_config", return_value=cfg):
        with patch.object(srv, "AsyncMongoClient", return_value=client):
            with pytest.raises(RuntimeError, match="index boom"):
                _run(srv.startup())

    client.close.assert_awaited_once()
    assert srv.client is None
    assert srv.db is None
    assert srv.app.state.db is None


# ---------------------------------------------------------------------------
# 5. Seed failure closes client exactly once
# Seed errors are fatal: logged then re-raised, triggering the outer cleanup.
# ---------------------------------------------------------------------------
def test_seed_failure_closes_client_once(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_SEED_ENV)

    db = _make_db()
    client = _make_client(db)

    with patch.object(srv, "load_runtime_config", return_value=cfg):
        with patch.object(srv, "AsyncMongoClient", return_value=client):
            with patch.object(srv, "seed_data", AsyncMock(side_effect=RuntimeError("seed initialization failed"))):
                with pytest.raises(RuntimeError, match="seed initialization failed"):
                    _run(srv.startup())

    client.close.assert_awaited_once()
    assert srv.client is None
    assert srv.db is None
    assert srv.app.state.db is None


# ---------------------------------------------------------------------------
# 6. Scheduler failure closes client exactly once
# ---------------------------------------------------------------------------
def test_scheduler_failure_closes_client_once(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    client = _make_client(db)

    def boom_task(coro, **kw):
        coro.close()
        raise RuntimeError("scheduler boom")

    with patch.object(srv, "load_runtime_config", return_value=cfg):
        with patch.object(srv, "AsyncMongoClient", return_value=client):
            with patch("asyncio.create_task", side_effect=boom_task):
                with pytest.raises(RuntimeError, match="scheduler boom"):
                    _run(srv.startup())

    client.close.assert_awaited_once()
    assert srv.client is None
    assert srv.db is None
    assert srv.app.state.db is None


# ---------------------------------------------------------------------------
# 7. After failed startup: all state is None
# ---------------------------------------------------------------------------
def test_after_failed_startup_state_is_none(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    db.users.create_index = AsyncMock(side_effect=RuntimeError("fail"))
    client = _make_client(db)

    with patch.object(srv, "load_runtime_config", return_value=cfg):
        with patch.object(srv, "AsyncMongoClient", return_value=client):
            with pytest.raises(RuntimeError):
                _run(srv.startup())

    assert srv.client is None
    assert srv.db is None
    assert srv.app.state.db is None


# ---------------------------------------------------------------------------
# 8. Normal shutdown closes a live client exactly once
# ---------------------------------------------------------------------------
def test_normal_shutdown_sequence(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    client = _make_client(db)

    async def scenario():
        with patch.object(srv, "load_runtime_config", return_value=cfg):
            with patch.object(srv, "AsyncMongoClient", return_value=client):
                await srv.startup()

        assert srv.client is client

        await srv.shutdown()

    _run(scenario())

    client.close.assert_awaited_once()
    assert srv.client is None
    assert srv.db is None
    assert srv.app.state.db is None


# ---------------------------------------------------------------------------
# 9. Shutdown with client=None does not fail or close
# ---------------------------------------------------------------------------
def test_shutdown_with_none_client_does_not_fail(srv):
    assert srv.client is None
    _run(srv.shutdown())  # must not raise


def test_shutdown_with_none_client_does_not_call_close(srv):
    fake_client = MagicMock()
    # Ensure client is None — shutdown must NOT close anything
    assert srv.client is None
    _run(srv.shutdown())
    fake_client.close.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Package 2A-4: shutdown cancels and awaits background tasks
#
# The startup() default stubs for scheduler_loop / _reconciliation_loop are
# AsyncMocks that resolve instantly, so these tests install real coroutines
# that hang on an unset asyncio.Event to prove actual cancellation happens.
# ---------------------------------------------------------------------------
def _make_hanging_loop(events: list, name: str):
    """A background-loop stand-in that never returns until cancelled."""
    async def _loop(db):
        try:
            await asyncio.Event().wait()
        finally:
            events.append(f"{name}:torn_down")
    return _loop


async def _boom_loop(db):
    raise RuntimeError(f"{db!r} boom")


def test_shutdown_cancels_and_awaits_both_tasks_before_client_close(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    client = _make_client(db)
    events = []
    client.close = AsyncMock(side_effect=lambda: events.append("client:closed"))

    async def scenario():
        with patch.object(srv, "load_runtime_config", return_value=cfg):
            with patch.object(srv, "AsyncMongoClient", return_value=client):
                with patch.object(srv.scheduler_mod, "scheduler_loop", _make_hanging_loop(events, "scheduler_task")):
                    with patch.object(srv.scheduler_mod, "_reconciliation_loop", _make_hanging_loop(events, "reconcile_task")):
                        await srv.startup()

        scheduler_task = srv.app.state.scheduler_task
        reconcile_task = srv.app.state.reconcile_task
        assert isinstance(scheduler_task, asyncio.Task)
        assert isinstance(reconcile_task, asyncio.Task)

        await asyncio.sleep(0)
        assert not scheduler_task.done()
        assert not reconcile_task.done()

        await srv.shutdown()

        assert scheduler_task.cancelled()
        assert reconcile_task.cancelled()

    _run(scenario())

    # Both background tasks must be fully torn down before the client closes.
    # Relative order between the two tasks' teardown is not required — only
    # that client:closed is last.
    assert events[-1] == "client:closed"
    assert set(events[:-1]) == {"scheduler_task:torn_down", "reconcile_task:torn_down"}
    client.close.assert_awaited_once()
    assert srv.app.state.scheduler_task is None
    assert srv.app.state.reconcile_task is None
    assert srv.client is None
    assert srv.db is None
    assert srv.app.state.db is None


def test_shutdown_cancelled_error_does_not_escape(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    client = _make_client(db)
    events = []

    async def scenario():
        with patch.object(srv, "load_runtime_config", return_value=cfg):
            with patch.object(srv, "AsyncMongoClient", return_value=client):
                with patch.object(srv.scheduler_mod, "scheduler_loop", _make_hanging_loop(events, "scheduler_task")):
                    with patch.object(srv.scheduler_mod, "_reconciliation_loop", _make_hanging_loop(events, "reconcile_task")):
                        await srv.startup()

        # Must not raise asyncio.CancelledError (or anything else) to the caller.
        await srv.shutdown()

    _run(scenario())  # must not raise
    client.close.assert_awaited_once()


def test_shutdown_logs_non_cancellation_exception_and_still_closes_client(srv, caplog):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    client = _make_client(db)

    async def scenario():
        with patch.object(srv, "load_runtime_config", return_value=cfg):
            with patch.object(srv, "AsyncMongoClient", return_value=client):
                await srv.startup()

        # Replace scheduler_task with one already *done* with a real exception.
        bad_task = asyncio.create_task(_boom_loop(db))
        await asyncio.sleep(0)  # let it run to completion
        assert bad_task.done()
        srv.app.state.scheduler_task = bad_task

        with caplog.at_level(logging.ERROR):
            await srv.shutdown()  # must not raise

    _run(scenario())

    assert any("scheduler_task" in m for m in caplog.messages)
    client.close.assert_awaited_once()
    assert srv.app.state.scheduler_task is None
    assert srv.app.state.reconcile_task is None


def test_shutdown_one_task_failure_does_not_block_the_other(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    client = _make_client(db)
    events = []

    async def scenario():
        with patch.object(srv, "load_runtime_config", return_value=cfg):
            with patch.object(srv, "AsyncMongoClient", return_value=client):
                with patch.object(srv.scheduler_mod, "_reconciliation_loop", _make_hanging_loop(events, "reconcile_task")):
                    await srv.startup()

        bad_task = asyncio.create_task(_boom_loop(db))
        await asyncio.sleep(0)
        assert bad_task.done()
        srv.app.state.scheduler_task = bad_task
        reconcile_task = srv.app.state.reconcile_task

        await srv.shutdown()  # must not raise despite scheduler_task's failure

        assert reconcile_task.cancelled()

    _run(scenario())

    assert "reconcile_task:torn_down" in events
    client.close.assert_awaited_once()
    assert srv.app.state.scheduler_task is None
    assert srv.app.state.reconcile_task is None


def test_shutdown_missing_task_attributes_does_not_raise(srv):
    assert not hasattr(srv.app.state, "scheduler_task")
    assert not hasattr(srv.app.state, "reconcile_task")
    _run(srv.shutdown())  # must not raise


def test_shutdown_none_task_attributes_does_not_raise(srv):
    srv.app.state.scheduler_task = None
    srv.app.state.reconcile_task = None
    _run(srv.shutdown())  # must not raise
    assert srv.app.state.scheduler_task is None
    assert srv.app.state.reconcile_task is None


def test_shutdown_done_successful_task_does_not_raise(srv):
    async def _ok(db):
        return "done"

    async def scenario():
        task = asyncio.create_task(_ok(None))
        await asyncio.sleep(0)
        assert task.done()
        srv.app.state.scheduler_task = task
        srv.app.state.reconcile_task = None
        await srv.shutdown()  # must not raise

    _run(scenario())
    assert srv.app.state.scheduler_task is None


def test_shutdown_idempotent_when_called_twice(srv):
    from runtime_config import load_runtime_config as _real_lcr
    cfg = _real_lcr(_GOOD_ENV)

    db = _make_db()
    client = _make_client(db)
    events = []

    async def scenario():
        with patch.object(srv, "load_runtime_config", return_value=cfg):
            with patch.object(srv, "AsyncMongoClient", return_value=client):
                with patch.object(srv.scheduler_mod, "scheduler_loop", _make_hanging_loop(events, "scheduler_task")):
                    with patch.object(srv.scheduler_mod, "_reconciliation_loop", _make_hanging_loop(events, "reconcile_task")):
                        await srv.startup()

        await srv.shutdown()
        await srv.shutdown()  # second call must be a safe no-op

    _run(scenario())

    client.close.assert_awaited_once()
    assert srv.app.state.scheduler_task is None
    assert srv.app.state.reconcile_task is None
    assert srv.client is None
    assert srv.db is None
    assert srv.app.state.db is None


# ---------------------------------------------------------------------------
# Startup log: no secrets or DB_NAME in summary
# ---------------------------------------------------------------------------
def test_startup_log_does_not_contain_secrets(srv, caplog):
    from runtime_config import load_runtime_config as _real_lcr

    secret_jwt = "z" * 32
    secret_db = "my_secret_dbname"
    env = dict(_GOOD_ENV, JWT_SECRET=secret_jwt, DB_NAME=secret_db)
    cfg = _real_lcr(env)

    db = _make_db()
    client = _make_client(db)

    with caplog.at_level(logging.INFO):
        with patch.object(srv, "load_runtime_config", return_value=cfg):
            with patch.object(srv, "AsyncMongoClient", return_value=client):
                _run(srv.startup())

    combined = "\n".join(caplog.messages)
    assert secret_jwt not in combined, "JWT_SECRET appeared in startup log"
    assert secret_db not in combined, "DB_NAME appeared in startup log"
