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
