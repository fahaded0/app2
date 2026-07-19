"""Data providers for the 10 formal reports.

Each provider returns a tuple of (headers, rows, meta) ready for excel/pdf builders.
"""
from datetime import datetime, timezone, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def _fmt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return iso


# ===== Stock reports =====
async def report_zero_level(db: AsyncDatabase, user: dict) -> tuple:
    rows_raw = await db.stock_entries.find({"status": "zero_level"}, {"_id": 0}).to_list(2000)
    headers = ["Department", "Item Code", "Item Name", "Unit", "Balance",
               "Min", "Critical", "Life-Saving", "Shortage Since", "Last Updated"]
    rows = []
    for r in rows_raw:
        item = await db.items.find_one({"id": r["item_id"]}, {"_id": 0}) or {}
        dept = await db.departments.find_one({"id": r["department_id"]}, {"_id": 0}) or {}
        rows.append([
            dept.get("code", "—"), item.get("internal_code", "—"), item.get("name_en", "—"),
            item.get("unit", "—"), r.get("balance", 0),
            item.get("min_level", 0), item.get("critical_threshold", 0),
            "Yes" if item.get("is_life_saving") else "—",
            _fmt(r.get("shortage_start")), _fmt(r.get("last_updated_at")),
        ])
    return headers, rows, {
        "title": "Zero Stock Items Report",
        "period": "Current state",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "Items whose balance is currently zero in any department.",
    }


async def report_critical_level(db: AsyncDatabase, user: dict) -> tuple:
    rows_raw = await db.stock_entries.find({"status": "critical_level"}, {"_id": 0}).to_list(2000)
    headers = ["Department", "Item Code", "Item Name", "Unit", "Balance",
               "Critical Threshold", "Min", "Life-Saving", "Shortage Since", "Last Updated"]
    rows = []
    for r in rows_raw:
        item = await db.items.find_one({"id": r["item_id"]}, {"_id": 0}) or {}
        dept = await db.departments.find_one({"id": r["department_id"]}, {"_id": 0}) or {}
        rows.append([
            dept.get("code", "—"), item.get("internal_code", "—"), item.get("name_en", "—"),
            item.get("unit", "—"), r.get("balance", 0),
            item.get("critical_threshold", 0), item.get("min_level", 0),
            "Yes" if item.get("is_life_saving") else "—",
            _fmt(r.get("shortage_start")), _fmt(r.get("last_updated_at")),
        ])
    return headers, rows, {
        "title": "Critical Stock Items Report",
        "period": "Current state",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "Items whose balance is below the critical threshold.",
    }


async def report_life_saving(db: AsyncDatabase, user: dict) -> tuple:
    life_ids = [i["id"] for i in await db.items.find(
        {"is_life_saving": True}, {"_id": 0, "id": 1}
    ).to_list(500)]
    rows_raw = await db.stock_entries.find(
        {"item_id": {"$in": life_ids}, "status": {"$in": ["zero_level", "critical_level"]}},
        {"_id": 0},
    ).to_list(500)
    headers = ["Department", "Item Code", "Item Name", "Balance", "Min", "Critical",
               "Status", "Shortage Since"]
    rows = []
    for r in rows_raw:
        item = await db.items.find_one({"id": r["item_id"]}, {"_id": 0}) or {}
        dept = await db.departments.find_one({"id": r["department_id"]}, {"_id": 0}) or {}
        rows.append([
            dept.get("code", "—"), item.get("internal_code", "—"), item.get("name_en", "—"),
            r.get("balance", 0), item.get("min_level", 0), item.get("critical_threshold", 0),
            r.get("status", "—"), _fmt(r.get("shortage_start")),
        ])
    return headers, rows, {
        "title": "Life-Saving Items at Risk",
        "period": "Current state",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "Items flagged as life-saving currently at Zero or Critical level. Requires immediate action.",
    }


