"""Critical Medical Stock Monitoring & Alerting System - main API."""
from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import io
import csv

from auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    set_auth_cookies,
    clear_auth_cookies,
    get_current_user,
    require_roles,
    check_lockout,
    register_failed_attempt,
    clear_failed_attempts,
)
from models import (
    UserCreate, UserUpdate, LoginBody,
    DepartmentCreate, ItemCreate, ItemUpdate,
    StockEntryUpdate, StockRequestCreate,
    ApproveBody, RejectBody, DispatchBody, ReceiveBody,
    _new_id, _now_iso,
)
from seed import seed as seed_data


# ---------- App ----------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Critical Medical Stock Monitoring System")
app.state.db = db

api = APIRouter(prefix="/api")


# ---------- Utilities ----------
async def write_audit(
    user: Optional[dict],
    action: str,
    entity: str,
    entity_id: Optional[str] = None,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    request: Optional[Request] = None,
    reason: Optional[str] = None,
) -> None:
    doc = {
        "id": _new_id(),
        "user_id": user["id"] if user else None,
        "user_email": user["email"] if user else None,
        "user_role": user["role"] if user else None,
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "old_value": old_value,
        "new_value": new_value,
        "ip": request.client.host if request and request.client else None,
        "reason": reason,
        "created_at": _now_iso(),
    }
    await db.audit_logs.insert_one(doc)


def _calc_stock_status(balance: int, min_level: int, critical_threshold: int) -> str:
    if balance == 0:
        return "zero_level"
    if balance < critical_threshold:
        return "critical_level"
    if balance < min_level:
        return "critical_level"
    return "available"


def _strip_mongo_id(doc: dict) -> dict:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


# ===== AUTH =====
@api.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    email = body.email.lower().strip()
    # Use email alone as identifier since K8s ingress upstream IPs vary per request.
    identifier = f"email:{email}"

    await check_lockout(db, identifier)

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        await register_failed_attempt(db, identifier)
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="الحساب معطل")

    await clear_failed_attempts(db, identifier)

    access = create_access_token(user["id"], user["email"], user["role"])
    refresh = create_refresh_token(user["id"])
    set_auth_cookies(response, access, refresh)

    await write_audit({"id": user["id"], "email": user["email"], "role": user["role"]},
                      "login", "auth", entity_id=user["id"], request=request)

    return {
        "access_token": access,
        "refresh_token": refresh,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "department_id": user.get("department_id"),
        },
    }


@api.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user), request: Request = None):
    clear_auth_cookies(response)
    await write_audit(user, "logout", "auth", entity_id=user["id"], request=request)
    return {"status": "ok"}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# ===== USERS (admin only) =====
@api.get("/users")
async def list_users(user: dict = Depends(require_roles("super_admin", "digital_health_manager"))):
    docs = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)
    return docs


@api.post("/users")
async def create_user(
    body: UserCreate,
    request: Request,
    user: dict = Depends(require_roles("super_admin")),
):
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="البريد الإلكتروني مسجل مسبقاً")
    doc = {
        "id": _new_id(),
        "email": email,
        "full_name": body.full_name,
        "password_hash": hash_password(body.password),
        "role": body.role,
        "department_id": body.department_id,
        "is_active": True,
        "created_at": _now_iso(),
    }
    await db.users.insert_one(doc)
    _strip_mongo_id(doc)
    await write_audit(user, "create_user", "users", entity_id=doc["id"],
                      new_value={"email": email, "role": body.role}, request=request)
    return {k: v for k, v in doc.items() if k != "password_hash"}


@api.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    user: dict = Depends(require_roles("super_admin")),
):
    existing = await db.users.find_one({"id": user_id})
    if not existing:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "password" in update:
        update["password_hash"] = hash_password(update.pop("password"))
    await db.users.update_one({"id": user_id}, {"$set": update})
    await write_audit(user, "update_user", "users", entity_id=user_id,
                      old_value={"role": existing.get("role"), "is_active": existing.get("is_active")},
                      new_value=update, request=request)
    return {"status": "ok"}


# ===== DEPARTMENTS =====
@api.get("/departments")
async def list_departments(user: dict = Depends(get_current_user)):
    docs = await db.departments.find({}, {"_id": 0}).to_list(1000)
    return docs


