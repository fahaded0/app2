"""Seed initial data: admin, departments, users, item master, sample stock."""
import os
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorDatabase

from auth import hash_password
from models import _new_id, _now_iso


SAMPLE_DEPARTMENTS = [
    {"code": "ER", "name_ar": "الطوارئ", "name_en": "Emergency Room", "is_critical": True},
    {"code": "ICU", "name_ar": "العناية المركزة", "name_en": "Intensive Care Unit", "is_critical": True},
    {"code": "LAB", "name_ar": "المختبر", "name_en": "Laboratory", "is_critical": False},
    {"code": "RAD", "name_ar": "الأشعة", "name_en": "Radiology", "is_critical": False},
    {"code": "PHARM", "name_ar": "الصيدلية", "name_en": "Pharmacy", "is_critical": False},
]

SAMPLE_ITEMS = [
    {"internal_code": "ETT-CUFF-2", "barcode": "8901234500021", "name_ar": "أنبوب قصبة هوائية مع كف 2",
     "name_en": "ETT W/ Cuff 2", "category": "Airway", "unit": "PCS",
     "min_level": 10, "critical_threshold": 5, "max_level": 30, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "ETT-CUFF-3", "barcode": "8901234500038", "name_ar": "أنبوب قصبة هوائية مع كف 3",
     "name_en": "ETT W/ Cuff 3", "category": "Airway", "unit": "PCS",
     "min_level": 10, "critical_threshold": 5, "max_level": 30, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "CRICO-KIT", "barcode": "8901234500045", "name_ar": "طقم بضع الغضروف الدرقي الحلقي",
     "name_en": "Cricothyroidotomy Kit", "category": "Airway", "unit": "KIT",
     "min_level": 3, "critical_threshold": 1, "max_level": 5, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "IV-CANN-18", "barcode": "8901234500052", "name_ar": "قنية وريدية 18",
     "name_en": "IV Cannula 18G", "category": "IV", "unit": "PCS",
     "min_level": 50, "critical_threshold": 20, "max_level": 200},
    {"internal_code": "IV-CANN-20", "barcode": "8901234500069", "name_ar": "قنية وريدية 20",
     "name_en": "IV Cannula 20G", "category": "IV", "unit": "PCS",
     "min_level": 50, "critical_threshold": 20, "max_level": 200},
    {"internal_code": "GLOVE-M", "barcode": "8901234500076", "name_ar": "قفازات طبية وسط",
     "name_en": "Medical Gloves M", "category": "PPE", "unit": "BOX",
     "min_level": 20, "critical_threshold": 8, "max_level": 80},
    {"internal_code": "MASK-N95", "barcode": "8901234500083", "name_ar": "كمامة N95",
     "name_en": "N95 Mask", "category": "PPE", "unit": "PCS",
     "min_level": 100, "critical_threshold": 40, "max_level": 500, "is_life_saving": True},
    {"internal_code": "GAUZE-4x4", "barcode": "8901234500090", "name_ar": "شاش 4×4",
     "name_en": "Gauze 4x4", "category": "Wound Care", "unit": "PACK",
     "min_level": 30, "critical_threshold": 10, "max_level": 100},
    {"internal_code": "SYRINGE-5", "barcode": "8901234500106", "name_ar": "سرنجة 5 مل",
     "name_en": "Syringe 5ml", "category": "IV", "unit": "PCS",
     "min_level": 100, "critical_threshold": 40, "max_level": 400},
    {"internal_code": "DEFIB-PAD", "barcode": "8901234500113", "name_ar": "لاصقات الصاعق",
     "name_en": "Defibrillator Pads", "category": "Equipment", "unit": "PCS",
     "min_level": 6, "critical_threshold": 2, "max_level": 12, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "BVM-ADULT", "barcode": "8901234500120", "name_ar": "جهاز إنعاش بالكيس - بالغ",
     "name_en": "BVM Adult", "category": "Airway", "unit": "PCS",
     "min_level": 4, "critical_threshold": 1, "max_level": 6, "is_life_saving": True, "is_crash_cart": True},
    {"internal_code": "EPI-1MG", "barcode": "8901234500137", "name_ar": "إبينفرين 1 ملغ",
     "name_en": "Epinephrine 1mg", "category": "Medication", "unit": "VIAL",
     "min_level": 20, "critical_threshold": 8, "max_level": 50, "is_life_saving": True, "is_crash_cart": True,
     "requires_expiry": True},
]


