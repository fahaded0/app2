"""Package 2A-3 — Ledger v2 baseline backfill.

Closes the reconciliation coverage blind spot left by legacy stock_entries that
predate ledger_version tracking: rows whose ledger_version is missing or 0 and
that have no schema_version=2 stock_transactions record for their
(department_id, item_id) pair.

For each such pair, exactly one opening_balance v2 record (sequence_no=1) is
written via the existing ``ledger.ensure_v2_baseline`` and, in the same
transaction, stock_entries.ledger_version is set to 1. No other stock_entry
field, no legacy transaction, and no existing v2 chain is ever touched. Each
pair is committed or rolled back as a single atomic unit — this module never
wraps the whole scan in one database transaction.
"""
from typing import Optional

from pymongo.errors import DuplicateKeyError

import ledger as ledger_mod

BACKFILL_SOURCE = "ledger_v2_backfill"


def baseline_idempotency_key(department_id: str, item_id: str) -> str:
    """Deterministic idempotency key shared with the ledger_v2_cutover baseline path."""
    return f"baseline:{department_id}:{item_id}"


class LedgerVersionConflict(Exception):
    """Raised to abort the transaction when the ledger_version CAS guard misses."""


async def _process_candidate(db, session, *, entry_id: str) -> dict:
    """Runs inside an active transaction for a single candidate stock_entry.

    Re-reads the stock_entry by id (inside the transaction) so the decision is
    made against the current, not the pre-scan, state. Writes at most one
    opening_balance v2 record and the matching ledger_version=1 update — both
    inside the same transaction, so a failure after either write rolls back both.
    """
    se = await db.stock_entries.find_one({"id": entry_id}, session=session)
    if se is None:
        return {"outcome": "conflict_missing_stock_entry",
                "department_id": None, "item_id": None, "entry_id": entry_id}

    department_id = se["department_id"]
    item_id = se["item_id"]
    previous_lv = se.get("ledger_version") or 0
    pair = {"department_id": department_id, "item_id": item_id, "entry_id": entry_id}

    if previous_lv >= 1:
        # Already baselined (or otherwise on a v2 chain) — never write.
        return {"outcome": "already_baselined", **pair}

    existing_v2 = await db.stock_transactions.find_one(
        {"department_id": department_id, "item_id": item_id, "schema_version": 2},
        session=session,
    )
    if existing_v2:
        # ledger_version is 0/missing but a v2 entry already exists for this pair —
        # inconsistent state. Never repair the chain here; just report it.
        return {"outcome": "conflict_existing_v2_with_zero_version", **pair}

    await ledger_mod.ensure_v2_baseline(
        db,
        department_id=department_id,
        item_id=item_id,
        entry_id=entry_id,
        balance=se["balance"],
        user_id=None,
        user_name=None,
        idempotency_key=baseline_idempotency_key(department_id, item_id),
        status=se["status"],
        source=BACKFILL_SOURCE,
        session=session,
    )

    # CAS guard: only flip ledger_version if it still matches what we read.
    version_filter = {"id": entry_id}
    if "ledger_version" in se:
        version_filter["ledger_version"] = se["ledger_version"]
    else:
        version_filter["$or"] = [{"ledger_version": {"$exists": False}}, {"ledger_version": 0}]

    upd = await db.stock_entries.update_one(
        version_filter, {"$set": {"ledger_version": 1}}, session=session,
    )
    if upd.matched_count != 1:
        raise LedgerVersionConflict(
            f"ledger_version CAS guard mismatch for department_id={department_id} "
            f"item_id={item_id} entry_id={entry_id}"
        )

    return {"outcome": "backfilled", **pair}


