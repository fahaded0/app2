"""Package 1 — MongoDB transaction integration tests for POST /api/stock/issue.

All tests use unique item codes and idempotency keys to remain independent.
Credentials are read from environment variables with backward-compatible defaults.
"""
import os
import uuid
import threading
import concurrent.futures
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").strip().rstrip("/")
API = f"{BASE_URL}/api"

pytestmark = pytest.mark.integration

_ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@medstock.sa")
_ADMIN_PW    = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@12345")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _login(email: str, pw: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(_ADMIN_EMAIL, _ADMIN_PW)


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _unique(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10].upper()}"


def _create_item(token: str, internal_code: str, balance: int = 100) -> dict:
    """Create an item with given code and return its full record."""
    payload = {
        "internal_code": internal_code,
        "name_ar": f"عنصر اختبار {internal_code}",
        "name_en": f"TXN Test Item {internal_code}",
        "category": "Other",
        "unit": "PCS",
        "min_level": 20,
        "critical_threshold": 10,
        "max_level": 200,
    }
    r = requests.post(f"{API}/items", headers=_h(token), json=payload, timeout=15)
    assert r.status_code == 200, f"create item failed: {r.status_code} {r.text}"
    item = r.json()

    # Seed stock in ER department
    depts = requests.get(f"{API}/departments", headers=_h(token)).json()
    er = next(d for d in depts if d["code"] == "ER")
    stock_r = requests.post(f"{API}/stock", headers=_h(token), json={
        "department_id": er["id"],
        "item_id": item["id"],
        "balance": balance,
        "notes": "txn test seed",
    }, timeout=15)
    assert stock_r.status_code == 200, f"seed stock failed: {stock_r.status_code} {stock_r.text}"
    return {"item": item, "dept": er}


def _issue(token: str, item_id: str, dept_id: str, qty: int,
           idem_key: str = None, fail_after: str = None) -> requests.Response:
    headers = _h(token)
    if fail_after:
        headers["X-Test-Txn-Fail-After"] = fail_after
    return requests.post(f"{API}/stock/issue", headers=headers, json={
        "item_id": item_id,
        "department_id": dept_id,
        "quantity": qty,
        "idempotency_key": idem_key or _unique("IK"),
        "notes": "txn test",
    }, timeout=30)


def _balance(token: str, item_id: str, dept_id: str) -> int:
    r = requests.get(f"{API}/stock-balance/{dept_id}/{item_id}", headers=_h(token))
    assert r.status_code == 200
    return r.json()["current_balance"]


# ---------------------------------------------------------------------------
# Test 1 — Normal issue commits correctly
# ---------------------------------------------------------------------------

class TestNormalIssue:
    def test_transaction_committed(self, admin_token):
        ctx = _create_item(admin_token, _unique("T1N"), balance=50)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK1N")

        r = _issue(admin_token, item_id, dept_id, qty=5, idem_key=idem_key)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body.get("idempotent_replay") is not True
        txn_id = body["transaction_id"]

        # transaction record exists
        txns = requests.get(f"{API}/stock/transactions?item_id={item_id}",
                            headers=_h(admin_token)).json()
        assert any(t["id"] == txn_id for t in txns), "transaction not found"

        # stock balance updated
        assert body["current_balance"] == 45
        assert _balance(admin_token, item_id, dept_id) == 45

        # audit record exists — entity_id filter verifies correct scoping
        audit = requests.get(
            f"{API}/audit-logs?entity=stock_transactions&entity_id={txn_id}",
            headers=_h(admin_token)).json()
        assert len(audit) >= 1

        # no alert for normal issue (balance stays above critical)
        assert body.get("alert_id") is None


# ---------------------------------------------------------------------------
# Test 2 — Alert-producing issue
# ---------------------------------------------------------------------------

