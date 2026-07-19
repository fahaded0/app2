"""Stock Issue Workflow with Reserve Control and Escalation.

Implements the 5 business rules:
  1. Normal      — projected_balance >= minimum_level                       → allow, no alert
  2. Warning     — critical_level < projected < minimum                     → allow + medium alert
  3. Escalated   — no_issue_threshold <= projected <= critical_level        → allow + high alert
  4. Blocked     — projected < no_issue_threshold (non life-saving)         → BLOCK
  5. Emergency   — projected < no_issue_threshold (life-saving + override)  → allow + critical alert

All decisions are made in the backend; the frontend is purely a viewer.
"""
from typing import Optional
from datetime import datetime, timezone

from pymongo.asynchronous.database import AsyncDatabase
from fastapi import HTTPException

from models import _new_id, _now_iso


# ---------- Threshold model helpers ----------
async def ensure_threshold(
    db: AsyncDatabase, item_id: str, department_id: str, *, session=None
) -> dict:
    """Return the per-department threshold, falling back to item defaults if missing."""
    th = await db.item_department_thresholds.find_one(
        {"item_id": item_id, "department_id": department_id}, {"_id": 0},
        session=session,
    )
    if th:
        return th
    item = await db.items.find_one({"id": item_id}, {"_id": 0}, session=session)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return {
        "id": None,
        "item_id": item_id,
        "department_id": department_id,
        "minimum_level": item.get("min_level", 0),
        "critical_level": item.get("critical_threshold", 0),
        "emergency_reserve_level": 0,
        "no_issue_threshold": 0,
        "allow_emergency_override": bool(item.get("is_life_saving")),
        "requires_approval_below_reserve": True,
        "escalation_minutes": 30,
    }


async def upsert_threshold(
    db: AsyncDatabase, *, item_id: str, department_id: str,
    minimum_level: int, critical_level: int,
    emergency_reserve_level: int, no_issue_threshold: int,
    allow_emergency_override: bool = True,
    requires_approval_below_reserve: bool = True,
    escalation_minutes: int = 30,
    user_id: Optional[str] = None,
) -> dict:
    if not (no_issue_threshold <= emergency_reserve_level <= critical_level <= minimum_level):
        raise HTTPException(
            status_code=400,
            detail=("Threshold ordering must be: "
                    "no_issue_threshold <= emergency_reserve_level <= critical_level <= minimum_level"),
        )
    existing = await db.item_department_thresholds.find_one(
        {"item_id": item_id, "department_id": department_id}
    )
    doc = {
        "item_id": item_id,
        "department_id": department_id,
        "minimum_level": int(minimum_level),
        "critical_level": int(critical_level),
        "emergency_reserve_level": int(emergency_reserve_level),
        "no_issue_threshold": int(no_issue_threshold),
        "allow_emergency_override": bool(allow_emergency_override),
        "requires_approval_below_reserve": bool(requires_approval_below_reserve),
        "escalation_minutes": int(escalation_minutes),
        "updated_by": user_id,
        "updated_at": _now_iso(),
    }
    if existing:
        await db.item_department_thresholds.update_one(
            {"id": existing["id"]}, {"$set": doc}
        )
        doc["id"] = existing["id"]
    else:
        doc["id"] = _new_id()
        await db.item_department_thresholds.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ---------- Decision engine ----------
def evaluate_issue_decision(
    *,
    item: dict,
    threshold: dict,
    previous_balance: int,
    projected_balance: int,
    user_role: str,
    override_reason: Optional[str],
) -> dict:
    """Return a dict describing the action the backend will take.

    Keys:
      block (bool), override (bool), create_alert (bool),
      severity (str), message (str), escalate_to (list[str]),
      rule (str — for diagnostics/UI).
    """
    minimum_level = threshold["minimum_level"]
    critical_level = threshold["critical_level"]
    no_issue_threshold = threshold["no_issue_threshold"]
    is_life_saving = bool(item.get("is_life_saving"))
    allow_emergency_override = bool(threshold.get("allow_emergency_override"))

    # Rule 1: normal
    if projected_balance >= minimum_level:
        return {
            "block": False, "override": False, "create_alert": False,
            "severity": "info", "rule": "normal",
            "message": "Issue allowed (balance remains above minimum).",
            "escalate_to": [],
        }

    # Rule 2: warning band
    if critical_level < projected_balance < minimum_level:
        return {
            "block": False, "override": False, "create_alert": True,
            "severity": "warning", "rule": "below_minimum",
            "message": "Balance after issue falls below minimum level.",
            "escalate_to": ["department_head"],
        }

    # Rule 3: critical band
    if no_issue_threshold <= projected_balance <= critical_level:
        return {
            "block": False, "override": False, "create_alert": True,
            "severity": "danger", "rule": "below_critical",
            "message": "Balance reached critical level. Replenishment required.",
            "escalate_to": ["supply_officer", "department_head"],
        }

    # Rule 4 / 5: below no-issue threshold
    if projected_balance < no_issue_threshold:
        can_override = (
            is_life_saving
            and allow_emergency_override
            and user_role in ("super_admin", "hospital_manager",
                              "department_head", "supply_officer",
                              "digital_health_manager")
            and bool(override_reason)
        )
        if can_override:
            return {
                "block": False, "override": True, "create_alert": True,
                "severity": "critical", "rule": "emergency_override",
                "message": "Emergency override accepted for life-saving item.",
                "escalate_to": ["hospital_manager", "supply_officer", "department_head"],
            }
        return {
            "block": True, "override": False, "create_alert": False,
            "severity": "critical", "rule": "blocked_no_issue",
            "message": ("Issue blocked: balance after operation would fall below "
                        "the no-issue threshold. Provide approval or alternative item."),
            "escalate_to": [],
        }

    # Defensive default — should never reach here
    return {
        "block": False, "override": False, "create_alert": False,
        "severity": "info", "rule": "unknown",
        "message": "Issue allowed.",
        "escalate_to": [],
    }


# ---------- Status calculator (post-issue) ----------
def calc_status(balance: int, threshold: dict) -> str:
    if balance == 0:
        return "zero_level"
    if balance < threshold["critical_level"]:
        return "critical_level"
    if balance < threshold["minimum_level"]:
        return "below_minimum"
    return "available"


# ---------- Helpers ----------
async def get_stock_balance(
    db: AsyncDatabase, item_id: str, department_id: str
) -> dict:
    """Get current stock entry (balance) for an item+department, or zero defaults."""
    entry = await db.stock_entries.find_one(
        {"item_id": item_id, "department_id": department_id}, {"_id": 0}
    )
    threshold = await ensure_threshold(db, item_id, department_id)
    if entry:
        balance = entry.get("balance", 0)
        return {
            "item_id": item_id,
            "department_id": department_id,
            "current_balance": balance,
            "available_to_issue": max(0, balance - threshold.get("emergency_reserve_level", 0)),
            "status": entry.get("status", calc_status(balance, threshold)),
            "last_updated_at": entry.get("last_updated_at"),
            "minimum_level": threshold["minimum_level"],
            "critical_level": threshold["critical_level"],
            "emergency_reserve_level": threshold["emergency_reserve_level"],
            "no_issue_threshold": threshold["no_issue_threshold"],
        }
    return {
        "item_id": item_id,
        "department_id": department_id,
        "current_balance": 0,
        "available_to_issue": 0,
        "status": "zero_level",
        "last_updated_at": None,
        "minimum_level": threshold["minimum_level"],
        "critical_level": threshold["critical_level"],
        "emergency_reserve_level": threshold["emergency_reserve_level"],
        "no_issue_threshold": threshold["no_issue_threshold"],
    }