async def _reclassify_after_abort(db, entry_id: str, exc: Exception) -> dict:
    """Re-read a pair after its transaction aborted and classify it predictably.

    Only reports already_baselined when both a ledger_version>=1 stock_entry
    and a v2 baseline are actually present post-abort — an unexplained
    inconsistency is surfaced as a conflict or failed result, never swallowed.
    """
    se = await db.stock_entries.find_one({"id": entry_id})
    if se is None:
        return {"outcome": "conflict_missing_stock_entry",
                "department_id": None, "item_id": None, "entry_id": entry_id}

    department_id = se["department_id"]
    item_id = se["item_id"]
    lv = se.get("ledger_version") or 0
    pair = {"department_id": department_id, "item_id": item_id, "entry_id": entry_id}

    existing_v2 = await db.stock_transactions.find_one(
        {"department_id": department_id, "item_id": item_id, "schema_version": 2}
    )

    if lv >= 1 and existing_v2:
        return {"outcome": "already_baselined", **pair}
    if existing_v2 and lv == 0:
        return {"outcome": "conflict_existing_v2_with_zero_version", **pair}

    return {"outcome": "failed", "error": str(exc), **pair}


async def backfill_pair(db, client, *, entry_id: str) -> dict:
    """Backfill a single candidate stock_entry (identified by id).

    One transaction boundary per pair: the opening_balance insert and the
    ledger_version=1 update either both commit or both roll back. A
    duplicate-key race (another writer already created the baseline) aborts
    the transaction; the pair is then re-read and classified rather than
    retried blindly or silently skipped.
    """
    async def _txn_callback(session):
        return await _process_candidate(db, session, entry_id=entry_id)

    try:
        async with client.start_session() as session:
            return await session.with_transaction(_txn_callback)
    except (DuplicateKeyError, LedgerVersionConflict) as exc:
        return await _reclassify_after_abort(db, entry_id, exc)
    except Exception as exc:
        # Never swallow an unexplained database error — surface it as a failed
        # pair so the caller sees it, without aborting other pairs' results.
        se = await db.stock_entries.find_one({"id": entry_id})
        return {
            "outcome": "failed",
            "department_id": se.get("department_id") if se else None,
            "item_id": se.get("item_id") if se else None,
            "entry_id": entry_id,
            "error": str(exc),
        }


async def backfill_department_item_pair(db, client, *, department_id: str, item_id: str) -> dict:
    """Backfill one (department_id, item_id) pair directly, by identity rather than scan.

    Never creates a stock_entry for a transaction-only pair: if none exists,
    the pair is reported as conflict_missing_stock_entry.
    """
    se = await db.stock_entries.find_one({"department_id": department_id, "item_id": item_id})
    if se is None:
        return {"outcome": "conflict_missing_stock_entry",
                "department_id": department_id, "item_id": item_id, "entry_id": None}
    return await backfill_pair(db, client, entry_id=se["id"])


async def backfill_v2_baselines(db, client) -> dict:
    """Scan legacy stock_entries and backfill missing Ledger v2 opening baselines.

    Each eligible (department_id, item_id) pair is processed independently in
    its own transaction, so one pair's failure never rolls back another pair's
    already-committed baseline. Returns structured counts and pair identifiers
    for every outcome bucket.
    """
    candidates = await db.stock_entries.find(
        {"$or": [{"ledger_version": {"$exists": False}}, {"ledger_version": 0}]},
        {"_id": 0, "id": 1},
    ).to_list(None)

    buckets: dict[str, list[dict]] = {
        "backfilled": [],
        "already_baselined": [],
        "conflict_existing_v2_with_zero_version": [],
        "conflict_missing_stock_entry": [],
        "failed": [],
    }

    for candidate in candidates:
        result = await backfill_pair(db, client, entry_id=candidate["id"])
        outcome = result.pop("outcome")
        buckets.setdefault(outcome, []).append(result)

    return {
        "scanned": len(candidates),
        "backfilled_count": len(buckets["backfilled"]),
        "already_baselined_count": len(buckets["already_baselined"]),
        "conflict_existing_v2_with_zero_version_count": len(buckets["conflict_existing_v2_with_zero_version"]),
        "conflict_missing_stock_entry_count": len(buckets["conflict_missing_stock_entry"]),
        "failed_count": len(buckets["failed"]),
        "backfilled": buckets["backfilled"],
        "already_baselined": buckets["already_baselined"],
        "conflict_existing_v2_with_zero_version": buckets["conflict_existing_v2_with_zero_version"],
        "conflict_missing_stock_entry": buckets["conflict_missing_stock_entry"],
        "failed": buckets["failed"],
    }