# ===== Request reports =====
async def report_backorder(db: AsyncDatabase, user: dict) -> tuple:
    rows_raw = await db.stock_requests.find({"status": "backorder"}, {"_id": 0}).to_list(2000)
    now = datetime.now(timezone.utc)
    headers = ["Request #", "Department", "Item Code", "Item Name", "Requested Qty",
               "Days Open", "Priority", "Expected Supply", "Created"]
    rows = []
    for r in rows_raw:
        item = await db.items.find_one({"id": r["item_id"]}, {"_id": 0}) or {}
        dept = await db.departments.find_one({"id": r["department_id"]}, {"_id": 0}) or {}
        try:
            dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days_open = round((now - dt).total_seconds() / 86400, 1)
        except Exception:
            days_open = "—"
        rows.append([
            r.get("request_number", "—"), dept.get("code", "—"),
            item.get("internal_code", "—"), item.get("name_en", "—"),
            r.get("requested_qty", 0), days_open,
            r.get("priority", "—"), _fmt(r.get("expected_supply_date")),
            _fmt(r.get("created_at")),
        ])
    return headers, rows, {
        "title": "Backorder Report",
        "period": "Active",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "Requests not fulfilled because the central warehouse is out of stock.",
    }


async def report_open_requests(db: AsyncDatabase, user: dict) -> tuple:
    rows_raw = await db.stock_requests.find(
        {"status": {"$in": ["pending_approval", "approved", "dispatched",
                            "partially_received", "backorder"]}},
        {"_id": 0},
    ).to_list(2000)
    headers = ["Request #", "Department", "Item Code", "Item Name",
               "Requested", "Approved", "Dispatched", "Received",
               "Status", "Priority", "Created"]
    rows = []
    for r in rows_raw:
        item = await db.items.find_one({"id": r["item_id"]}, {"_id": 0}) or {}
        dept = await db.departments.find_one({"id": r["department_id"]}, {"_id": 0}) or {}
        rows.append([
            r.get("request_number", "—"), dept.get("code", "—"),
            item.get("internal_code", "—"), item.get("name_en", "—"),
            r.get("requested_qty", 0), r.get("approved_qty") if r.get("approved_qty") is not None else "—",
            r.get("dispatched_qty", 0), r.get("received_qty", 0),
            r.get("status", "—"), r.get("priority", "—"),
            _fmt(r.get("created_at")),
        ])
    return headers, rows, {
        "title": "Open Requests Report",
        "period": "Active",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "All requests that have not reached the Received/Closed state.",
    }


# ===== Data quality report (combines no_barcode + stale + duplicate barcode) =====
async def report_data_quality(db: AsyncDatabase, user: dict) -> tuple:
    headers = ["Issue", "Entity", "Identifier", "Detail"]
    rows = []
    # No barcode
    async for it in db.items.find(
        {"$or": [{"barcode": None}, {"barcode": ""}], "is_active": True}, {"_id": 0}
    ):
        rows.append(["Missing Barcode", "Item", it.get("internal_code", "—"), it.get("name_en", "—")])
    # Duplicate barcode
    pipeline = [
        {"$match": {"barcode": {"$nin": [None, ""]}, "is_active": True}},
        {"$group": {"_id": "$barcode", "n": {"$sum": 1}, "items": {"$push": "$internal_code"}}},
        {"$match": {"n": {"$gt": 1}}},
    ]
    duplicate_cursor = await db.items.aggregate(pipeline)
    async for d in duplicate_cursor:
        rows.append(["Duplicate Barcode", "Item",
                     d["_id"], f"shared by: {', '.join(d['items'])}"])
    # Stale stock (>24h)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    async for s in db.stock_entries.find({"last_updated_at": {"$lt": cutoff}}, {"_id": 0}):
        item = await db.items.find_one({"id": s["item_id"]}, {"_id": 0}) or {}
        dept = await db.departments.find_one({"id": s["department_id"]}, {"_id": 0}) or {}
        rows.append([
            "Not Updated > 24h", "Stock",
            f"{dept.get('code','—')} / {item.get('internal_code','—')}",
            f"Last updated {_fmt(s.get('last_updated_at'))}",
        ])
    return headers, rows, {
        "title": "Data Quality Report",
        "period": "Current state",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "Issues that undermine the reliability of operational decisions.",
    }


