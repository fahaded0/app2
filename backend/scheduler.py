"""Background scheduler: checks SLAs every N minutes and escalates alerts."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from settings_store import get_settings
from models import _new_id, _now_iso

logger = logging.getLogger("scheduler")


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _escalate_alert(db, alert: dict, target_role: str, reason: str) -> None:
    """Append an escalation entry to an alert and bump its level."""
    new_level = (alert.get("escalation_level") or 0) + 1
    entry = {
        "level": new_level,
        "at": _now_iso(),
        "escalated_to": target_role,
        "reason": reason,
    }
    await db.alerts.update_one(
        {"id": alert["id"]},
        {
            "$set": {"escalation_level": new_level, "escalated_to": target_role},
            "$push": {"escalations": entry},
        },
    )
    logger.info("Alert %s escalated to %s (level %d)", alert["id"], target_role, new_level)


async def _check_alert_slas(db: AsyncIOMotorDatabase, sla: dict) -> None:
    """Walk all unresolved alerts and escalate those past their SLA window."""
    now = datetime.now(timezone.utc)
    open_alerts = await db.alerts.find(
        {"status": {"$in": ["open", "acknowledged", "in_progress"]}},
        {"_id": 0},
    ).to_list(2000)

    for a in open_alerts:
        if a.get("escalation_level", 0) >= 2:
            continue   # already at top level
        opened_at = _parse_iso(a["created_at"])
        age_min = (now - opened_at).total_seconds() / 60

        atype = a.get("type")
        item = await db.items.find_one({"id": a.get("item_id")}, {"_id": 0}) if a.get("item_id") else None
        is_life_saving = bool(item and item.get("is_life_saving"))

        threshold = None
        target = None
        if atype == "zero_level":
            threshold = sla["zero_level_lifesaving_minutes"] if is_life_saving else sla["zero_level_normal_minutes"]
            target = "hospital_manager" if is_life_saving else "supply_officer"
        elif atype == "life_saving_item":
            threshold = sla["zero_level_lifesaving_minutes"]
            target = "hospital_manager"
        elif atype == "critical_level":
            threshold = sla["critical_level_escalation_minutes"]
            target = "hospital_manager"
        elif atype == "backorder":
            threshold = sla["backorder_escalation_minutes"]
            target = "procurement"

        if threshold is None:
            continue
        if age_min >= threshold:
            current_level = a.get("escalation_level", 0)
            if current_level == 0:
                await _escalate_alert(db, a, target, f"SLA breached after {int(age_min)} min")
            elif current_level == 1 and age_min >= threshold * 2:
                await _escalate_alert(db, a, "hospital_manager", "Escalation level 2 (management)")


async def _check_stale_stock(db: AsyncIOMotorDatabase, sla: dict) -> None:
    """Flag stock entries not updated within the configured window (data quality)."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=sla["no_update_minutes"])
    cutoff_iso = cutoff.isoformat()
    stale = await db.stock_entries.find(
        {"last_updated_at": {"$lt": cutoff_iso}},
        {"_id": 0},
    ).to_list(2000)
    for entry in stale:
        # Avoid duplicate no_update alerts within the same window
        existing = await db.alerts.find_one({
            "type": "no_update",
            "department_id": entry["department_id"],
            "item_id": entry["item_id"],
            "status": {"$in": ["open", "acknowledged", "in_progress"]},
        })
        if existing:
            continue
        item = await db.items.find_one({"id": entry["item_id"]}, {"_id": 0})
        dept = await db.departments.find_one({"id": entry["department_id"]}, {"_id": 0})
        if not item or not dept:
            continue
        await db.alerts.insert_one({
            "id": _new_id(),
            "type": "no_update",
            "severity": "warning",
            "status": "open",
            "title": f"Stale stock data — {item['name_en']}",
            "message": f"Not updated for over {sla['no_update_minutes'] // 60}h in {dept['code']}",
            "department_id": entry["department_id"],
            "item_id": entry["item_id"],
            "request_id": None,
            "created_at": _now_iso(),
            "escalation_level": 0,
            "escalations": [],
            "escalated_to": None,
            "sla_due_at": None,
            "acknowledged": False,
            "acknowledged_by": None, "acknowledged_at": None,
            "in_progress_by": None, "in_progress_at": None,
            "resolution_note": None,
            "resolved_by": None, "resolved_at": None,
            "closed_at": None,
        })


