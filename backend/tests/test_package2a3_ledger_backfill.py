"""Package 2A-3: Ledger v2 Baseline Backfill — test suite.

All tests run against a small in-memory fake MongoDB (see ``_FakeMongo`` below)
that implements real transactional commit/abort semantics — including unique
index enforcement across concurrently open "sessions" — so the atomicity,
rollback, and race-classification behaviour of ``ledger_backfill`` can be
verified without a live MongoDB replica set.

No global sys.modules stubbing. Normal imports throughout. asyncio.run() is
used for sequential scenarios and asyncio.gather() for the true-concurrency
scenario, consistent with the repository's existing isolated unit-test style
(see test_package2a2_ledger_reconciliation.py).

These tests require the project's real runtime dependencies (motor, pymongo,
fastapi, pydantic, python-dotenv, pytest) to be installed — e.g. inside the
project's Docker test environment. They are not runnable in a bare host
environment that lacks those packages.

A second suite further down (search for "REAL DOCKER INTEGRATION TESTS")
exercises the live HTTP endpoint against the disposable MongoDB replica set
used by the Package 2A-1 / 2A-2 integration suites: real transactions, real
unique indexes, real concurrent sessions, and real authorization/audit
behaviour. Those tests are marked ``@pytest.mark.integration`` and are
auto-skipped by tests/conftest.py unless REACT_APP_BACKEND_URL is configured
(i.e. under docker-compose.test.yml).
"""
from __future__ import annotations

import asyncio
import copy
import sys
import os
import uuid
from types import SimpleNamespace

import pytest
import requests
from pymongo.errors import DuplicateKeyError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ledger as ledger_mod
import ledger_backfill
import scheduler as scheduler_mod


def _uid() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# In-memory fake MongoDB with real transaction (commit/abort) semantics
# ---------------------------------------------------------------------------

def _match(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
            continue
        if isinstance(cond, dict) and "$exists" in cond:
            if (key in doc) != cond["$exists"]:
                return False
            continue
        if isinstance(cond, dict) and "$gte" in cond:
            if not ((doc.get(key) or 0) >= cond["$gte"]):
                return False
            continue
        if doc.get(key) != cond:
            return False
    return True


class _FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, *a, **kw):
        return self

    async def to_list(self, n):
        return list(self._docs) if n is None else list(self._docs[:n])


class _FakeSession:
    def __init__(self, mongo: "_FakeMongo"):
        self.mongo = mongo
        self.id = _uid()
        self.staged: dict | None = None
        self.own_inserts: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def with_transaction(self, callback):
        self.staged = {name: [dict(d) for d in docs] for name, docs in self.mongo.committed.items()}
        self.own_inserts = {name: [] for name in self.mongo.committed}
        self.mongo.active_sessions[self.id] = self
        try:
            result = await callback(self)
        except Exception:
            self.mongo.active_sessions.pop(self.id, None)
            self.staged = None
            raise
        else:
            self.mongo.committed = self.staged
            self.mongo.active_sessions.pop(self.id, None)
            self.staged = None
            return result


class _FakeClient:
    def __init__(self, mongo: "_FakeMongo"):
        self.mongo = mongo

    async def start_session(self):
        return _FakeSession(self.mongo)


class _FakeCollection:
    """Unique indexes mirror the real ones created at server startup:
    stock_transactions.idempotency_key (partial: string type) and
    (department_id, item_id, sequence_no) (partial: schema_version=2).
    """

    UNIQUE_INDEXES = {
        "stock_transactions": (
            {"fields": ("idempotency_key",), "partial": lambda d: isinstance(d.get("idempotency_key"), str)},
            {"fields": ("department_id", "item_id", "sequence_no"), "partial": lambda d: d.get("schema_version") == 2},
        ),
    }

    def __init__(self, mongo: "_FakeMongo", name: str):
        self.mongo = mongo
        self.name = name

    def _view(self, session) -> list[dict]:
        if session is not None and session.staged is not None:
            return session.staged[self.name]
        return self.mongo.committed[self.name]

    def _violates_unique(self, doc: dict, exclude_session_id) -> bool:
        for idx in self.UNIQUE_INDEXES.get(self.name, ()):
            if not idx["partial"](doc):
                continue
            fields = idx["fields"]
            key = tuple(doc.get(f) for f in fields)
            for existing in self.mongo.committed[self.name]:
                if idx["partial"](existing) and tuple(existing.get(f) for f in fields) == key:
                    return True
            for sid, sess in self.mongo.active_sessions.items():
                if sid == exclude_session_id:
                    continue
                for existing in sess.own_inserts.get(self.name, []):
                    if idx["partial"](existing) and tuple(existing.get(f) for f in fields) == key:
                        return True
        return False

    async def find_one(self, query=None, projection=None, session=None):
        await asyncio.sleep(0)
        query = query or {}
        result = None
        for d in self._view(session):
            if _match(d, query):
                result = dict(d)
                break
        self.mongo.fire_hook(self.name, "find_one")
        return result

    def find(self, query=None, projection=None, session=None):
        query = query or {}
        matched = [dict(d) for d in self._view(session) if _match(d, query)]
        return _FakeCursor(matched)

    async def insert_one(self, doc, session=None):
        await asyncio.sleep(0)
        exclude = session.id if session is not None else None
        if self._violates_unique(doc, exclude):
            raise DuplicateKeyError(f"E11000 duplicate key error collection {self.name}")
        stored = dict(doc)
        self._view(session).append(stored)
        if session is not None:
            session.own_inserts[self.name].append(stored)
        self.mongo.fire_hook(self.name, "insert_one")
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, filt, update, session=None):
        await asyncio.sleep(0)
        matched = 0
        for d in self._view(session):
            if _match(d, filt):
                for k, v in update.get("$set", {}).items():
                    d[k] = v
                matched = 1
                break
        self.mongo.fire_hook(self.name, "update_one")
        return SimpleNamespace(matched_count=matched, modified_count=matched)