def _calc_status(balance: int, min_level: int, critical: int) -> str:
    if balance == 0:
        return "zero_level"
    if balance < critical:
        return "critical_level"
    return "available"


async def seed(db: AsyncIOMotorDatabase) -> None:
    # ---- Admin ----
    admin_email = os.environ["ADMIN_EMAIL"]
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "id": _new_id(),
            "email": admin_email,
            "full_name": "مدير النظام",
            "password_hash": hash_password(admin_password),
            "role": "super_admin",
            "department_id": None,
            "is_active": True,
            "created_at": _now_iso(),
        })

    # ---- Departments ----
    department_ids = {}
    for d in SAMPLE_DEPARTMENTS:
        doc = await db.departments.find_one({"code": d["code"]})
        if not doc:
            new_id = _new_id()
            await db.departments.insert_one({
                "id": new_id,
                **d,
                "created_at": _now_iso(),
            })
            department_ids[d["code"]] = new_id
        else:
            department_ids[d["code"]] = doc["id"]

    # ---- Items ----
    item_ids = {}
    for it in SAMPLE_ITEMS:
        doc = await db.items.find_one({"internal_code": it["internal_code"]})
        if not doc:
            new_id = _new_id()
            full = {
                "id": new_id,
                "internal_code": it["internal_code"],
                "barcode": it.get("barcode"),
                "udi": None,
                "name_ar": it["name_ar"],
                "name_en": it["name_en"],
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
            }
            await db.items.insert_one(full)
            item_ids[it["internal_code"]] = new_id
        else:
            item_ids[it["internal_code"]] = doc["id"]

    # ---- Sample users by role ----
    sample_users = [
        {"email": "head.er@medstock.sa", "full_name": "رئيس قسم الطوارئ",
         "role": "department_head", "department_id": department_ids.get("ER"), "password": "Head@12345"},
        {"email": "officer.er@medstock.sa", "full_name": "مسؤول مخزون الطوارئ",
         "role": "department_stock_officer", "department_id": department_ids.get("ER"), "password": "Officer@12345"},
        {"email": "officer.icu@medstock.sa", "full_name": "مسؤول مخزون العناية",
         "role": "department_stock_officer", "department_id": department_ids.get("ICU"), "password": "Officer@12345"},
        {"email": "supply@medstock.sa", "full_name": "مسؤول التموين الطبي",
         "role": "supply_officer", "department_id": None, "password": "Supply@12345"},
        {"email": "auditor@medstock.sa", "full_name": "المراجع الداخلي",
         "role": "auditor", "department_id": None, "password": "Audit@12345"},
    ]
    for u in sample_users:
        if not await db.users.find_one({"email": u["email"]}):
            await db.users.insert_one({
                "id": _new_id(),
                "email": u["email"],
                "full_name": u["full_name"],
                "password_hash": hash_password(u["password"]),
                "role": u["role"],
                "department_id": u["department_id"],
                "is_active": True,
                "created_at": _now_iso(),
            })

    # ---- Sample stock entries (ER + ICU) ----
    admin = await db.users.find_one({"email": admin_email})
    admin_id = admin["id"]
    admin_name = admin["full_name"]

    sample_stock = [
        # ER
        ("ER", "ETT-CUFF-2", 0),       # zero
        ("ER", "ETT-CUFF-3", 12),      # available
        ("ER", "CRICO-KIT", 1),        # critical (life-saving!)
        ("ER", "IV-CANN-18", 18),      # critical
        ("ER", "IV-CANN-20", 80),      # available
        ("ER", "GLOVE-M", 6),          # critical
        ("ER", "MASK-N95", 0),         # zero life-saving
        ("ER", "GAUZE-4x4", 35),
        ("ER", "SYRINGE-5", 220),
        ("ER", "DEFIB-PAD", 3),        # available (above critical)
        ("ER", "BVM-ADULT", 0),        # zero life-saving
        ("ER", "EPI-1MG", 22),
        # ICU
        ("ICU", "ETT-CUFF-2", 4),      # critical
        ("ICU", "ETT-CUFF-3", 0),      # zero
        ("ICU", "CRICO-KIT", 2),       # available
        ("ICU", "IV-CANN-18", 60),
        ("ICU", "IV-CANN-20", 15),     # critical
        ("ICU", "GLOVE-M", 25),
        ("ICU", "MASK-N95", 110),
        ("ICU", "GAUZE-4x4", 8),       # critical
        ("ICU", "SYRINGE-5", 350),
        ("ICU", "DEFIB-PAD", 1),       # critical life-saving
        ("ICU", "BVM-ADULT", 2),
        ("ICU", "EPI-1MG", 5),         # critical life-saving
    ]
    for dept_code, item_code, balance in sample_stock:
        dept_id = department_ids[dept_code]
        item_id = item_ids[item_code]
        item_doc = await db.items.find_one({"id": item_id})
        existing_stock = await db.stock_entries.find_one(
            {"department_id": dept_id, "item_id": item_id}
        )
        if existing_stock:
            continue
        status = _calc_status(balance, item_doc["min_level"], item_doc["critical_threshold"])
        await db.stock_entries.insert_one({
            "id": _new_id(),
            "department_id": dept_id,
            "item_id": item_id,
            "balance": balance,
            "status": status,
            "last_updated_by": admin_id,
            "last_updated_by_name": admin_name,
            "last_updated_at": _now_iso(),
            "shortage_start": _now_iso() if status in ("zero_level", "critical_level") else None,
            "notes": None,
        })
        # transaction history
        await db.stock_transactions.insert_one({
            "id": _new_id(),
            "department_id": dept_id,
            "item_id": item_id,
            "previous_balance": None,
            "new_balance": balance,
            "delta": balance,
            "status": status,
            "user_id": admin_id,
            "user_name": admin_name,
            "created_at": _now_iso(),
            "reason": "seed",
        })
        # initial alert if status is critical / zero
        if status in ("zero_level", "critical_level"):
            await db.alerts.insert_one({
                "id": _new_id(),
                "type": status,
                "severity": "critical" if status == "zero_level" else "warning",
                "title": f"{'صفر مخزون' if status == 'zero_level' else 'مخزون حرج'} - {item_doc['name_ar']}",
                "message": f"الرصيد الحالي {balance} في {dept_code}",
                "department_id": dept_id,
                "item_id": item_id,
                "request_id": None,
                "created_at": _now_iso(),
                "acknowledged": False,
                "acknowledged_by": None,
                "acknowledged_at": None,
            })

    # ---- test_credentials.md ----
    cred_path = Path("/app/memory/test_credentials.md")
    cred_path.parent.mkdir(parents=True, exist_ok=True)
    cred_path.write_text(
        "# Test Credentials\n\n"
        "## Admin\n"
        f"- Email: {admin_email}\n"
        f"- Password: {admin_password}\n"
        "- Role: super_admin\n\n"
        "## Sample Users\n"
        "- Department Head (ER): head.er@medstock.sa / Head@12345\n"
        "- Stock Officer (ER): officer.er@medstock.sa / Officer@12345\n"
        "- Stock Officer (ICU): officer.icu@medstock.sa / Officer@12345\n"
        "- Supply Officer: supply@medstock.sa / Supply@12345\n"
        "- Auditor: auditor@medstock.sa / Audit@12345\n\n"
        "## Auth Endpoints\n"
        "- POST /api/auth/login\n"
        "- GET /api/auth/me\n"
        "- POST /api/auth/logout\n",
        encoding="utf-8",
    )