class TestAlertProducingIssue:
    def test_alert_created_and_linked(self, admin_token):
        # balance=15, min=20, critical=10, qty=8 → projected=7 (below critical → alert)
        ctx = _create_item(admin_token, _unique("T2A"), balance=15)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK2A")

        r = _issue(admin_token, item_id, dept_id, qty=8, idem_key=idem_key)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        alert_id = body.get("alert_id")
        assert alert_id is not None, "expected an alert to be created"
        assert body.get("alert_severity") is not None

        # stock entry updated
        assert body["current_balance"] == 7
        assert _balance(admin_token, item_id, dept_id) == 7

        # alert exists and is linked to the transaction
        alerts = requests.get(f"{API}/alerts?limit=500", headers=_h(admin_token)).json()
        matched = [a for a in alerts if a["id"] == alert_id]
        assert matched, "alert not found in alerts list"

        txns = requests.get(f"{API}/stock/transactions?item_id={item_id}",
                            headers=_h(admin_token)).json()
        txn = next((t for t in txns if t["id"] == body["transaction_id"]), None)
        assert txn is not None
        assert txn.get("alert_id") == alert_id

        # audit record
        audit = requests.get(
            f"{API}/audit-logs?entity=stock_transactions&entity_id={body['transaction_id']}",
            headers=_h(admin_token)).json()
        assert len(audit) >= 1


# ---------------------------------------------------------------------------
# Test 3 — Failure after transaction_insert → full rollback
# ---------------------------------------------------------------------------

class TestRollbackAfterTransactionInsert:
    def test_no_partial_state(self, admin_token):
        ctx = _create_item(admin_token, _unique("T3F"), balance=50)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK3F")
        bal_before = _balance(admin_token, item_id, dept_id)

        # Snapshot alerts before rollback attempt
        alerts_before = requests.get(f"{API}/alerts?limit=500",
                                     headers=_h(admin_token)).json()
        before_alert_ids = {a["id"] for a in alerts_before}

        r = _issue(admin_token, item_id, dept_id, qty=5, idem_key=idem_key,
                   fail_after="transaction_insert")
        # Should get 503 (infrastructure failure) not 400 (business rule)
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"

        # balance unchanged
        assert _balance(admin_token, item_id, dept_id) == bal_before

        # no transaction record
        txns = requests.get(f"{API}/stock/transactions?item_id={item_id}",
                            headers=_h(admin_token)).json()
        assert not any(t.get("idempotency_key") == idem_key for t in txns)

        # no new alert created by the rolled-back transaction
        alerts_after = requests.get(f"{API}/alerts?limit=500",
                                    headers=_h(admin_token)).json()
        new_alerts = [a for a in alerts_after
                      if a["id"] not in before_alert_ids and a.get("item_id") == item_id]
        assert not new_alerts, f"rollback leaked {len(new_alerts)} alert(s)"

        # no audit for this idempotency key
        audit = requests.get(
            f"{API}/audit-logs?entity=stock_transactions",
            headers=_h(admin_token)).json()
        assert not any(
            a.get("new_value", {}).get("idempotency_key") == idem_key for a in audit
        )


# ---------------------------------------------------------------------------
# Test 4 — Failure after stock_update → full rollback
# ---------------------------------------------------------------------------

class TestRollbackAfterStockUpdate:
    def test_stock_restored(self, admin_token):
        ctx = _create_item(admin_token, _unique("T4F"), balance=50)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK4F")
        bal_before = _balance(admin_token, item_id, dept_id)

        alerts_before = requests.get(f"{API}/alerts?limit=500",
                                     headers=_h(admin_token)).json()
        before_alert_ids = {a["id"] for a in alerts_before}

        r = _issue(admin_token, item_id, dept_id, qty=5, idem_key=idem_key,
                   fail_after="stock_update")
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"

        # balance must be unchanged (transaction rolled back)
        assert _balance(admin_token, item_id, dept_id) == bal_before

        # no committed transaction
        txns = requests.get(f"{API}/stock/transactions?item_id={item_id}",
                            headers=_h(admin_token)).json()
        assert not any(t.get("idempotency_key") == idem_key for t in txns)

        # no new alert
        alerts_after = requests.get(f"{API}/alerts?limit=500",
                                    headers=_h(admin_token)).json()
        new_alerts = [a for a in alerts_after
                      if a["id"] not in before_alert_ids and a.get("item_id") == item_id]
        assert not new_alerts, f"rollback leaked {len(new_alerts)} alert(s)"


# ---------------------------------------------------------------------------
# Test 5 — Failure after alert_insert → full rollback
# ---------------------------------------------------------------------------

