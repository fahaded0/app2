"""Phase 3 — Stock Issue with Reserve Control + Escalation."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").strip().rstrip("/")
API = f"{BASE_URL}/api"

pytestmark = pytest.mark.integration

ADMIN = ("admin@medstock.sa", "Admin@12345")
HEAD_ER = ("head.er@medstock.sa", "Head@12345")
OFFICER_ER = ("officer.er@medstock.sa", "Officer@12345")
OFFICER_ICU = ("officer.icu@medstock.sa", "Officer@12345")
SUPPLY = ("supply@medstock.sa", "Supply@12345")


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def officer_er_token():
    return _login(*OFFICER_ER)


@pytest.fixture(scope="module")
def officer_icu_token():
    return _login(*OFFICER_ICU)


@pytest.fixture(scope="module")
def supply_token():
    return _login(*SUPPLY)


@pytest.fixture(scope="module")
def er_dept(admin_token):
    depts = requests.get(f"{API}/departments", headers=_h(admin_token)).json()
    return next(d for d in depts if d["code"] == "ER")


@pytest.fixture(scope="module")
def icu_dept(admin_token):
    depts = requests.get(f"{API}/departments", headers=_h(admin_token)).json()
    return next(d for d in depts if d["code"] == "ICU")


@pytest.fixture(scope="module")
def bvm_item(admin_token):
    items = requests.get(f"{API}/items?search=BVM-ADULT", headers=_h(admin_token)).json()
    assert items, "BVM-ADULT life-saving item must be seeded"
    return next(i for i in items if i["internal_code"] == "BVM-ADULT")


@pytest.fixture(scope="module")
def setup_threshold_and_stock(admin_token, er_dept, bvm_item):
    """Set per-dept thresholds (min=10, crit=5, reserve=3, no_issue=3) and stock=25."""
    th = requests.put(
        f"{API}/items/{bvm_item['id']}/thresholds/{er_dept['id']}",
        headers=_h(admin_token),
        json={
            "minimum_level": 10, "critical_level": 5,
            "emergency_reserve_level": 3, "no_issue_threshold": 3,
            "allow_emergency_override": True,
        },
    )
    assert th.status_code == 200, th.text
    st = requests.post(f"{API}/stock", headers=_h(admin_token), json={
        "department_id": er_dept["id"], "item_id": bvm_item["id"],
        "balance": 25, "notes": "TEST_PH3_seed",
    })
    assert st.status_code == 200, st.text
    return True


# ---------- Threshold ordering ----------
class TestThresholdOrdering:
    def test_valid_ordering_200(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        r = requests.put(
            f"{API}/items/{bvm_item['id']}/thresholds/{er_dept['id']}",
            headers=_h(admin_token),
            json={"minimum_level": 10, "critical_level": 5,
                  "emergency_reserve_level": 3, "no_issue_threshold": 3},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["minimum_level"] == 10
        assert body["critical_level"] == 5
        assert body["no_issue_threshold"] == 3

    def test_bad_ordering_400(self, admin_token, er_dept, bvm_item):
        # critical>min violates ordering
        r = requests.put(
            f"{API}/items/{bvm_item['id']}/thresholds/{er_dept['id']}",
            headers=_h(admin_token),
            json={"minimum_level": 4, "critical_level": 5,
                  "emergency_reserve_level": 3, "no_issue_threshold": 3},
        )
        assert r.status_code == 400, r.text


# ---------- Stock-balance fallback ----------
class TestStockBalanceEndpoint:
    def test_returns_thresholds(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        r = requests.get(f"{API}/stock-balance/{er_dept['id']}/{bvm_item['id']}",
                         headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        assert d["current_balance"] == 25
        assert d["minimum_level"] == 10
        assert d["critical_level"] == 5
        assert d["no_issue_threshold"] == 3


# ---------- Preview decision rules ----------
class TestPreviewRules:
    def _preview(self, token, dept, item, qty, override=None):
        body = {"department_id": dept["id"], "item_id": item["id"], "quantity": qty}
        if override is not None:
            body["override_reason"] = override
        return requests.post(f"{API}/stock/issue/preview", headers=_h(token), json=body)

    def test_qty_zero_400(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        r = self._preview(admin_token, er_dept, bvm_item, 0)
        assert r.status_code == 400

    def test_rule1_normal(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        # 25-10=15 >= min=10
        r = self._preview(admin_token, er_dept, bvm_item, 10)
        assert r.status_code == 200, r.text
        d = r.json()["decision"]
        assert d["rule"] == "normal", d
        assert d["create_alert"] is False

    def test_rule2_below_minimum(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        # 25-19=6, crit(5) < 6 < min(10)
        r = self._preview(admin_token, er_dept, bvm_item, 19)
        d = r.json()["decision"]
        assert d["rule"] == "below_minimum", d
        assert d["create_alert"] is True
        assert d["severity"] == "warning"

    def test_rule3_below_critical(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        # 25-21=4, no_issue(3) <= 4 <= crit(5)
        r = self._preview(admin_token, er_dept, bvm_item, 21)
        d = r.json()["decision"]
        assert d["rule"] == "below_critical", d
        assert d["severity"] == "danger"

    def test_rule4_blocked_or_override_path(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        # 25-23=2 < no_issue(3); BVM is life-saving -> with override_reason -> emergency_override
        r1 = self._preview(admin_token, er_dept, bvm_item, 23)
        d1 = r1.json()["decision"]
        # Without override_reason: rule should be blocked_no_issue (life-saving, but no reason yet)
        assert d1["rule"] == "blocked_no_issue", d1
        # Preview currently ignores override_reason (informational only) — confirm payload
        # exposes is_life_saving + allow_emergency_override so frontend can offer override UI.
        body = r1.json()
        assert body["is_life_saving"] is True
        assert body["allow_emergency_override"] is True


# ---------- Execute issue rules ----------
class TestExecuteIssue:
    def _reset_balance(self, token, dept, item, balance=25):
        r = requests.post(f"{API}/stock", headers=_h(token), json={
            "department_id": dept["id"], "item_id": item["id"],
            "balance": balance, "notes": "TEST_PH3_reset",
        })
        assert r.status_code == 200

    def test_rule1_normal_no_alert(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        self._reset_balance(admin_token, er_dept, bvm_item, 25)
        r = requests.post(f"{API}/stock/issue", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": bvm_item["id"], "quantity": 5,
            "notes": "TEST_PH3_normal",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["previous_balance"] == 25
        assert body["current_balance"] == 20
        assert body["alert_id"] is None
        assert body["decision"]["rule"] == "normal"

    def test_rule2_below_minimum_creates_warning_alert(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        self._reset_balance(admin_token, er_dept, bvm_item, 25)
        r = requests.post(f"{API}/stock/issue", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": bvm_item["id"], "quantity": 19,
            "notes": "TEST_PH3_rule2",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["current_balance"] == 6
        assert body["alert_id"] is not None
        assert body["alert_severity"] == "warning"

    def test_rule3_below_critical_creates_danger_alert(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        self._reset_balance(admin_token, er_dept, bvm_item, 25)
        r = requests.post(f"{API}/stock/issue", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": bvm_item["id"], "quantity": 21,
            "notes": "TEST_PH3_rule3",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["current_balance"] == 4
        assert body["alert_severity"] == "danger"

    def test_rule5_emergency_without_reason_400(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        self._reset_balance(admin_token, er_dept, bvm_item, 25)
        r = requests.post(f"{API}/stock/issue", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": bvm_item["id"], "quantity": 23,
        })
        assert r.status_code == 400, r.text

    def test_rule5_emergency_with_reason_200(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        self._reset_balance(admin_token, er_dept, bvm_item, 25)
        r = requests.post(f"{API}/stock/issue", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": bvm_item["id"], "quantity": 23,
            "override_reason": "patient code blue",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision"]["rule"] == "emergency_override"
        assert body["decision"]["override"] is True
        assert body["alert_severity"] == "critical"
        # verify txn persisted with override
        txns = requests.get(
            f"{API}/stock/transactions?item_id={bvm_item['id']}&department_id={er_dept['id']}",
            headers=_h(admin_token)
        ).json()
        latest = txns[0]
        assert latest["override_flag"] is True
        assert latest["override_reason"] == "patient code blue"
        assert latest["decision_rule"] == "emergency_override"
        assert latest["previous_balance"] == 25
        assert latest["new_balance"] == 2

    def test_insufficient_stock_400(self, admin_token, er_dept, bvm_item, setup_threshold_and_stock):
        self._reset_balance(admin_token, er_dept, bvm_item, 25)
        r = requests.post(f"{API}/stock/issue", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": bvm_item["id"], "quantity": 999,
        })
        assert r.status_code == 400

    def test_negative_qty_400(self, admin_token, er_dept, bvm_item):
        r = requests.post(f"{API}/stock/issue", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": bvm_item["id"], "quantity": -1,
        })
        assert r.status_code == 400

    def test_officer_cross_department_403(self, officer_icu_token, er_dept, bvm_item, setup_threshold_and_stock):
        # ICU officer tries to issue from ER -> 403
        r = requests.post(f"{API}/stock/issue", headers=_h(officer_icu_token), json={
            "department_id": er_dept["id"], "item_id": bvm_item["id"], "quantity": 1,
        })
        assert r.status_code == 403, r.text

    def test_rule4_blocked_non_lifesaving(self, admin_token, er_dept, supply_token):
        """Create a non-lifesaving item, set thresholds, stock it, try to drop below no_issue -> 400."""
        import uuid
        code = f"TEST_PH3_NLS_{uuid.uuid4().hex[:6]}"
        ic = requests.post(f"{API}/items", headers=_h(admin_token), json={
            "internal_code": code, "name_ar": "غير منقذ", "name_en": code,
            "category": "Other", "unit": "PCS",
            "min_level": 10, "critical_threshold": 5, "max_level": 50,
            "is_life_saving": False,
        })
        assert ic.status_code == 200, ic.text
        item = ic.json()
        # threshold
        requests.put(f"{API}/items/{item['id']}/thresholds/{er_dept['id']}",
                     headers=_h(admin_token),
                     json={"minimum_level": 10, "critical_level": 5,
                           "emergency_reserve_level": 3, "no_issue_threshold": 3})
        # stock 5
        requests.post(f"{API}/stock", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": item["id"], "balance": 5,
        })
        # try to issue 3 → projected=2 < no_issue=3, non-lifesaving -> blocked 400
        r = requests.post(f"{API}/stock/issue", headers=_h(admin_token), json={
            "department_id": er_dept["id"], "item_id": item["id"], "quantity": 3,
            "override_reason": "trying override should still block",
        })
        assert r.status_code == 400, r.text


# ---------- Audit logs ----------
class TestAuditLogs:
    def test_audit_entries_written(self, admin_token):
        r = requests.get(f"{API}/audit-logs?limit=300", headers=_h(admin_token))
        assert r.status_code == 200
        actions = {a["action"] for a in r.json()}
        assert "upsert_threshold" in actions
        assert "stock_issue" in actions
        assert "stock_issue_override" in actions


# ---------- Escalation Recipients ----------
class TestEscalationRecipients:
    def test_get_list(self, admin_token):
        r = requests.get(f"{API}/settings/escalation-recipients", headers=_h(admin_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_upsert_then_clear(self, admin_token):
        r = requests.put(f"{API}/settings/escalation-recipients", headers=_h(admin_token),
                         json={"role": "supply_officer", "email": "test_supply@example.com"})
        assert r.status_code == 200
        lst = requests.get(f"{API}/settings/escalation-recipients", headers=_h(admin_token)).json()
        assert any(x["role"] == "supply_officer" and x["email"] == "test_supply@example.com" for x in lst)

        # clear with null
        r2 = requests.put(f"{API}/settings/escalation-recipients", headers=_h(admin_token),
                          json={"role": "supply_officer", "email": None})
        assert r2.status_code == 200
        lst2 = requests.get(f"{API}/settings/escalation-recipients", headers=_h(admin_token)).json()
        assert not any(x["role"] == "supply_officer" for x in lst2)


# ---------- Regression ----------
class TestRegression:
    def test_login(self):
        assert _login(*ADMIN)

    def test_items_alerts_kpis_reports(self, admin_token):
        for path in ["/items", "/alerts", "/dashboard/kpis"]:
            r = requests.get(f"{API}{path}", headers=_h(admin_token))
            assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
