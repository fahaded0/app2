"""Phase 4 backend tests:
  1. Idempotency on /api/stock/issue
  2. Reconciliation endpoints (/api/admin/reconcile-stock, /api/admin/reconciliation-log)
  3. /api/stock/transactions filters + dept-scoping + enrichment
  4. /api/reports/{name}/email RBAC + validation
  5. Light regression on iteration 1/2 endpoints (login, items, stock, alerts, kpis, reports)
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@medstock.sa", "password": "Admin@12345"}
OFFICER_ER = {"email": "officer.er@medstock.sa", "password": "Officer@12345"}
OFFICER_ICU = {"email": "officer.icu@medstock.sa", "password": "Officer@12345"}
SUPPLY = {"email": "supply@medstock.sa", "password": "Supply@12345"}
AUDITOR = {"email": "auditor@medstock.sa", "password": "Audit@12345"}


def login(creds: dict) -> str:
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_token():
    return login(ADMIN)


@pytest.fixture(scope="module")
def er_officer_token():
    return login(OFFICER_ER)


@pytest.fixture(scope="module")
def supply_token():
    return login(SUPPLY)


@pytest.fixture(scope="module")
def auditor_token():
    return login(AUDITOR)


@pytest.fixture(scope="module")
def bvm_item(admin_token):
    """Return BVM-ADULT item dict (life-saving test item)."""
    r = requests.get(f"{API}/items", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    items = r.json()
    for it in items:
        if it.get("internal_code") == "BVM-ADULT":
            return it
    pytest.skip("BVM-ADULT seed item not found")


@pytest.fixture(scope="module")
def er_dept(admin_token):
    r = requests.get(f"{API}/departments", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    for d in r.json():
        if d.get("code") == "ER":
            return d
    pytest.skip("ER department not found")


@pytest.fixture(scope="module")
def restock_bvm_er(admin_token, bvm_item, er_dept):
    """Restock BVM-ADULT @ ER to a known balance of 50 before idempotency tests."""
    payload = {
        "department_id": er_dept["id"],
        "item_id": bvm_item["id"],
        "balance": 50,
        "notes": "phase4 idempotency setup",
    }
    r = requests.post(f"{API}/stock", headers=H(admin_token), json=payload, timeout=15)
    assert r.status_code == 200, f"restock failed: {r.status_code} {r.text}"
    return 50


# ===================== IDEMPOTENCY =====================
class TestIdempotency:

    def test_same_key_twice_returns_same_txn(self, admin_token, bvm_item, er_dept, restock_bvm_er):
        idem = f"TEST_idem_{uuid.uuid4()}"
        body = {
            "department_id": er_dept["id"],
            "item_id": bvm_item["id"],
            "quantity": 5,
            "notes": "phase4 idempotency first",
            "idempotency_key": idem,
        }
        r1 = requests.post(f"{API}/stock/issue", headers=H(admin_token), json=body, timeout=15)
        assert r1.status_code == 200, f"first call failed: {r1.text}"
        d1 = r1.json()
        assert d1["previous_balance"] == 50
        assert d1["current_balance"] == 45
        assert d1.get("idempotent_replay") in (False, None, False)
        txn1 = d1["transaction_id"]

        # Replay
        r2 = requests.post(f"{API}/stock/issue", headers=H(admin_token), json=body, timeout=15)
        assert r2.status_code == 200, f"replay failed: {r2.text}"
        d2 = r2.json()
        assert d2.get("idempotent_replay") is True
        assert d2["transaction_id"] == txn1
        assert d2["previous_balance"] == 45 or d2["previous_balance"] == 50  # stored from original
        assert d2["current_balance"] == 45

        # Verify balance is still 45 (NOT double-decremented)
        sb = requests.get(
            f"{API}/stock-balance/{er_dept['id']}/{bvm_item['id']}",
            headers=H(admin_token), timeout=15,
        )
        assert sb.status_code == 200, sb.text
        body = sb.json()
        bal = body.get("balance", body.get("current_balance"))
        assert bal == 45, f"expected 45 got {bal}: {body}"

    def test_no_idempotency_key_works(self, admin_token, bvm_item, er_dept):
        # Balance should currently be 45 from previous test
        body = {
            "department_id": er_dept["id"],
            "item_id": bvm_item["id"],
            "quantity": 1,
            "notes": "phase4 no-key",
        }
        r = requests.post(f"{API}/stock/issue", headers=H(admin_token), json=body, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("idempotent_replay") in (False, None)
        assert "transaction_id" in d
        assert d["current_balance"] == d["previous_balance"] - 1

    def test_two_different_keys_produce_two_txns(self, admin_token, bvm_item, er_dept):
        bodyA = {
            "department_id": er_dept["id"], "item_id": bvm_item["id"],
            "quantity": 2, "idempotency_key": f"TEST_idemA_{uuid.uuid4()}",
        }
        bodyB = {
            "department_id": er_dept["id"], "item_id": bvm_item["id"],
            "quantity": 2, "idempotency_key": f"TEST_idemB_{uuid.uuid4()}",
        }
        rA = requests.post(f"{API}/stock/issue", headers=H(admin_token), json=bodyA, timeout=15)
        rB = requests.post(f"{API}/stock/issue", headers=H(admin_token), json=bodyB, timeout=15)
        assert rA.status_code == 200 and rB.status_code == 200, f"{rA.text} | {rB.text}"
        assert rA.json()["transaction_id"] != rB.json()["transaction_id"]
        # Each decremented by 2
        assert rB.json()["previous_balance"] == rA.json()["current_balance"]
        assert rB.json()["current_balance"] == rA.json()["current_balance"] - 2


# ===================== RECONCILIATION =====================
class TestReconciliation:

    def test_reconcile_super_admin_ok(self, admin_token):
        r = requests.post(f"{API}/admin/reconcile-stock", headers=H(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "checked_at" in body
        assert "count" in body
        assert "discrepancies" in body
        assert isinstance(body["discrepancies"], list)
        assert body["count"] == len(body["discrepancies"])

    def test_reconcile_forbidden_for_officer(self, er_officer_token):
        r = requests.post(f"{API}/admin/reconcile-stock", headers=H(er_officer_token), timeout=15)
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text}"

    def test_reconcile_forbidden_for_supply(self, supply_token):
        r = requests.post(f"{API}/admin/reconcile-stock", headers=H(supply_token), timeout=15)
        assert r.status_code == 403

    def test_reconciliation_log_super_admin(self, admin_token):
        r = requests.get(f"{API}/admin/reconciliation-log", headers=H(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_reconciliation_log_auditor(self, auditor_token):
        r = requests.get(f"{API}/admin/reconciliation-log", headers=H(auditor_token), timeout=15)
        assert r.status_code == 200, r.text

    def test_reconciliation_log_forbidden_for_officer(self, er_officer_token):
        r = requests.get(f"{API}/admin/reconciliation-log", headers=H(er_officer_token), timeout=15)
        assert r.status_code == 403


# ===================== TRANSACTIONS =====================
class TestTransactions:

    def test_admin_list_all(self, admin_token):
        r = requests.get(f"{API}/stock/transactions", headers=H(admin_token),
                         params={"limit": 50}, timeout=15)
        assert r.status_code == 200, r.text
        docs = r.json()
        assert isinstance(docs, list)
        if docs:
            d = docs[0]
            assert "item" in d
            assert "department" in d
            # Enrichment must include denormalised dicts (or None if item/dept missing)
            assert d.get("item") is None or "internal_code" in d["item"]
            assert d.get("department") is None or "code" in d["department"]

    def test_filter_by_item_and_dept(self, admin_token, bvm_item, er_dept):
        r = requests.get(
            f"{API}/stock/transactions",
            headers=H(admin_token),
            params={"item_id": bvm_item["id"], "department_id": er_dept["id"], "limit": 100},
            timeout=15,
        )
        assert r.status_code == 200
        for d in r.json():
            assert d["item_id"] == bvm_item["id"]
            assert d["department_id"] == er_dept["id"]

    def test_filter_entry_type_issue(self, admin_token):
        r = requests.get(f"{API}/stock/transactions", headers=H(admin_token),
                         params={"entry_type": "issue", "limit": 50}, timeout=15)
        assert r.status_code == 200
        for d in r.json():
            assert d["entry_type"] == "issue"

    def test_dept_officer_sees_only_own(self, er_officer_token, admin_token):
        r = requests.get(f"{API}/stock/transactions", headers=H(er_officer_token),
                         params={"limit": 200}, timeout=15)
        assert r.status_code == 200, r.text
        # Discover ER dept_id from /auth/me
        me = requests.get(f"{API}/auth/me", headers=H(er_officer_token), timeout=10).json()
        my_dept = me.get("department_id")
        assert my_dept, "ER officer must have department_id"
        for d in r.json():
            assert d["department_id"] == my_dept, f"saw other dept: {d['department_id']}"


# ===================== REPORTS EMAIL =====================
class TestReportsEmail:

    def test_email_valid_recipient(self, admin_token):
        r = requests.post(
            f"{API}/reports/zero_level/email",
            headers=H(admin_token),
            json={"recipients": ["test@example.com"], "message": "phase4 test"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("status") == "queued"
        assert d.get("report") == "zero_level"
        assert "test@example.com" in d.get("recipients", [])

    def test_email_no_valid_recipient(self, admin_token):
        r = requests.post(
            f"{API}/reports/zero_level/email",
            headers=H(admin_token),
            json={"recipients": ["not-an-email", ""]},
            timeout=15,
        )
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"

    def test_email_forbidden_for_dept_officer(self, er_officer_token):
        r = requests.post(
            f"{API}/reports/zero_level/email",
            headers=H(er_officer_token),
            json={"recipients": ["test@example.com"]},
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code}"

    def test_email_allowed_for_supply_officer(self, supply_token):
        r = requests.post(
            f"{API}/reports/zero_level/email",
            headers=H(supply_token),
            json={"recipients": ["test@example.com"]},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "queued"

    def test_email_allowed_for_auditor(self, auditor_token):
        r = requests.post(
            f"{API}/reports/zero_level/email",
            headers=H(auditor_token),
            json={"recipients": ["test@example.com"]},
            timeout=30,
        )
        assert r.status_code == 200, r.text


# ===================== REGRESSION =====================
class TestRegression:

    def test_items(self, admin_token):
        r = requests.get(f"{API}/items", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_stock(self, admin_token):
        r = requests.get(f"{API}/stock", headers=H(admin_token), timeout=15)
        assert r.status_code == 200

    def test_alerts(self, admin_token):
        r = requests.get(f"{API}/alerts", headers=H(admin_token), timeout=15)
        assert r.status_code == 200

    def test_kpis(self, admin_token):
        r = requests.get(f"{API}/dashboard/kpis", headers=H(admin_token), timeout=15)
        assert r.status_code == 200

    def test_reports_list(self, admin_token):
        r = requests.get(f"{API}/reports", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
