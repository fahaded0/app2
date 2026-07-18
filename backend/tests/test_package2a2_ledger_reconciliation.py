"""Package 2A-2: Correct Ledger V2 Reconciliation — test suite.

Tests 01-19: Unit tests on pure validate_v2_ledger_chain.
Tests 20-34: Mock-DB tests for scheduler.reconcile_stock_balances behaviour.
"""
from __future__ import annotations

import sys
import os
import uuid
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure backend directory is on the path so scheduler / models are importable.
# No global sys.modules stubbing — real project dependencies are used.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scheduler import validate_v2_ledger_chain, reconcile_stock_balances


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _se(
    item_id: str,
    department_id: str,
    balance: int,
    ledger_version: int | None,
    entry_id: str,
) -> dict:
    """Build a minimal stock_entry dict."""
    d: dict = {
        "id": entry_id,
        "item_id": item_id,
        "department_id": department_id,
        "balance": balance,
    }
    if ledger_version is not None:
        d["ledger_version"] = ledger_version
    return d


def _txn(
    item_id: str,
    department_id: str,
    entry_id: str,
    sequence_no: int,
    previous_balance: int,
    quantity_change: int,
) -> dict:
    new_balance = previous_balance + quantity_change
    return {
        "item_id": item_id,
        "department_id": department_id,
        "entry_id": entry_id,
        "schema_version": 2,
        "sequence_no": sequence_no,
        "previous_balance": previous_balance,
        "quantity_change": quantity_change,
        "new_balance": new_balance,
        "delta": quantity_change,
    }


def _chain(
    item_id: str,
    department_id: str,
    entry_id: str,
    changes: list[int],
) -> list[dict]:
    """Build a valid chain from a list of quantity_changes."""
    entries = []
    bal = 0
    for i, qc in enumerate(changes, start=1):
        entries.append(_txn(item_id, department_id, entry_id, i, bal, qc))
        bal += qc
    return entries


def _kinds(discs: list[dict]) -> list[str]:
    return [d["kind"] for d in discs]


# ---------------------------------------------------------------------------
# Async iterator helper used by the mock DB
# ---------------------------------------------------------------------------

class _AsyncIter:
    """Minimal async iterator wrapping a plain list."""

    def __init__(self, items: list) -> None:
        self._it = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


# ---------------------------------------------------------------------------
# Mock DB factory
# ---------------------------------------------------------------------------

def _make_db(
    *,
    v2_pairs: list[tuple[str, str]] | None = None,
    stock_entries_with_lv: list[dict] | None = None,
    txns_by_pair: dict | None = None,
    se_by_pair: dict | None = None,
    items: dict | None = None,
    depts: dict | None = None,
    existing_alert: dict | None = None,
):
    """Build a MagicMock db with explicit AsyncMock wiring.

    ``existing_alert``, if provided, is returned by alerts.find_one **only when
    the status query $in filter includes the alert's status** (mimicking MongoDB's
    behaviour for the unresolved-status query used by reconciliation).
    """
    v2_pairs = v2_pairs or []
    stock_entries_with_lv = stock_entries_with_lv or []
    txns_by_pair = txns_by_pair or {}
    se_by_pair = se_by_pair or {}
    items = items or {}
    depts = depts or {}

    db = MagicMock()

    # --- stock_transactions.aggregate → async-iterates v2 pair group docs ---
    v2_agg_result = [
        {"_id": {"item_id": p[0], "department_id": p[1]}} for p in v2_pairs
    ]
    db.stock_transactions.aggregate = MagicMock(
        return_value=_AsyncIter(v2_agg_result)
    )

    # --- stock_entries.find → async-iterates stock entries with ledger_version >= 1 ---
    db.stock_entries.find = MagicMock(
        return_value=_AsyncIter(stock_entries_with_lv)
    )

    # --- stock_transactions.find(query).sort(...).to_list(None) ---
    def _txns_find(query, proj=None):
        iid = query.get("item_id")
        did = query.get("department_id")
        txns = txns_by_pair.get((iid, did), [])
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=txns)
        cursor.sort = MagicMock(return_value=cursor)
        return cursor

    db.stock_transactions.find = MagicMock(side_effect=_txns_find)

    # --- stock_entries.find_one ---
    async def _se_find_one(query, proj=None):
        return se_by_pair.get((query.get("item_id"), query.get("department_id")))

    db.stock_entries.find_one = AsyncMock(side_effect=_se_find_one)

    # --- items.find_one ---
    async def _item_find_one(query, proj=None):
        return items.get(query.get("id"))

    db.items.find_one = AsyncMock(side_effect=_item_find_one)

    # --- departments.find_one ---
    async def _dept_find_one(query, proj=None):
        return depts.get(query.get("id"))

    db.departments.find_one = AsyncMock(side_effect=_dept_find_one)

    # --- alerts.find_one — respects the status $in filter ---
    async def _alert_find_one(query, proj=None):
        if existing_alert is None:
            return None
        status_filter = None
        if isinstance(query.get("status"), dict):
            status_filter = query["status"].get("$in")
        if status_filter is not None:
            if existing_alert.get("status", "open") not in status_filter:
                return None
        return existing_alert

    db.alerts.find_one = AsyncMock(side_effect=_alert_find_one)

    # --- writable collections ---
    db.alerts.insert_one = AsyncMock(return_value=None)
    db.reconciliation_log.insert_one = AsyncMock(return_value=None)

    # --- mutation stubs for read-only verification ---
    for method in ("insert_one", "update_one", "update_many",
                   "replace_one", "delete_one", "delete_many"):
        setattr(db.stock_entries, method, AsyncMock(return_value=None))
        setattr(db.stock_transactions, method, AsyncMock(return_value=None))

    return db