class _FakeMongo:
    COLLECTIONS = ("stock_entries", "stock_transactions", "alerts", "reconciliation_log", "audit_logs")

    def __init__(self):
        self.committed: dict[str, list[dict]] = {name: [] for name in self.COLLECTIONS}
        self.active_sessions: dict[str, _FakeSession] = {}
        self._hooks: dict[tuple, callable] = {}

    def register_hook(self, collection: str, method: str, fn) -> None:
        """Fires once, immediately after the given collection/method op applies
        its effect (append/update) but before it returns — used to simulate a
        failure occurring right after a specific write within a transaction,
        or a concurrent write landing right after a read."""
        self._hooks[(collection, method)] = fn

    def fire_hook(self, collection: str, method: str) -> None:
        hook = self._hooks.pop((collection, method), None)
        if hook is not None:
            hook()


class _FakeDB:
    def __init__(self, mongo: _FakeMongo):
        for name in mongo.COLLECTIONS:
            setattr(self, name, _FakeCollection(mongo, name))


def _setup():
    mongo = _FakeMongo()
    return mongo, _FakeDB(mongo), _FakeClient(mongo)


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------

def _mk_stock_entry(*, department_id, item_id, balance, status="available",
                     ledger_version=None, entry_id=None, **extra) -> dict:
    doc = {
        "id": entry_id or _uid(),
        "department_id": department_id,
        "item_id": item_id,
        "balance": balance,
        "status": status,
        "last_updated_by": "u1",
        "last_updated_by_name": "Legacy User",
        "last_updated_at": "2020-01-01T00:00:00Z",
        "shortage_start": None,
        "notes": "legacy seed data",
    }
    if ledger_version is not None:
        doc["ledger_version"] = ledger_version
    doc.update(extra)
    return doc


def _mk_v2_entry(*, department_id, item_id, entry_id, sequence_no=1,
                  previous_balance=0, quantity_change=0, source="ledger_v2_cutover",
                  idempotency_key=None, status="available") -> dict:
    new_balance = previous_balance + quantity_change
    return {
        "id": _uid(),
        "schema_version": 2,
        "department_id": department_id,
        "item_id": item_id,
        "entry_type": "opening_balance",
        "sequence_no": sequence_no,
        "previous_balance": previous_balance,
        "quantity_change": quantity_change,
        "delta": quantity_change,
        "new_balance": new_balance,
        "status": status,
        "user_id": None,
        "user_name": None,
        "actor_type": "system",
        "source": source,
        "idempotency_key": idempotency_key or f"baseline:{department_id}:{item_id}",
        "entry_id": entry_id,
        "reference_no": None,
        "created_at": "2020-01-01T00:00:00Z",
    }


def _mk_legacy_txn(*, department_id, item_id, entry_id, balance) -> dict:
    """Legacy (pre-v2) stock_transactions doc — no schema_version key at all."""
    return {
        "id": _uid(),
        "department_id": department_id,
        "item_id": item_id,
        "entry_id": entry_id,
        "type": "adjustment",
        "balance": balance,
        "created_at": "2019-01-01T00:00:00Z",
    }


def _find_committed_stock_entry(mongo, entry_id):
    return next((s for s in mongo.committed["stock_entries"] if s["id"] == entry_id), None)


def _find_committed_v2_entries(mongo, department_id, item_id):
    return [t for t in mongo.committed["stock_transactions"]
            if t.get("schema_version") == 2 and t["department_id"] == department_id and t["item_id"] == item_id]


# ---------------------------------------------------------------------------
# 01-09: Core backfill behaviour for a single pair
# ---------------------------------------------------------------------------

