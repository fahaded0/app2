"""Seed initial data: admin, departments, users, item master, sample stock."""
import os

from motor.motor_asyncio import AsyncIOMotorDatabase

from auth import hash_password
from models import _new_id, _now_iso
import ledger as ledger_mod


SAMPLE_DEPARTMENTS = [
    {"code": "ER", "name_ar": "Emergency Room", "name_en": "Emergency Room", "is_critical": True},
    {"code": "ICU", "name_ar": "Intensive Care Unit", "name_en": "Intensive Care Unit", "is_critical": True},
    {"code": "LAB", "name_ar": "Laboratory", "name_en": "Laboratory", "is_critical": False},
    {"code": "RAD", "name_ar": "Radiology", "name_en": "Radiology", "is_critical": False},
    {"code": "PHARM", "name_ar": "Pharmacy", "name_en": "Pharmacy", "is_critical": False},
]

SAMPLE_ITEMS = [
    {"internal_code": "ETT-CUFF-2", "barcode": "8901234500021", "name_en": "ETT W/ Cuff 2",
     "category": "Airway", "unit": "PCS",
     "min_level": 10, "critical_threshold": 5, "max_level": 30, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "ETT-CUFF-3", "barcode": "8901234500038", "name_en": "ETT W/ Cuff 3",
     "category": "Airway", "unit": "PCS",
     "min_level": 10, "critical_threshold": 5, "max_level": 30, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "CRICO-KIT", "barcode": "8901234500045", "name_en": "Cricothyroidotomy Kit",
     "category": "Airway", "unit": "KIT",
     "min_level": 3, "critical_threshold": 1, "max_level": 5, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "IV-CANN-18", "barcode": "8901234500052", "name_en": "IV Cannula 18G",
     "category": "IV", "unit": "PCS",
     "min_level": 50, "critical_threshold": 20, "max_level": 200},
    {"internal_code": "IV-CANN-20", "barcode": "8901234500069", "name_en": "IV Cannula 20G",
     "category": "IV", "unit": "PCS",
     "min_level": 50, "critical_threshold": 20, "max_level": 200},
    {"internal_code": "GLOVE-M", "barcode": "8901234500076", "name_en": "Medical Gloves M",
     "category": "PPE", "unit": "BOX",
     "min_level": 20, "critical_threshold": 8, "max_level": 80},
    {"internal_code": "MASK-N95", "barcode": "8901234500083", "name_en": "N95 Mask",
     "category": "PPE", "unit": "PCS",
     "min_level": 100, "critical_threshold": 40, "max_level": 500, "is_life_saving": True},
    {"internal_code": "GAUZE-4x4", "barcode": "8901234500090", "name_en": "Gauze 4x4",
     "category": "Wound Care", "unit": "PACK",
     "min_level": 30, "critical_threshold": 10, "max_level": 100},
    {"internal_code": "SYRINGE-5", "barcode": "8901234500106", "name_en": "Syringe 5ml",
     "category": "IV", "unit": "PCS",
     "min_level": 100, "critical_threshold": 40, "max_level": 400},
    {"internal_code": "DEFIB-PAD", "barcode": "8901234500113", "name_en": "Defibrillator Pads",
     "category": "Equipment", "unit": "PCS",
     "min_level": 6, "critical_threshold": 2, "max_level": 12, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "BVM-ADULT", "barcode": "8901234500120", "name_en": "BVM Adult",
     "category": "Airway", "unit": "PCS",
     "min_level": 4, "critical_threshold": 1, "max_level": 6, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "EPI-1MG", "barcode": "8901234500137", "name_en": "Epinephrine 1mg",
     "category": "Medication", "unit": "VIAL",
     "min_level": 20, "critical_threshold": 8, "max_level": 50, "is_life_saving": True, "is_crash_cart": True,
     "requires_expiry": True},
]


SAMPLE_USERS = [
    {"email": "head.er@medstock.sa", "full_name": "Emergency Room Head",
     "role": "department_head", "dept_code": "ER", "password": "Head@12345"},
    {"email": "officer.er@medstock.sa", "full_name": "ER Stock Officer",
     "role": "department_stock_officer", "dept_code": "ER", "password": "Officer@12345"},
    {"email": "officer.icu@medstock.sa", "full_name": "ICU Stock Officer",
     "role": "department_stock_officer", "dept_code": "ICU", "password": "Officer@12345"},
    {"email": "supply@medstock.sa", "full_name": "Medical Supply Officer",
     "role": "supply_officer", "dept_code": None, "password": "Supply@12345"},
    {"email": "auditor@medstock.sa", "full_name": "Internal Auditor",
     "role": "auditor", "dept_code": None, "password": "Audit@12345"},
]