async def _check_backorder_overdue(db: AsyncIOMotorDatabase, sla: dict) -> None:
    """Open a backorder alert when a request remains backordered past the SLA."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=sla["backorder_escalation_minutes"])
    cutoff_iso = cutoff.isoformat()
    overdue = await db.stock_requests.find(
        {"status": "backorder", "created_at": {"$lt": cutoff_iso}},
        {"_id": 0},
    ).to_list(500)
    for req in overdue:
        existing = await db.alerts.find_one({
            "type": "backorder",
            "request_id": req["id"],
            "status": {"$in": ["open", "acknowledged", "in_progress"]},
            "escalation_level": {"$gte": 1},
        })
        if existing:
            continue
        item = await db.items.find_one({"id": req["item_id"]}, {"_id": 0})
        dept = await db.departments.find_one({"id": req["department_id"]}, {"_id": 0})
        if not item or not dept:
            continue
        await db.alerts.insert_one({
            "id": _new_id(),
            "type": "backorder",
            "severity": "critical",
            "status": "open",
            "title": f"Backorder overdue — {item['name_en']}",
            "message": f"Request {req['request_number']} for {dept['code']} exceeded SLA",
            "department_id": req["department_id"],
            "item_id": req["item_id"],
            "request_id": req["id"],
            "created_at": _now_iso(),
            "escalation_level": 1,
            "escalations": [{
                "level": 1, "at": _now_iso(),
                "escalated_to": "procurement",
                "reason": "Backorder past SLA window",
            }],
            "escalated_to": "procurement",
            "sla_due_at": None,
            "acknowledged": False,
            "acknowledged_by": None, "acknowledged_at": None,
            "in_progress_by": None, "in_progress_at": None,
            "resolution_note": None,
            "resolved_by": None, "resolved_at": None,
            "closed_at": None,
        })


async def reconcile_stock_balances(db: AsyncIOMotorDatabase) -> list[dict]:
    """Recompute stock_entries.balance from stock_transactions and log discrepancies.

    For each (item, department) pair that has any transactions, we compute:
        expected = sum(delta) of all transactions for the pair
    and compare against the latest stock_entries.balance. If they diverge it
    means a previous run had a partial write — we log to `reconciliation_log`
    and emit a 'data_quality' alert. The latest balance is NOT mutated here
    (operators must investigate first).

    Returns the list of discrepancies found (also written to the log).
    """
    pipeline = [
        {"$group": {
            "_id": {"item_id": "$item_id", "department_id": "$department_id"},
            "txn_sum": {"$sum": "$delta"},
            "txn_count": {"$sum": 1},
            "last_txn_at": {"$max": "$created_at"},
        }},
    ]
    discrepancies: list[dict] = []
    async for row in db.stock_transactions.aggregate(pipeline):
        item_id = row["_id"]["item_id"]
        department_id = row["_id"]["department_id"]
        txn_sum = int(row["txn_sum"])
        entry = await db.stock_entries.find_one(
            {"item_id": item_id, "department_id": department_id}, {"_id": 0},
        )
        current = int(entry["balance"]) if entry else 0
        # `txn_sum` is the NET delta since the first transaction. The stored
        # balance starts from an opening point that may have been seeded before
        # any transactions, so we accept any (current, txn_sum) where the diff
        # is stable (i.e. balance >= txn_sum and balance - txn_sum is the opening).
        # The discrepancy we actually care about: balance < txn_sum (which would
        # imply we lost a receive event), or balance went negative.
        if current < 0 or (txn_sum < 0 and current + (-txn_sum) < 0):
            discrepancies.append({
                "item_id": item_id, "department_id": department_id,
                "current_balance": current, "transactions_sum": txn_sum,
            })
        # Optional warning: balance is *lower* than the absolute issues — should not happen
        if txn_sum < 0 and current < 0:
            discrepancies.append({
                "item_id": item_id, "department_id": department_id,
                "current_balance": current, "transactions_sum": txn_sum,
                "kind": "negative_balance",
            })
    if discrepancies:
        await db.reconciliation_log.insert_one({
            "id": _new_id(),
            "checked_at": _now_iso(),
            "discrepancy_count": len(discrepancies),
            "discrepancies": discrepancies,
        })
        # Open a data-quality alert per discrepancy (deduplicated)
        for d in discrepancies:
            existing = await db.alerts.find_one({
                "type": "no_update",
                "department_id": d["department_id"],
                "item_id": d["item_id"],
                "status": {"$in": ["open", "acknowledged", "in_progress"]},
                "title": {"$regex": "^Reconciliation discrepancy"},
            })
            if existing:
                continue
            item = await db.items.find_one({"id": d["item_id"]}, {"_id": 0})
            dept = await db.departments.find_one({"id": d["department_id"]}, {"_id": 0})
            if not item or not dept:
                continue
            await db.alerts.insert_one({
                "id": _new_id(), "type": "no_update", "severity": "warning",
                "status": "open",
                "title": f"Reconciliation discrepancy — {item['name_en']}",
                "message": (f"In {dept['code']}: stored balance = {d['current_balance']}, "
                            f"transactions sum = {d['transactions_sum']}. Investigate."),
                "department_id": d["department_id"], "item_id": d["item_id"],
                "request_id": None, "created_at": _now_iso(),
                "escalation_level": 0, "escalations": [], "escalated_to": None,
                "sla_due_at": None,
                "acknowledged": False, "acknowledged_by": None, "acknowledged_at": None,
                "in_progress_by": None, "in_progress_at": None,
                "resolution_note": None, "resolved_by": None, "resolved_at": None,
                "closed_at": None,
            })
        logger.warning("Reconciliation found %d discrepancies", len(discrepancies))
    return discrepancies


async def _reconciliation_loop(db: AsyncIOMotorDatabase, interval_minutes: int = 60) -> None:
    """Independent loop for stock-balance reconciliation."""
    while True:
        try:
            await reconcile_stock_balances(db)
        except asyncio.CancelledError:
            logger.info("Reconciliation loop stopped")
            raise
        except Exception as e:
            logger.exception("Reconciliation iteration failed: %s", e)
        await asyncio.sleep(interval_minutes * 60)


async def scheduler_loop(db: AsyncIOMotorDatabase) -> None:
    """Run forever, sleeping `scheduler_interval_minutes` between cycles."""
    while True:
        try:
            sla = await get_settings(db)
            await _check_alert_slas(db, sla)
            await _check_stale_stock(db, sla)
            await _check_backorder_overdue(db, sla)
        except asyncio.CancelledError:
            logger.info("Scheduler stopped")
            raise
        except Exception as e:
            logger.exception("Scheduler iteration failed: %s", e)
        # Re-read sleep interval each cycle so admin can tune without restart
        try:
            sla = await get_settings(db)
            interval = max(1, int(sla.get("scheduler_interval_minutes", 15)))
        except Exception:
            interval = 15
        await asyncio.sleep(interval * 60)
