"""Backend integration tests for Critical Medical Stock Monitoring System."""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").strip().rstrip("/")
API = f"{BASE_URL}/api"

pytestmark = pytest.mark.integration

_ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@medstock.sa")
_ADMIN_PW    = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@12345")

CREDS = {
    "admin":   (_ADMIN_EMAIL, _ADMIN_PW),
    "head_er": ("head.er@medstock.sa", "Head@12345"),
    "off_er":  ("officer.er@medstock.sa", "Officer@12345"),
    "off_icu": ("officer.icu@medstock.sa", "Officer@12345"),
    "supply":  ("supply@medstock.sa", "Supply@12345"),
    "auditor": ("auditor@medstock.sa", "Audit@12345"),
}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    return r


def _tok(role):
    email, pw = CREDS[role]
    r = _login(email, pw)
    assert r.status_code == 200, f"login {role} failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(role):
    return {"Authorization": f"Bearer {_tok(role)}"}


# Cache tokens lazily
@pytest.fixture(scope="session")
def tokens():
    return {r: _tok(r) for r in CREDS}


@pytest.fixture(scope="session")
def H(tokens):
    return {r: {"Authorization": f"Bearer {tokens[r]}"} for r in tokens}


# ---------- AUTH ----------
class TestAuth:
    def test_login_admin(self):
        r = _login(*CREDS["admin"])
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["role"] == "super_admin"
        assert d["user"]["email"] == "admin@medstock.sa"
        assert "access_token" in d

    def test_login_officer(self):
        r = _login(*CREDS["off_er"])
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["role"] == "department_stock_officer"
        assert d["user"]["department_id"] is not None

    def test_login_auditor(self):
        r = _login(*CREDS["auditor"])
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "auditor"

    def test_login_wrong(self):
        r = _login("admin@medstock.sa", "wrong-pass-xyz")
        assert r.status_code == 401

    def test_me_endpoint(self, H):
        r = requests.get(f"{API}/auth/me", headers=H["admin"], timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == "admin@medstock.sa"
        assert d["role"] == "super_admin"


# ---------- BRUTE FORCE LOCKOUT ----------
class TestLockout:
    def test_lockout_after_5_fails(self):
        # unique email to avoid affecting real users
        bad_email = f"lock_{uuid.uuid4().hex[:6]}@test.sa"
        for _ in range(5):
            r = requests.post(f"{API}/auth/login",
                              json={"email": bad_email, "password": "x"}, timeout=10)
            assert r.status_code in (401, 429)
        r = requests.post(f"{API}/auth/login",
                          json={"email": bad_email, "password": "x"}, timeout=10)
        assert r.status_code == 429, f"expected 429 lockout, got {r.status_code}"


# ---------- DASHBOARD ----------
class TestDashboard:
    def test_kpis(self, H):
        r = requests.get(f"{API}/dashboard/kpis", headers=H["admin"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("zero_count", "critical_count", "life_saving_risk",
                  "open_alerts", "top_departments", "by_department", "recent_alerts"):
            assert k in d, f"missing key {k}"
        assert d["zero_count"] > 0
        assert d["critical_count"] > 0


# ---------- DEPARTMENTS ----------
class TestDepartments:
    def test_list_departments(self, H):
        r = requests.get(f"{API}/departments", headers=H["admin"], timeout=10)
        assert r.status_code == 200
        depts = r.json()
        assert len(depts) >= 5
        codes = {d["code"] for d in depts}
        assert {"ER", "ICU", "LAB", "RAD", "PHARM"}.issubset(codes)


# ---------- ITEMS ----------
class TestItems:
    def test_list_items(self, H):
        r = requests.get(f"{API}/items", headers=H["admin"], timeout=10)
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 10

    def test_create_item_admin(self, H):
        code = f"TEST-{uuid.uuid4().hex[:8]}"
        body = {"internal_code": code, "name_ar": "تست", "name_en": "Test",
                "category": "Other", "unit": "PCS", "min_level": 5,
                "critical_threshold": 2, "max_level": 10}
        r = requests.post(f"{API}/items", json=body, headers=H["admin"], timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["internal_code"] == code
        assert "_id" not in d
        # verify get
        r2 = requests.get(f"{API}/items?search={code}", headers=H["admin"], timeout=10)
        assert any(i["internal_code"] == code for i in r2.json())

    def test_create_item_officer_403(self, H):
        body = {"internal_code": f"NEG-{uuid.uuid4().hex[:6]}",
                "name_ar": "x", "name_en": "x"}
        r = requests.post(f"{API}/items", json=body, headers=H["off_er"], timeout=10)
        assert r.status_code == 403


# ---------- STOCK ----------
class TestStock:
    def test_stock_list_admin(self, H):
        r = requests.get(f"{API}/stock", headers=H["admin"], timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0
        assert rows[0].get("item") is not None
        assert rows[0].get("department") is not None

    def test_officer_only_sees_own_dept(self, H):
        r = requests.get(f"{API}/stock", headers=H["off_er"], timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0
        dept_codes = {row["department"]["code"] for row in rows if row.get("department")}
        assert dept_codes == {"ER"}, f"officer ER sees: {dept_codes}"

    def test_admin_set_zero_creates_alert(self, H):
        # find ER department + an item not currently zero with non-life-saving
        depts = requests.get(f"{API}/departments", headers=H["admin"]).json()
        er = next(d for d in depts if d["code"] == "ER")
        # use GAUZE-4x4 (not life saving) in ER (balance 35 in seed)
        items = requests.get(f"{API}/items?search=GAUZE-4x4", headers=H["admin"]).json()
        gauze = items[0]
        r = requests.post(f"{API}/stock",
                          json={"department_id": er["id"], "item_id": gauze["id"], "balance": 0},
                          headers=H["admin"], timeout=15)
        assert r.status_code == 200
        assert r.json()["stock_status"] == "zero_level"
        # check alert
        alerts = requests.get(f"{API}/alerts?acknowledged=false",
                              headers=H["admin"]).json()
        match = [a for a in alerts if a["item_id"] == gauze["id"]
                 and a["department_id"] == er["id"] and a["type"] == "zero_level"]
        assert match, "expected zero_level alert created"

    def test_life_saving_zero_creates_two_alerts(self, H):
        depts = requests.get(f"{API}/departments", headers=H["admin"]).json()
        icu = next(d for d in depts if d["code"] == "ICU")
        # CRICO-KIT is life-saving, in ICU seed=2 (available)
        items = requests.get(f"{API}/items?search=CRICO-KIT", headers=H["admin"]).json()
        crico = items[0]
        # First snapshot existing alerts
        before = requests.get(f"{API}/alerts?acknowledged=false",
                              headers=H["admin"]).json()
        before_ids = {a["id"] for a in before}
        r = requests.post(f"{API}/stock",
                          json={"department_id": icu["id"], "item_id": crico["id"], "balance": 0},
                          headers=H["admin"], timeout=15)
        assert r.status_code == 200
        after = requests.get(f"{API}/alerts?acknowledged=false",
                             headers=H["admin"]).json()
        new_for_item = [a for a in after if a["id"] not in before_ids
                        and a["item_id"] == crico["id"] and a["department_id"] == icu["id"]]
        types = {a["type"] for a in new_for_item}
        assert "zero_level" in types
        assert "life_saving_item" in types
        ls_alert = next(a for a in new_for_item if a["type"] == "life_saving_item")
        assert ls_alert["severity"] == "critical"

    def test_officer_cannot_update_other_dept(self, H):
        depts = requests.get(f"{API}/departments", headers=H["admin"]).json()
        icu = next(d for d in depts if d["code"] == "ICU")
        items = requests.get(f"{API}/items?search=GLOVE-M", headers=H["admin"]).json()
        item = items[0]
        r = requests.post(f"{API}/stock",
                          json={"department_id": icu["id"], "item_id": item["id"], "balance": 50},
                          headers=H["off_er"], timeout=10)
        assert r.status_code == 403


# ---------- REQUESTS LIFECYCLE ----------
class TestRequestLifecycle:
    def test_full_lifecycle_and_backorder(self, H):
        depts = requests.get(f"{API}/departments", headers=H["admin"]).json()
        er = next(d for d in depts if d["code"] == "ER")
        items = requests.get(f"{API}/items?search=IV-CANN-20", headers=H["admin"]).json()
        item = items[0]

        # CREATE as ER officer
        r = requests.post(f"{API}/requests",
                          json={"department_id": er["id"], "item_id": item["id"],
                                "requested_qty": 50, "priority": "routine"},
                          headers=H["off_er"], timeout=10)
        assert r.status_code == 200, r.text
        req_id = r.json()["id"]
        assert r.json()["status"] == "pending_approval"

        # APPROVE as head.er
        r = requests.post(f"{API}/requests/{req_id}/approve",
                          json={"approved_qty": 50}, headers=H["head_er"], timeout=10)
        assert r.status_code == 200

        # DISPATCH as supply
        r = requests.post(f"{API}/requests/{req_id}/dispatch",
                          json={"dispatched_qty": 50, "backorder": False},
                          headers=H["supply"], timeout=10)
        assert r.status_code == 200

        # capture pre-receive balance
        stock_list = requests.get(f"{API}/stock", headers=H["admin"]).json()
        pre = next((s for s in stock_list
                    if s["item_id"] == item["id"] and s["department_id"] == er["id"]), None)
        pre_bal = pre["balance"] if pre else 0

        # RECEIVE as ER officer
        r = requests.post(f"{API}/requests/{req_id}/receive",
                          json={"received_qty": 50}, headers=H["off_er"], timeout=10)
        assert r.status_code == 200

        # verify final status
        r = requests.get(f"{API}/requests", headers=H["admin"]).json()
        final = next(rq for rq in r if rq["id"] == req_id)
        assert final["status"] == "received"

        # verify stock increased
        stock_list2 = requests.get(f"{API}/stock", headers=H["admin"]).json()
        post = next(s for s in stock_list2
                    if s["item_id"] == item["id"] and s["department_id"] == er["id"])
        assert post["balance"] == pre_bal + 50

    def test_dispatch_backorder_creates_alert(self, H):
        depts = requests.get(f"{API}/departments", headers=H["admin"]).json()
        er = next(d for d in depts if d["code"] == "ER")
        items = requests.get(f"{API}/items?search=SYRINGE-5", headers=H["admin"]).json()
        item = items[0]
        # create + approve
        r = requests.post(f"{API}/requests",
                          json={"department_id": er["id"], "item_id": item["id"],
                                "requested_qty": 100, "priority": "urgent"},
                          headers=H["off_er"]).json()
        req_id = r["id"]
        requests.post(f"{API}/requests/{req_id}/approve",
                      json={"approved_qty": 100}, headers=H["head_er"])
        # dispatch with backorder
        r2 = requests.post(f"{API}/requests/{req_id}/dispatch",
                           json={"dispatched_qty": 0, "backorder": True,
                                 "expected_supply_date": "2026-02-01"},
                           headers=H["supply"], timeout=10)
        assert r2.status_code == 200
        # request status backorder
        reqs = requests.get(f"{API}/requests", headers=H["admin"]).json()
        rq = next(x for x in reqs if x["id"] == req_id)
        assert rq["status"] == "backorder"
        # backorder alert
        alerts = requests.get(f"{API}/alerts", headers=H["admin"]).json()
        assert any(a["type"] == "backorder" and a["request_id"] == req_id for a in alerts)


# ---------- ALERTS ----------
class TestAlerts:
    def test_acknowledge_alert(self, H):
        alerts = requests.get(f"{API}/alerts?acknowledged=false",
                              headers=H["admin"]).json()
        assert len(alerts) > 0
        aid = alerts[0]["id"]
        r = requests.post(f"{API}/alerts/{aid}/acknowledge",
                          headers=H["admin"], timeout=10)
        assert r.status_code == 200
        after = requests.get(f"{API}/alerts?acknowledged=false",
                             headers=H["admin"]).json()
        assert not any(a["id"] == aid for a in after)


# ---------- AUDIT LOGS ----------
class TestAudit:
    def test_auditor_can_view(self, H):
        r = requests.get(f"{API}/audit-logs", headers=H["auditor"], timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_officer_forbidden(self, H):
        r = requests.get(f"{API}/audit-logs", headers=H["off_er"], timeout=10)
        assert r.status_code == 403


# ---------- REPORTS ----------
class TestReports:
    def test_reports_data(self, H):
        for name in ("zero_level", "critical_level", "life_saving"):
            r = requests.get(f"{API}/reports/{name}", headers=H["admin"], timeout=15)
            assert r.status_code == 200, f"{name} -> {r.status_code}"
            d = r.json()
            assert "rows" in d and "count" in d

    def test_export_csv(self, H):
        import csv as _csv, io as _io
        r = requests.get(f"{API}/reports/zero_level/export.csv",
                         headers=H["admin"], timeout=15)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        reader = _csv.reader(_io.StringIO(r.text))
        header_row = next(reader)
        assert "Department" in header_row
        assert "Item Code" in header_row


# ---------- USER RBAC ----------
class TestUserRBAC:
    def test_admin_create_user(self, H):
        email = f"test_{uuid.uuid4().hex[:8]}@medstock.sa"
        r = requests.post(f"{API}/users",
                          json={"email": email, "full_name": "Test U",
                                "password": "Pass@1234", "role": "viewer"},
                          headers=H["admin"], timeout=10)
        assert r.status_code == 200
        assert r.json()["email"] == email
        assert "password_hash" not in r.json()

    def test_officer_cannot_create_user(self, H):
        r = requests.post(f"{API}/users",
                          json={"email": f"x_{uuid.uuid4().hex[:6]}@x.sa",
                                "full_name": "X", "password": "Pass@1234",
                                "role": "viewer"},
                          headers=H["off_er"], timeout=10)
        assert r.status_code == 403
