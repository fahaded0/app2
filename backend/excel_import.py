"""Excel (.xlsx) import for items. Matching order: barcode -> internal_code -> name -> manual_review."""
import io
from typing import Optional

from openpyxl import load_workbook
from motor.motor_asyncio import AsyncIOMotorDatabase

from models import _new_id, _now_iso

# Expected headers (lowercased). All optional except internal_code OR barcode.
EXPECTED_HEADERS = [
    "internal_code", "barcode", "name", "category", "unit",
    "min_level", "critical_threshold", "max_level",
    "department_code", "balance",
]


def _norm(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _to_int(v, default: int = 0) -> int:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def parse_workbook(file_bytes: bytes) -> list[dict]:
    """Read the first worksheet and return a list of row dicts keyed by header."""
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    ws = wb.active
    if ws is None:
        return []
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers_raw = [(_norm(h) or "").lower() for h in rows[0]]
    parsed: list[dict] = []
    for i, row in enumerate(rows[1:], start=2):     # 1-based excel row, header on row 1
        if all(c is None or c == "" for c in row):
            continue
        item: dict = {"__row__": i}
        for h, c in zip(headers_raw, row):
            if h:
                item[h] = c
        parsed.append(item)
    return parsed


async def _find_match(db: AsyncIOMotorDatabase, row: dict) -> tuple[Optional[dict], str]:
    """Return (existing_item or None, match_strategy).
    Strategies: 'barcode', 'internal_code', 'name', 'none'."""
    barcode = _norm(row.get("barcode"))
    if barcode:
        existing = await db.items.find_one({"barcode": barcode}, {"_id": 0})
        if existing:
            return existing, "barcode"
    code = _norm(row.get("internal_code"))
    if code:
        existing = await db.items.find_one({"internal_code": code}, {"_id": 0})
        if existing:
            return existing, "internal_code"
    name = _norm(row.get("name"))
    if name:
        existing = await db.items.find_one(
            {"$or": [{"name_en": name}, {"name_ar": name}]}, {"_id": 0}
        )
        if existing:
            return existing, "name"
    return None, "none"


async def analyse(db: AsyncIOMotorDatabase, file_bytes: bytes) -> dict:
    """Build a preview report describing what a commit would do."""
    rows = parse_workbook(file_bytes)
    departments = {d["code"]: d for d in await db.departments.find({}, {"_id": 0}).to_list(500)}

    summary = {
        "total_rows": len(rows),
        "to_create": [],
        "to_update": [],
        "manual_review": [],
        "errors": [],
    }
    for r in rows:
        ref = r["__row__"]
        name = _norm(r.get("name"))
        code = _norm(r.get("internal_code"))
        barcode = _norm(r.get("barcode"))

        if not (name or code or barcode):
            summary["errors"].append({"row": ref, "reason": "Empty key fields (need at least one of internal_code/barcode/name)"})
            continue

        existing, strategy = await _find_match(db, r)
        dept_code = _norm(r.get("department_code"))
        if dept_code and dept_code not in departments:
            summary["errors"].append({"row": ref, "reason": f"Unknown department_code '{dept_code}'"})
            continue

        entry = {
            "row": ref,
            "strategy": strategy,
            "existing_id": existing["id"] if existing else None,
            "internal_code": code,
            "barcode": barcode,
            "name": name,
            "category": _norm(r.get("category")),
            "unit": _norm(r.get("unit")),
            "min_level": _to_int(r.get("min_level")),
            "critical_threshold": _to_int(r.get("critical_threshold")),
            "max_level": _to_int(r.get("max_level")),
            "department_code": dept_code,
            "balance": _to_int(r.get("balance"), default=None) if r.get("balance") not in (None, "") else None,
        }
        if existing:
            summary["to_update"].append(entry)
        elif strategy == "none" and not code:
            # No code and no match → needs manual review
            summary["manual_review"].append(entry)
        else:
            summary["to_create"].append(entry)
    return summary


def _calc_status(balance: int, min_level: int, critical: int) -> str:
    if balance == 0:
        return "zero_level"
    if balance < critical:
        return "critical_level"
    return "available"


async def commit(
    db: AsyncIOMotorDatabase,
    file_bytes: bytes,
    user: dict,
    *,
    include_manual_review: bool = False,
) -> dict:
    """Apply the import. Returns a summary of created/updated counts."""
    plan = await analyse(db, file_bytes)
    departments = {d["code"]: d for d in await db.departments.find({}, {"_id": 0}).to_list(500)}
    created = 0
    updated = 0
    stock_updated = 0
    skipped = 0

    rows_to_process = plan["to_create"] + plan["to_update"]
    if include_manual_review:
        rows_to_process += plan["manual_review"]

    for entry in rows_to_process:
        # Resolve / create item
        if entry["existing_id"]:
            item_id = entry["existing_id"]
            update_doc = {k: v for k, v in {
                "barcode": entry["barcode"],
                "name_en": entry["name"],
                "name_ar": entry["name"],
                "category": entry["category"],
                "unit": entry["unit"],
                "min_level": entry["min_level"],
                "critical_threshold": entry["critical_threshold"],
                "max_level": entry["max_level"],
                "updated_at": _now_iso(),
            }.items() if v not in (None, "")}
            if update_doc:
                await db.items.update_one({"id": item_id}, {"$set": update_doc})
                updated += 1
        else:
            # Build a new item — internal_code required for creation
            if not entry["internal_code"]:
                skipped += 1
                continue
            item_id = _new_id()
            await db.items.insert_one({
                "id": item_id,
                "internal_code": entry["internal_code"],
                "barcode": entry["barcode"],
                "udi": None,
                "gtin": None,
                "name_ar": entry["name"] or entry["internal_code"],
                "name_en": entry["name"] or entry["internal_code"],
                "category": entry["category"] or "Other",
                "unit": entry["unit"] or "PCS",
                "min_level": entry["min_level"],
                "critical_threshold": entry["critical_threshold"],
                "max_level": entry["max_level"],
                "reorder_qty": 0,
                "lead_time_days": 0,
                "alternative_item_id": None,
                "is_life_saving": False,
                "is_crash_cart": False,
                "requires_expiry": False,
                "supplier": None,
                "is_active": True,
                "notes": None,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            })
            created += 1

        # Optionally upsert stock balance per department
        if entry["balance"] is not None and entry["department_code"]:
            dept = departments.get(entry["department_code"])
            if not dept:
                continue
            item = await db.items.find_one({"id": item_id})
            status = _calc_status(entry["balance"], item["min_level"], item["critical_threshold"])
            existing = await db.stock_entries.find_one(
                {"department_id": dept["id"], "item_id": item_id}
            )
            stock_doc = {
                "department_id": dept["id"],
                "item_id": item_id,
                "balance": entry["balance"],
                "status": status,
                "last_updated_by": user["id"],
                "last_updated_by_name": user["full_name"],
                "last_updated_at": _now_iso(),
                "shortage_start": _now_iso() if status in ("zero_level", "critical_level") else None,
                "notes": "Excel import",
            }
            if existing:
                await db.stock_entries.update_one({"id": existing["id"]}, {"$set": stock_doc})
            else:
                await db.stock_entries.insert_one({"id": _new_id(), **stock_doc})
            stock_updated += 1

    return {
        "created_items": created,
        "updated_items": updated,
        "stock_entries_touched": stock_updated,
        "skipped": skipped + len(plan["errors"]),
        "errors": plan["errors"],
        "manual_review_count": 0 if include_manual_review else len(plan["manual_review"]),
    }
