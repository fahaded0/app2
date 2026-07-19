"""Immutable stock ledger v2 — authoritative write-ahead record for all stock movements.

Ledger v2 records are stored in the stock_transactions collection, identified by
schema_version=2. Legacy stock_transactions records (schema_version absent) remain
untouched and are not affected by v2 indexes.
"""
import hashlib
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pymongo.asynchronous.database import AsyncDatabase

try:
    from models import _new_id, _now_iso
except ImportError:  # unit-test environment without production dependencies
    import uuid, datetime as _dt
    def _new_id() -> str:
        return uuid.uuid4().hex
    def _now_iso() -> str:
        return _dt.datetime.utcnow().isoformat() + "Z"

VALID_ENTRY_TYPES = frozenset({
    "opening_balance", "issue", "receive", "adjustment", "physical_count",
    "transfer_in", "transfer_out", "return",
})

# Fields that callers may NOT override via **extra
_RESERVED_OVERRIDE_FIELDS = frozenset({
    "id", "schema_version", "department_id", "item_id", "entry_type",
    "sequence_no", "previous_balance", "quantity_change", "delta",
    "new_balance", "actor_type", "source", "idempotency_key", "created_at",
})


def build_ledger_entry(
    *,
    department_id: str,
    item_id: str,
    entry_type: str,
    sequence_no: int,
    previous_balance: int,
    quantity_change: int,
    new_balance: int,
    user_id: Optional[str],
    user_name: Optional[str],
    actor_type: str = "user",
    source: str,
    idempotency_key: str,
    status: str,
    entry_id: str,
    transaction_id: Optional[str] = None,
    reference_no: Optional[str] = None,
    **extra,
) -> dict:
    """Build and validate a v2 ledger entry dict (does not write to DB).

    Raises ValueError if entry_type is invalid, balance arithmetic is wrong,
    or extra kwargs attempt to override reserved ledger fields.
    """
    if entry_type not in VALID_ENTRY_TYPES:
        raise ValueError(f"Invalid entry_type: {entry_type!r}")
    if new_balance != previous_balance + quantity_change:
        raise ValueError(
            f"Ledger integrity: {previous_balance} + {quantity_change} != {new_balance}"
        )
    reserved_conflicts = _RESERVED_OVERRIDE_FIELDS & set(extra)
    if reserved_conflicts:
        raise ValueError(
            f"Extra fields may not override reserved ledger fields: {sorted(reserved_conflicts)}"
        )
    doc: dict = {
        "id": transaction_id or _new_id(),
        "schema_version": 2,
        "department_id": department_id,
        "item_id": item_id,
        "entry_type": entry_type,
        "sequence_no": sequence_no,
        "previous_balance": previous_balance,
        "quantity_change": quantity_change,
        "delta": quantity_change,
        "new_balance": new_balance,
        "status": status,
        "user_id": user_id,
        "user_name": user_name,
        "actor_type": actor_type,
        "source": source,
        "idempotency_key": idempotency_key,
        "entry_id": entry_id,
        "reference_no": reference_no,
        "created_at": _now_iso(),
    }
    doc.update(extra)
    return doc


async def insert_ledger_entry(
    db,
    entry: dict,
    session=None,
) -> None:
    """Insert a v2 ledger entry into stock_transactions."""
    await db.stock_transactions.insert_one(entry, session=session)


async def ensure_v2_baseline(
    db,
    *,
    department_id: str,
    item_id: str,
    entry_id: str,
    balance: int,
    user_id: Optional[str],
    user_name: Optional[str],
    idempotency_key: str,
    status: str,
    source: str = "ledger_v2_cutover",
    session=None,
) -> bool:
    """Write an opening_balance v2 record (seq=1) if no v2 entry exists for (department_id, item_id).

    Returns True if a new baseline was written, False if one already existed.
    Must be called inside a transaction; DuplicateKeyError is NOT swallowed here —
    it aborts the transaction so the driver can retry.
    """
    existing = await db.stock_transactions.find_one(
        {"department_id": department_id, "item_id": item_id, "schema_version": 2},
        session=session,
    )
    if existing:
        return False
    entry = build_ledger_entry(
        department_id=department_id,
        item_id=item_id,
        entry_type="opening_balance",
        sequence_no=1,
        previous_balance=0,
        quantity_change=balance,
        new_balance=balance,
        user_id=user_id,
        user_name=user_name,
        actor_type="system",
        source=source,
        idempotency_key=idempotency_key,
        status=status,
        entry_id=entry_id,
    )
    await db.stock_transactions.insert_one(entry, session=session)
    return True


def workbook_row_idempotency_key(file_bytes: bytes, row_number: int) -> str:
    """Deterministic idempotency key for Excel import rows: SHA-256(file) + row number."""
    sha = hashlib.sha256(file_bytes).hexdigest()
    return f"excel:{sha}:{row_number}"