# ===== Item movement =====
async def report_item_movement(db: AsyncDatabase, user: dict, item_id: str | None = None) -> tuple:
    q: dict = {}
    if item_id:
        q["item_id"] = item_id
    rows_raw = await db.stock_transactions.find(q, {"_id": 0}).sort("created_at", -1).limit(1000).to_list(1000)
    headers = ["Date", "Department", "Item Code", "Item Name",
               "Previous", "New Balance", "Delta", "New Status", "User", "Reason"]
    rows = []
    for tx in rows_raw:
        item = await db.items.find_one({"id": tx["item_id"]}, {"_id": 0}) or {}
        dept = await db.departments.find_one({"id": tx["department_id"]}, {"_id": 0}) or {}
        rows.append([
            _fmt(tx.get("created_at")), dept.get("code", "—"),
            item.get("internal_code", "—"), item.get("name_en", "—"),
            tx.get("previous_balance") if tx.get("previous_balance") is not None else "—",
            tx.get("new_balance", 0), tx.get("delta", 0), tx.get("status", "—"),
            tx.get("user_name", "—"), tx.get("reason", "—"),
        ])
    return headers, rows, {
        "title": "Item Movement Report",
        "period": "Last 1000 movements",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "Full transaction history with user attribution.",
    }


# ===== Department performance =====
async def report_department_performance(db: AsyncDatabase, user: dict) -> tuple:
    headers = ["Department", "Code", "Items Tracked", "Zero", "Critical",
               "Stale >24h", "Open Requests", "Avg Approval (h)", "Fulfillment %"]
    departments = await db.departments.find({}, {"_id": 0}).to_list(200)
    rows = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    for d in departments:
        dept_id = d["id"]
        items_tracked = await db.stock_entries.count_documents({"department_id": dept_id})
        zero = await db.stock_entries.count_documents({"department_id": dept_id, "status": "zero_level"})
        crit = await db.stock_entries.count_documents({"department_id": dept_id, "status": "critical_level"})
        stale = await db.stock_entries.count_documents({
            "department_id": dept_id, "last_updated_at": {"$lt": cutoff}
        })
        open_reqs = await db.stock_requests.count_documents({
            "department_id": dept_id,
            "status": {"$in": ["pending_approval", "approved", "dispatched", "partially_received", "backorder"]},
        })
        # Avg approval time (only for approved requests in last 30d)
        approved_docs = await db.stock_requests.find(
            {"department_id": dept_id, "approved_at": {"$ne": None},
             "created_at": {"$gte": cutoff_30}},
            {"_id": 0, "created_at": 1, "approved_at": 1},
        ).to_list(500)
        avg_h = "—"
        if approved_docs:
            total = 0.0
            n = 0
            for a in approved_docs:
                try:
                    c = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
                    p = datetime.fromisoformat(a["approved_at"].replace("Z", "+00:00"))
                    if c.tzinfo is None:
                        c = c.replace(tzinfo=timezone.utc)
                    if p.tzinfo is None:
                        p = p.replace(tzinfo=timezone.utc)
                    total += (p - c).total_seconds() / 3600
                    n += 1
                except Exception:
                    pass
            if n:
                avg_h = round(total / n, 1)
        # Fulfillment % (30d)
        total_30 = await db.stock_requests.count_documents({
            "department_id": dept_id, "created_at": {"$gte": cutoff_30}
        })
        rec_30 = await db.stock_requests.count_documents({
            "department_id": dept_id, "created_at": {"$gte": cutoff_30},
            "status": {"$in": ["received", "closed"]},
        })
        fulfill = round(rec_30 / total_30 * 100, 1) if total_30 else "—"
        rows.append([
            d["name_en"], d["code"], items_tracked, zero, crit, stale,
            open_reqs, avg_h, fulfill,
        ])
    return headers, rows, {
        "title": "Department Performance Report",
        "period": "Snapshot + 30d trends",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "Per-department operational metrics for shift handover or weekly review.",
    }