class TestRollbackAfterAlertInsert:
    def test_no_partial_state(self, admin_token):
        # balance=15 → qty=8 → projected=7 → alert would be created
        ctx = _create_item(admin_token, _unique("T5F"), balance=15)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK5F")
        bal_before = _balance(admin_token, item_id, dept_id)

        alerts_before = requests.get(f"{API}/alerts?limit=500",
                                     headers=_h(admin_token)).json()
        before_alert_ids = {a["id"] for a in alerts_before}

        r = _issue(admin_token, item_id, dept_id, qty=8, idem_key=idem_key,
                   fail_after="alert_insert")
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"

        # balance unchanged
        assert _balance(admin_token, item_id, dept_id) == bal_before

        # no transaction
        txns = requests.get(f"{API}/stock/transactions?item_id={item_id}",
                            headers=_h(admin_token)).json()
        assert not any(t.get("idempotency_key") == idem_key for t in txns)

        # no new alert
        alerts_after = requests.get(f"{API}/alerts?limit=500",
                                    headers=_h(admin_token)).json()
        new_alerts = [a for a in alerts_after
                      if a["id"] not in before_alert_ids and a.get("item_id") == item_id]
        assert not new_alerts, f"rollback leaked {len(new_alerts)} alert(s)"


# ---------------------------------------------------------------------------
# Test 6 — Failure after audit_insert → full rollback
# ---------------------------------------------------------------------------

class TestRollbackAfterAuditInsert:
    def test_no_partial_state(self, admin_token):
        # balance=15 → qty=8 → all writes succeed up to audit, then fail
        ctx = _create_item(admin_token, _unique("T6F"), balance=15)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK6F")
        bal_before = _balance(admin_token, item_id, dept_id)

        alerts_before = requests.get(f"{API}/alerts?limit=500",
                                     headers=_h(admin_token)).json()
        before_alert_ids = {a["id"] for a in alerts_before}

        r = _issue(admin_token, item_id, dept_id, qty=8, idem_key=idem_key,
                   fail_after="audit_insert")
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"

        # balance unchanged
        assert _balance(admin_token, item_id, dept_id) == bal_before

        # no transaction record (audit_insert fires after txn insert, so txn rolled back too)
        txns = requests.get(f"{API}/stock/transactions?item_id={item_id}",
                            headers=_h(admin_token)).json()
        assert not any(t.get("idempotency_key") == idem_key for t in txns)

        # no new alert
        alerts_after = requests.get(f"{API}/alerts?limit=500",
                                    headers=_h(admin_token)).json()
        new_alerts = [a for a in alerts_after
                      if a["id"] not in before_alert_ids and a.get("item_id") == item_id]
        assert not new_alerts, f"rollback leaked {len(new_alerts)} alert(s)"

        # no audit record for this idempotency key
        audit = requests.get(
            f"{API}/audit-logs?entity=stock_transactions",
            headers=_h(admin_token)).json()
        assert not any(
            a.get("new_value", {}).get("idempotency_key") == idem_key for a in audit
        )


# ---------------------------------------------------------------------------
# Test 7 — Duplicate idempotency key (alert-producing issue)
# ---------------------------------------------------------------------------

class TestIdempotentReplay:
    def test_replay_does_not_double_deduct(self, admin_token):
        # balance=15, min=20, critical=10, qty=8 → projected=7 → alert created
        ctx = _create_item(admin_token, _unique("T7I"), balance=15)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK7I")

        r1 = _issue(admin_token, item_id, dept_id, qty=8, idem_key=idem_key)
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1["success"] is True
        assert body1.get("idempotent_replay") is not True
        txn_id = body1["transaction_id"]
        alert_id = body1.get("alert_id")
        assert alert_id is not None, "expected alert on below-critical issue"

        r2 = _issue(admin_token, item_id, dept_id, qty=8, idem_key=idem_key)
        assert r2.status_code == 200, r2.text
        body2 = r2.json()

        # second response is a replay
        assert body2.get("idempotent_replay") is True
        # both responses carry the same transaction and alert IDs
        assert body2["transaction_id"] == txn_id
        assert body2.get("alert_id") == alert_id

        # final balance reflects exactly one deduction (no duplicate)
        assert _balance(admin_token, item_id, dept_id) == 7

        # exactly one matching stock transaction
        txns = requests.get(f"{API}/stock/transactions?item_id={item_id}",
                            headers=_h(admin_token)).json()
        matching_txns = [t for t in txns if t.get("idempotency_key") == idem_key]
        assert len(matching_txns) == 1

        # exactly one matching issue alert
        alerts = requests.get(f"{API}/alerts?limit=500", headers=_h(admin_token)).json()
        matching_alerts = [a for a in alerts if a["id"] == alert_id]
        assert len(matching_alerts) == 1, "expected exactly one alert for this transaction"

        # exactly one audit record for this transaction
        audit = requests.get(
            f"{API}/audit-logs?entity=stock_transactions&entity_id={txn_id}",
            headers=_h(admin_token)).json()
        assert len(audit) == 1