class TestCoreBackfill:

    def test_01_missing_ledger_version_creates_exactly_one_baseline(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=42, entry_id=eid)  # no ledger_version key
        mongo.committed["stock_entries"].append(se)

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "backfilled"
        v2 = _find_committed_v2_entries(mongo, dep, itm)
        assert len(v2) == 1
        assert _find_committed_stock_entry(mongo, eid)["ledger_version"] == 1

    def test_02_zero_ledger_version_creates_exactly_one_baseline(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=15, ledger_version=0, entry_id=eid)
        mongo.committed["stock_entries"].append(se)

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "backfilled"
        assert len(_find_committed_v2_entries(mongo, dep, itm)) == 1
        assert _find_committed_stock_entry(mongo, eid)["ledger_version"] == 1

    def test_03_balance_zero_is_a_valid_baseline(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=0, status="zero_level", entry_id=eid)
        mongo.committed["stock_entries"].append(se)

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "backfilled"
        v2 = _find_committed_v2_entries(mongo, dep, itm)
        assert len(v2) == 1
        assert v2[0]["previous_balance"] == 0
        assert v2[0]["quantity_change"] == 0
        assert v2[0]["new_balance"] == 0

    def test_04_opening_entry_has_all_required_fields(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=77, status="critical_level", entry_id=eid)
        mongo.committed["stock_entries"].append(se)

        asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        v2 = _find_committed_v2_entries(mongo, dep, itm)
        assert len(v2) == 1
        entry = v2[0]
        assert entry["schema_version"] == 2
        assert entry["entry_type"] == "opening_balance"
        assert entry["sequence_no"] == 1
        assert entry["previous_balance"] == 0
        assert entry["quantity_change"] == 77
        assert entry["delta"] == 77
        assert entry["new_balance"] == 77
        assert entry["source"] == "ledger_v2_backfill"
        assert entry["idempotency_key"] == f"baseline:{dep}:{itm}"
        assert entry["entry_id"] == eid
        # status is preserved from the stock_entry, not recomputed
        assert entry["status"] == "critical_level"

    def test_05_ledger_version_flips_to_1_in_the_same_transaction(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=5, entry_id=eid)
        mongo.committed["stock_entries"].append(se)

        asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert _find_committed_stock_entry(mongo, eid)["ledger_version"] == 1

    def test_06_no_unrelated_stock_entry_field_is_changed(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=88, status="available", entry_id=eid,
                              notes="do not touch me", last_updated_by="original-user")
        mongo.committed["stock_entries"].append(copy.deepcopy(se))

        asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        after = _find_committed_stock_entry(mongo, eid)
        before_minus_lv = {k: v for k, v in se.items()}
        after_minus_lv = {k: v for k, v in after.items() if k != "ledger_version"}
        assert before_minus_lv == after_minus_lv
        assert after["balance"] == 88
        assert after["status"] == "available"
        assert after["notes"] == "do not touch me"
        assert after["last_updated_by"] == "original-user"

    def test_07_existing_ledger_version_gte_1_is_not_modified(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=10, ledger_version=3, entry_id=eid)
        mongo.committed["stock_entries"].append(copy.deepcopy(se))

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "already_baselined"
        assert _find_committed_stock_entry(mongo, eid) == se
        assert _find_committed_v2_entries(mongo, dep, itm) == []

    def test_08_existing_v2_with_zero_ledger_version_is_a_conflict_not_modified(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=10, ledger_version=0, entry_id=eid)
        v2 = _mk_v2_entry(department_id=dep, item_id=itm, entry_id=eid)
        mongo.committed["stock_entries"].append(copy.deepcopy(se))
        mongo.committed["stock_transactions"].append(copy.deepcopy(v2))

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "conflict_existing_v2_with_zero_version"
        assert _find_committed_stock_entry(mongo, eid) == se
        assert mongo.committed["stock_transactions"] == [v2]

    def test_09_existing_legacy_transactions_do_not_block_a_valid_baseline(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        se = _mk_stock_entry(department_id=dep, item_id=itm, balance=30, entry_id=eid)
        legacy = _mk_legacy_txn(department_id=dep, item_id=itm, entry_id=eid, balance=30)
        mongo.committed["stock_entries"].append(se)
        mongo.committed["stock_transactions"].append(legacy)

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "backfilled"
        assert len(_find_committed_v2_entries(mongo, dep, itm)) == 1
        # legacy transaction is untouched
        assert legacy in mongo.committed["stock_transactions"]


# ---------------------------------------------------------------------------
# 10-12: Scan-level behaviour, idempotence, and transaction-only pairs
# ---------------------------------------------------------------------------

class TestScanAndIdempotence:

    def test_10_second_sequential_scan_is_a_no_op(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=20, entry_id=eid))

        first = asyncio.run(ledger_backfill.backfill_v2_baselines(db, client))
        assert first["scanned"] == 1
        assert first["backfilled_count"] == 1

        second = asyncio.run(ledger_backfill.backfill_v2_baselines(db, client))
        assert second["scanned"] == 0
        assert second["backfilled_count"] == 0
        assert len(_find_committed_v2_entries(mongo, dep, itm)) == 1

    def test_11_transaction_only_pair_reports_conflict_missing_stock_entry(self):
        """A pair with v2 transactions but no stock_entry is never turned into
        a new stock_entry by the backfill."""
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_transactions"].append(
            _mk_v2_entry(department_id=dep, item_id=itm, entry_id=eid)
        )

        result = asyncio.run(
            ledger_backfill.backfill_department_item_pair(db, client, department_id=dep, item_id=itm)
        )

        assert result["outcome"] == "conflict_missing_stock_entry"
        assert mongo.committed["stock_entries"] == []

    def test_12_scan_never_scans_pairs_with_ledger_version_gte_1(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(
            _mk_stock_entry(department_id=dep, item_id=itm, balance=5, ledger_version=1, entry_id=eid)
        )
        result = asyncio.run(ledger_backfill.backfill_v2_baselines(db, client))
        assert result["scanned"] == 0


# ---------------------------------------------------------------------------
# 13-15: Atomicity and rollback
# ---------------------------------------------------------------------------

class TestAtomicityAndRollback:

    def test_13_failure_after_baseline_insertion_rolls_back_both_writes(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=9, entry_id=eid))

        def _boom():
            raise RuntimeError("simulated failure right after baseline insertion")

        mongo.register_hook("stock_transactions", "insert_one", _boom)

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "failed"
        assert "simulated failure" in result["error"]
        assert _find_committed_v2_entries(mongo, dep, itm) == []
        se_after = _find_committed_stock_entry(mongo, eid)
        assert se_after.get("ledger_version", 0) in (0, None)

    def test_14_failure_after_ledger_version_update_rolls_back_both_writes(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=9, entry_id=eid))

        def _boom():
            raise RuntimeError("simulated failure right after ledger_version update")

        mongo.register_hook("stock_entries", "update_one", _boom)

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "failed"
        assert "simulated failure" in result["error"]
        # both the insert and the update must have been rolled back together
        assert _find_committed_v2_entries(mongo, dep, itm) == []
        se_after = _find_committed_stock_entry(mongo, eid)
        assert se_after.get("ledger_version", 0) in (0, None)

    def test_15_one_pair_failure_does_not_undo_other_successful_pairs(self):
        mongo, db, client = _setup()
        dep_a, itm_a, eid_a = _uid(), _uid(), _uid()
        dep_b, itm_b, eid_b = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep_a, item_id=itm_a, balance=1, entry_id=eid_a))
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep_b, item_id=itm_b, balance=2, entry_id=eid_b))

        def _boom():
            raise RuntimeError("pair A explodes")

        mongo.register_hook("stock_transactions", "insert_one", _boom)

        result = asyncio.run(ledger_backfill.backfill_v2_baselines(db, client))

        assert result["scanned"] == 2
        assert result["failed_count"] == 1
        assert result["backfilled_count"] == 1
        assert any(p["entry_id"] == eid_a for p in result["failed"])
        assert any(p["entry_id"] == eid_b for p in result["backfilled"])
        assert _find_committed_stock_entry(mongo, eid_b)["ledger_version"] == 1
        assert _find_committed_stock_entry(mongo, eid_a).get("ledger_version", 0) in (0, None)