# ===== Monthly management overview =====
async def report_monthly_management(db: AsyncDatabase, user: dict) -> tuple:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    period_label = f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
    cutoff_iso = start.isoformat()

    headers = ["Metric", "Value", "Comment"]
    total_items = await db.items.count_documents({"is_active": True})
    zero = await db.stock_entries.count_documents({"status": "zero_level"})
    crit = await db.stock_entries.count_documents({"status": "critical_level"})
    bo = await db.stock_requests.count_documents({"status": "backorder"})
    no_bc = await db.items.count_documents({"$or": [{"barcode": None}, {"barcode": ""}], "is_active": True})
    open_alerts = await db.alerts.count_documents({"status": {"$in": ["open", "acknowledged", "in_progress"]}})
    closed_alerts = await db.alerts.count_documents({"status": {"$in": ["resolved", "closed"]},
                                                     "created_at": {"$gte": cutoff_iso}})
    requests_30 = await db.stock_requests.count_documents({"created_at": {"$gte": cutoff_iso}})
    fulfilled_30 = await db.stock_requests.count_documents({
        "created_at": {"$gte": cutoff_iso},
        "status": {"$in": ["received", "closed"]},
    })
    ff = round(fulfilled_30 / requests_30 * 100, 1) if requests_30 else 0.0
    life_items = await db.items.find({"is_life_saving": True}, {"_id": 0, "id": 1}).to_list(500)
    life_ids = [i["id"] for i in life_items]
    life_risk = await db.stock_entries.count_documents({
        "item_id": {"$in": life_ids}, "status": {"$in": ["zero_level", "critical_level"]},
    })

    rows = [
        ["Active items", total_items, ""],
        ["Zero stock", zero, "Immediate risk" if zero else "OK"],
        ["Critical stock", crit, "Watch list" if crit else "OK"],
        ["Backorder requests", bo, "Procurement to follow up" if bo else "—"],
        ["Items without barcode", no_bc, "Data quality gap" if no_bc else "—"],
        ["Open alerts", open_alerts, ""],
        ["Resolved/Closed alerts (30d)", closed_alerts, ""],
        ["Requests (30d)", requests_30, ""],
        ["Fulfilled requests (30d)", fulfilled_30, f"{ff}% fulfillment"],
        ["Life-saving items at risk", life_risk, "Critical clinical risk" if life_risk else "OK"],
    ]
    return headers, rows, {
        "title": "Monthly Management Report",
        "period": period_label,
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "High-level KPIs for executive review. Detailed reports support each metric.",
    }


# ===== Audit Trail =====
async def report_audit_trail(db: AsyncDatabase, user: dict) -> tuple:
    rows_raw = await db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).limit(2000).to_list(2000)
    headers = ["Timestamp", "User", "Role", "Action", "Entity", "Entity ID", "IP"]
    rows = []
    for log in rows_raw:
        rows.append([
            _fmt(log.get("created_at")), log.get("user_email", "—"),
            log.get("user_role", "—"), log.get("action", "—"),
            log.get("entity", "—"),
            (log.get("entity_id") or "")[:12], log.get("ip", "—"),
        ])
    return headers, rows, {
        "title": "Audit Trail Report",
        "period": "Last 2000 events",
        "extracted_by": user.get("full_name") or user.get("email", "—"),
        "count": len(rows),
        "notes": "Tamper-proof log of system actions for compliance and investigation.",
    }


REPORT_BUILDERS = {
    "zero_level":             report_zero_level,
    "critical_level":         report_critical_level,
    "life_saving":            report_life_saving,
    "backorder":              report_backorder,
    "open_requests":          report_open_requests,
    "data_quality":           report_data_quality,
    "item_movement":          report_item_movement,
    "department_performance": report_department_performance,
    "monthly_management":     report_monthly_management,
    "audit_trail":            report_audit_trail,
}
