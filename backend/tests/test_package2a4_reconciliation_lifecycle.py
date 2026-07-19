"""Package 2A-4: Reconciliation Lifecycle and Audit Hardening — test suite.

Covers the two Package 2A-4 functional changes:
  1. Background task cancellation/await during normal shutdown of
     backend/server.py (unit-tested separately in test_server_lifecycle.py).
  2. Audit logging of successful manual POST /api/admin/reconcile-stock
     invocations.

This file has two independent suites:

  * A fast, isolated unit suite (below) that imports backend/server.py with
    normal imports (no sys.modules stubbing) and exercises
    ``admin_reconcile_stock`` directly with ``scheduler_mod.reconcile_stock_balances``
    and ``write_audit`` mocked via ``unittest.mock``. These require the
    project's real runtime dependencies (fastapi, pymongo, jwt,
    bcrypt, python-dotenv, pytest) to be importable — consistent with the
    rest of the repository's non-integration unit tests that import server.py
    or its collaborators directly.

  * A ``@pytest.mark.integration`` suite (search for "DOCKER INTEGRATION
    TESTS") that exercises the live HTTP endpoint and a live MongoDB replica
    set, following the exact conventions already established in
    test_package2a3_ledger_backfill.py's "REAL DOCKER INTEGRATION TESTS"
    section: REACT_APP_BACKEND_URL-gated, auto-skipped by tests/conftest.py
    otherwise, no dependence on fixed seed counts, no cleanup of audit_logs
    (audit evidence is treated as permanent, matching the existing
    backfill_v2_baselines audit-evidence test).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server as srv  # noqa: E402  (normal import — no global stubbing)


# ---------------------------------------------------------------------------
# Unit-test helpers
# ---------------------------------------------------------------------------
def _fake_user(role: str = "super_admin") -> dict:
    return {
        "id": f"user-{uuid.uuid4().hex[:8]}",
        "email": "admin@example.com",
        "role": role,
        "full_name": "Test Admin",
    }


def _fake_request():
    """A minimal stand-in for fastapi.Request — write_audit only reads .client.host."""
    return SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))


def _discrepancy(kind, **extra) -> dict:
    return {"kind": kind, "item_id": "item-x", "department_id": "dept-x", "message": "mismatch", **extra}


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Successful reconciliation writes exactly one audit entry
# ---------------------------------------------------------------------------
class TestSuccessfulReconcileAudit:
    def test_write_audit_called_exactly_once_on_success(self):
        discrepancies = [_discrepancy("missing_stock_entry")]
        user = _fake_user()
        request = _fake_request()

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", AsyncMock(return_value=discrepancies)):
            with patch.object(srv, "write_audit", AsyncMock()) as mock_audit:
                result = _run(srv.admin_reconcile_stock(request=request, user=user))

        mock_audit.assert_called_once()
        assert result["count"] == 1
        assert result["discrepancies"] == discrepancies

    def test_write_audit_receives_actual_user_and_request(self):
        discrepancies = [_discrepancy("missing_v2_ledger")]
        user = _fake_user()
        request = _fake_request()

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", AsyncMock(return_value=discrepancies)):
            with patch.object(srv, "write_audit", AsyncMock()) as mock_audit:
                _run(srv.admin_reconcile_stock(request=request, user=user))

        args, kwargs = mock_audit.call_args
        assert args[0] is user
        assert kwargs["request"] is request

    def test_action_entity_and_entity_id(self):
        user = _fake_user()
        request = _fake_request()

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", AsyncMock(return_value=[])):
            with patch.object(srv, "write_audit", AsyncMock()) as mock_audit:
                _run(srv.admin_reconcile_stock(request=request, user=user))

        args, kwargs = mock_audit.call_args
        assert args[1] == "reconcile_stock"
        assert args[2] == "reconciliation_log"
        assert kwargs["entity_id"] is None
        assert kwargs["old_value"] is None

    def test_new_value_contains_only_count_and_kinds(self):
        discrepancies = [_discrepancy("missing_stock_entry"), _discrepancy("balance_mismatch")]
        user = _fake_user()
        request = _fake_request()

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", AsyncMock(return_value=discrepancies)):
            with patch.object(srv, "write_audit", AsyncMock()) as mock_audit:
                _run(srv.admin_reconcile_stock(request=request, user=user))

        new_value = mock_audit.call_args.kwargs["new_value"]
        assert set(new_value.keys()) == {"discrepancy_count", "discrepancy_kinds"}
        assert new_value["discrepancy_count"] == 2

    def test_full_discrepancies_list_not_placed_in_new_value(self):
        discrepancies = [
            _discrepancy("missing_stock_entry", item_id="secret-item", department_id="secret-dept",
                         message="do not leak me"),
        ]
        user = _fake_user()
        request = _fake_request()

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", AsyncMock(return_value=discrepancies)):
            with patch.object(srv, "write_audit", AsyncMock()) as mock_audit:
                _run(srv.admin_reconcile_stock(request=request, user=user))

        new_value = mock_audit.call_args.kwargs["new_value"]
        blob = str(new_value)
        assert "secret-item" not in blob
        assert "secret-dept" not in blob
        assert "do not leak me" not in blob
        assert "discrepancies" not in new_value

    def test_endpoint_return_shape_unchanged(self):
        discrepancies = [_discrepancy("missing_stock_entry")]
        user = _fake_user()
        request = _fake_request()

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", AsyncMock(return_value=discrepancies)):
            with patch.object(srv, "write_audit", AsyncMock()):
                result = _run(srv.admin_reconcile_stock(request=request, user=user))

        assert set(result.keys()) == {"checked_at", "count", "discrepancies"}
        assert result["count"] == len(result["discrepancies"]) == 1


# ---------------------------------------------------------------------------
# 2. Defensive discrepancy_kinds construction
# ---------------------------------------------------------------------------
class TestDiscrepancyKindsExtraction:
    def _kinds_for(self, discrepancies) -> list:
        user = _fake_user()
        request = _fake_request()
        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", AsyncMock(return_value=discrepancies)):
            with patch.object(srv, "write_audit", AsyncMock()) as mock_audit:
                _run(srv.admin_reconcile_stock(request=request, user=user))
        return mock_audit.call_args.kwargs["new_value"]["discrepancy_kinds"]

    def test_duplicate_kinds_are_deduplicated_and_sorted(self):
        discrepancies = [
            _discrepancy("missing_stock_entry"),
            _discrepancy("balance_mismatch"),
            _discrepancy("missing_stock_entry"),
            _discrepancy("balance_mismatch"),
        ]
        kinds = self._kinds_for(discrepancies)
        assert kinds == sorted(set(kinds))
        assert kinds == ["balance_mismatch", "missing_stock_entry"]

    def test_missing_kind_key_becomes_unknown(self):
        d = {"item_id": "x", "department_id": "y", "message": "no kind field"}
        kinds = self._kinds_for([d])
        assert kinds == ["unknown"]

    def test_null_kind_becomes_unknown(self):
        kinds = self._kinds_for([_discrepancy(None)])
        assert kinds == ["unknown"]

    def test_empty_string_kind_becomes_unknown(self):
        kinds = self._kinds_for([_discrepancy("")])
        assert kinds == ["unknown"]

    def test_mixed_known_and_unknown_kinds(self):
        discrepancies = [
            _discrepancy("missing_stock_entry"),
            _discrepancy(None),
            {"item_id": "x", "department_id": "y", "message": "no kind"},
            _discrepancy(""),
        ]
        kinds = self._kinds_for(discrepancies)
        assert kinds == ["missing_stock_entry", "unknown"]

    def test_no_discrepancies_yields_empty_kinds(self):
        kinds = self._kinds_for([])
        assert kinds == []


# ---------------------------------------------------------------------------
# 3. Failure behaviour
# ---------------------------------------------------------------------------
class TestFailureBehaviour:
    def test_reconcile_failure_results_in_zero_audit_calls(self):
        user = _fake_user()
        request = _fake_request()

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances",
                           AsyncMock(side_effect=RuntimeError("reconciliation exploded"))):
            with patch.object(srv, "write_audit", AsyncMock()) as mock_audit:
                with pytest.raises(RuntimeError, match="reconciliation exploded"):
                    _run(srv.admin_reconcile_stock(request=request, user=user))

        mock_audit.assert_not_called()

    def test_audit_failure_propagates(self):
        user = _fake_user()
        request = _fake_request()

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", AsyncMock(return_value=[])):
            with patch.object(srv, "write_audit", AsyncMock(side_effect=RuntimeError("audit write failed"))):
                with pytest.raises(RuntimeError, match="audit write failed"):
                    _run(srv.admin_reconcile_stock(request=request, user=user))

    def test_audit_failure_does_not_trigger_a_reconciliation_retry(self):
        user = _fake_user()
        request = _fake_request()
        reconcile_mock = AsyncMock(return_value=[])

        with patch.object(srv.scheduler_mod, "reconcile_stock_balances", reconcile_mock):
            with patch.object(srv, "write_audit", AsyncMock(side_effect=RuntimeError("audit write failed"))):
                with pytest.raises(RuntimeError, match="audit write failed"):
                    _run(srv.admin_reconcile_stock(request=request, user=user))

        reconcile_mock.assert_called_once()


# ===========================================================================
# DOCKER INTEGRATION TESTS
#
# Exercise the live HTTP endpoint and a live MongoDB replica set, following
# the same conventions as test_package2a3_ledger_backfill.py's "REAL DOCKER
# INTEGRATION TESTS" section: REACT_APP_BACKEND_URL-gated (auto-skipped by
# tests/conftest.py when it is not set), no fixed seed-count dependence
# (before/after deltas only), and no shutdown/kill of the backend container
# — shutdown behaviour is proved at the unit level in test_server_lifecycle.py.
#
# audit_logs entries created by these tests are NOT deleted: they are audit
# evidence, and the existing repository precedent (test_package2a3's
# TestRealAuditEvidence) leaves its equivalent audit_logs entries in place
# too. Nothing else is created or modified by these tests, so there is
# nothing unsafe left behind.
# ===========================================================================
import requests  # noqa: E402

_BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").strip().rstrip("/")
_API = f"{_BASE_URL}/api"

_ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@medstock.sa")
_ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@12345")
# Seeded by backend/seed.py — a role outside {super_admin, digital_health_manager}.
_AUDITOR_EMAIL = os.environ.get("TEST_AUDITOR_EMAIL", "auditor@medstock.sa")
_AUDITOR_PASSWORD = os.environ.get("TEST_AUDITOR_PASSWORD", "Audit@12345")

_MONGO_URL = os.environ.get("TEST_MONGO_URL", "mongodb://mongo:27017/?replicaSet=rs0")
_MONGO_DB_NAME = os.environ.get("TEST_DB_NAME", "medstock_test")

_RECONCILE_ENDPOINT = f"{_API}/admin/reconcile-stock"


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(email: str, password: str):
    return requests.post(f"{_API}/auth/login", json={"email": email, "password": password}, timeout=15)


@pytest.fixture(scope="module")
def admin_session():
    r = _login(_ADMIN_EMAIL, _ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    return {"token": body["access_token"], "user": body["user"]}


@pytest.fixture(scope="module")
def admin_token(admin_session):
    return admin_session["token"]


@pytest.fixture(scope="module")
def auditor_token():
    r = _login(_AUDITOR_EMAIL, _AUDITOR_PASSWORD)
    assert r.status_code == 200, f"auditor login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _mongo_client():
    # Imported lazily so module import does not require PyMongo on a bare host.
    from pymongo import AsyncMongoClient
    return AsyncMongoClient(_MONGO_URL, serverSelectionTimeoutMS=5000)


async def _direct_count(collection: str, query: dict) -> int:
    c = _mongo_client()
    try:
        return await c[_MONGO_DB_NAME][collection].count_documents(query)
    finally:
        await c.close()
async def _direct_find(collection: str, query: dict, limit: int = 100, sort=None) -> list:
    c = _mongo_client()
    try:
        cursor = c[_MONGO_DB_NAME][collection].find(query, {"_id": 0})
        if sort:
            cursor = cursor.sort(sort)
        return await cursor.to_list(limit)
    finally:
        await c.close()
class TestRealAuthorizedReconcileAudit:
    pytestmark = pytest.mark.integration

    def test_authorized_invocation_creates_exactly_one_audit_entry(self, admin_session):
        token = admin_session["token"]
        user = admin_session["user"]

        count_before = asyncio.run(_direct_count("audit_logs", {"action": "reconcile_stock"}))

        r = requests.post(_RECONCILE_ENDPOINT, headers=_bearer(token), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()

        count_after = asyncio.run(_direct_count("audit_logs", {"action": "reconcile_stock"}))
        assert count_after == count_before + 1, (
            f"expected exactly one new audit_logs entry, before={count_before} after={count_after}"
        )

        assert "checked_at" in body
        assert "count" in body
        assert "discrepancies" in body
        assert isinstance(body["discrepancies"], list)
        assert body["count"] == len(body["discrepancies"])

        entries = asyncio.run(_direct_find(
            "audit_logs", {"action": "reconcile_stock"}, limit=1, sort=[("created_at", -1)],
        ))
        assert len(entries) == 1
        entry = entries[0]

        assert entry["entity"] == "reconciliation_log"
        assert entry["entity_id"] is None
        assert entry["user_id"] == user["id"]
        assert entry["user_email"] == user["email"]
        assert entry["user_role"] == user["role"]
        assert entry["ip"] is not None

        new_value = entry["new_value"]
        assert new_value["discrepancy_count"] == body["count"]
        assert set(new_value.keys()) == {"discrepancy_count", "discrepancy_kinds"}

        # The audit entry must not carry the full discrepancies payload.
        assert "discrepancies" not in entry
        assert "discrepancies" not in new_value


class TestRealUnauthorizedReconcileAudit:
    pytestmark = pytest.mark.integration

    def test_unauthorized_role_gets_403_and_writes_no_audit_entry(self, auditor_token):
        count_before = asyncio.run(_direct_count("audit_logs", {"action": "reconcile_stock"}))

        r = requests.post(_RECONCILE_ENDPOINT, headers=_bearer(auditor_token), timeout=15)
        assert r.status_code == 403, f"expected 403 for auditor role, got {r.status_code}: {r.text}"

        count_after = asyncio.run(_direct_count("audit_logs", {"action": "reconcile_stock"}))
        assert count_after == count_before, "a 403 response must not create an audit_logs entry"


class TestRealTwoInvocationsCreateTwoEntries:
    pytestmark = pytest.mark.integration

    def test_two_successful_invocations_create_two_separate_audit_entries(self, admin_token):
        count_before = asyncio.run(_direct_count("audit_logs", {"action": "reconcile_stock"}))

        r1 = requests.post(_RECONCILE_ENDPOINT, headers=_bearer(admin_token), timeout=30)
        assert r1.status_code == 200, r1.text
        r2 = requests.post(_RECONCILE_ENDPOINT, headers=_bearer(admin_token), timeout=30)
        assert r2.status_code == 200, r2.text

        count_after = asyncio.run(_direct_count("audit_logs", {"action": "reconcile_stock"}))
        assert count_after == count_before + 2, (
            f"expected exactly two new audit_logs entries, before={count_before} after={count_after}"
        )

        entries = asyncio.run(_direct_find(
            "audit_logs", {"action": "reconcile_stock"}, limit=2, sort=[("created_at", -1)],
        ))
        assert len(entries) == 2
        assert entries[0]["id"] != entries[1]["id"]