# ---------------------------------------------------------------------------
# 16-18: Concurrency and duplicate-key race classification
# ---------------------------------------------------------------------------

class TestConcurrency:

    def test_16_concurrent_executions_cannot_create_duplicate_baselines(self):
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=50, entry_id=eid))

        async def _run():
            return await asyncio.gather(
                ledger_backfill.backfill_pair(db, client, entry_id=eid),
                ledger_backfill.backfill_pair(db, client, entry_id=eid),
            )

        r1, r2 = asyncio.run(_run())

        outcomes = [r1["outcome"], r2["outcome"]]
        assert outcomes.count("backfilled") == 1, f"expected exactly one backfilled outcome, got {outcomes}"
        other = outcomes[0] if outcomes[1] == "backfilled" else outcomes[1]
        assert other in ("already_baselined", "conflict_existing_v2_with_zero_version", "failed")
        # exactly one baseline was ever committed, and no unhandled exception escaped
        assert len(_find_committed_v2_entries(mongo, dep, itm)) == 1
        assert _find_committed_stock_entry(mongo, eid)["ledger_version"] == 1

    def test_17_duplicate_key_race_is_reread_and_classified_as_already_baselined(self):
        """Simulates: our pre-insert check found nothing, but a concurrent writer
        fully committed the same baseline (v2 entry + ledger_version=1) right
        after our check — the DuplicateKeyError must be re-read and classified
        as already_baselined, not treated as an unexplained failure."""
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=12, entry_id=eid))

        def _concurrent_writer_commits():
            mongo.committed["stock_transactions"].append(
                _mk_v2_entry(department_id=dep, item_id=itm, entry_id=eid,
                             previous_balance=0, quantity_change=12,
                             source="ledger_v2_backfill")
            )
            se = _find_committed_stock_entry(mongo, eid)
            se["ledger_version"] = 1

        # Fires after our own existing_v2 pre-check (inside the transaction)
        # returns None, simulating the race window that the unique index closes.
        mongo.register_hook("stock_transactions", "find_one", _concurrent_writer_commits)

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        assert result["outcome"] == "already_baselined"
        assert len(_find_committed_v2_entries(mongo, dep, itm)) == 1
        assert _find_committed_stock_entry(mongo, eid)["ledger_version"] == 1

    def test_18_duplicate_key_race_with_inconsistent_state_is_reported_not_swallowed(self):
        """If the post-abort re-read finds neither a clean already_baselined
        state nor a clean existing-v2-conflict state, the race must be
        surfaced (conflict/failed), never silently classified as success."""
        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=12, entry_id=eid))

        def _raise_duplicate():
            raise DuplicateKeyError("E11000 duplicate key error collection stock_transactions")

        mongo.register_hook("stock_transactions", "insert_one", _raise_duplicate)

        result = asyncio.run(ledger_backfill.backfill_pair(db, client, entry_id=eid))

        # No v2 entry and ledger_version still 0/missing after the abort — this
        # is neither already_baselined nor a clean existing-v2 conflict.
        assert result["outcome"] == "failed"
        assert _find_committed_v2_entries(mongo, dep, itm) == []
        assert _find_committed_stock_entry(mongo, eid).get("ledger_version", 0) in (0, None)


# ---------------------------------------------------------------------------
# 19: Full mixed-dataset read-only guarantees
# ---------------------------------------------------------------------------

class TestReadOnlyGuarantees:

    def test_19_full_scan_touches_only_the_eligible_pair(self):
        mongo, db, client = _setup()

        # Pair A: eligible candidate
        dep_a, itm_a, eid_a = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep_a, item_id=itm_a, balance=10, entry_id=eid_a))

        # Pair B: already on a valid v2 chain — must be left untouched
        dep_b, itm_b, eid_b = _uid(), _uid(), _uid()
        se_b = _mk_stock_entry(department_id=dep_b, item_id=itm_b, balance=20, ledger_version=1, entry_id=eid_b)
        v2_b = _mk_v2_entry(department_id=dep_b, item_id=itm_b, entry_id=eid_b, quantity_change=20)
        mongo.committed["stock_entries"].append(copy.deepcopy(se_b))
        mongo.committed["stock_transactions"].append(copy.deepcopy(v2_b))

        # Pair C: legacy stock_entry + legacy transaction, no v2 — must remain untouched
        # except for the one expected backfill write.
        dep_c, itm_c, eid_c = _uid(), _uid(), _uid()
        se_c = _mk_stock_entry(department_id=dep_c, item_id=itm_c, balance=5, entry_id=eid_c)
        legacy_c = _mk_legacy_txn(department_id=dep_c, item_id=itm_c, entry_id=eid_c, balance=5)
        mongo.committed["stock_entries"].append(copy.deepcopy(se_c))
        mongo.committed["stock_transactions"].append(copy.deepcopy(legacy_c))

        mongo.committed["alerts"].append({"id": "keep-me", "type": "zero_level"})
        mongo.committed["reconciliation_log"].append({"id": "keep-me-too"})

        asyncio.run(ledger_backfill.backfill_v2_baselines(db, client))

        # Pair A backfilled
        assert _find_committed_stock_entry(mongo, eid_a)["ledger_version"] == 1
        assert len(_find_committed_v2_entries(mongo, dep_a, itm_a)) == 1

        # Pair B completely untouched
        assert _find_committed_stock_entry(mongo, eid_b) == se_b
        assert _find_committed_v2_entries(mongo, dep_b, itm_b) == [v2_b]

        # Pair C: backfilled, legacy transaction untouched
        se_c_after = _find_committed_stock_entry(mongo, eid_c)
        assert se_c_after["balance"] == 5
        assert se_c_after["status"] == "available"
        assert se_c_after["ledger_version"] == 1
        assert legacy_c in mongo.committed["stock_transactions"]

        # No alert or reconciliation-log writes
        assert mongo.committed["alerts"] == [{"id": "keep-me", "type": "zero_level"}]
        assert mongo.committed["reconciliation_log"] == [{"id": "keep-me-too"}]