@api.post("/departments")
async def create_department(
    body: DepartmentCreate,
    request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager")),
):
    if await db.departments.find_one({"code": body.code}):
        raise HTTPException(status_code=400, detail="رمز القسم مستخدم")
    doc = {"id": _new_id(), **body.model_dump(), "created_at": _now_iso()}
    await db.departments.insert_one(doc)
    _strip_mongo_id(doc)
    await write_audit(user, "create_department", "departments", entity_id=doc["id"],
                      new_value=body.model_dump(), request=request)
    return doc


# ===== ITEMS =====
@api.get("/items")
async def list_items(
    user: dict = Depends(get_current_user),
    search: Optional[str] = None,
    category: Optional[str] = None,
    only_active: bool = True,
):
    q: dict = {}
    if only_active:
        q["is_active"] = True
    if category:
        q["category"] = category
    if search:
        q["$or"] = [
            {"internal_code": {"$regex": search, "$options": "i"}},
            {"name_ar": {"$regex": search, "$options": "i"}},
            {"name_en": {"$regex": search, "$options": "i"}},
            {"barcode": {"$regex": search, "$options": "i"}},
        ]
    docs = await db.items.find(q, {"_id": 0}).sort("name_ar", 1).to_list(2000)
    return docs


@api.post("/items")
async def create_item(
    body: ItemCreate,
    request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager", "supply_officer")),
):
    if await db.items.find_one({"internal_code": body.internal_code}):
        raise HTTPException(status_code=400, detail="رمز الصنف الداخلي مستخدم")
    if body.barcode and await db.items.find_one({"barcode": body.barcode}):
        raise HTTPException(status_code=400, detail="الباركود مكرر")
    doc = {
        "id": _new_id(),
        **body.model_dump(),
        "is_active": True,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.items.insert_one(doc)
    _strip_mongo_id(doc)
    await write_audit(user, "create_item", "items", entity_id=doc["id"],
                      new_value=body.model_dump(), request=request)
    return doc


@api.patch("/items/{item_id}")
async def update_item(
    item_id: str,
    body: ItemUpdate,
    request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager", "supply_officer")),
):
    existing = await db.items.find_one({"id": item_id})
    if not existing:
        raise HTTPException(status_code=404, detail="الصنف غير موجود")
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    update["updated_at"] = _now_iso()
    await db.items.update_one({"id": item_id}, {"$set": update})

    # Recalculate stock statuses if min/critical changed
    if "min_level" in update or "critical_threshold" in update:
        item = await db.items.find_one({"id": item_id})
        async for entry in db.stock_entries.find({"item_id": item_id}):
            new_status = _calc_stock_status(entry["balance"], item["min_level"], item["critical_threshold"])
            await db.stock_entries.update_one(
                {"id": entry["id"]}, {"$set": {"status": new_status}}
            )

    await write_audit(user, "update_item", "items", entity_id=item_id,
                      old_value=existing, new_value=update, request=request)
    return {"status": "ok"}


# ===== STOCK =====
@api.get("/stock")
async def list_stock(
    user: dict = Depends(get_current_user),
    department_id: Optional[str] = None,
    status: Optional[str] = None,
):
    q: dict = {}
    if department_id:
        q["department_id"] = department_id
    if status:
        q["status"] = status
    # Department officers see only their own department
    if user["role"] in ("department_stock_officer", "department_head") and user.get("department_id"):
        q["department_id"] = user["department_id"]
    docs = await db.stock_entries.find(q, {"_id": 0}).to_list(5000)

    # Enrich with item + department info
    item_map = {}
    dept_map = {}
    for d in docs:
        if d["item_id"] not in item_map:
            item_map[d["item_id"]] = await db.items.find_one(
                {"id": d["item_id"]}, {"_id": 0}
            )
        if d["department_id"] not in dept_map:
            dept_map[d["department_id"]] = await db.departments.find_one(
                {"id": d["department_id"]}, {"_id": 0}
            )
        d["item"] = item_map[d["item_id"]]
        d["department"] = dept_map[d["department_id"]]
    return docs


@api.post("/stock")
async def upsert_stock(
    body: StockEntryUpdate,
    request: Request,
    user: dict = Depends(require_roles(
        "super_admin", "department_stock_officer", "department_head", "supply_officer"
    )),
):
    if user["role"] in ("department_stock_officer", "department_head"):
        if user.get("department_id") != body.department_id:
            raise HTTPException(status_code=403, detail="لا يمكنك إدخال رصيد لقسم آخر")

    item = await db.items.find_one({"id": body.item_id})
    if not item:
        raise HTTPException(status_code=404, detail="الصنف غير موجود")
    dept = await db.departments.find_one({"id": body.department_id})
    if not dept:
        raise HTTPException(status_code=404, detail="القسم غير موجود")

    existing = await db.stock_entries.find_one({"department_id": body.department_id, "item_id": body.item_id})
    new_status = _calc_stock_status(body.balance, item["min_level"], item["critical_threshold"])
    previous_balance = existing["balance"] if existing else None
    previous_status = existing["status"] if existing else None

    shortage_start = None
    if new_status in ("zero_level", "critical_level"):
        if existing and existing.get("shortage_start"):
            shortage_start = existing["shortage_start"]
        else:
            shortage_start = _now_iso()

    entry_doc = {
        "department_id": body.department_id,
        "item_id": body.item_id,
        "balance": body.balance,
        "status": new_status,
        "last_updated_by": user["id"],
        "last_updated_by_name": user["full_name"],
        "last_updated_at": _now_iso(),
        "shortage_start": shortage_start,
        "notes": body.notes,
    }
    if existing:
        await db.stock_entries.update_one({"id": existing["id"]}, {"$set": entry_doc})
        entry_id = existing["id"]
    else:
        entry_id = _new_id()
        await db.stock_entries.insert_one({"id": entry_id, **entry_doc})

    await db.stock_transactions.insert_one({
        "id": _new_id(),
        "department_id": body.department_id,
        "item_id": body.item_id,
        "previous_balance": previous_balance,
        "new_balance": body.balance,
        "delta": body.balance - (previous_balance or 0),
        "status": new_status,
        "user_id": user["id"],
        "user_name": user["full_name"],
        "created_at": _now_iso(),
        "reason": body.notes,
    })

    # Generate alerts on status change
    if new_status != previous_status:
        if new_status == "zero_level":
            sev = "critical" if item.get("is_life_saving") else "danger"
            await db.alerts.insert_one({
                "id": _new_id(),
                "type": "zero_level",
                "severity": sev,
                "title": f"صفر مخزون - {item['name_ar']}",
                "message": f"الرصيد في {dept['code']} وصل إلى صفر",
                "department_id": body.department_id,
                "item_id": body.item_id,
                "request_id": None,
                "created_at": _now_iso(),
                "acknowledged": False, "acknowledged_by": None, "acknowledged_at": None,
            })
            if item.get("is_life_saving"):
                await db.alerts.insert_one({
                    "id": _new_id(),
                    "type": "life_saving_item",
                    "severity": "critical",
                    "title": f"تنبيه فوري: صنف منقذ للحياة غير متوفر - {item['name_ar']}",
                    "message": f"القسم: {dept['code']} - يلزم إجراء فوري",
                    "department_id": body.department_id,
                    "item_id": body.item_id,
                    "request_id": None,
                    "created_at": _now_iso(),
                    "acknowledged": False, "acknowledged_by": None, "acknowledged_at": None,
                })
        elif new_status == "critical_level":
            await db.alerts.insert_one({
                "id": _new_id(),
                "type": "critical_level",
                "severity": "warning",
                "title": f"مخزون حرج - {item['name_ar']}",
                "message": f"الرصيد في {dept['code']} = {body.balance} (الحد الحرج {item['critical_threshold']})",
                "department_id": body.department_id,
                "item_id": body.item_id,
                "request_id": None,
                "created_at": _now_iso(),
                "acknowledged": False, "acknowledged_by": None, "acknowledged_at": None,
            })
        elif new_status == "available" and previous_status in ("zero_level", "critical_level"):
            # Mark briefly as back_in_stock for visibility
            await db.stock_entries.update_one(
                {"id": entry_id}, {"$set": {"status": "back_in_stock", "shortage_start": None}}
            )
            new_status = "back_in_stock"
            await db.alerts.insert_one({
                "id": _new_id(),
                "type": "zero_level",  # informational reuse
                "severity": "info",
                "title": f"عاد الصنف للمخزون - {item['name_ar']}",
                "message": f"القسم: {dept['code']} - الرصيد الجديد {body.balance}",
                "department_id": body.department_id,
                "item_id": body.item_id,
                "request_id": None,
                "created_at": _now_iso(),
                "acknowledged": False, "acknowledged_by": None, "acknowledged_at": None,
            })

    await write_audit(user, "upsert_stock", "stock_entries", entity_id=entry_id,
                      old_value={"balance": previous_balance, "status": previous_status},
                      new_value={"balance": body.balance, "status": new_status},
                      request=request)
    return {"status": "ok", "stock_status": new_status}


@api.get("/stock/transactions")
async def list_transactions(
    item_id: Optional[str] = None,
    department_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q: dict = {}
    if item_id:
        q["item_id"] = item_id
    if department_id:
        q["department_id"] = department_id
    docs = await db.stock_transactions.find(q, {"_id": 0}).sort("created_at", -1).limit(500).to_list(500)
    return docs


# ===== REQUESTS =====
async def _gen_request_number() -> str:
    n = await db.stock_requests.count_documents({})
    return f"REQ-{datetime.now(timezone.utc).strftime('%Y%m')}-{n + 1:05d}"


@api.get("/requests")
async def list_requests(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    department_id: Optional[str] = None,
):
    q: dict = {}
    if status:
        q["status"] = status
    if department_id:
        q["department_id"] = department_id
    if user["role"] in ("department_stock_officer", "department_head") and user.get("department_id"):
        q["department_id"] = user["department_id"]
    docs = await db.stock_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)

    for d in docs:
        d["item"] = await db.items.find_one({"id": d["item_id"]}, {"_id": 0})
        d["department"] = await db.departments.find_one({"id": d["department_id"]}, {"_id": 0})
    return docs


@api.post("/requests")
async def create_request(
    body: StockRequestCreate,
    request: Request,
    user: dict = Depends(require_roles(
        "super_admin", "department_stock_officer", "department_head"
    )),
):
    if user["role"] in ("department_stock_officer", "department_head"):
        if user.get("department_id") != body.department_id:
            raise HTTPException(status_code=403, detail="لا يمكنك رفع طلب لقسم آخر")

    item = await db.items.find_one({"id": body.item_id})
    if not item:
        raise HTTPException(status_code=404, detail="الصنف غير موجود")
    if not await db.departments.find_one({"id": body.department_id}):
        raise HTTPException(status_code=404, detail="القسم غير موجود")

    req_num = await _gen_request_number()
    doc = {
        "id": _new_id(),
        "request_number": req_num,
        "department_id": body.department_id,
        "item_id": body.item_id,
        "requested_qty": body.requested_qty,
        "approved_qty": None,
        "dispatched_qty": 0,
        "received_qty": 0,
        "priority": body.priority,
        "reason": body.reason,
        "status": "pending_approval",
        "created_by": user["id"],
        "created_by_name": user["full_name"],
        "created_at": _now_iso(),
        "approved_by": None, "approved_at": None, "rejected_reason": None,
        "dispatched_at": None, "received_at": None, "closed_at": None,
        "expected_supply_date": None,
    }
    await db.stock_requests.insert_one(doc)
    _strip_mongo_id(doc)
    await write_audit(user, "create_request", "requests", entity_id=doc["id"],
                      new_value={"req": req_num, "qty": body.requested_qty}, request=request)
    return doc


@api.post("/requests/{req_id}/approve")
async def approve_request(
    req_id: str, body: ApproveBody, request: Request,
    user: dict = Depends(require_roles("super_admin", "department_head", "supply_officer")),
):
    req = await db.stock_requests.find_one({"id": req_id})
    if not req:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if req["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="الطلب ليس في حالة انتظار الاعتماد")
    if user["role"] == "department_head" and user.get("department_id") != req["department_id"]:
        raise HTTPException(status_code=403, detail="لا تستطيع اعتماد طلب من قسم آخر")
    await db.stock_requests.update_one({"id": req_id}, {"$set": {
        "approved_qty": body.approved_qty,
        "approved_by": user["id"],
        "approved_at": _now_iso(),
        "status": "approved",
    }})
    await write_audit(user, "approve_request", "requests", entity_id=req_id,
                      new_value={"approved_qty": body.approved_qty}, request=request)
    return {"status": "ok"}


@api.post("/requests/{req_id}/reject")
async def reject_request(
    req_id: str, body: RejectBody, request: Request,
    user: dict = Depends(require_roles("super_admin", "department_head", "supply_officer")),
):
    req = await db.stock_requests.find_one({"id": req_id})
    if not req:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    await db.stock_requests.update_one({"id": req_id}, {"$set": {
        "status": "rejected",
        "rejected_reason": body.reason,
        "approved_by": user["id"],
        "approved_at": _now_iso(),
    }})
    await write_audit(user, "reject_request", "requests", entity_id=req_id,
                      new_value={"reason": body.reason}, request=request)
    return {"status": "ok"}


@api.post("/requests/{req_id}/dispatch")
async def dispatch_request(
    req_id: str, body: DispatchBody, request: Request,
    user: dict = Depends(require_roles("super_admin", "supply_officer")),
):
    req = await db.stock_requests.find_one({"id": req_id})
    if not req:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if req["status"] not in ("approved", "backorder"):
        raise HTTPException(status_code=400, detail="الطلب يجب أن يكون معتمداً")

    update = {
        "dispatched_qty": body.dispatched_qty,
        "dispatched_at": _now_iso(),
        "expected_supply_date": body.expected_supply_date,
    }
    if body.backorder:
        update["status"] = "backorder"
        # Generate backorder alert
        item = await db.items.find_one({"id": req["item_id"]}, {"_id": 0})
        dept = await db.departments.find_one({"id": req["department_id"]}, {"_id": 0})
        await db.alerts.insert_one({
            "id": _new_id(),
            "type": "backorder",
            "severity": "critical" if item.get("is_life_saving") else "warning",
            "title": f"Backorder - {item['name_ar']}",
            "message": f"الطلب {req['request_number']} - القسم {dept['code']}",
            "department_id": req["department_id"],
            "item_id": req["item_id"],
            "request_id": req_id,
            "created_at": _now_iso(),
            "acknowledged": False, "acknowledged_by": None, "acknowledged_at": None,
        })
    else:
        update["status"] = "dispatched"
    await db.stock_requests.update_one({"id": req_id}, {"$set": update})
    await write_audit(user, "dispatch_request", "requests", entity_id=req_id,
                      new_value=update, request=request)
    return {"status": "ok"}


@api.post("/requests/{req_id}/receive")
async def receive_request(
    req_id: str, body: ReceiveBody, request: Request,
    user: dict = Depends(require_roles(
        "super_admin", "department_head", "department_stock_officer", "supply_officer"
    )),
):
    req = await db.stock_requests.find_one({"id": req_id})
    if not req:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if user["role"] in ("department_head", "department_stock_officer") and user.get("department_id") != req["department_id"]:
        raise HTTPException(status_code=403, detail="لا تستطيع الاستلام لقسم آخر")
    if req["status"] not in ("dispatched", "partially_received"):
        raise HTTPException(status_code=400, detail="لا يمكن الاستلام في الحالة الحالية")

    new_received = req["received_qty"] + body.received_qty
    if new_received >= req["dispatched_qty"]:
        new_status = "received"
        closed = _now_iso()
    else:
        new_status = "partially_received"
        closed = None

    update = {
        "received_qty": new_received,
        "received_at": _now_iso(),
        "status": new_status,
        "closed_at": closed,
    }
    await db.stock_requests.update_one({"id": req_id}, {"$set": update})

    # Auto-increase department stock balance
    item = await db.items.find_one({"id": req["item_id"]})
    entry = await db.stock_entries.find_one({"department_id": req["department_id"], "item_id": req["item_id"]})
    if entry:
        new_balance = entry["balance"] + body.received_qty
        new_st = _calc_stock_status(new_balance, item["min_level"], item["critical_threshold"])
        # if previous status was zero/critical and we now hit available
        if entry["status"] in ("zero_level", "critical_level") and new_st == "available":
            new_st = "back_in_stock"
        await db.stock_entries.update_one({"id": entry["id"]}, {"$set": {
            "balance": new_balance, "status": new_st,
            "last_updated_by": user["id"], "last_updated_by_name": user["full_name"],
            "last_updated_at": _now_iso(),
            "shortage_start": None if new_st in ("available", "back_in_stock") else entry.get("shortage_start"),
        }})
        await db.stock_transactions.insert_one({
            "id": _new_id(),
            "department_id": req["department_id"],
            "item_id": req["item_id"],
            "previous_balance": entry["balance"],
            "new_balance": new_balance,
            "delta": body.received_qty,
            "status": new_st,
            "user_id": user["id"],
            "user_name": user["full_name"],
            "created_at": _now_iso(),
            "reason": f"استلام طلب {req['request_number']}",
        })

    await write_audit(user, "receive_request", "requests", entity_id=req_id,
                      new_value={"received": body.received_qty}, request=request)
    return {"status": "ok"}


# ===== ALERTS =====
@api.get("/alerts")
async def list_alerts(
    user: dict = Depends(get_current_user),
    acknowledged: Optional[bool] = None,
    severity: Optional[str] = None,
    limit: int = 200,
):
    q: dict = {}
    if acknowledged is not None:
        q["acknowledged"] = acknowledged
    if severity:
        q["severity"] = severity
    docs = await db.alerts.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    for d in docs:
        if d.get("item_id"):
            d["item"] = await db.items.find_one({"id": d["item_id"]}, {"_id": 0})
        if d.get("department_id"):
            d["department"] = await db.departments.find_one({"id": d["department_id"]}, {"_id": 0})
    return docs


@api.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, request: Request, user: dict = Depends(get_current_user)):
    await db.alerts.update_one({"id": alert_id}, {"$set": {
        "acknowledged": True,
        "acknowledged_by": user["id"],
        "acknowledged_at": _now_iso(),
    }})
    await write_audit(user, "acknowledge_alert", "alerts", entity_id=alert_id, request=request)
    return {"status": "ok"}


# ===== DASHBOARD =====
@api.get("/dashboard/kpis")
async def dashboard_kpis(user: dict = Depends(get_current_user)):
    q_stock: dict = {}
    if user["role"] in ("department_stock_officer", "department_head") and user.get("department_id"):
        q_stock["department_id"] = user["department_id"]

    zero_count = await db.stock_entries.count_documents({**q_stock, "status": "zero_level"})
    crit_count = await db.stock_entries.count_documents({**q_stock, "status": "critical_level"})
    back_count = await db.stock_entries.count_documents({**q_stock, "status": "back_in_stock"})
    avail_count = await db.stock_entries.count_documents({**q_stock, "status": "available"})

    backorder_count = await db.stock_requests.count_documents({"status": "backorder"})
    pending_count = await db.stock_requests.count_documents({"status": "pending_approval"})
    dispatched_count = await db.stock_requests.count_documents({"status": "dispatched"})

    open_alerts = await db.alerts.count_documents({"acknowledged": False})

    # Life-saving items at risk
    life_saving_items = await db.items.find({"is_life_saving": True}, {"_id": 0, "id": 1}).to_list(500)
    life_saving_ids = [i["id"] for i in life_saving_items]
    life_saving_risk = await db.stock_entries.count_documents({
        **q_stock,
        "item_id": {"$in": life_saving_ids},
        "status": {"$in": ["zero_level", "critical_level"]},
    })

    # Not updated 24h+
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    stale = await db.stock_entries.count_documents({**q_stock, "last_updated_at": {"$lt": cutoff}})

    # Top affected departments
    pipeline = [
        {"$match": {"status": {"$in": ["zero_level", "critical_level"]}}},
        {"$group": {"_id": "$department_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 5},
    ]
    top_dept_raw = await db.stock_entries.aggregate(pipeline).to_list(10)
    top_departments = []
    for r in top_dept_raw:
        d = await db.departments.find_one({"id": r["_id"]}, {"_id": 0})
        if d:
            top_departments.append({"department": d, "count": r["count"]})

    # Recent activity
    recent_alerts = await db.alerts.find({}, {"_id": 0}).sort("created_at", -1).limit(8).to_list(8)
    for d in recent_alerts:
        if d.get("item_id"):
            d["item"] = await db.items.find_one({"id": d["item_id"]}, {"_id": 0})
        if d.get("department_id"):
            d["department"] = await db.departments.find_one({"id": d["department_id"]}, {"_id": 0})

    # Stock status distribution by department
    pipeline2 = [
        {"$group": {"_id": {"dept": "$department_id", "status": "$status"}, "count": {"$sum": 1}}},
    ]
    raw = await db.stock_entries.aggregate(pipeline2).to_list(500)
    dept_status: dict = {}
    for r in raw:
        dept_id = r["_id"]["dept"]
        if dept_id not in dept_status:
            d = await db.departments.find_one({"id": dept_id}, {"_id": 0})
            dept_status[dept_id] = {"department": d, "zero_level": 0, "critical_level": 0,
                                    "available": 0, "back_in_stock": 0}
        dept_status[dept_id][r["_id"]["status"]] = r["count"]

    return {
        "zero_count": zero_count,
        "critical_count": crit_count,
        "back_in_stock_count": back_count,
        "available_count": avail_count,
        "backorder_count": backorder_count,
        "pending_requests": pending_count,
        "dispatched_requests": dispatched_count,
        "open_alerts": open_alerts,
        "life_saving_risk": life_saving_risk,
        "stale_count": stale,
        "top_departments": top_departments,
        "recent_alerts": recent_alerts,
        "by_department": list(dept_status.values()),
    }


# ===== AUDIT =====
@api.get("/audit-logs")
async def list_audit_logs(
    user: dict = Depends(require_roles(
        "super_admin", "digital_health_manager", "auditor"
    )),
    entity: Optional[str] = None,
    limit: int = 300,
):
    q: dict = {}
    if entity:
        q["entity"] = entity
    docs = await db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return docs


# ===== REPORTS =====
@api.get("/reports/{report_name}")
async def reports(
    report_name: str,
    user: dict = Depends(get_current_user),
):
    docs: list = []
    if report_name == "zero_level":
        docs = await db.stock_entries.find({"status": "zero_level"}, {"_id": 0}).to_list(2000)
    elif report_name == "critical_level":
        docs = await db.stock_entries.find({"status": "critical_level"}, {"_id": 0}).to_list(2000)
    elif report_name == "backorder":
        docs = await db.stock_requests.find({"status": "backorder"}, {"_id": 0}).to_list(2000)
    elif report_name == "open_requests":
        docs = await db.stock_requests.find(
            {"status": {"$in": ["pending_approval", "approved", "dispatched", "partially_received", "backorder"]}},
            {"_id": 0}
        ).to_list(2000)
    elif report_name == "no_barcode":
        docs = await db.items.find({"$or": [{"barcode": None}, {"barcode": ""}]}, {"_id": 0}).to_list(2000)
    elif report_name == "life_saving":
        items = await db.items.find({"is_life_saving": True}, {"_id": 0}).to_list(500)
        item_ids = [i["id"] for i in items]
        docs = await db.stock_entries.find(
            {"item_id": {"$in": item_ids}, "status": {"$in": ["zero_level", "critical_level"]}},
            {"_id": 0}
        ).to_list(500)
    else:
        raise HTTPException(status_code=404, detail="تقرير غير معروف")

    # enrich
    for d in docs:
        if "item_id" in d:
            d["item"] = await db.items.find_one({"id": d["item_id"]}, {"_id": 0})
        if "department_id" in d:
            d["department"] = await db.departments.find_one({"id": d["department_id"]}, {"_id": 0})
    return {"report": report_name, "count": len(docs), "rows": docs}


@api.get("/reports/{report_name}/export.csv")
async def export_report_csv(report_name: str, user: dict = Depends(get_current_user)):
    data = await reports(report_name, user)
    rows = data["rows"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Common header set
    writer.writerow([
        "department_code", "item_code", "item_name_ar", "item_name_en",
        "balance", "status", "min_level", "critical_threshold", "last_updated_at",
        "request_number", "requested_qty", "priority"
    ])
    for r in rows:
        item = r.get("item") or {}
        dept = r.get("department") or {}
        writer.writerow([
            dept.get("code", ""),
            item.get("internal_code", ""),
            item.get("name_ar", ""),
            item.get("name_en", ""),
            r.get("balance", ""),
            r.get("status", ""),
            item.get("min_level", ""),
            item.get("critical_threshold", ""),
            r.get("last_updated_at", ""),
            r.get("request_number", ""),
            r.get("requested_qty", ""),
            r.get("priority", ""),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={report_name}.csv"},
    )


# ----- Health -----
@api.get("/")
async def root():
    return {"status": "ok", "service": "medical-stock-monitoring"}


app.include_router(api)


# ----- CORS -----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,           # we use bearer header from frontend; cookies optional
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- Startup -----
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.items.create_index("internal_code", unique=True)
    await db.items.create_index("barcode")
    await db.departments.create_index("code", unique=True)
    await db.stock_entries.create_index([("department_id", 1), ("item_id", 1)], unique=True)
    await db.stock_requests.create_index("request_number", unique=True)
    await db.alerts.create_index("created_at")
    await db.audit_logs.create_index("created_at")
    await db.login_attempts.create_index("identifier")
    try:
        await seed_data(db)
        logger.info("Seed data ensured.")
    except Exception as e:
        logger.exception("Seed failed: %s", e)


@app.on_event("shutdown")
async def shutdown():
    client.close()