# ---------------------------------------------------------------------------
# Tests 01-19: pure validate_v2_ledger_chain
# ---------------------------------------------------------------------------

class TestValidateV2LedgerChain:

    # 01 — valid single-record chain
    def test_01_valid_single_entry(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 10, 1, eid)
        assert validate_v2_ledger_chain(entries, se) == []

    # 02 — valid multi-record chain
    def test_02_valid_multi_entry(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10, 5, -3])
        se = _se(iid, did, 12, 3, eid)
        assert validate_v2_ledger_chain(entries, se) == []

    # 03 — missing stock entry
    def test_03_missing_stock_entry(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [5])
        discs = validate_v2_ledger_chain(entries, None)
        assert "missing_stock_entry" in _kinds(discs)

    # 04 — missing v2 ledger (stock entry with ledger_version >= 1 but no txns)
    def test_04_missing_v2_ledger(self):
        iid, did, eid = _uid(), _uid(), _uid()
        se = _se(iid, did, 5, 1, eid)
        discs = validate_v2_ledger_chain([], se)
        assert _kinds(discs) == ["missing_v2_ledger"]

    # 05 — invalid first sequence (starts at 2)
    def test_05_invalid_first_sequence(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        entries[0]["sequence_no"] = 2
        se = _se(iid, did, 10, 2, eid)
        assert "invalid_first_sequence" in _kinds(validate_v2_ledger_chain(entries, se))

    # 06 — invalid first previous balance (non-zero)
    def test_06_invalid_first_previous_balance(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        entries[0]["previous_balance"] = 5
        se = _se(iid, did, 15, 1, eid)
        assert "invalid_first_previous_balance" in _kinds(
            validate_v2_ledger_chain(entries, se)
        )

    # 07 — sequence gap
    def test_07_sequence_gap(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10, 5])
        entries[1]["sequence_no"] = 3   # gap: 1 → 3
        se = _se(iid, did, 15, 3, eid)
        assert "sequence_gap" in _kinds(validate_v2_ledger_chain(entries, se))

    # 08 — chain break (previous_balance ≠ prior new_balance)
    def test_08_chain_break(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10, 5])
        entries[1]["previous_balance"] = 99   # should be 10
        se = _se(iid, did, 104, 2, eid)
        assert "chain_break" in _kinds(validate_v2_ledger_chain(entries, se))

    # 09 — arithmetic mismatch (new_balance wrong)
    def test_09_arithmetic_mismatch_bad_new_balance(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        entries[0]["new_balance"] = 999   # corrupted; delta still == quantity_change
        se = _se(iid, did, 999, 1, eid)
        assert "arithmetic_mismatch" in _kinds(validate_v2_ledger_chain(entries, se))

    # 10 — delta differs from quantity_change (new_balance remains correct)
    def test_10_delta_differs_from_quantity_change(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        # new_balance == previous_balance + quantity_change is still true (10 == 0+10)
        # but delta is wrong
        entries[0]["delta"] = 99
        se = _se(iid, did, 10, 1, eid)
        # Must detect independently that delta != quantity_change
        kinds = _kinds(validate_v2_ledger_chain(entries, se))
        assert "arithmetic_mismatch" in kinds

    # 11 — balance mismatch (last new_balance ≠ stock_entry.balance)
    def test_11_balance_mismatch(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)   # wrong balance
        assert "balance_mismatch" in _kinds(validate_v2_ledger_chain(entries, se))

    # 12 — version mismatch (last sequence_no ≠ ledger_version)
    def test_12_version_mismatch(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 10, 99, eid)   # wrong ledger_version
        assert "version_mismatch" in _kinds(validate_v2_ledger_chain(entries, se))

    # 13 — entry_id mismatch
    def test_13_entry_id_mismatch(self):
        iid, did, eid = _uid(), _uid(), _uid()
        wrong_eid = _uid()
        entries = _chain(iid, did, wrong_eid, [10])
        se = _se(iid, did, 10, 1, eid)
        assert "entry_id_mismatch" in _kinds(validate_v2_ledger_chain(entries, se))

    # 14 — legacy stock entry with missing ledger_version → no discrepancy
    def test_14_legacy_stock_entry_missing_ledger_version(self):
        iid, did, eid = _uid(), _uid(), _uid()
        # No ledger_version key at all
        se = {"id": eid, "item_id": iid, "department_id": did, "balance": 5}
        assert validate_v2_ledger_chain([], se) == []

    # 15 — legacy stock entry with ledger_version=0 → no discrepancy
    def test_15_legacy_stock_entry_zero_ledger_version(self):
        iid, did, eid = _uid(), _uid(), _uid()
        se = _se(iid, did, 5, 0, eid)
        assert validate_v2_ledger_chain([], se) == []

    # 16 — missing stock entry does NOT prevent ledger-only chain validation
    def test_16_missing_stock_entry_continues_chain_validation(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        # Corrupt the first sequence_no — ledger-only check should fire
        entries[0]["sequence_no"] = 2
        # No stock entry
        kinds = _kinds(validate_v2_ledger_chain(entries, None))
        assert "missing_stock_entry" in kinds, "missing_stock_entry must be recorded"
        assert "invalid_first_sequence" in kinds, (
            "ledger-only checks must continue when stock_entry is absent"
        )

    # 17 — every discrepancy returned by validate_v2_ledger_chain has a non-empty message
    def test_17_every_discrepancy_has_non_empty_message(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        entries[0]["sequence_no"] = 2   # trigger invalid_first_sequence
        se = _se(iid, did, 99, 2, eid)  # also balance_mismatch and version_mismatch
        discs = validate_v2_ledger_chain(entries, se)
        assert len(discs) > 0
        for d in discs:
            assert "message" in d, f"discrepancy missing 'message': {d}"
            assert d["message"], f"discrepancy has empty 'message': {d}"

    # 18 — both entries and stock_entry absent → empty list (no crash)
    def test_18_both_absent_returns_empty(self):
        assert validate_v2_ledger_chain([], None) == []

    # 19 — malformed v2 entry is reported instead of raising KeyError
    def test_19_missing_sequence_no_reported_as_malformed(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        del entries[0]["sequence_no"]
        se = _se(iid, did, 10, 1, eid)

        discs = validate_v2_ledger_chain(entries, se)

        malformed = [d for d in discs if d["kind"] == "malformed_ledger_entry"]
        assert len(malformed) == 1
        assert "sequence_no" in malformed[0]["missing_fields"]
        assert "sequence_no" in malformed[0]["message"]


# ---------------------------------------------------------------------------
# Tests 20-34: Mock-DB tests for reconcile_stock_balances
# ---------------------------------------------------------------------------

class TestReconcileStockBalancesScheduler:

    # 20 — legacy stock transactions excluded: verify schema_version=2 filter in
    #      both the pair-discovery pipeline and the per-pair find query
    def test_20_legacy_transactions_excluded_by_schema_version_filter(self):
        iid, did, eid = _uid(), _uid(), _uid()
        se = _se(iid, did, 10, 1, eid)
        entries = _chain(iid, did, eid, [10])
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
        )
        asyncio.run(reconcile_stock_balances(db))

        # Verify aggregation pipeline has schema_version=2 match stage
        agg_pipeline = db.stock_transactions.aggregate.call_args[0][0]
        match_filters = [s["$match"] for s in agg_pipeline if "$match" in s]
        assert any(m.get("schema_version") == 2 for m in match_filters), (
            "aggregate pipeline must contain {$match: {schema_version: 2}}"
        )

        # Verify per-pair find query also has schema_version=2
        find_query = db.stock_transactions.find.call_args[0][0]
        assert find_query.get("schema_version") == 2, (
            "per-pair find must filter schema_version=2"
        )

    # 21 — stock entry with missing ledger_version and no v2 txns is skipped
    def test_21_missing_ledger_version_skipped(self):
        iid, did, eid = _uid(), _uid(), _uid()
        # stock entry has no ledger_version key
        se = {"id": eid, "item_id": iid, "department_id": did, "balance": 5}
        db = _make_db(
            v2_pairs=[],
            stock_entries_with_lv=[],   # not included in the find results
            txns_by_pair={(iid, did): []},
            se_by_pair={(iid, did): se},
        )
        result = asyncio.run(reconcile_stock_balances(db))
        assert result == []
        db.reconciliation_log.insert_one.assert_not_called()

    # 22 — stock entry with ledger_version=0 and no v2 txns is skipped
    def test_22_zero_ledger_version_skipped(self):
        iid, did, eid = _uid(), _uid(), _uid()
        se = _se(iid, did, 5, 0, eid)
        db = _make_db(
            v2_pairs=[],
            stock_entries_with_lv=[],   # not surfaced by the ledger_version >= 1 find
            txns_by_pair={(iid, did): []},
            se_by_pair={(iid, did): se},
        )
        result = asyncio.run(reconcile_stock_balances(db))
        assert result == []
        db.reconciliation_log.insert_one.assert_not_called()

    # 23 — reconciliation never calls mutation methods on stock_entries
    def test_23_read_only_stock_entries(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)   # provoke a discrepancy
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
        )
        asyncio.run(reconcile_stock_balances(db))
        for method in ("insert_one", "update_one", "update_many",
                       "replace_one", "delete_one", "delete_many"):
            getattr(db.stock_entries, method).assert_not_called(), (
                f"reconciliation must not call stock_entries.{method}"
            )

    # 24 — reconciliation never calls mutation methods on stock_transactions
    def test_24_read_only_stock_transactions(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
        )
        asyncio.run(reconcile_stock_balances(db))
        for method in ("insert_one", "update_one", "update_many",
                       "replace_one", "delete_one", "delete_many"):
            getattr(db.stock_transactions, method).assert_not_called(), (
                f"reconciliation must not call stock_transactions.{method}"
            )

    # 25 — reconciliation_log is written when discrepancies exist
    def test_25_log_written_when_discrepancies_exist(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)   # balance_mismatch
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Med"}},
            depts={did: {"id": did, "code": "ICU"}},
        )
        asyncio.run(reconcile_stock_balances(db))
        db.reconciliation_log.insert_one.assert_called_once()
        doc = db.reconciliation_log.insert_one.call_args[0][0]
        assert doc["schema_version"] == 2
        assert doc["checked_pair_count"] >= 1
        assert doc["discrepancy_count"] >= 1

    # 26 — alert type is "data_quality"
    def test_26_alert_type_is_data_quality(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
        )
        asyncio.run(reconcile_stock_balances(db))
        db.alerts.insert_one.assert_called()
        alert_doc = db.alerts.insert_one.call_args[0][0]
        assert alert_doc["type"] == "data_quality"
        assert alert_doc["discrepancy_kind"] == "balance_mismatch"
        assert "reconciliation_key" in alert_doc

    # 27 — duplicate unresolved alert (status=open) is not inserted again
    def test_27_duplicate_unresolved_alert_not_created(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)
        existing = {"type": "data_quality", "status": "open"}
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
            existing_alert=existing,
        )
        asyncio.run(reconcile_stock_balances(db))
        db.alerts.insert_one.assert_not_called()

    # 28 — a resolved prior alert does NOT block a new alert
    def test_28_resolved_alert_does_not_block_new_alert(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)
        # status="resolved" is excluded by the $in filter → mock returns None → new alert inserted
        resolved_alert = {"type": "data_quality", "status": "resolved"}
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
            existing_alert=resolved_alert,
        )
        asyncio.run(reconcile_stock_balances(db))
        db.alerts.insert_one.assert_called()

    # 29 — a closed prior alert does NOT block a new alert
    def test_29_closed_alert_does_not_block_new_alert(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)
        closed_alert = {"type": "data_quality", "status": "closed"}
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
            existing_alert=closed_alert,
        )
        asyncio.run(reconcile_stock_balances(db))
        db.alerts.insert_one.assert_called()

    # 30 — the ledger chain query uses to_list(None), not a fixed limit
    def test_30_ledger_query_not_silently_truncated(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 10, 1, eid)

        captured: list = []

        def _capturing_find(query, proj=None):
            cursor = MagicMock()
            async def _to_list(length):
                captured.append(length)
                iid_ = query.get("item_id")
                did_ = query.get("department_id")
                return {(iid, did): entries}.get((iid_, did_), [])
            cursor.to_list = _to_list
            cursor.sort = MagicMock(return_value=cursor)
            return cursor

        db = _make_db(
            v2_pairs=[(iid, did)],
            se_by_pair={(iid, did): se},
        )
        db.stock_transactions.find = MagicMock(side_effect=_capturing_find)

        asyncio.run(reconcile_stock_balances(db))

        assert len(captured) >= 1, "to_list must be called for the pair"
        assert captured[0] is None, (
            f"to_list must be called with None (no fixed limit) to avoid silent "
            f"truncation; got {captured[0]!r}"
        )

    # 31 — stored alert contains the full discrepancy explanation and values
    def test_31_alert_message_preserves_discrepancy_explanation(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        se = _se(iid, did, 99, 1, eid)
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
        )

        result = asyncio.run(reconcile_stock_balances(db))

        discrepancy = next(d for d in result if d["kind"] == "balance_mismatch")
        alert_doc = db.alerts.insert_one.call_args[0][0]
        assert discrepancy["message"] in alert_doc["message"]
        assert "new_balance=10" in alert_doc["message"]
        assert "stock_entry.balance=99" in alert_doc["message"]

    # 32 — duplicate occurrences remain in evidence but create one active alert
    def test_32_same_kind_occurrences_preserved_but_alert_deduplicated(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10, 5])
        entries[0]["delta"] = 91
        entries[1]["delta"] = 92
        se = _se(iid, did, 15, 2, eid)
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
        )

        result = asyncio.run(reconcile_stock_balances(db))

        arithmetic = [d for d in result if d["kind"] == "arithmetic_mismatch"]
        assert len(arithmetic) == 2
        log_doc = db.reconciliation_log.insert_one.call_args[0][0]
        assert log_doc["discrepancy_count"] == 2
        assert len(log_doc["discrepancies"]) == 2
        db.alerts.insert_one.assert_called_once()

    # 33 — malformed entry does not stop reconciliation of another pair
    def test_33_malformed_entry_does_not_abort_reconciliation_round(self):
        iid1, did1, eid1 = _uid(), _uid(), _uid()
        malformed = _chain(iid1, did1, eid1, [10])
        del malformed[0]["sequence_no"]
        se1 = _se(iid1, did1, 10, 1, eid1)

        iid2, did2, eid2 = _uid(), _uid(), _uid()
        valid = _chain(iid2, did2, eid2, [7])
        se2 = _se(iid2, did2, 99, 1, eid2)

        db = _make_db(
            v2_pairs=[(iid1, did1), (iid2, did2)],
            txns_by_pair={(iid1, did1): malformed, (iid2, did2): valid},
            se_by_pair={(iid1, did1): se1, (iid2, did2): se2},
            items={
                iid1: {"id": iid1, "name_en": "Malformed Drug"},
                iid2: {"id": iid2, "name_en": "Other Drug"},
            },
            depts={
                did1: {"id": did1, "code": "ER"},
                did2: {"id": did2, "code": "ICU"},
            },
        )

        result = asyncio.run(reconcile_stock_balances(db))
        kinds = _kinds(result)

        assert "malformed_ledger_entry" in kinds
        assert "balance_mismatch" in kinds
        log_doc = db.reconciliation_log.insert_one.call_args[0][0]
        assert log_doc["checked_pair_count"] == 2

    # 34 — malformed record alert also carries the missing-field explanation
    def test_34_malformed_alert_contains_missing_field(self):
        iid, did, eid = _uid(), _uid(), _uid()
        entries = _chain(iid, did, eid, [10])
        del entries[0]["sequence_no"]
        se = _se(iid, did, 10, 1, eid)
        db = _make_db(
            v2_pairs=[(iid, did)],
            txns_by_pair={(iid, did): entries},
            se_by_pair={(iid, did): se},
            items={iid: {"id": iid, "name_en": "Drug"}},
            depts={did: {"id": did, "code": "ER"}},
        )

        asyncio.run(reconcile_stock_balances(db))

        alert_doc = db.alerts.insert_one.call_args[0][0]
        assert alert_doc["discrepancy_kind"] == "malformed_ledger_entry"
        assert "sequence_no" in alert_doc["message"]