# ---------------------------------------------------------------------------
# 20-23: Admin endpoint — authorization, audit, response shape
# ---------------------------------------------------------------------------

class TestAdminEndpoint:

    def _fake_request(self):
        return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})

    def test_20_unauthorized_role_receives_403(self):
        import auth
        from fastapi import HTTPException

        checker = auth.require_roles("super_admin", "digital_health_manager")

        async def _call():
            return await checker(user={"id": "u1", "role": "auditor"})

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_call())
        assert exc_info.value.status_code == 403

    def test_21_authorized_invocation_writes_exactly_one_audit_record(self, monkeypatch):
        import server

        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=33, entry_id=eid))

        monkeypatch.setattr(server, "db", db)
        monkeypatch.setattr(server, "client", client)

        admin_user = {"id": "admin-1", "email": "admin@medstock.sa", "role": "super_admin"}

        async def _call():
            return await server.admin_backfill_v2_baselines(request=self._fake_request(), user=admin_user)

        summary = asyncio.run(_call())

        assert summary["scanned"] == 1
        assert summary["backfilled_count"] == 1

        audits = [a for a in mongo.committed["audit_logs"] if a["action"] == "backfill_v2_baselines"]
        assert len(audits) == 1
        assert audits[0]["new_value"]["backfilled_count"] == 1
        assert audits[0]["new_value"]["scanned"] == 1

    def test_22_endpoint_response_has_summary_counts_and_no_secrets(self, monkeypatch):
        import server

        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=8, entry_id=eid))

        monkeypatch.setattr(server, "db", db)
        monkeypatch.setattr(server, "client", client)
        admin_user = {"id": "admin-2", "email": "admin2@medstock.sa", "role": "digital_health_manager"}

        async def _call():
            return await server.admin_backfill_v2_baselines(request=self._fake_request(), user=admin_user)

        summary = asyncio.run(_call())

        for key in ("scanned", "backfilled_count", "already_baselined_count",
                    "conflict_existing_v2_with_zero_version_count",
                    "conflict_missing_stock_entry_count", "failed_count"):
            assert key in summary

        blob = str(summary).lower()
        for forbidden in ("password", "secret", "token", "jwt"):
            assert forbidden not in blob

    def test_23_endpoint_invocation_writes_no_alert_or_reconciliation_log(self, monkeypatch):
        import server

        mongo, db, client = _setup()
        dep, itm, eid = _uid(), _uid(), _uid()
        mongo.committed["stock_entries"].append(_mk_stock_entry(department_id=dep, item_id=itm, balance=8, entry_id=eid))

        monkeypatch.setattr(server, "db", db)
        monkeypatch.setattr(server, "client", client)
        admin_user = {"id": "admin-3", "email": "admin3@medstock.sa", "role": "super_admin"}

        async def _call():
            return await server.admin_backfill_v2_baselines(request=self._fake_request(), user=admin_user)

        asyncio.run(_call())

        assert mongo.committed["alerts"] == []
        assert mongo.committed["reconciliation_log"] == []


# ---------------------------------------------------------------------------
# 24: Regression smoke — Package 2A-1 / 2A-2 behaviour is unchanged
# ---------------------------------------------------------------------------

class TestExistingBehaviourUnchanged:

    def test_24_ledger_build_entry_and_ensure_v2_baseline_unaffected(self):
        # Package 2A-1 pure-logic entry point still works exactly as before.
        doc = ledger_mod.build_ledger_entry(
            department_id="d1", item_id="i1", entry_type="adjustment",
            sequence_no=2, previous_balance=10, quantity_change=-5, new_balance=5,
            user_id="u1", user_name="User", source="test",
            idempotency_key="regress-1", status="available", entry_id="e1",
        )
        assert doc["schema_version"] == 2
        assert doc["delta"] == -5

        # ensure_v2_baseline still writes exactly one opening_balance record.
        mongo, db, client = _setup()

        async def _run():
            async with await client.start_session() as session:
                async def _cb(s):
                    return await ledger_mod.ensure_v2_baseline(
                        db, department_id="d1", item_id="i1", entry_id="e1",
                        balance=99, user_id=None, user_name=None,
                        idempotency_key="regress-2", status="available", session=s,
                    )
                return await session.with_transaction(_cb)

        created = asyncio.run(_run())
        assert created is True
        assert len(_find_committed_v2_entries(mongo, "d1", "i1")) == 1

    def test_25_scheduler_validate_v2_ledger_chain_unaffected(self):
        # Package 2A-2 pure-logic validator still works exactly as before.
        assert scheduler_mod.validate_v2_ledger_chain([], None) == []
        se = {"id": "e1", "item_id": "i1", "department_id": "d1", "balance": 5}
        assert scheduler_mod.validate_v2_ledger_chain([], se) == []


# ===========================================================================
# REAL DOCKER INTEGRATION TESTS (Package 2A-3 acceptance gap)
# ===========================================================================
#
# The suites above use an in-memory fake MongoDB. That is sufficient for pure
# unit coverage of ledger_backfill's decision logic, but it cannot exercise:
#   - real MongoDB multi-document transactions and commit/abort semantics,
#   - the real unique indexes created at server startup,
#   - real concurrent sessions racing against each other, or
#   - the live HTTP endpoint (auth, audit, response shape).
#
# The tests below do exactly that, against the disposable MongoDB replica set
# and live backend used by test_package2a1_ledger_writes.py / backend_test.py
# (docker-compose.test.yml). They are marked ``@pytest.mark.integration`` and
# are auto-skipped by tests/conftest.py when REACT_APP_BACKEND_URL is not set,
# so they do not run — and are not claimed to run — on a bare host.
#
# No global sys.modules stubbing. Every stock_entries/stock_transactions
# fixture created here is scoped to a fresh uuid4 item/department pair and is
# deleted in a `finally` block; nothing depends on fixed seed counts (audit
# and scan assertions use before/after deltas, not absolute totals).

_BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").strip().rstrip("/")
_API = f"{_BASE_URL}/api"

_ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@medstock.sa")
_ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@12345")
# Seeded by backend/seed.py — a role outside {super_admin, digital_health_manager}.
_AUDITOR_EMAIL = os.environ.get("TEST_AUDITOR_EMAIL", "auditor@medstock.sa")
_AUDITOR_PASSWORD = os.environ.get("TEST_AUDITOR_PASSWORD", "Audit@12345")

_MONGO_URL = os.environ.get("TEST_MONGO_URL", "mongodb://mongo:27017/?replicaSet=rs0")
_MONGO_DB_NAME = os.environ.get("TEST_DB_NAME", "medstock_test")

_BACKFILL_ENDPOINT = f"{_API}/admin/backfill-v2-baselines"


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(email: str, password: str):
    return requests.post(f"{_API}/auth/login", json={"email": email, "password": password}, timeout=15)


@pytest.fixture(scope="module")
def admin_token():
    r = _login(_ADMIN_EMAIL, _ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auditor_token():
    r = _login(_AUDITOR_EMAIL, _AUDITOR_PASSWORD)
    assert r.status_code == 200, f"auditor login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _mongo_client():
    # Imported lazily so module import does not require motor on a bare host.
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(_MONGO_URL, serverSelectionTimeoutMS=5000)


async def _direct_find_one(collection: str, query: dict, sort=None):
    c = _mongo_client()
    try:
        return await c[_MONGO_DB_NAME][collection].find_one(query, {"_id": 0}, sort=sort)
    finally:
        c.close()


async def _direct_find(collection: str, query: dict, limit: int = 100) -> list:
    c = _mongo_client()
    try:
        return await c[_MONGO_DB_NAME][collection].find(query, {"_id": 0}).to_list(limit)
    finally:
        c.close()


async def _direct_count(collection: str, query: dict) -> int:
    c = _mongo_client()
    try:
        return await c[_MONGO_DB_NAME][collection].count_documents(query)
    finally:
        c.close()


async def _direct_insert_legacy_stock_entry(*, department_id: str, item_id: str, balance: int,
                                             status: str, ledger_version=None) -> str:
    """Insert a stock_entries doc directly, bypassing the API entirely.

    The live API always sets ledger_version>=1 on every write path, so a
    genuine pre-Ledger-v2 legacy row can only be modeled by writing straight
    to the disposable test database, exactly as a real historical migration
    gap would look.
    """
    entry_id = _uid()
    doc = {
        "id": entry_id,
        "department_id": department_id,
        "item_id": item_id,
        "balance": balance,
        "status": status,
        "last_updated_by": None,
        "last_updated_by_name": "Legacy Import",
        "last_updated_at": "2020-01-01T00:00:00Z",
        "shortage_start": None,
        "notes": "Package 2A-3 real integration test seed",
    }
    if ledger_version is not None:
        doc["ledger_version"] = ledger_version
    c = _mongo_client()
    try:
        await c[_MONGO_DB_NAME].stock_entries.insert_one(doc)
    finally:
        c.close()
    return entry_id


async def _direct_insert_v2_entry(*, department_id: str, item_id: str, entry_id: str, balance: int) -> None:
    c = _mongo_client()
    try:
        await c[_MONGO_DB_NAME].stock_transactions.insert_one({
            "id": _uid(),
            "schema_version": 2,
            "department_id": department_id,
            "item_id": item_id,
            "entry_type": "opening_balance",
            "sequence_no": 1,
            "previous_balance": 0,
            "quantity_change": balance,
            "delta": balance,
            "new_balance": balance,
            "status": "available",
            "user_id": None,
            "user_name": None,
            "actor_type": "system",
            "source": "ledger_v2_cutover",
            "idempotency_key": f"baseline:{department_id}:{item_id}",
            "entry_id": entry_id,
            "reference_no": None,
            "created_at": "2020-01-01T00:00:00Z",
        })
    finally:
        c.close()


async def _direct_cleanup(*, department_id: str, item_id: str, entry_id: str) -> None:
    """Delete only the records this test created (scoped by the unique
    item_id/department_id pair and the specific stock_entry id)."""
    c = _mongo_client()
    try:
        db = c[_MONGO_DB_NAME]
        await db.stock_entries.delete_many({"id": entry_id})
        await db.stock_transactions.delete_many({"department_id": department_id, "item_id": item_id})
    finally:
        c.close()


def _create_item_and_department(token: str) -> dict:
    """Create a uniquely-coded item via the live API and fetch the ER department."""
    code = f"P2A3_{_uid()[:10].upper()}"
    r = requests.post(f"{_API}/items", headers=_bearer(token), json={
        "internal_code": code,
        "name_ar": f"عنصر {code}",
        "name_en": f"Package 2A-3 item {code}",
        "category": "Other",
        "unit": "PCS",
        "min_level": 10,
        "critical_threshold": 5,
        "max_level": 100,
    }, timeout=15)
    assert r.status_code == 200, f"create item failed: {r.status_code} {r.text}"
    item = r.json()

    depts_r = requests.get(f"{_API}/departments", headers=_bearer(token), timeout=15)
    assert depts_r.status_code == 200, f"list departments failed: {depts_r.status_code} {depts_r.text}"
    dept = next(d for d in depts_r.json() if d["code"] == "ER")
    return {"item": item, "dept": dept}


# ---------------------------------------------------------------------------
# Real test 1 — legacy-pair backfill via the live endpoint
# ---------------------------------------------------------------------------

class TestRealLegacyPairBackfill:
    pytestmark = pytest.mark.integration

    def test_real_backfill_creates_valid_v2_baseline(self, admin_token):
        ctx = _create_item_and_department(admin_token)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        balance = 37
        status = "available"

        entry_id = asyncio.run(_direct_insert_legacy_stock_entry(
            department_id=dept_id, item_id=item_id, balance=balance, status=status,
        ))
        try:
            r = requests.post(_BACKFILL_ENDPOINT, headers=_bearer(admin_token), timeout=30)
            assert r.status_code == 200, f"backfill endpoint failed: {r.status_code} {r.text}"

            v2_entries = asyncio.run(_direct_find(
                "stock_transactions",
                {"department_id": dept_id, "item_id": item_id, "schema_version": 2},
            ))
            assert len(v2_entries) == 1, f"expected exactly 1 v2 baseline, got {v2_entries}"
            entry = v2_entries[0]
            assert entry["entry_type"] == "opening_balance"
            assert entry["sequence_no"] == 1
            assert entry["previous_balance"] == 0
            assert entry["quantity_change"] == balance
            assert entry["delta"] == balance
            assert entry["new_balance"] == balance
            assert entry["source"] == "ledger_v2_backfill"
            assert entry["idempotency_key"] == f"baseline:{dept_id}:{item_id}"

            se_after = asyncio.run(_direct_find_one("stock_entries", {"id": entry_id}))
            assert se_after is not None
            assert se_after["ledger_version"] == 1
            assert se_after["balance"] == balance, "balance must be unchanged by the backfill"
            assert se_after["status"] == status, "status must be unchanged by the backfill"
        finally:
            asyncio.run(_direct_cleanup(department_id=dept_id, item_id=item_id, entry_id=entry_id))


# ---------------------------------------------------------------------------
# Real test 2 — idempotency across two live invocations
# ---------------------------------------------------------------------------

class TestRealIdempotency:
    pytestmark = pytest.mark.integration

    def test_real_second_invocation_creates_no_additional_baseline(self, admin_token):
        ctx = _create_item_and_department(admin_token)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        balance = 41
        entry_id = asyncio.run(_direct_insert_legacy_stock_entry(
            department_id=dept_id, item_id=item_id, balance=balance, status="available",
        ))
        try:
            r1 = requests.post(_BACKFILL_ENDPOINT, headers=_bearer(admin_token), timeout=30)
            assert r1.status_code == 200, r1.text
            r2 = requests.post(_BACKFILL_ENDPOINT, headers=_bearer(admin_token), timeout=30)
            assert r2.status_code == 200, r2.text

            v2_entries = asyncio.run(_direct_find(
                "stock_transactions",
                {"department_id": dept_id, "item_id": item_id, "schema_version": 2},
            ))
            assert len(v2_entries) == 1, f"expected exactly 1 v2 baseline after 2 invocations, got {v2_entries}"

            se_after = asyncio.run(_direct_find_one("stock_entries", {"id": entry_id}))
            assert se_after["ledger_version"] == 1
        finally:
            asyncio.run(_direct_cleanup(department_id=dept_id, item_id=item_id, entry_id=entry_id))


# ---------------------------------------------------------------------------
# Real test 3 — existing-v2-with-zero-version conflict
# ---------------------------------------------------------------------------

class TestRealExistingV2Conflict:
    pytestmark = pytest.mark.integration

    def test_real_existing_v2_with_zero_version_is_reported_as_conflict(self, admin_token):
        ctx = _create_item_and_department(admin_token)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        balance = 23
        entry_id = asyncio.run(_direct_insert_legacy_stock_entry(
            department_id=dept_id, item_id=item_id, balance=balance, status="available", ledger_version=0,
        ))
        asyncio.run(_direct_insert_v2_entry(
            department_id=dept_id, item_id=item_id, entry_id=entry_id, balance=balance,
        ))
        try:
            se_before = asyncio.run(_direct_find_one("stock_entries", {"id": entry_id}))
            v2_before = asyncio.run(_direct_find(
                "stock_transactions", {"department_id": dept_id, "item_id": item_id, "schema_version": 2},
            ))

            r = requests.post(_BACKFILL_ENDPOINT, headers=_bearer(admin_token), timeout=30)
            assert r.status_code == 200, r.text
            summary = r.json()
            conflicts = summary.get("conflict_existing_v2_with_zero_version", [])
            assert any(p.get("department_id") == dept_id and p.get("item_id") == item_id for p in conflicts), (
                f"expected pair under conflict_existing_v2_with_zero_version, got {summary}"
            )

            se_after = asyncio.run(_direct_find_one("stock_entries", {"id": entry_id}))
            v2_after = asyncio.run(_direct_find(
                "stock_transactions", {"department_id": dept_id, "item_id": item_id, "schema_version": 2},
            ))
            assert se_after == se_before, "stock_entry must not be modified on conflict"
            assert v2_after == v2_before, "existing v2 transaction must not be modified on conflict"
        finally:
            asyncio.run(_direct_cleanup(department_id=dept_id, item_id=item_id, entry_id=entry_id))


# ---------------------------------------------------------------------------
# Real test 4 — concurrent live HTTP invocations
# ---------------------------------------------------------------------------

class TestRealConcurrentInvocation:
    pytestmark = pytest.mark.integration

    def test_real_concurrent_endpoint_calls_create_only_one_baseline(self, admin_token):
        import concurrent.futures

        ctx = _create_item_and_department(admin_token)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        balance = 58
        entry_id = asyncio.run(_direct_insert_legacy_stock_entry(
            department_id=dept_id, item_id=item_id, balance=balance, status="available",
        ))
        try:
            def _call():
                return requests.post(_BACKFILL_ENDPOINT, headers=_bearer(admin_token), timeout=30)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futs = [pool.submit(_call) for _ in range(2)]
                results = [f.result() for f in concurrent.futures.as_completed(futs)]

            for r in results:
                assert r.status_code == 200, f"unhandled server error on concurrent call: {r.status_code} {r.text}"

            v2_entries = asyncio.run(_direct_find(
                "stock_transactions", {"department_id": dept_id, "item_id": item_id, "schema_version": 2},
            ))
            assert len(v2_entries) == 1, (
                f"expected exactly 1 v2 baseline after concurrent invocations, got {v2_entries}"
            )
            se_after = asyncio.run(_direct_find_one("stock_entries", {"id": entry_id}))
            assert se_after["ledger_version"] == 1, "final ledger_version must be 1 (consistent, not corrupted)"
            assert se_after["balance"] == balance
        finally:
            asyncio.run(_direct_cleanup(department_id=dept_id, item_id=item_id, entry_id=entry_id))


# ---------------------------------------------------------------------------
# Real test 5 — rollback
# ---------------------------------------------------------------------------
#
# backend/server.py's existing failure-injection mechanism (_TXN_HOOKS_ACTIVE /
# X-Test-Txn-Fail-After / _check_fail_point) is active in docker-compose.test.yml
# (TRANSACTION_TEST_HOOKS_ENABLED=true), but it is wired ONLY into upsert_stock,
# stock_issue_execute, and receive_request. It is NOT called anywhere in
# ledger_backfill.py or in the admin_backfill_v2_baselines endpoint. Adding
# _check_fail_point calls there would mean editing backend/server.py and/or
# backend/ledger_backfill.py, which is prohibited here absent a test proving
# an actual defect. No such defect has been found.
#
# THEREFORE: controlled fail-after-write rollback injection for Package 2A-3
# remains UNTESTED. This is reported explicitly in the accompanying report
# rather than faked.
#
# What CAN be proven with real infrastructure, without touching production
# source, is that a genuine MongoDB DuplicateKeyError raised mid-transaction
# by the real unique index causes a real, full transaction rollback (no
# partial baseline, no partial ledger_version bump) for the losing side. That
# is what this test demonstrates, using two independent real Motor clients
# racing on the same stock_entry via the already-existing, unmodified
# ledger_backfill.backfill_pair function.

class TestRealRollback:
    pytestmark = pytest.mark.integration

    def test_real_transaction_rollback_via_genuine_duplicate_key(self, admin_token):
        ctx = _create_item_and_department(admin_token)
        item_id = ctx["item"]["id"]
        dept_id = ctx["dept"]["id"]
        balance = 64
        entry_id = asyncio.run(_direct_insert_legacy_stock_entry(
            department_id=dept_id, item_id=item_id, balance=balance, status="available",
        ))
        try:
            async def _run():
                client_a = _mongo_client()
                client_b = _mongo_client()
                try:
                    db_a = client_a[_MONGO_DB_NAME]
                    db_b = client_b[_MONGO_DB_NAME]
                    return await asyncio.gather(
                        ledger_backfill.backfill_pair(db_a, client_a, entry_id=entry_id),
                        ledger_backfill.backfill_pair(db_b, client_b, entry_id=entry_id),
                    )
                finally:
                    client_a.close()
                    client_b.close()

            r1, r2 = asyncio.run(_run())
            outcomes = [r1["outcome"], r2["outcome"]]
            assert outcomes.count("backfilled") == 1, f"expected exactly one winner, got {outcomes}"

            v2_entries = asyncio.run(_direct_find(
                "stock_transactions", {"department_id": dept_id, "item_id": item_id, "schema_version": 2},
            ))
            assert len(v2_entries) == 1, (
                f"real MongoDB transaction rollback failed to prevent a duplicate baseline: {v2_entries}"
            )
            se_after = asyncio.run(_direct_find_one("stock_entries", {"id": entry_id}))
            assert se_after["ledger_version"] == 1
        finally:
            asyncio.run(_direct_cleanup(department_id=dept_id, item_id=item_id, entry_id=entry_id))


# ---------------------------------------------------------------------------
# Real test 6 — authorization
# ---------------------------------------------------------------------------

class TestRealAuthorization:
    pytestmark = pytest.mark.integration

    def test_unauthorized_role_receives_403(self, auditor_token):
        r = requests.post(_BACKFILL_ENDPOINT, headers=_bearer(auditor_token), timeout=15)
        assert r.status_code == 403, f"expected 403 for auditor role, got {r.status_code}: {r.text}"

    def test_authorized_role_succeeds(self, admin_token):
        r = requests.post(_BACKFILL_ENDPOINT, headers=_bearer(admin_token), timeout=30)
        assert r.status_code == 200, f"expected 200 for super_admin, got {r.status_code}: {r.text}"
        assert "scanned" in r.json()


# ---------------------------------------------------------------------------
# Real test 7 — audit evidence
# ---------------------------------------------------------------------------

class TestRealAuditEvidence:
    pytestmark = pytest.mark.integration

    def test_authorized_invocation_writes_exactly_one_audit_entry(self, admin_token):
        count_before = asyncio.run(_direct_count("audit_logs", {"action": "backfill_v2_baselines"}))

        r = requests.post(_BACKFILL_ENDPOINT, headers=_bearer(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        summary = r.json()

        count_after = asyncio.run(_direct_count("audit_logs", {"action": "backfill_v2_baselines"}))
        assert count_after == count_before + 1, (
            f"expected exactly one new audit_logs entry for this invocation, "
            f"before={count_before} after={count_after}"
        )

        for key in ("scanned", "backfilled_count", "already_baselined_count",
                    "conflict_existing_v2_with_zero_version_count",
                    "conflict_missing_stock_entry_count", "failed_count"):
            assert key in summary

        response_blob = str(summary).lower()
        for forbidden in ("password", "secret", "token", "jwt"):
            assert forbidden not in response_blob

        latest_audit = asyncio.run(_direct_find_one(
            "audit_logs", {"action": "backfill_v2_baselines"}, sort=[("created_at", -1)],
        ))
        assert latest_audit is not None
        assert "scanned" in latest_audit["new_value"]
        assert "backfilled_count" in latest_audit["new_value"]
        audit_blob = str(latest_audit).lower()
        for forbidden in ("password_hash", "jwt_secret", "access_token"):
            assert forbidden not in audit_blob