def _calc_status(balance: int, min_level: int, critical: int) -> str:
    if balance == 0:
        return "zero_level"
    if balance < critical:
        return "critical_level"
    return "available"


async def _ensure_admin(db: AsyncIOMotorDatabase) -> dict:
    """Ensure the admin user exists with the English full_name. Never reactivates an existing user."""
    admin_email = os.environ["ADMIN_EMAIL"]
    admin_password = os.environ["ADMIN_PASSWORD"]
    target_name = "System Administrator"
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        admin = {
            "id": _new_id(),
            "email": admin_email,
            "full_name": target_name,
            "password_hash": hash_password(admin_password),
            "role": "super_admin",
            "department_id": None,
            "is_active": True,
            "created_at": _now_iso(),
        }
        await db.users.insert_one(admin)
    elif existing.get("full_name") != target_name:
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"full_name": target_name}}
        )
    return await db.users.find_one({"email": admin_email})


async def _ensure_departments(db: AsyncIOMotorDatabase) -> dict:
    """Ensure the seed departments exist and have English names. Returns code -> id."""
    ids: dict = {}
    for d in SAMPLE_DEPARTMENTS:
        doc = await db.departments.find_one({"code": d["code"]})
        if not doc:
            new_id = _new_id()
            await db.departments.insert_one({"id": new_id, **d, "created_at": _now_iso()})
            ids[d["code"]] = new_id
        else:
            # Force update to English name if previous seed had Arabic
            await db.departments.update_one(
                {"id": doc["id"]},
                {"$set": {"name_ar": d["name_ar"], "name_en": d["name_en"]}}
            )
            ids[d["code"]] = doc["id"]
    return ids


async def _ensure_items(db: AsyncIOMotorDatabase) -> dict:
    """Ensure the seed items exist and have English names. Returns code -> id."""
    ids: dict = {}
    for it in SAMPLE_ITEMS:
        doc = await db.items.find_one({"internal_code": it["internal_code"]})
        name_en = it["name_en"]
        if not doc:
            new_id = _new_id()
            await db.items.insert_one({
                "id": new_id,
                "internal_code": it["internal_code"],
                "barcode": it.get("barcode"),
                "udi": None,
                "name_ar": name_en,
                "name_en": name_en,
                "category": it.get("category", "Other"),
                "unit": it.get("unit", "PCS"),
                "min_level": it.get("min_level", 0),
                "critical_threshold": it.get("critical_threshold", 0),
                "max_level": it.get("max_level", 0),
                "is_life_saving": it.get("is_life_saving", False),
                "is_crash_cart": it.get("is_crash_cart", False),
                "requires_expiry": it.get("requires_expiry", False),
                "supplier": None,
                "is_active": True,
                "notes": None,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            })
            ids[it["internal_code"]] = new_id
        else:
            # Force-update names to English
            await db.items.update_one(
                {"id": doc["id"]},
                {"$set": {"name_ar": name_en, "name_en": name_en}}
            )
            ids[it["internal_code"]] = doc["id"]
    return ids


async def _ensure_users(db: AsyncIOMotorDatabase, dept_ids: dict) -> None:
    """Ensure sample users exist with the English full_name."""
    for u in SAMPLE_USERS:
        dept_id = dept_ids.get(u["dept_code"]) if u["dept_code"] else None
        existing = await db.users.find_one({"email": u["email"]})
        if not existing:
            await db.users.insert_one({
                "id": _new_id(),
                "email": u["email"],
                "full_name": u["full_name"],
                "password_hash": hash_password(u["password"]),
                "role": u["role"],
                "department_id": dept_id,
                "is_active": True,
                "created_at": _now_iso(),
            })
        else:
            await db.users.update_one(
                {"email": u["email"]},
                {"$set": {"full_name": u["full_name"], "department_id": dept_id}}
            )