# ---------------------------------------------------------------------------
# Test 8 — Concurrent issue: only one succeeds when balance is insufficient
# ---------------------------------------------------------------------------

class TestConcurrentIssue:
    def test_exactly_one_succeeds(self, admin_token):
        # balance=10, each request asks for 8 → only one can succeed
        ctx = _create_item(admin_token, _unique("T8C"), balance=10)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_a = _unique("IKA")
        idem_b = _unique("IKB")

        barrier = threading.Barrier(2)
        results: list[requests.Response] = []

        def _worker(idem_key: str) -> None:
            barrier.wait()  # both threads start their HTTP request simultaneously
            r = _issue(admin_token, item_id, dept_id, qty=8, idem_key=idem_key)
            results.append(r)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_worker, idem_a),
                pool.submit(_worker, idem_b),
            ]
            for f in concurrent.futures.as_completed(futures):
                f.result()  # re-raise any worker exception

        statuses = [r.status_code for r in results]
        successes = [r for r in results if r.status_code == 200]
        failures  = [r for r in results if r.status_code != 200]

        assert len(successes) == 1, f"expected exactly 1 success, got statuses {statuses}"
        assert len(failures)  == 1

        # failure must be a controlled 400 (insufficient stock), not a 503
        assert failures[0].status_code == 400

        # final balance is non-negative and reflects exactly one deduction
        final = _balance(admin_token, item_id, dept_id)
        assert final == 2, f"expected balance=2, got {final}"
        assert final >= 0

        # exactly one transaction committed
        txns = requests.get(f"{API}/stock/transactions?item_id={item_id}",
                            headers=_h(admin_token)).json()
        issue_txns = [t for t in txns if t.get("entry_type") == "issue"
                      and t.get("idempotency_key") in (idem_a, idem_b)]
        assert len(issue_txns) == 1


# ---------------------------------------------------------------------------
# Test 9 — Rolled-back transaction does not schedule email
# ---------------------------------------------------------------------------

class TestRollbackEmailNotScheduled:
    def test_503_on_rollback_no_email_side_effect(self, admin_token):
        """A rolled-back issue returns 503 without X-Test-Email-Scheduled header."""
        # balance=15 → qty=8 → alert would be created → email would be scheduled
        ctx = _create_item(admin_token, _unique("T9E"), balance=15)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK9E")

        r = _issue(admin_token, item_id, dept_id, qty=8, idem_key=idem_key,
                   fail_after="alert_insert")
        assert r.status_code == 503

        # Header must be absent — email scheduling only happens post-commit
        assert "X-Test-Email-Scheduled" not in r.headers, (
            "email scheduling header must not be set on a rolled-back response"
        )

        # Belt-and-suspenders: confirm the alert was not committed
        alerts = requests.get(f"{API}/alerts?limit=500", headers=_h(admin_token)).json()
        assert not any(
            a.get("item_id") == item_id
            and a.get("type") in ("below_minimum_issue", "below_critical_issue", "emergency_override")
            for a in alerts
            if a.get("created_at", "") > "2020-01-01"
        ), "rolled-back alert must not persist"


# ---------------------------------------------------------------------------
# Test 10 — Successful alert-producing transaction schedules email after commit
# ---------------------------------------------------------------------------

class TestEmailScheduledAfterCommit:
    def test_email_scheduled_header_present_on_committed_alert(self, admin_token):
        """X-Test-Email-Scheduled: true must be present when a committed issue creates an alert
        with escalation roles, proving the email background task was registered post-commit."""
        ctx = _create_item(admin_token, _unique("T10E"), balance=15)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        idem_key = _unique("IK10E")

        r = _issue(admin_token, item_id, dept_id, qty=8, idem_key=idem_key)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True

        alert_id = body.get("alert_id")
        assert alert_id is not None, "expected alert on below-critical issue"

        # The durable post-commit observable: header set iff email task was registered
        assert r.headers.get("X-Test-Email-Scheduled") == "true", (
            "X-Test-Email-Scheduled header must be 'true' when a committed issue "
            "creates an alert with escalation roles"
        )

        # Alert is committed and queryable — confirms the transaction completed fully
        alerts = requests.get(f"{API}/alerts?limit=500", headers=_h(admin_token)).json()
        assert any(a["id"] == alert_id for a in alerts), "alert not found after commit"
