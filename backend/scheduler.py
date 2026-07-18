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


def validate_v2_ledger_chain(entries: list[dict], stock_entry: dict | None) -> list[dict]:
    """Validate one Ledger v2 chain without mutating application data.

    The function is deliberately defensive because reconciliation is expected to
    inspect corrupted records. Malformed v2 entries are reported as
    ``malformed_ledger_entry`` discrepancies instead of raising ``KeyError`` and
    aborting the reconciliation round.
    """
    if not entries and stock_entry is None:
        return []

    first_entry = entries[0] if entries else {}
    stock_entry = stock_entry or None
    item_id = first_entry.get("item_id") or ((stock_entry or {}).get("item_id"))
    department_id = first_entry.get("department_id") or ((stock_entry or {}).get("department_id"))

    def _disc(kind: str, message: str, **extra) -> dict:
        return {
            "kind": kind,
            "item_id": item_id,
            "department_id": department_id,
            "message": message,
            **extra,
        }

    discrepancies: list[dict] = []
    has_stock_entry = stock_entry is not None

    # Missing stock entry: record discrepancy, then continue validating ledger-only invariants.
    if entries and not has_stock_entry:
        discrepancies.append(_disc(
            "missing_stock_entry",
            message="v2 transactions exist but no stock_entry found for this pair",
        ))

    # Missing v2 ledger when stock entry has ledger_version >= 1.
    if not entries and has_stock_entry:
        lv = stock_entry.get("ledger_version") or 0
        if lv >= 1:
            discrepancies.append(_disc(
                "missing_v2_ledger",
                message=(f"stock_entry has ledger_version={lv} "
                         f"but no v2 transactions found for this pair"),
            ))
        return discrepancies

    if not entries:
        return discrepancies

    required_fields = frozenset({
        "schema_version", "item_id", "department_id", "entry_id",
        "sequence_no", "previous_balance", "quantity_change",
        "new_balance", "delta",
    })
    for index, entry in enumerate(entries):
        missing = required_fields - set(entry)
        if missing:
            missing_list = sorted(missing)
            discrepancies.append(_disc(
                "malformed_ledger_entry",
                message=(f"Ledger v2 entry at index={index} is missing required "
                         f"fields: {', '.join(missing_list)}"),
                detail=f"entry index={index}; missing_fields={missing_list}",
                entry_index=index,
                missing_fields=missing_list,
            ))

    # ---- Chain integrity checks ----
    first = entries[0]
    first_seq = first.get("sequence_no")
    if first_seq is not None and first_seq != 1:
        discrepancies.append(_disc(
            "invalid_first_sequence",
            message=(f"Ledger chain must start at sequence_no=1; "
                     f"got sequence_no={first_seq}"),
            detail=f"first sequence_no={first_seq}, expected 1",
        ))

    if "previous_balance" in first and first.get("previous_balance") != 0:
        discrepancies.append(_disc(
            "invalid_first_previous_balance",
            message=(f"First entry previous_balance must be 0; "
                     f"got {first.get('previous_balance')}"),
            detail=f"first previous_balance={first.get('previous_balance')}, expected 0",
        ))

    for i, entry in enumerate(entries):
        prev = entries[i - 1] if i > 0 else None
        seq = entry.get("sequence_no")

        # sequence gap — only when both sequence values exist.
        if prev is not None:
            prev_seq = prev.get("sequence_no")
            if seq is not None and prev_seq is not None and seq != prev_seq + 1:
                discrepancies.append(_disc(
                    "sequence_gap",
                    message=(f"Sequence jumped from {prev_seq} to {seq}; "
                             f"entries may be missing from the chain"),
                    detail=f"gap detected at index {i}",
                ))

        # chain break — only when the required balance fields exist.
        if (prev is not None and "previous_balance" in entry
                and "new_balance" in prev
                and entry.get("previous_balance") != prev.get("new_balance")):
            discrepancies.append(_disc(
                "chain_break",
                message=(f"Entry at sequence_no={seq}: previous_balance="
                         f"{entry.get('previous_balance')} does not match prior "
                         f"new_balance={prev.get('new_balance')}"),
            ))

        # arithmetic mismatch — evaluate only when all arithmetic fields exist.
        arithmetic_fields = {"previous_balance", "new_balance", "quantity_change", "delta"}
        if arithmetic_fields.issubset(entry):
            pb = entry["previous_balance"]
            nb = entry["new_balance"]
            qc = entry["quantity_change"]
            delta = entry["delta"]
            if nb != pb + qc or delta != qc:
                discrepancies.append(_disc(
                    "arithmetic_mismatch",
                    message=(f"Arithmetic error at sequence_no={seq}: "
                             f"new_balance={nb} (expected {pb + qc}), "
                             f"delta={delta} (expected quantity_change={qc})"),
                    detail=(f"previous_balance={pb}, quantity_change={qc}, "
                            f"new_balance={nb}, delta={delta}"),
                ))

        # entry_id mismatch — only when both identifiers are available.
        stock_entry_id = stock_entry.get("id") if has_stock_entry else None
        if (has_stock_entry and "entry_id" in entry and stock_entry_id is not None
                and entry.get("entry_id") != stock_entry_id):
            discrepancies.append(_disc(
                "entry_id_mismatch",
                message=(f"Entry at sequence_no={seq} references "
                         f"entry_id={entry.get('entry_id')} but "
                         f"stock_entry.id={stock_entry_id}"),
            ))

    last = entries[-1]
    if has_stock_entry:
        # balance mismatch
        if "new_balance" in last and "balance" in stock_entry:
            if last.get("new_balance") != stock_entry.get("balance"):
                discrepancies.append(_disc(
                    "balance_mismatch",
                    message=(f"Last ledger entry new_balance={last.get('new_balance')} "
                             f"does not match stock_entry.balance={stock_entry.get('balance')}"),
                ))

        # version mismatch
        if "sequence_no" in last:
            if last.get("sequence_no") != stock_entry.get("ledger_version"):
                discrepancies.append(_disc(
                    "version_mismatch",
                    message=(f"Last sequence_no={last.get('sequence_no')} does not match "
                             f"stock_entry.ledger_version={stock_entry.get('ledger_version')}"),
                ))

    return discrepancies