_SAMPLE_STOCK = [
    # ER
    ("ER", "ETT-CUFF-2", 0),
    ("ER", "ETT-CUFF-3", 12),
    ("ER", "CRICO-KIT", 1),
    ("ER", "IV-CANN-18", 18),
    ("ER", "IV-CANN-20", 80),
    ("ER", "GLOVE-M", 6),
    ("ER", "MASK-N95", 0),
    ("ER", "GAUZE-4x4", 35),
    ("ER", "SYRINGE-5", 220),
    ("ER", "DEFIB-PAD", 3),
    ("ER", "BVM-ADULT", 0),
    ("ER", "EPI-1MG", 22),
    # ICU
    ("ICU", "ETT-CUFF-2", 4),
    ("ICU", "ETT-CUFF-3", 0),
    ("ICU", "CRICO-KIT", 2),
    ("ICU", "IV-CANN-18", 60),
    ("ICU", "IV-CANN-20", 15),
    ("ICU", "GLOVE-M", 25),
    ("ICU", "MASK-N95", 110),
    ("ICU", "GAUZE-4x4", 8),
    ("ICU", "SYRINGE-5", 350),
    ("ICU", "DEFIB-PAD", 1),
    ("ICU", "BVM-ADULT", 2),
    ("ICU", "EPI-1MG", 5),
]


async def _ensure_sample_stock(
    db: AsyncIOMotorDatabase,
    dept_ids: dict,
    item_ids: dict,
    admin_id: str,
    admin_name: str,
    client=None,
) -> None:
    if client is None:
        raise RuntimeError("Seed stock writes require a transactional MongoDB client")
    for dept_code, item_code, balance in _SAMPLE_STOCK:
        dept_id = dept_ids[dept_code]
        item_id = item_ids[item_code]

        async def _pair_callback(session, _dept_id=dept_id, _item_id=item_id,
                                 _balance=balance, _dept_code=dept_code):
            await _seed_pair(db, _dept_id, _item_id, _balance, admin_id, admin_name,
                             _dept_code, item_ids, session=session)

        async with await client.start_session() as session:
            await session.with_transaction(_pair_callback)


async def _seed_pair(
    db: AsyncIOMotorDatabase,
    dept_id: str,
    item_id: str,
    balance: int,
    admin_id: str,
    admin_name: str,
    dept_code: str,
    item_ids: dict,
    session=None,
) -> None:
    if await db.stock_entries.find_one(
        {"department_id": dept_id, "item_id": item_id}, session=session
    ):
        return

    item_doc = await db.items.find_one({"id": item_id}, session=session)
    if not item_doc:
        return

    status = _calc_status(balance, item_doc["min_level"], item_doc["critical_threshold"])
    stock_id = _new_id()
    await db.stock_entries.insert_one({
        "id": stock_id,
        "department_id": dept_id,
        "item_id": item_id,
        "balance": balance,
        "status": status,
        "last_updated_by": admin_id,
        "last_updated_by_name": admin_name,
        "last_updated_at": _now_iso(),
        "shortage_start": _now_iso() if status in ("zero_level", "critical_level") else None,
        "notes": None,
        "ledger_version": 1,
    }, session=session)

    # Write the v2 opening_balance ledger record directly into stock_transactions
    idem_key = f"seed:{dept_id}:{item_id}"
    ledger_entry = ledger_mod.build_ledger_entry(
        department_id=dept_id,
        item_id=item_id,
        entry_type="opening_balance",
        sequence_no=1,
        previous_balance=0,
        quantity_change=balance,
        new_balance=balance,
        user_id=admin_id,
        user_name=admin_name,
        actor_type="system",
        source="seed",
        idempotency_key=idem_key,
        status=status,
        entry_id=stock_id,
        ledger_version=1,
    )
    await db.stock_transactions.insert_one(ledger_entry, session=session)

    if status in ("zero_level", "critical_level"):
        title = ("Zero stock" if status == "zero_level" else "Critical stock") + f" — {item_doc['name_en']}"
        await db.alerts.insert_one({
            "id": _new_id(),
            "type": status,
            "severity": "critical" if status == "zero_level" else "warning",
            "title": title,
            "message": f"Current balance is {balance} in {dept_code}",
            "department_id": dept_id,
            "item_id": item_id,
            "request_id": None,
            "created_at": _now_iso(),
            "acknowledged": False, "acknowledged_by": None, "acknowledged_at": None,
        }, session=session)


async def seed(db: AsyncIOMotorDatabase, client=None) -> None:
    admin = await _ensure_admin(db)
    dept_ids = await _ensure_departments(db)
    item_ids = await _ensure_items(db)
    await _ensure_users(db, dept_ids)
    await _ensure_sample_stock(db, dept_ids, item_ids, admin["id"], admin["full_name"], client=client)