async def reconcile_stock_balances(db: AsyncIOMotorDatabase) -> list[dict]:
    """Validate v2 ledger chains for all (item, department) pairs and log discrepancies.

    Only schema_version=2 stock_transactions are examined. The pair universe is
    the union of pairs that have v2 transactions and pairs whose stock_entry has
    ledger_version >= 1. Stock entries with missing or zero ledger_version are
    skipped entirely.

    Does NOT mutate stock_entries or stock_transactions.
    Returns the list of discrepancies found (also written to reconciliation_log).
    """
    # Collect all v2 transaction pairs
    v2_pipeline = [
        {"$match": {"schema_version": 2}},
        {"$group": {
            "_id": {"item_id": "$item_id", "department_id": "$department_id"},
        }},
    ]
    pairs: set[tuple[str, str]] = set()
    async for row in db.stock_transactions.aggregate(v2_pipeline):
        pairs.add((row["_id"]["item_id"], row["_id"]["department_id"]))

    # Also include stock entries with ledger_version >= 1
    ledger_entries_cursor = db.stock_entries.find(
        {"ledger_version": {"$gte": 1}}, {"_id": 0, "item_id": 1, "department_id": 1}
    )
    async for se in ledger_entries_cursor:
        pairs.add((se["item_id"], se["department_id"]))

    checked_pair_count = len(pairs)
    all_discrepancies: list[dict] = []

    for item_id, department_id in pairs:
        # Fetch v2 entries for this pair, sorted by sequence_no
        v2_entries = await db.stock_transactions.find(
            {"schema_version": 2, "item_id": item_id, "department_id": department_id},
            {"_id": 0},
        ).sort("sequence_no", 1).to_list(None)

        stock_entry = await db.stock_entries.find_one(
            {"item_id": item_id, "department_id": department_id}, {"_id": 0}
        )

        # Skip stock entries with missing or zero ledger_version and no v2 transactions
        if not v2_entries and (not stock_entry or not stock_entry.get("ledger_version")):
            continue

        pair_discs = validate_v2_ledger_chain(v2_entries, stock_entry)

        for d in pair_discs:
            # Preserve every detected occurrence in the reconciliation evidence.
            # The reconciliation key is intentionally shared by discrepancies of
            # the same kind/pair and is used only to deduplicate operational alerts.
            d["item_id"] = d.get("item_id") or item_id
            d["department_id"] = d.get("department_id") or department_id
            d["reconciliation_key"] = f"{d['kind']}:{department_id}:{item_id}"
            all_discrepancies.append(d)

    if all_discrepancies:
        await db.reconciliation_log.insert_one({
            "id": _new_id(),
            "checked_at": _now_iso(),
            "schema_version": 2,
            "checked_pair_count": checked_pair_count,
            "discrepancy_count": len(all_discrepancies),
            "discrepancies": all_discrepancies,
        })

        alerted_keys: set[str] = set()
        for d in all_discrepancies:
            # Multiple occurrences remain in the audit log, but only one active
            # alert is created for each discrepancy kind/item/department key.
            if d["reconciliation_key"] in alerted_keys:
                continue
            alerted_keys.add(d["reconciliation_key"])
            existing = await db.alerts.find_one({
                "type": "data_quality",
                "department_id": d["department_id"],
                "item_id": d["item_id"],
                "status": {"$in": ["open", "acknowledged", "in_progress"]},
                "reconciliation_key": d["reconciliation_key"],
            })
            if existing:
                continue
            item = await db.items.find_one({"id": d["item_id"]}, {"_id": 0})
            dept = await db.departments.find_one({"id": d["department_id"]}, {"_id": 0})
            if not item or not dept:
                continue
            await db.alerts.insert_one({
                "id": _new_id(),
                "type": "data_quality",
                "severity": "warning",
                "status": "open",
                "title": f"Ledger chain discrepancy — {item['name_en']}",
                "message": f"In {dept['code']}: {d['kind']} — {d['message']}",
                "department_id": d["department_id"],
                "item_id": d["item_id"],
                "request_id": None,
                "created_at": _now_iso(),
                "escalation_level": 0,
                "escalations": [],
                "escalated_to": None,
                "sla_due_at": None,
                "acknowledged": False,
                "acknowledged_by": None,
                "acknowledged_at": None,
                "in_progress_by": None,
                "in_progress_at": None,
                "resolution_note": None,
                "resolved_by": None,
                "resolved_at": None,
                "closed_at": None,
                "reconciliation_key": d["reconciliation_key"],
                "discrepancy_kind": d["kind"],
            })
        logger.warning("Reconciliation found %d discrepancies across %d pairs",
                       len(all_discrepancies), checked_pair_count)
    return all_discrepancies


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
