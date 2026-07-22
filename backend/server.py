"""Critical Medical Stock Monitoring & Alerting System - main API."""
from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import asyncio
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, BackgroundTasks, Header
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError
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
from state_machine import validate_request_transition, validate_alert_transition
from settings_store import get_settings, update_settings
import scheduler as scheduler_mod
import excel_import
import stock_issue
import email_service
import ledger as ledger_mod
import ledger_backfill
from models import (
    UserCreate, UserUpdate, LoginBody,
    DepartmentCreate, ItemCreate, ItemUpdate,
    StockEntryUpdate, StockRequestCreate,
    ApproveBody, RejectBody, DispatchBody, ReceiveBody,
    ThresholdUpdate, StockIssuePreviewBody, StockIssueBody,
    EscalationRecipientUpdate, ReportEmailBody,
    _new_id, _now_iso,
)
from seed import seed as seed_data
from runtime_config import load_runtime_config, parse_cors_origins


# ---------- App ----------
# MongoDB client and database are created during the startup lifecycle event.
# These module-level names are reassigned in startup() so that all route
# functions that close over `db` pick up the live connection.
client: AsyncMongoClient | None = None  # type: ignore[type-arg]
db = None  # type: ignore[assignment]

app = FastAPI(title="Critical Medical Stock Monitoring System")

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
    session=None,
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
    await db.audit_logs.insert_one(doc, session=session)


def _calc_stock_status(balance: int, min_level: int, critical_threshold: int) -> str:
    if balance == 0:
        return "zero_level"
    if balance < critical_threshold:
        return "critical_level"
    if balance < min_level:
        return "critical_level"
    return "available"


def _validate_idempotent_replay(prior: dict, *, source: str, department_id: str, item_id: str, entry_type: str, **op_fields) -> None:
    """Raise HTTP 409 if prior ledger record doesn't match this operation's payload."""
    mismatches = []
    for field, expected in [
        ("source", source),
        ("department_id", department_id),
        ("item_id", item_id),
        ("entry_type", entry_type),
    ]:
        if prior.get(field) != expected:
            mismatches.append(field)
    for field, expected in op_fields.items():
        if prior.get(field) != expected:
            mismatches.append(field)
    if mismatches:
        raise HTTPException(status_code=409, detail=f"Idempotency key reused with different payload: {mismatches}")


_RESERVED_IDEM_PREFIXES = ("baseline:", "excel:", "seed:")


def _check_reserved_idempotency_key(key: Optional[str]) -> None:
    """Raise HTTP 422 if the key uses an internally-reserved namespace prefix."""
    if not key:
        return
    for prefix in _RESERVED_IDEM_PREFIXES:
        if key.startswith(prefix):
            raise HTTPException(
                status_code=422,
                detail=f"Idempotency key may not use reserved '{prefix}' prefix",
            )


def _strip_mongo_id(doc: dict) -> dict:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


def _new_alert(
    *, type: str, severity: str, title: str, message: str,
    department_id=None, item_id=None, request_id=None,
    escalated_to: str = None, escalation_level: int = 0,
) -> dict:
    """Build a fresh alert document with full lifecycle fields."""
    escalations = []
    if escalation_level > 0 and escalated_to:
        escalations.append({
            "level": escalation_level,
            "at": _now_iso(),
            "escalated_to": escalated_to,
            "reason": "Created at escalation level",
        })
    return {
        "id": _new_id(),
        "type": type,
        "severity": severity,
        "status": "open",
        "title": title,
        "message": message,
        "department_id": department_id,
        "item_id": item_id,
        "request_id": request_id,
        "created_at": _now_iso(),
        "escalation_level": escalation_level,
        "escalations": escalations,
        "escalated_to": escalated_to,
        "sla_due_at": None,
        # backwards-compat fields
        "acknowledged": False,
        "acknowledged_by": None, "acknowledged_at": None,
        "in_progress_by": None, "in_progress_at": None,
        "resolution_note": None,
        "resolved_by": None, "resolved_at": None,
        "closed_at": None,
    }


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
        raise HTTPException(status_code=401, detail="Invalid login credentials")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is disabled")

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
        raise HTTPException(status_code=400, detail="Email is already registered")
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
        raise HTTPException(status_code=404, detail="User not found")
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
        raise HTTPException(status_code=400, detail="Department code already in use")
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
        raise HTTPException(status_code=400, detail="Internal item code already in use")
    if body.barcode and await db.items.find_one({"barcode": body.barcode}):
        raise HTTPException(status_code=400, detail="Barcode is duplicated")
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
        raise HTTPException(status_code=404, detail="Item not found")
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
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(require_roles(
        "super_admin", "department_stock_officer", "department_head", "supply_officer"
    )),
):
    if user["role"] in ("department_stock_officer", "department_head"):
        if user.get("department_id") != body.department_id:
            raise HTTPException(status_code=403, detail="You cannot post stock for a different department")

    _check_reserved_idempotency_key(idempotency_key)

    # Fast 404 guards before starting a transaction
    if not await db.items.find_one({"id": body.item_id}, {"_id": 0}):
        raise HTTPException(status_code=404, detail="Item not found")
    if not await db.departments.find_one({"id": body.department_id}, {"_id": 0}):
        raise HTTPException(status_code=404, detail="Department not found")

    idem_key = idempotency_key or _new_id()

    # Fast idempotency pre-check (avoids starting a transaction for replays)
    prior = await db.stock_transactions.find_one({"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0})
    if prior:
        _validate_idempotent_replay(prior, source="upsert_stock", department_id=body.department_id,
                                    item_id=body.item_id, entry_type=prior.get("entry_type", "adjustment"),
                                    new_balance=body.balance)
        return {"status": "ok", "stock_status": prior.get("status"), "idempotent_replay": True}

    fail_after = request.headers.get("X-Test-Txn-Fail-After") if _TXN_HOOKS_ACTIVE else None

    async def _txn_callback(session):
        # Recheck idempotency key inside transaction (race-condition guard)
        prior_inner = await db.stock_transactions.find_one(
            {"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0}, session=session
        )
        if prior_inner:
            _validate_idempotent_replay(prior_inner, source="upsert_stock", department_id=body.department_id,
                                        item_id=body.item_id, entry_type=prior_inner.get("entry_type", "adjustment"),
                                        new_balance=body.balance)
            return {"status": "ok", "stock_status": prior_inner.get("status"), "idempotent_replay": True}

        item_inner = await db.items.find_one({"id": body.item_id}, {"_id": 0}, session=session)
        if not item_inner:
            raise HTTPException(status_code=404, detail="Item not found")
        dept_inner = await db.departments.find_one(
            {"id": body.department_id}, {"_id": 0}, session=session
        )
        if not dept_inner:
            raise HTTPException(status_code=404, detail="Department not found")

        existing = await db.stock_entries.find_one(
            {"department_id": body.department_id, "item_id": body.item_id},
            session=session,
        )
        previous_balance = existing["balance"] if existing else 0
        previous_status = existing["status"] if existing else None
        quantity_change = body.balance - previous_balance
        entry_type = "opening_balance" if existing is None else "adjustment"

        # Determine final stock status upfront (including back_in_stock) so stock_entry
        # is written exactly once with its final state.
        raw_status = _calc_stock_status(body.balance, item_inner["min_level"], item_inner["critical_threshold"])
        if raw_status == "available" and previous_status in ("zero_level", "critical_level"):
            new_status = "back_in_stock"
        else:
            new_status = raw_status

        shortage_start = None
        if new_status in ("zero_level", "critical_level"):
            shortage_start = (
                existing.get("shortage_start") if existing and existing.get("shortage_start")
                else _now_iso()
            )

        entry_id = existing["id"] if existing else _new_id()
        previous_lv = existing.get("ledger_version", 0) if existing else 0

        if existing is None:
            # New stock entry
            seq_no = 1
        elif previous_lv == 0:
            # Legacy stock entry without v2 ledger history — create cutover baseline first
            await ledger_mod.ensure_v2_baseline(
                db,
                department_id=body.department_id,
                item_id=body.item_id,
                entry_id=entry_id,
                balance=previous_balance,
                user_id=user["id"],
                user_name=user["full_name"],
                idempotency_key=f"baseline:{body.department_id}:{body.item_id}",
                status=_calc_stock_status(previous_balance, item_inner["min_level"], item_inner["critical_threshold"]),
                source="ledger_v2_cutover",
                session=session,
            )
            seq_no = 2
        else:
            # Existing v2 entry
            seq_no = previous_lv + 1

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
            filter_doc = {"id": entry_id, "balance": previous_balance}
            if previous_lv >= 1:
                filter_doc["ledger_version"] = previous_lv
            else:
                filter_doc["$or"] = [{"ledger_version": {"$exists": False}}, {"ledger_version": 0}]
            upd = await db.stock_entries.update_one(
                filter_doc, {"$set": {**entry_doc, "ledger_version": seq_no}}, session=session
            )
            if upd.matched_count != 1:
                raise HTTPException(status_code=409, detail="Concurrent modification: please retry.")
        else:
            await db.stock_entries.insert_one({"id": entry_id, **entry_doc, "ledger_version": seq_no}, session=session)
        _check_fail_point(fail_after, "stock_update")

        # Alerts — inside the transaction so they roll back atomically with the ledger
        if new_status != previous_status:
            if new_status == "zero_level":
                sev = "critical" if item_inner.get("is_life_saving") else "danger"
                await db.alerts.insert_one(_new_alert(
                    type="zero_level", severity=sev,
                    title=f"Zero stock — {item_inner['name_en']}",
                    message=f"Balance in {dept_inner['code']} reached zero",
                    department_id=body.department_id, item_id=body.item_id,
                ), session=session)
                if item_inner.get("is_life_saving"):
                    await db.alerts.insert_one(_new_alert(
                        type="life_saving_item", severity="critical",
                        title=f"URGENT: Life-saving item out of stock — {item_inner['name_en']}",
                        message=f"Department: {dept_inner['code']} — immediate action required",
                        department_id=body.department_id, item_id=body.item_id,
                        escalated_to="hospital_manager", escalation_level=1,
                    ), session=session)
            elif new_status == "critical_level":
                await db.alerts.insert_one(_new_alert(
                    type="critical_level", severity="warning",
                    title=f"Critical stock — {item_inner['name_en']}",
                    message=f"Balance in {dept_inner['code']} = {body.balance} (critical threshold {item_inner['critical_threshold']})",
                    department_id=body.department_id, item_id=body.item_id,
                ), session=session)
            elif new_status == "back_in_stock":
                await db.alerts.insert_one(_new_alert(
                    type="zero_level", severity="info",
                    title=f"Item back in stock — {item_inner['name_en']}",
                    message=f"Department: {dept_inner['code']} — new balance {body.balance}",
                    department_id=body.department_id, item_id=body.item_id,
                ), session=session)
        _check_fail_point(fail_after, "alert_insert")

        await write_audit(
            user, "upsert_stock", "stock_entries", entity_id=entry_id,
            old_value={"balance": previous_balance if existing else None, "status": previous_status},
            new_value={"balance": body.balance, "status": new_status, "idempotency_key": idem_key},
            request=request,
            session=session,
        )
        _check_fail_point(fail_after, "audit_insert")

        # Final, complete, immutable Ledger v2 record — inserted once
        txn_doc = ledger_mod.build_ledger_entry(
            department_id=body.department_id,
            item_id=body.item_id,
            entry_type=entry_type,
            sequence_no=seq_no,
            previous_balance=previous_balance,
            quantity_change=quantity_change,
            new_balance=body.balance,
            user_id=user["id"],
            user_name=user["full_name"],
            actor_type="user",
            source="upsert_stock",
            idempotency_key=idem_key,
            status=new_status,
            entry_id=entry_id,
            # Extra fields for audit trail
            reason=body.notes,
        )
        await ledger_mod.insert_ledger_entry(db, txn_doc, session=session)
        _check_fail_point(fail_after, "ledger_insert")

        return {"status": "ok", "stock_status": new_status}

    try:
        async with client.start_session() as session:
            result = await session.with_transaction(_txn_callback)
    except _TxnTestFailure as exc:
        logger.warning("Test-injected transaction failure: %s", exc)
        raise HTTPException(status_code=503, detail="Stock update could not be completed. Please retry.")
    except DuplicateKeyError:
        prior = await db.stock_transactions.find_one({"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0})
        if prior:
            _validate_idempotent_replay(prior, source="upsert_stock", department_id=body.department_id,
                                        item_id=body.item_id, entry_type=prior.get("entry_type", "adjustment"),
                                        new_balance=body.balance)
            return {"status": "ok", "stock_status": prior.get("status"), "idempotent_replay": True}
        # Baseline race — retry once if another transaction created the cutover baseline
        baseline_key = f"baseline:{body.department_id}:{body.item_id}"
        baseline = await db.stock_transactions.find_one(
            {"idempotency_key": baseline_key, "schema_version": 2}, {"_id": 0}
        )
        if baseline:
            try:
                async with client.start_session() as _session2:
                    result = await _session2.with_transaction(_txn_callback)
                return result
            except DuplicateKeyError:
                prior2 = await db.stock_transactions.find_one(
                    {"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0}
                )
                if prior2:
                    _validate_idempotent_replay(prior2, source="upsert_stock",
                                                department_id=body.department_id,
                                                item_id=body.item_id,
                                                entry_type=prior2.get("entry_type", "adjustment"),
                                                new_balance=body.balance)
                    return {"status": "ok", "stock_status": prior2.get("status"), "idempotent_replay": True}
                raise HTTPException(status_code=409, detail="Write conflict. Please retry.")
            except HTTPException:
                raise
            except Exception as exc:
                logger.exception("Unexpected error in upsert_stock baseline-race retry", exc_info=exc)
                raise HTTPException(status_code=503, detail="Stock update could not be completed. Please retry.")
        raise HTTPException(status_code=409, detail="Write conflict. Please retry.")

    return result


@api.get("/stock/transactions")
async def list_transactions(
    item_id: Optional[str] = None,
    department_id: Optional[str] = None,
    entry_type: Optional[str] = None,
    override_only: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 500,
    user: dict = Depends(get_current_user),
):
    q: dict = {}
    if item_id:
        q["item_id"] = item_id
    if department_id:
        q["department_id"] = department_id
    if entry_type:
        q["entry_type"] = entry_type
    if override_only:
        q["override_flag"] = True
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["created_at"] = rng
    # Department staff: limit to their own department
    if user["role"] in ("department_stock_officer", "department_head") and user.get("department_id"):
        q["department_id"] = user["department_id"]
    limit = max(1, min(int(limit), 2000))
    docs = await db.stock_transactions.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)

    # Enrich with item + department info (small denormalised payload — same pattern as /stock)
    item_map: dict = {}
    dept_map: dict = {}
    for d in docs:
        if d.get("item_id") and d["item_id"] not in item_map:
            it = await db.items.find_one({"id": d["item_id"]}, {"_id": 0})
            item_map[d["item_id"]] = it
        if d.get("department_id") and d["department_id"] not in dept_map:
            dept_map[d["department_id"]] = await db.departments.find_one(
                {"id": d["department_id"]}, {"_id": 0}
            )
        d["item"] = item_map.get(d.get("item_id"))
        d["department"] = dept_map.get(d.get("department_id"))
    return docs



# ===== STOCK ISSUE (Reserve Control + Escalation) =====
def _decision_severity_to_alert(severity: str) -> str:
    """Map decision severity → alert severity literal."""
    return {
        "info":     "info",
        "warning":  "warning",
        "danger":   "danger",
        "critical": "critical",
    }.get(severity, "warning")


def _decision_to_alert_type(rule: str) -> str:
    return {
        "below_minimum":      "below_minimum_issue",
        "below_critical":     "below_critical_issue",
        "emergency_override": "emergency_override",
    }.get(rule, "critical_level")


async def _escalation_email_task(
    db_, *,
    roles: list[str], title: str, severity: str, message: str,
    department_code: str, item_name: str, extra_rows: list[tuple[str, str]],
):
    """Resolve recipients and send escalation email. Runs fully inside a BackgroundTask.
    Errors are logged and swallowed — never allowed to alter the committed transaction."""
    try:
        recipients = await email_service.resolve_recipients_for_roles(db_, roles)
        if not recipients:
            return
        await email_service.send_alert_email(
            recipients,
            title=title,
            severity=severity,
            message=message,
            department=department_code,
            item=item_name,
            extra_rows=extra_rows,
        )
    except Exception:
        logger.exception(
            "Escalation email failed (roles=%s, title=%r) — "
            "committed stock transaction is unaffected",
            roles, title,
        )


@api.get("/stock-balance/{department_id}/{item_id}")
async def get_stock_balance_endpoint(
    department_id: str,
    item_id: str,
    user: dict = Depends(get_current_user),
):
    # Department officers can only read their own department
    if user["role"] in ("department_stock_officer", "department_head"):
        if user.get("department_id") != department_id:
            raise HTTPException(status_code=403, detail="Cannot read stock for another department")
    return await stock_issue.get_stock_balance(db, item_id, department_id)


@api.post("/stock/issue/preview")
async def stock_issue_preview(
    body: StockIssuePreviewBody,
    user: dict = Depends(require_roles(
        "super_admin", "department_stock_officer", "department_head",
        "supply_officer", "hospital_manager", "digital_health_manager",
    )),
):
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")

    if user["role"] in ("department_stock_officer", "department_head"):
        if user.get("department_id") != body.department_id:
            raise HTTPException(status_code=403, detail="Cannot issue stock for another department")

    item = await db.items.find_one({"id": body.item_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    dept = await db.departments.find_one({"id": body.department_id}, {"_id": 0})
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    threshold = await stock_issue.ensure_threshold(db, body.item_id, body.department_id)
    balance_doc = await stock_issue.get_stock_balance(db, body.item_id, body.department_id)
    current_balance = balance_doc["current_balance"]
    projected = current_balance - body.quantity

    insufficient = projected < 0
    decision = stock_issue.evaluate_issue_decision(
        item=item, threshold=threshold,
        previous_balance=current_balance, projected_balance=projected,
        user_role=user["role"], override_reason=body.override_reason,
    )

    return {
        "current_balance": current_balance,
        "requested_quantity": body.quantity,
        "projected_balance": projected,
        "insufficient_stock": insufficient,
        "minimum_level": threshold["minimum_level"],
        "critical_level": threshold["critical_level"],
        "emergency_reserve_level": threshold["emergency_reserve_level"],
        "no_issue_threshold": threshold["no_issue_threshold"],
        "is_life_saving": bool(item.get("is_life_saving")),
        "allow_emergency_override": bool(threshold.get("allow_emergency_override")),
        "decision": decision,
        "item": {"id": item["id"], "internal_code": item["internal_code"],
                 "name_en": item.get("name_en"), "name_ar": item.get("name_ar")},
        "department": {"id": dept["id"], "code": dept["code"],
                       "name_en": dept.get("name_en"), "name_ar": dept.get("name_ar")},
    }


def _build_idempotent_replay(prior: dict) -> dict:
    """Rebuild the standard response dict from a previously committed transaction."""
    return {
        "success": True,
        "idempotent_replay": True,
        "entry_id": prior.get("entry_id"),
        "transaction_id": prior["id"],
        "previous_balance": prior["previous_balance"],
        "current_balance": prior["new_balance"],
        "status": prior.get("status"),
        "decision": {"rule": prior.get("decision_rule"), "override": prior.get("override_flag")},
        "alert_id": prior.get("alert_id"),
        "alert_severity": prior.get("alert_severity"),
    }


# ---- Test-only failure injection --------------------------------------------
# Active only when APP_ENV=test AND TRANSACTION_TEST_HOOKS_ENABLED=true.
# Never active in development, staging, or production.
_TXN_HOOKS_ACTIVE = (
    os.environ.get("APP_ENV", "").lower() == "test"
    and os.environ.get("TRANSACTION_TEST_HOOKS_ENABLED", "").lower() == "true"
)
_VALID_FAIL_POINTS = frozenset(
    {"transaction_insert", "stock_update", "alert_insert", "audit_insert", "ledger_insert"}
)


class _TxnTestFailure(Exception):
    """Internal exception used only by test failure injection to force rollback."""


def _check_fail_point(header_value: Optional[str], stage: str) -> None:
    """Raise _TxnTestFailure if the test hook requests failure at this stage."""
    if not _TXN_HOOKS_ACTIVE:
        return
    if header_value and header_value.strip() in _VALID_FAIL_POINTS:
        if header_value.strip() == stage:
            raise _TxnTestFailure(f"Test-injected failure at stage: {stage}")


@api.post("/stock/issue")
async def stock_issue_execute(
    body: StockIssueBody,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    user: dict = Depends(require_roles(
        "super_admin", "department_stock_officer", "department_head",
        "supply_officer", "hospital_manager", "digital_health_manager",
    )),
):
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")

    if user["role"] in ("department_stock_officer", "department_head"):
        if user.get("department_id") != body.department_id:
            raise HTTPException(status_code=403, detail="Cannot issue stock for another department")

    _check_reserved_idempotency_key(body.idempotency_key)

    # ---- Pre-transaction fast 404 guards (no session needed) ----
    if not await db.items.find_one({"id": body.item_id}, {"_id": 0}):
        raise HTTPException(status_code=404, detail="Item not found")
    if not await db.departments.find_one({"id": body.department_id}, {"_id": 0}):
        raise HTTPException(status_code=404, detail="Department not found")

    # ---- Fast idempotency pre-check (avoids starting a transaction for replays) ----
    idem_key = body.idempotency_key or _new_id()
    prior = await db.stock_transactions.find_one({"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0})
    if prior:
        _validate_idempotent_replay(prior, source="stock_issue", department_id=body.department_id,
                                    item_id=body.item_id, entry_type="issue",
                                    quantity_change=-body.quantity,
                                    reference_no=body.reference_no or None,
                                    approval_id=body.approval_id or None)
        return _build_idempotent_replay(prior)

    # ---- Test-hook header (ignored outside test environment) ----
    fail_after = request.headers.get("X-Test-Txn-Fail-After") if _TXN_HOOKS_ACTIVE else None

    # ---- Transaction --------------------------------------------------------
    # session.with_transaction() handles TransientTransactionError retries and
    # UnknownTransactionCommitResult commit retries automatically.
    # The callback returns (result_dict, email_payload | None).
    # No external side effects occur inside the callback.

    async def _txn_callback(session):
        # 1. Recheck idempotency key inside the transaction
        prior_inner = await db.stock_transactions.find_one(
            {"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0}, session=session
        )
        if prior_inner:
            _validate_idempotent_replay(prior_inner, source="stock_issue", department_id=body.department_id,
                                        item_id=body.item_id, entry_type="issue",
                                        quantity_change=-body.quantity,
                                        reference_no=body.reference_no or None,
                                        approval_id=body.approval_id or None)
            return _build_idempotent_replay(prior_inner), None

        # 2. Read item, dept, threshold, and stock entry under the session
        item_inner = await db.items.find_one({"id": body.item_id}, {"_id": 0}, session=session)
        if not item_inner:
            raise HTTPException(status_code=404, detail="Item not found")
        dept_inner = await db.departments.find_one(
            {"id": body.department_id}, {"_id": 0}, session=session
        )
        if not dept_inner:
            raise HTTPException(status_code=404, detail="Department not found")
        threshold = await stock_issue.ensure_threshold(
            db, body.item_id, body.department_id, session=session
        )
        existing = await db.stock_entries.find_one(
            {"department_id": body.department_id, "item_id": body.item_id},
            session=session,
        )
        previous_balance = existing["balance"] if existing else 0
        projected = previous_balance - body.quantity

        # 3. Validate balance
        if projected < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock. Current balance: {previous_balance}, "
                       f"requested: {body.quantity}",
            )

        # 4. Business rule evaluation
        decision = stock_issue.evaluate_issue_decision(
            item=item_inner, threshold=threshold,
            previous_balance=previous_balance, projected_balance=projected,
            user_role=user["role"], override_reason=body.override_reason,
        )
        if decision["block"]:
            raise HTTPException(status_code=400, detail=decision["message"])
        if (projected < threshold["no_issue_threshold"]
                and decision["rule"] != "emergency_override"):
            raise HTTPException(status_code=400, detail=decision["message"])

        db_status = "zero_level" if projected == 0 else (
            "critical_level" if projected < threshold["critical_level"] else "available"
        )

        # 5. Generate all IDs before any writes (so the final record is complete in one insert)
        txn_id = _new_id()
        entry_id = existing["id"] if existing else _new_id()
        alert_id = _new_id() if decision["create_alert"] else None

        previous_lv = existing.get("ledger_version", 0) if existing else 0

        if existing is None:
            issue_seq_no = 1
        elif previous_lv == 0:
            # Legacy cutover baseline
            await ledger_mod.ensure_v2_baseline(
                db,
                department_id=body.department_id,
                item_id=body.item_id,
                entry_id=entry_id,
                balance=previous_balance,
                user_id=user["id"],
                user_name=user["full_name"],
                idempotency_key=f"baseline:{body.department_id}:{body.item_id}",
                status=_calc_stock_status(previous_balance, item_inner["min_level"], item_inner["critical_threshold"]),
                source="ledger_v2_cutover",
                session=session,
            )
            issue_seq_no = 2
        else:
            issue_seq_no = previous_lv + 1

        # 6. Upsert stock entry — filter on exact previous_balance to guard against
        #    lost-update races; matched_count == 0 means a concurrent write won.
        entry_doc = {
            "department_id": body.department_id,
            "item_id": body.item_id,
            "balance": projected,
            "status": db_status,
            "last_updated_by": user["id"],
            "last_updated_by_name": user["full_name"],
            "last_updated_at": _now_iso(),
            "shortage_start": (
                (existing.get("shortage_start") if existing else None)
                if db_status not in ("zero_level", "critical_level")
                else (existing.get("shortage_start")
                      if existing and existing.get("shortage_start")
                      else _now_iso())
            ),
            "notes": body.notes,
        }
        if existing:
            filter_doc = {"id": entry_id, "balance": previous_balance}
            if previous_lv >= 1:
                filter_doc["ledger_version"] = previous_lv
            else:
                filter_doc["$or"] = [{"ledger_version": {"$exists": False}}, {"ledger_version": 0}]
            upd = await db.stock_entries.update_one(
                filter_doc,
                {"$set": {**entry_doc, "ledger_version": issue_seq_no}},
                session=session,
            )
            if upd.matched_count != 1:
                raise HTTPException(
                    status_code=409,
                    detail="Concurrent modification: stock balance changed. Please retry.",
                )
        else:
            await db.stock_entries.insert_one({"id": entry_id, **entry_doc, "ledger_version": issue_seq_no}, session=session)
        _check_fail_point(fail_after, "transaction_insert")
        _check_fail_point(fail_after, "stock_update")

        # 7. Alert (if required)
        alert_doc = None
        email_payload: Optional[dict] = None
        if decision["create_alert"]:
            sev = _decision_severity_to_alert(decision["severity"])
            atype = _decision_to_alert_type(decision["rule"])
            title_prefix = (
                "EMERGENCY OVERRIDE" if decision["rule"] == "emergency_override"
                else ("Critical stock after issue" if decision["rule"] == "below_critical"
                      else "Below minimum after issue")
            )
            title = f"{title_prefix} — {item_inner.get('name_en', item_inner.get('internal_code'))}"
            msg = (f"{decision['message']} Department: {dept_inner['code']}. "
                   f"Balance: {previous_balance} → {projected} (issued {body.quantity}).")
            if decision["override"] and body.override_reason:
                msg += f" Override reason: {body.override_reason}."

            alert_doc = _new_alert(
                type=atype, severity=sev,
                title=title, message=msg,
                department_id=body.department_id, item_id=body.item_id,
                escalated_to=(decision["escalate_to"][0] if decision["escalate_to"] else None),
                escalation_level=(1 if decision["escalate_to"] else 0),
            )
            alert_doc["id"] = alert_id
            await db.alerts.insert_one(alert_doc, session=session)
            _check_fail_point(fail_after, "alert_insert")

            if decision["escalate_to"]:
                extra_rows = [
                    ("Previous balance",   str(previous_balance)),
                    ("Issued quantity",    str(body.quantity)),
                    ("New balance",        str(projected)),
                    ("No-issue threshold", str(threshold["no_issue_threshold"])),
                    ("Critical level",     str(threshold["critical_level"])),
                    ("Minimum level",      str(threshold["minimum_level"])),
                    ("Issued by",          user["full_name"]),
                    ("Rule",               decision["rule"]),
                ]
                if body.reference_no:
                    extra_rows.append(("Reference", body.reference_no))
                if decision["override"] and body.override_reason:
                    extra_rows.append(("Override reason", body.override_reason))
                email_payload = {
                    "roles": decision["escalate_to"],
                    "title": title,
                    "severity": sev,
                    "message": msg,
                    "department_code": dept_inner.get("code", ""),
                    "item_name": item_inner.get("name_en") or item_inner.get("internal_code"),
                    "extra_rows": extra_rows,
                }

        # 8. Audit log
        await write_audit(
            user,
            "stock_issue_override" if decision["override"] else "stock_issue",
            "stock_transactions", entity_id=txn_id,
            old_value={"balance": previous_balance},
            new_value={
                "balance": projected, "quantity": body.quantity,
                "rule": decision["rule"], "override": decision["override"],
                "item_id": body.item_id, "department_id": body.department_id,
                "idempotency_key": idem_key,
            },
            request=request,
            reason=body.override_reason,
            session=session,
        )
        _check_fail_point(fail_after, "audit_insert")

        # 9. One final, complete, immutable Ledger v2 record — no update_one after this
        seq_no = issue_seq_no
        txn_doc = ledger_mod.build_ledger_entry(
            department_id=body.department_id,
            item_id=body.item_id,
            entry_type="issue",
            sequence_no=seq_no,
            previous_balance=previous_balance,
            quantity_change=-body.quantity,
            new_balance=projected,
            user_id=user["id"],
            user_name=user["full_name"],
            actor_type="user",
            source="stock_issue",
            idempotency_key=idem_key,
            status=db_status,
            entry_id=entry_id,
            transaction_id=txn_id,
            reference_no=body.reference_no,
            # Extra fields for idempotent replay and audit trail
            alert_id=alert_id,
            alert_severity=alert_doc["severity"] if alert_doc else None,
            reason=body.notes,
            override_flag=decision["override"],
            override_reason=body.override_reason if decision["override"] else None,
            approval_id=body.approval_id,
            decision_rule=decision["rule"],
        )
        await db.stock_transactions.insert_one(txn_doc, session=session)
        _check_fail_point(fail_after, "ledger_insert")

        result = {
            "success": True,
            "entry_id": entry_id,
            "transaction_id": txn_id,
            "previous_balance": previous_balance,
            "current_balance": projected,
            "status": db_status,
            "decision": decision,
            "alert_id": alert_id,
            "alert_severity": alert_doc["severity"] if alert_doc else None,
        }
        return result, email_payload

    # ---- Execute — driver-managed retry on TransientTransactionError / UnknownCommitResult ----
    try:
        async with client.start_session() as session:
            outcome = await session.with_transaction(_txn_callback)
    except _TxnTestFailure as exc:
        logger.warning("Test-injected transaction failure: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Stock issue could not be completed. Please retry.",
        )
    except DuplicateKeyError:
        # Check for user-operation idempotency match first
        prior = await db.stock_transactions.find_one(
            {"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0}
        )
        if prior:
            _validate_idempotent_replay(prior, source="stock_issue", department_id=body.department_id,
                                        item_id=body.item_id, entry_type="issue",
                                        quantity_change=-body.quantity,
                                        reference_no=body.reference_no or None,
                                        approval_id=body.approval_id or None)
            return _build_idempotent_replay(prior)
        # Check if baseline race caused the DuplicateKeyError — retry once
        baseline_key = f"baseline:{body.department_id}:{body.item_id}"
        baseline = await db.stock_transactions.find_one(
            {"idempotency_key": baseline_key, "schema_version": 2}, {"_id": 0}
        )
        if baseline:
            try:
                async with client.start_session() as _session2:
                    outcome = await _session2.with_transaction(_txn_callback)
                result, email_payload = outcome
                if email_payload:
                    background.add_task(_escalation_email_task, db, **email_payload)
                return result
            except DuplicateKeyError:
                prior2 = await db.stock_transactions.find_one(
                    {"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0}
                )
                if prior2:
                    _validate_idempotent_replay(prior2, source="stock_issue",
                                                department_id=body.department_id,
                                                item_id=body.item_id, entry_type="issue",
                                                quantity_change=-body.quantity,
                                                reference_no=body.reference_no or None,
                                                approval_id=body.approval_id or None)
                    return _build_idempotent_replay(prior2)
                raise HTTPException(status_code=409, detail="Write conflict. Please retry.")
            except HTTPException:
                raise
            except Exception as exc:
                logger.exception("Unexpected error in stock_issue baseline-race retry", exc_info=exc)
                raise HTTPException(status_code=503, detail="Stock issue could not be completed. Please retry.")
        raise HTTPException(status_code=409, detail="Write conflict. Please retry.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Transaction failed", exc_info=exc)
        raise HTTPException(
            status_code=503,
            detail="Stock issue could not be completed. Please retry.",
        )

    result, email_payload = outcome

    # ---- Post-commit: schedule email (never inside the transaction callback) ----
    if email_payload:
        background.add_task(_escalation_email_task, db, **email_payload)
        if _TXN_HOOKS_ACTIVE:
            response.headers["X-Test-Email-Scheduled"] = "true"

    return result


# ===== Per-department Item Thresholds =====
@api.get("/items/{item_id}/thresholds")
async def list_item_thresholds(
    item_id: str,
    user: dict = Depends(get_current_user),
):
    item = await db.items.find_one({"id": item_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    rows = await db.item_department_thresholds.find(
        {"item_id": item_id}, {"_id": 0}
    ).to_list(500)
    return rows


@api.get("/items/{item_id}/thresholds/{department_id}")
async def get_item_threshold(
    item_id: str,
    department_id: str,
    user: dict = Depends(get_current_user),
):
    return await stock_issue.ensure_threshold(db, item_id, department_id)


@api.put("/items/{item_id}/thresholds/{department_id}")
async def upsert_item_threshold(
    item_id: str,
    department_id: str,
    body: ThresholdUpdate,
    request: Request,
    user: dict = Depends(require_roles(
        "super_admin", "digital_health_manager", "supply_officer", "department_head",
    )),
):
    item = await db.items.find_one({"id": item_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    dept = await db.departments.find_one({"id": department_id}, {"_id": 0})
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    if user["role"] == "department_head" and user.get("department_id") != department_id:
        raise HTTPException(status_code=403, detail="Cannot edit thresholds for another department")

    doc = await stock_issue.upsert_threshold(
        db, item_id=item_id, department_id=department_id,
        minimum_level=body.minimum_level,
        critical_level=body.critical_level,
        emergency_reserve_level=body.emergency_reserve_level,
        no_issue_threshold=body.no_issue_threshold,
        allow_emergency_override=body.allow_emergency_override,
        requires_approval_below_reserve=body.requires_approval_below_reserve,
        escalation_minutes=body.escalation_minutes,
        user_id=user["id"],
    )
    await write_audit(
        user, "upsert_threshold", "item_department_thresholds",
        entity_id=doc["id"], new_value=body.model_dump(), request=request,
    )
    return doc


# ===== Stock Balance Reconciliation =====
@api.post("/admin/reconcile-stock")
async def admin_reconcile_stock(
    request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager")),
):
    """Trigger an on-demand reconciliation run and return discrepancies."""
    discrepancies = await scheduler_mod.reconcile_stock_balances(db)
    discrepancy_kinds = sorted({
        str(d.get("kind")) if d.get("kind") else "unknown"
        for d in discrepancies
    })
    await write_audit(
        user, "reconcile_stock", "reconciliation_log",
        entity_id=None,
        old_value=None,
        new_value={
            "discrepancy_count": len(discrepancies),
            "discrepancy_kinds": discrepancy_kinds,
        },
        request=request,
    )
    return {"checked_at": _now_iso(), "count": len(discrepancies), "discrepancies": discrepancies}


@api.get("/admin/reconciliation-log")
async def admin_reconciliation_log(
    user: dict = Depends(require_roles("super_admin", "digital_health_manager", "auditor")),
    limit: int = 50,
):
    docs = await db.reconciliation_log.find({}, {"_id": 0}).sort("checked_at", -1).limit(limit).to_list(limit)
    return docs


@api.post("/admin/backfill-v2-baselines")
async def admin_backfill_v2_baselines(
    request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager")),
):
    """Backfill Ledger v2 opening baselines for legacy stock_entries (Package 2A-3)."""
    summary = await ledger_backfill.backfill_v2_baselines(db, client)
    await write_audit(
        user, "backfill_v2_baselines", "stock_entries",
        new_value={
            "scanned": summary["scanned"],
            "backfilled_count": summary["backfilled_count"],
            "already_baselined_count": summary["already_baselined_count"],
            "conflict_existing_v2_with_zero_version_count": summary["conflict_existing_v2_with_zero_version_count"],
            "conflict_missing_stock_entry_count": summary["conflict_missing_stock_entry_count"],
            "failed_count": summary["failed_count"],
        },
        request=request,
    )
    return summary


# ===== Escalation Recipients =====
@api.get("/settings/escalation-recipients")
async def list_escalation_recipients(
    user: dict = Depends(require_roles(
        "super_admin", "digital_health_manager", "hospital_manager", "auditor",
    )),
):
    return await email_service.get_escalation_recipients(db)


@api.put("/settings/escalation-recipients")
async def set_escalation_recipient_endpoint(
    body: EscalationRecipientUpdate,
    request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager")),
):
    await email_service.set_escalation_recipient(db, body.role, body.email)
    await write_audit(
        user, "set_escalation_recipient", "escalation_recipients",
        entity_id=body.role, new_value={"role": body.role, "email": body.email},
        request=request,
    )
    return {"status": "ok"}


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
            raise HTTPException(status_code=403, detail="You cannot submit a request for a different department")

    item = await db.items.find_one({"id": body.item_id})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not await db.departments.find_one({"id": body.department_id}):
        raise HTTPException(status_code=404, detail="Department not found")

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
        raise HTTPException(status_code=404, detail="Request not found")
    validate_request_transition(req["status"], "approved")
    if user["role"] == "department_head" and user.get("department_id") != req["department_id"]:
        raise HTTPException(status_code=403, detail="You cannot approve a request from a different department")
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
        raise HTTPException(status_code=404, detail="Request not found")
    validate_request_transition(req["status"], "rejected")
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
        raise HTTPException(status_code=404, detail="Request not found")
    validate_request_transition(req["status"], "backorder" if body.backorder else "dispatched")
    target_state = "backorder" if body.backorder else "dispatched"
    validate_request_transition(req["status"], target_state)

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
        await db.alerts.insert_one(_new_alert(
            type="backorder",
            severity="critical" if item.get("is_life_saving") else "warning",
            title=f"Backorder - {item['name_en']}",
            message=f"Request {req['request_number']} — Department {dept['code']}",
            department_id=req["department_id"], item_id=req["item_id"], request_id=req_id,
        ))
    else:
        update["status"] = "dispatched"
    await db.stock_requests.update_one({"id": req_id}, {"$set": update})
    await write_audit(user, "dispatch_request", "requests", entity_id=req_id,
                      new_value=update, request=request)
    return {"status": "ok"}


@api.post("/requests/{req_id}/receive")
async def receive_request(
    req_id: str, body: ReceiveBody, request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(require_roles(
        "super_admin", "department_head", "department_stock_officer", "supply_officer"
    )),
):
    # Fast guard before starting a transaction
    req = await db.stock_requests.find_one({"id": req_id})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if user["role"] in ("department_head", "department_stock_officer") and user.get("department_id") != req["department_id"]:
        raise HTTPException(status_code=403, detail="You cannot receive for a different department")

    _check_reserved_idempotency_key(idempotency_key)

    idem_key = idempotency_key or _new_id()

    # Idempotency lookup BEFORE quantity validation — a legitimate replay after a full receive
    # must return 200 even though remaining is now 0.
    prior = await db.stock_transactions.find_one({"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0})
    if prior:
        _validate_idempotent_replay(prior, source="receive_request", department_id=req["department_id"],
                                    item_id=req["item_id"], entry_type="receive",
                                    request_id=req_id, quantity_change=body.received_qty)
        return {"status": "ok", "idempotent_replay": True}

    # Outer convenience check (non-authoritative — authoritative validation is inside the transaction)
    _RECEIVABLE_STATES = {"dispatched", "partially_received"}
    if req["status"] not in _RECEIVABLE_STATES:
        raise HTTPException(status_code=409, detail=f"Request is in state '{req['status']}' and cannot be received")
    if body.received_qty <= 0:
        raise HTTPException(status_code=422, detail="received_qty must be positive")
    remaining = req["dispatched_qty"] - req["received_qty"]
    if body.received_qty > remaining:
        raise HTTPException(status_code=422, detail=f"received_qty {body.received_qty} exceeds remaining dispatched quantity {remaining}")

    fail_after = request.headers.get("X-Test-Txn-Fail-After") if _TXN_HOOKS_ACTIVE else None

    async def _txn_callback(session):
        prior_inner = await db.stock_transactions.find_one(
            {"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0}, session=session
        )
        if prior_inner:
            _validate_idempotent_replay(prior_inner, source="receive_request",
                                        department_id=req["department_id"],
                                        item_id=req["item_id"], entry_type="receive",
                                        request_id=req_id, quantity_change=body.received_qty)
            return {"idempotent_replay": True}

        req_inner = await db.stock_requests.find_one({"id": req_id}, session=session)
        if not req_inner:
            raise HTTPException(status_code=404, detail="Request not found")

        # Authoritative state guard inside transaction (after replay check, before quantity check)
        if req_inner["status"] not in {"dispatched", "partially_received"}:
            raise HTTPException(status_code=409, detail=f"Request is in state '{req_inner['status']}' and cannot be received")

        # Authoritative quantity revalidation inside transaction (runs on every retry)
        remaining_inner = req_inner["dispatched_qty"] - req_inner["received_qty"]
        if body.received_qty <= 0:
            raise HTTPException(status_code=422, detail="received_qty must be positive")
        if body.received_qty > remaining_inner:
            raise HTTPException(status_code=422, detail=f"received_qty {body.received_qty} exceeds remaining {remaining_inner}")

        new_received = req_inner["received_qty"] + body.received_qty
        if new_received >= req_inner["dispatched_qty"]:
            new_req_status = "received"
            closed = _now_iso()
        else:
            new_req_status = "partially_received"
            closed = None
        validate_request_transition(req_inner["status"], new_req_status)

        previous_received_qty = req_inner["received_qty"]
        previous_request_status = req_inner["status"]
        req_upd = await db.stock_requests.update_one(
            {"id": req_id, "received_qty": previous_received_qty, "status": previous_request_status},
            {"$set": {
                "received_qty": new_received,
                "received_at": _now_iso(),
                "status": new_req_status,
                "closed_at": closed,
            }},
            session=session,
        )
        if req_upd.matched_count != 1:
            raise HTTPException(status_code=409, detail="Concurrent modification on request: please retry.")

        item_inner = await db.items.find_one({"id": req_inner["item_id"]}, session=session)
        if not item_inner:
            raise HTTPException(status_code=404, detail="Item not found")

        entry = await db.stock_entries.find_one(
            {"department_id": req_inner["department_id"], "item_id": req_inner["item_id"]},
            session=session,
        )

        previous_balance = entry["balance"] if entry else 0
        previous_status = entry["status"] if entry else None
        new_balance = previous_balance + body.received_qty
        raw_st = _calc_stock_status(new_balance, item_inner["min_level"], item_inner["critical_threshold"])
        if raw_st == "available" and previous_status in ("zero_level", "critical_level"):
            new_st = "back_in_stock"
        else:
            new_st = raw_st

        shortage_start = None
        if new_st in ("zero_level", "critical_level"):
            shortage_start = (
                entry.get("shortage_start") if entry and entry.get("shortage_start")
                else _now_iso()
            )

        entry_id = entry["id"] if entry else _new_id()
        previous_lv = entry.get("ledger_version", 0) if entry else 0

        if entry is None:
            receive_seq_no = 1
        elif previous_lv == 0:
            # Legacy cutover baseline
            await ledger_mod.ensure_v2_baseline(
                db,
                department_id=req_inner["department_id"],
                item_id=req_inner["item_id"],
                entry_id=entry_id,
                balance=previous_balance,
                user_id=user["id"],
                user_name=user["full_name"],
                idempotency_key=f"baseline:{req_inner['department_id']}:{req_inner['item_id']}",
                status=_calc_stock_status(previous_balance, item_inner["min_level"], item_inner["critical_threshold"]),
                source="ledger_v2_cutover",
                session=session,
            )
            receive_seq_no = 2
        else:
            receive_seq_no = previous_lv + 1

        entry_doc = {
            "department_id": req_inner["department_id"],
            "item_id": req_inner["item_id"],
            "balance": new_balance,
            "status": new_st,
            "last_updated_by": user["id"],
            "last_updated_by_name": user["full_name"],
            "last_updated_at": _now_iso(),
            "shortage_start": shortage_start,
            "notes": None,
        }
        if entry:
            filter_doc = {"id": entry_id, "balance": previous_balance}
            if previous_lv >= 1:
                filter_doc["ledger_version"] = previous_lv
            else:
                filter_doc["$or"] = [{"ledger_version": {"$exists": False}}, {"ledger_version": 0}]
            upd = await db.stock_entries.update_one(
                filter_doc, {"$set": {**entry_doc, "ledger_version": receive_seq_no}}, session=session
            )
            if upd.matched_count != 1:
                raise HTTPException(status_code=409, detail="Concurrent modification: please retry.")
        else:
            await db.stock_entries.insert_one({"id": entry_id, **entry_doc, "ledger_version": receive_seq_no}, session=session)
        _check_fail_point(fail_after, "stock_update")

        txn_doc = ledger_mod.build_ledger_entry(
            department_id=req_inner["department_id"],
            item_id=req_inner["item_id"],
            entry_type="receive",
            sequence_no=receive_seq_no,
            previous_balance=previous_balance,
            quantity_change=body.received_qty,
            new_balance=new_balance,
            user_id=user["id"],
            user_name=user["full_name"],
            actor_type="user",
            source="receive_request",
            idempotency_key=idem_key,
            status=new_st,
            entry_id=entry_id,
            reference_no=req_inner["request_number"],
            # Pass request_id as extra (not reserved)
            request_id=req_id,
        )
        await ledger_mod.insert_ledger_entry(db, txn_doc, session=session)
        _check_fail_point(fail_after, "ledger_insert")

        await write_audit(
            user, "receive_request", "requests", entity_id=req_id,
            new_value={"received": body.received_qty, "idempotency_key": idem_key},
            request=request,
            session=session,
        )
        return {"idempotent_replay": False}

    try:
        async with client.start_session() as session:
            result = await session.with_transaction(_txn_callback)
    except _TxnTestFailure as exc:
        raise HTTPException(status_code=503, detail="Receive could not be completed. Please retry.")
    except DuplicateKeyError:
        prior = await db.stock_transactions.find_one(
            {"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0}
        )
        if prior:
            _validate_idempotent_replay(prior, source="receive_request",
                                        department_id=req["department_id"],
                                        item_id=req["item_id"], entry_type="receive",
                                        request_id=req_id, quantity_change=body.received_qty)
            return {"status": "ok", "idempotent_replay": True}
        # Baseline race — retry once
        baseline_key = f"baseline:{req['department_id']}:{req['item_id']}"
        baseline = await db.stock_transactions.find_one(
            {"idempotency_key": baseline_key, "schema_version": 2}, {"_id": 0}
        )
        if baseline:
            try:
                async with client.start_session() as _session2:
                    result = await _session2.with_transaction(_txn_callback)
                if result.get("idempotent_replay"):
                    return {"status": "ok", "idempotent_replay": True}
                return {"status": "ok"}
            except DuplicateKeyError:
                prior2 = await db.stock_transactions.find_one(
                    {"idempotency_key": idem_key, "schema_version": 2}, {"_id": 0}
                )
                if prior2:
                    _validate_idempotent_replay(prior2, source="receive_request",
                                                department_id=req["department_id"],
                                                item_id=req["item_id"], entry_type="receive",
                                                request_id=req_id, quantity_change=body.received_qty)
                    return {"status": "ok", "idempotent_replay": True}
                raise HTTPException(status_code=409, detail="Write conflict. Please retry.")
            except HTTPException:
                raise
            except Exception as exc:
                logger.exception("Unexpected error in receive baseline-race retry", exc_info=exc)
                raise HTTPException(status_code=503, detail="Receive could not be completed. Please retry.")
        raise HTTPException(status_code=409, detail="Write conflict. Please retry.")

    if result.get("idempotent_replay"):
        return {"status": "ok", "idempotent_replay": True}
    return {"status": "ok"}


# ===== ALERTS =====
@api.get("/alerts")
async def list_alerts(
    user: dict = Depends(get_current_user),
    acknowledged: Optional[bool] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 200,
):
    q: dict = {}
    # New 'status' filter takes precedence; keep legacy 'acknowledged' bool for backward compat.
    if status:
        if status == "open":
            q["status"] = {"$in": ["open", "acknowledged", "in_progress"]}
        else:
            q["status"] = status
    elif acknowledged is not None:
        if acknowledged is False:
            # Legacy boolean filter implemented as a current-status bucket.
            # false excludes alerts whose current status is acknowledged, resolved, or closed.
            q["status"] = {"$in": ["open", "in_progress"]}
        else:
            q["status"] = {"$in": ["resolved", "closed"]}
    if severity:
        q["severity"] = severity
    docs = await db.alerts.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    for d in docs:
        if d.get("item_id"):
            d["item"] = await db.items.find_one({"id": d["item_id"]}, {"_id": 0})
        if d.get("department_id"):
            d["department"] = await db.departments.find_one({"id": d["department_id"]}, {"_id": 0})
        # Backfill lifecycle defaults for legacy alerts
        d.setdefault("status", "acknowledged" if d.get("acknowledged") else "open")
        d.setdefault("escalation_level", 0)
        d.setdefault("escalations", [])
    return docs


@api.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, request: Request, user: dict = Depends(get_current_user)):
    alert = await db.alerts.find_one({"id": alert_id})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    current = alert.get("status", "open")
    validate_alert_transition(current, "acknowledged")
    await db.alerts.update_one({"id": alert_id}, {"$set": {
        "status": "acknowledged",
        "acknowledged": True,
        "acknowledged_by": user["id"],
        "acknowledged_at": _now_iso(),
    }})
    await write_audit(user, "acknowledge_alert", "alerts", entity_id=alert_id, request=request)
    return {"status": "ok"}


@api.post("/alerts/{alert_id}/start")
async def start_alert(alert_id: str, request: Request, user: dict = Depends(get_current_user)):
    alert = await db.alerts.find_one({"id": alert_id})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    validate_alert_transition(alert.get("status", "open"), "in_progress")
    await db.alerts.update_one({"id": alert_id}, {"$set": {
        "status": "in_progress",
        "in_progress_by": user["id"],
        "in_progress_at": _now_iso(),
    }})
    await write_audit(user, "start_alert", "alerts", entity_id=alert_id, request=request)
    return {"status": "ok"}


class _ResolveBody(__import__("pydantic").BaseModel):
    note: Optional[str] = None


@api.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str, body: _ResolveBody, request: Request,
    user: dict = Depends(get_current_user),
):
    alert = await db.alerts.find_one({"id": alert_id})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    validate_alert_transition(alert.get("status", "open"), "resolved")
    await db.alerts.update_one({"id": alert_id}, {"$set": {
        "status": "resolved",
        "resolution_note": body.note,
        "resolved_by": user["id"],
        "resolved_at": _now_iso(),
    }})
    await write_audit(user, "resolve_alert", "alerts", entity_id=alert_id,
                      new_value={"note": body.note}, request=request)
    return {"status": "ok"}


@api.post("/alerts/{alert_id}/close")
async def close_alert(
    alert_id: str, request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager", "hospital_manager")),
):
    alert = await db.alerts.find_one({"id": alert_id})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    validate_alert_transition(alert.get("status", "open"), "closed")
    await db.alerts.update_one({"id": alert_id}, {"$set": {
        "status": "closed",
        "closed_at": _now_iso(),
    }})
    await write_audit(user, "close_alert", "alerts", entity_id=alert_id, request=request)
    return {"status": "ok"}


# ===== SETTINGS =====
@api.get("/settings/sla")
async def get_sla_settings(
    user: dict = Depends(require_roles(
        "super_admin", "digital_health_manager", "hospital_manager", "auditor"
    )),
):
    return await get_settings(db)


@api.put("/settings/sla")
async def put_sla_settings(
    payload: dict, request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager")),
):
    new = await update_settings(db, payload)
    await write_audit(user, "update_sla", "settings", entity_id="alert_sla",
                      new_value=new, request=request)
    return new


# ===== EXCEL IMPORT =====
@api.post("/items/import/preview")
async def items_import_preview(
    request: Request,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager", "supply_officer")),
):
    body = await request.body()
    # Accept either raw bytes or multipart-form; standard libs handle both transparently here.
    # Strip multipart envelope if present.
    if b"Content-Disposition" in body and b"\r\n\r\n" in body:
        first = body.find(b"\r\n\r\n") + 4
        end = body.rfind(b"\r\n--")
        body = body[first:end if end != -1 else len(body)]
    if not body:
        raise HTTPException(status_code=400, detail="Empty file body")
    try:
        return await excel_import.analyse(db, body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read workbook: {e}")


@api.post("/items/import/commit")
async def items_import_commit(
    request: Request,
    include_manual_review: bool = False,
    user: dict = Depends(require_roles("super_admin", "digital_health_manager", "supply_officer")),
):
    body = await request.body()
    if b"Content-Disposition" in body and b"\r\n\r\n" in body:
        first = body.find(b"\r\n\r\n") + 4
        end = body.rfind(b"\r\n--")
        body = body[first:end if end != -1 else len(body)]
    if not body:
        raise HTTPException(status_code=400, detail="Empty file body")
    async def _excel_audit_callback(*, session, item_id, dept_id, entry):
        await write_audit(
            user, "excel_stock_import", "stock_entries",
            entity_id=item_id,
            new_value={"department_id": dept_id, "balance": entry["new_balance"], "idempotency_key": entry["idempotency_key"]},
            request=request,
            session=session,
        )

    fail_after = request.headers.get("X-Test-Fail-After") if _TXN_HOOKS_ACTIVE else None
    try:
        result = await excel_import.commit(db, body, user, include_manual_review=include_manual_review, client=client, audit_callback=_excel_audit_callback, fail_after=fail_after)
    except excel_import.ExcelTestFailure as exc:
        logger.warning("Test-injected Excel failure: %s", exc)
        raise HTTPException(status_code=503, detail="Excel import could not be completed. Please retry.")
    except excel_import.ExcelWriteConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {e}")
    await write_audit(user, "import_excel", "items", new_value=result, request=request)
    return result


@api.get("/items/import/template.xlsx")
async def items_import_template(
    user: dict = Depends(require_roles("super_admin", "digital_health_manager", "supply_officer")),
):
    """Download an empty .xlsx template with the expected headers."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Items"
    ws.append([
        "internal_code", "barcode", "name", "category", "unit",
        "min_level", "critical_threshold", "max_level",
        "department_code", "balance",
    ])
    # Example row
    ws.append(["ETT-CUFF-2", "8901234500021", "ETT W/ Cuff 2", "Airway", "PCS", 10, 5, 30, "ER", 8])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=items_template.xlsx"},
    )


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

    open_alerts = await db.alerts.count_documents({
        "status": {"$in": ["open", "acknowledged", "in_progress"]}
    })

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

    # ----- Operational KPIs (new) -----
    total_stock = zero_count + crit_count + back_count + avail_count
    availability_pct = round(((avail_count + back_count) / total_stock) * 100, 1) if total_stock else 100.0

    no_barcode_count = await db.items.count_documents({
        "$or": [{"barcode": None}, {"barcode": ""}],
        "is_active": True,
    })

    # Request fulfillment rate (last 30 days)
    cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    total_reqs = await db.stock_requests.count_documents({"created_at": {"$gte": cutoff_30}})
    fulfilled_reqs = await db.stock_requests.count_documents({
        "created_at": {"$gte": cutoff_30},
        "status": {"$in": ["received", "closed"]},
    })
    fulfillment_rate = round((fulfilled_reqs / total_reqs) * 100, 1) if total_reqs else 0.0

    # Backorder aging buckets (in days)
    backorder_docs = await db.stock_requests.find(
        {"status": "backorder"}, {"_id": 0, "created_at": 1}
    ).to_list(500)
    aging = {"0-1d": 0, "1-2d": 0, "2-7d": 0, "7d+": 0}
    now = datetime.now(timezone.utc)
    for r in backorder_docs:
        try:
            dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (now - dt).total_seconds() / 86400
            if days < 1:
                aging["0-1d"] += 1
            elif days < 2:
                aging["1-2d"] += 1
            elif days < 7:
                aging["2-7d"] += 1
            else:
                aging["7d+"] += 1
        except Exception:
            pass

    # Top repeated stockout items (count distinct stockout events from transactions)
    pipeline_repeat = [
        {"$match": {"status": {"$in": ["zero_level", "critical_level"]}}},
        {"$group": {"_id": "$item_id", "events": {"$sum": 1}}},
        {"$sort": {"events": -1}},
        {"$limit": 5},
    ]
    repeat_cursor = await db.stock_transactions.aggregate(pipeline_repeat)
    repeat_raw = await repeat_cursor.to_list(10)
    top_repeated = []
    for r in repeat_raw:
        it = await db.items.find_one({"id": r["_id"]}, {"_id": 0})
        if it:
            top_repeated.append({"item": it, "events": r["events"]})

    # Average days currently out of stock (shortage_start vs now)
    shortages = await db.stock_entries.find(
        {**q_stock, "status": {"$in": ["zero_level", "critical_level"]},
         "shortage_start": {"$ne": None}},
        {"_id": 0, "shortage_start": 1},
    ).to_list(2000)
    avg_days_out = 0.0
    if shortages:
        total_secs = 0.0
        for s in shortages:
            try:
                dt = datetime.fromisoformat(s["shortage_start"].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                total_secs += (now - dt).total_seconds()
            except Exception:
                pass
        avg_days_out = round((total_secs / len(shortages)) / 86400, 1)

    # Top affected departments
    pipeline = [
        {"$match": {"status": {"$in": ["zero_level", "critical_level"]}}},
        {"$group": {"_id": "$department_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 5},
    ]
    top_dept_cursor = await db.stock_entries.aggregate(pipeline)
    top_dept_raw = await top_dept_cursor.to_list(10)
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
    dept_status_cursor = await db.stock_entries.aggregate(pipeline2)
    raw = await dept_status_cursor.to_list(500)
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
        # operational KPIs
        "availability_pct": availability_pct,
        "fulfillment_rate": fulfillment_rate,
        "no_barcode_count": no_barcode_count,
        "avg_days_out_of_stock": avg_days_out,
        "backorder_aging": aging,
        "top_repeated_stockouts": top_repeated,
    }


# ===== DASHBOARD DRILL-DOWN =====
async def _enrich_stock(rows: list[dict]) -> list[dict]:
    """Attach item + department to a list of stock_entries rows."""
    items_map, depts_map = {}, {}
    for r in rows:
        if r["item_id"] not in items_map:
            items_map[r["item_id"]] = await db.items.find_one({"id": r["item_id"]}, {"_id": 0})
        if r["department_id"] not in depts_map:
            depts_map[r["department_id"]] = await db.departments.find_one(
                {"id": r["department_id"]}, {"_id": 0}
            )
        r["item"] = items_map[r["item_id"]]
        r["department"] = depts_map[r["department_id"]]
    return rows


async def _enrich_requests(rows: list[dict]) -> list[dict]:
    items_map, depts_map = {}, {}
    for r in rows:
        if r["item_id"] not in items_map:
            items_map[r["item_id"]] = await db.items.find_one({"id": r["item_id"]}, {"_id": 0})
        if r["department_id"] not in depts_map:
            depts_map[r["department_id"]] = await db.departments.find_one(
                {"id": r["department_id"]}, {"_id": 0}
            )
        r["item"] = items_map[r["item_id"]]
        r["department"] = depts_map[r["department_id"]]
    return rows


_DRILL_TITLES = {
    "zero":          "Zero Stock Items",
    "critical":      "Critical Stock Items",
    "back_in_stock": "Back-in-Stock Items",
    "available":     "Available Items",
    "backorder":     "Backorder Requests",
    "pending":       "Pending Approval Requests",
    "dispatched":    "Dispatched Requests",
    "open_alerts":   "Open Alerts",
    "life_saving":   "Life-Saving Items at Risk",
    "stale":         "Stock Not Updated > 24h",
    "no_barcode":    "Items Without Barcode",
    "availability":  "Stock Availability Breakdown",
    "fulfillment":   "Recent Request Fulfillment (30d)",
    "avg_days_out":  "Active Shortages",
}


@api.get("/dashboard/drill/{metric}")
async def dashboard_drill(metric: str, user: dict = Depends(get_current_user)):
    """Return the underlying rows behind a dashboard KPI so the user can drill in."""
    if metric not in _DRILL_TITLES:
        raise HTTPException(status_code=404, detail="Unknown metric")

    # Scope to user's department when applicable
    q_stock: dict = {}
    if user["role"] in ("department_stock_officer", "department_head") and user.get("department_id"):
        q_stock["department_id"] = user["department_id"]

    rows: list = []
    kind = "stock"

    if metric in ("zero", "critical", "back_in_stock", "available"):
        status_key = {"zero": "zero_level", "critical": "critical_level",
                      "back_in_stock": "back_in_stock", "available": "available"}[metric]
        rows = await db.stock_entries.find(
            {**q_stock, "status": status_key}, {"_id": 0}
        ).sort("last_updated_at", -1).to_list(1000)
        rows = await _enrich_stock(rows)
    elif metric == "stale":
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = await db.stock_entries.find(
            {**q_stock, "last_updated_at": {"$lt": cutoff}}, {"_id": 0}
        ).sort("last_updated_at", 1).to_list(1000)
        rows = await _enrich_stock(rows)
    elif metric == "life_saving":
        life_ids = [i["id"] for i in await db.items.find(
            {"is_life_saving": True}, {"_id": 0, "id": 1}
        ).to_list(500)]
        rows = await db.stock_entries.find(
            {**q_stock, "item_id": {"$in": life_ids},
             "status": {"$in": ["zero_level", "critical_level"]}},
            {"_id": 0},
        ).to_list(500)
        rows = await _enrich_stock(rows)
    elif metric == "avg_days_out":
        now = datetime.now(timezone.utc)
        raw = await db.stock_entries.find(
            {**q_stock, "status": {"$in": ["zero_level", "critical_level"]},
             "shortage_start": {"$ne": None}},
            {"_id": 0},
        ).sort("shortage_start", 1).to_list(1000)
        for r in raw:
            try:
                dt = datetime.fromisoformat(r["shortage_start"].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                r["days_out"] = round((now - dt).total_seconds() / 86400, 1)
            except Exception:
                r["days_out"] = None
        rows = await _enrich_stock(raw)
    elif metric == "no_barcode":
        kind = "item"
        rows = await db.items.find(
            {"$or": [{"barcode": None}, {"barcode": ""}], "is_active": True}, {"_id": 0}
        ).to_list(1000)
    elif metric in ("backorder", "pending", "dispatched"):
        kind = "request"
        status_key = {"backorder": "backorder", "pending": "pending_approval",
                      "dispatched": "dispatched"}[metric]
        rows = await db.stock_requests.find(
            {"status": status_key}, {"_id": 0}
        ).sort("created_at", -1).to_list(1000)
        rows = await _enrich_requests(rows)
    elif metric == "open_alerts":
        kind = "alert"
        rows = await db.alerts.find(
            {"status": {"$in": ["open", "acknowledged", "in_progress"]}}, {"_id": 0}
        ).sort("created_at", -1).limit(500).to_list(500)
        for a in rows:
            if a.get("item_id"):
                a["item"] = await db.items.find_one({"id": a["item_id"]}, {"_id": 0})
            if a.get("department_id"):
                a["department"] = await db.departments.find_one(
                    {"id": a["department_id"]}, {"_id": 0}
                )
    elif metric == "availability":
        # Summary breakdown rather than a row list
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        if q_stock:
            pipeline = [{"$match": q_stock}] + pipeline
        stock_summary_cursor = await db.stock_entries.aggregate(pipeline)
        agg = await stock_summary_cursor.to_list(20)
        return {
            "metric": metric, "title": _DRILL_TITLES[metric], "kind": "summary",
            "rows": [{"status": x["_id"], "count": x["count"]} for x in agg],
        }
    elif metric == "fulfillment":
        kind = "summary"
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        pipeline = [
            {"$match": {"created_at": {"$gte": cutoff}}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        request_summary_cursor = await db.stock_requests.aggregate(pipeline)
        agg = await request_summary_cursor.to_list(20)
        return {
            "metric": metric, "title": _DRILL_TITLES[metric], "kind": "summary",
            "rows": [{"status": x["_id"], "count": x["count"]} for x in agg],
        }

    return {
        "metric": metric,
        "title": _DRILL_TITLES[metric],
        "kind": kind,
        "count": len(rows),
        "rows": rows,
    }


# ===== AUDIT =====
@api.get("/audit-logs")
async def list_audit_logs(
    user: dict = Depends(require_roles(
        "super_admin", "digital_health_manager", "auditor"
    )),
    entity: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 300,
):
    q: dict = {}
    if entity:
        q["entity"] = entity
    if entity_id:
        q["entity_id"] = entity_id
    docs = await db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return docs


# ===== REPORTS =====
from reports_data import REPORT_BUILDERS
from reports_export import build_excel, build_pdf

REPORT_TITLES = {
    "zero_level":             "Zero Stock Items",
    "critical_level":         "Critical Stock Items",
    "life_saving":            "Life-Saving Items at Risk",
    "backorder":              "Backorder Report",
    "open_requests":          "Open Requests",
    "data_quality":           "Data Quality Report",
    "item_movement":          "Item Movement Report",
    "department_performance": "Department Performance",
    "monthly_management":     "Monthly Management Report",
    "audit_trail":            "Audit Trail Report",
}


async def _build_report(report_name: str, user: dict) -> tuple:
    builder = REPORT_BUILDERS.get(report_name)
    if not builder:
        raise HTTPException(status_code=404, detail="Unknown report")
    return await builder(db, user)


@api.get("/reports")
async def list_reports(user: dict = Depends(get_current_user)):
    """Return the catalogue of available reports."""
    return [
        {"key": k, "title": v}
        for k, v in REPORT_TITLES.items()
    ]


@api.get("/reports/{report_name}")
async def reports(report_name: str, user: dict = Depends(get_current_user)):
    """Preview a report as JSON (headers + rows + metadata)."""
    headers, rows, meta = await _build_report(report_name, user)
    return {
        "report": report_name,
        "title": meta.get("title", REPORT_TITLES.get(report_name, report_name)),
        "headers": headers,
        "rows": rows,
        "meta": meta,
        "count": len(rows),
    }


@api.get("/reports/{report_name}/export.csv")
async def export_report_csv(report_name: str, user: dict = Depends(get_current_user)):
    headers, rows, meta = await _build_report(report_name, user)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for r in rows:
        writer.writerow(["" if v is None else v for v in r])
    buf.seek(0)
    await write_audit(user, "export_csv", "reports", entity_id=report_name)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={report_name}.csv"},
    )


@api.get("/reports/{report_name}/export.xlsx")
async def export_report_xlsx(report_name: str, user: dict = Depends(get_current_user)):
    headers, rows, meta = await _build_report(report_name, user)
    title = meta.get("title", REPORT_TITLES.get(report_name, report_name))
    blob = build_excel(title, headers, rows, meta, sheet_name=title[:31])
    await write_audit(user, "export_xlsx", "reports", entity_id=report_name)
    return StreamingResponse(
        iter([blob]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={report_name}.xlsx"},
    )


@api.get("/reports/{report_name}/export.pdf")
async def export_report_pdf(report_name: str, user: dict = Depends(get_current_user)):
    headers, rows, meta = await _build_report(report_name, user)
    title = meta.get("title", REPORT_TITLES.get(report_name, report_name))
    blob = build_pdf(title, headers, rows, meta)
    await write_audit(user, "export_pdf", "reports", entity_id=report_name)
    return StreamingResponse(
        iter([blob]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={report_name}.pdf"},
    )


@api.post("/reports/{report_name}/email")
async def email_report(
    report_name: str,
    body: ReportEmailBody,
    background: BackgroundTasks,
    request: Request,
    user: dict = Depends(require_roles(
        "super_admin", "digital_health_manager", "hospital_manager",
        "supply_officer", "auditor",
    )),
):
    """Generate the report PDF and email it (with attachment) to the supplied recipients."""
    recipients = [e.strip().lower() for e in body.recipients if e and "@" in e]
    if not recipients:
        raise HTTPException(status_code=400, detail="Provide at least one valid recipient email")
    headers, rows, meta = await _build_report(report_name, user)
    title = meta.get("title", REPORT_TITLES.get(report_name, report_name))
    blob = build_pdf(title, headers, rows, meta)
    filename = f"{report_name}.pdf"
    msg = body.message or "Please find the latest report attached for your review."

    background.add_task(
        email_service.send_report_email,
        recipients,
        report_title=title,
        sender_name=user.get("full_name", "System"),
        message_body=msg,
        pdf_bytes=blob,
        pdf_filename=filename,
    )
    await write_audit(
        user, "email_report", "reports", entity_id=report_name,
        new_value={"recipients": recipients, "message_preview": msg[:120]},
        request=request,
    )
    return {"status": "queued", "recipients": recipients, "report": report_name}


# ----- Health -----
@api.get("/")
async def root():
    return {"status": "ok", "service": "medical-stock-monitoring"}


@api.get("/healthz")
async def healthz():
    """Process liveness probe. It intentionally does not depend on MongoDB."""
    return {"status": "ok", "service": "medical-stock-monitoring"}


@api.get("/readyz")
async def readyz(response: Response):
    """Dependency-aware readiness probe for traffic and deployment gates."""
    current_db = db
    if current_db is None:
        response.status_code = 503
        return {"status": "not_ready", "dependencies": {"mongodb": "unavailable"}}

    try:
        await asyncio.wait_for(current_db.command("ping"), timeout=2.0)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Readiness check failed: %s", type(exc).__name__
        )
        response.status_code = 503
        return {"status": "not_ready", "dependencies": {"mongodb": "unavailable"}}

    return {"status": "ready", "dependencies": {"mongodb": "ready"}}


app.include_router(api)


# ----- CORS -----
# Parse origins at import time so middleware is installed before the first request.
# Full production validation runs inside startup() via load_runtime_config().
_allowed_origins = parse_cors_origins(os.environ.get("CORS_ALLOWED_ORIGINS", ""))
if not _allowed_origins:
    logging.getLogger(__name__).warning(
        "CORS_ALLOWED_ORIGINS is not set — all cross-origin requests will be blocked."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=bool(_allowed_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- Startup -----
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup():
    global client, db
    import asyncio

    # Validate all configuration first — raises ValueError on misconfiguration.
    cfg = load_runtime_config()
    logger.info(
        "Runtime config OK — env=%s seed=%s secure=%s samesite=%s cors_origins=%d",
        cfg.app_env,
        cfg.seed_enabled,
        cfg.cookie_secure,
        cfg.cookie_samesite,
        len(cfg.cors_origins),
    )

    # Create MongoDB connection using validated config values.
    client = AsyncMongoClient(cfg.mongo_url)

    try:
        db = client[cfg.db_name]
        app.state.db = db

        await db.users.create_index("email", unique=True)
        await db.items.create_index("internal_code", unique=True)
        await db.items.create_index("barcode")
        await db.departments.create_index("code", unique=True)
        await db.stock_entries.create_index([("department_id", 1), ("item_id", 1)], unique=True)
        await db.stock_transactions.create_index(
            "idempotency_key", unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string"}},
        )
        await db.stock_transactions.create_index(
            [("department_id", 1), ("item_id", 1), ("sequence_no", 1)],
            unique=True,
            partialFilterExpression={"schema_version": 2},
        )
        await db.item_department_thresholds.create_index(
            [("item_id", 1), ("department_id", 1)], unique=True
        )
        await db.escalation_recipients.create_index("role", unique=True)
        await db.stock_requests.create_index("request_number", unique=True)
        await db.alerts.create_index("created_at")
        await db.alerts.create_index("status")
        await db.audit_logs.create_index("created_at")
        await db.login_attempts.create_index("identifier")

        if cfg.seed_enabled:
            try:
                await seed_data(db, client=client)
                logger.info("Seed data ensured.")
            except Exception as e:
                logger.exception("Seed failed: %s", e)
                raise
        else:
            logger.info("SEED_DATA_ENABLED is not true — skipping seed data.")

        # Migrate legacy alerts that pre-date the lifecycle schema
        await db.alerts.update_many(
            {"status": {"$exists": False}},
            [{"$set": {
                "status": {"$cond": [{"$eq": ["$acknowledged", True]}, "acknowledged", "open"]},
                "escalation_level": 0,
                "escalations": [],
            }}],
        )

        # Launch SLA scheduler + reconciliation job in background
        app.state.scheduler_task = asyncio.create_task(scheduler_mod.scheduler_loop(db))
        app.state.reconcile_task = asyncio.create_task(scheduler_mod._reconciliation_loop(db))
        logger.info("SLA scheduler + reconciliation job launched.")

    except BaseException:
        # Best-effort scheduler cancellation if tasks were partially started
        for task_attr in ("scheduler_task", "reconcile_task"):
            task = getattr(app.state, task_attr, None)
            if task is not None and not task.done():
                task.cancel()
        await client.close()
        client = None
        db = None
        app.state.db = None
        raise


@app.on_event("shutdown")
async def shutdown():
    global client, db

    for task_attr in ("scheduler_task", "reconcile_task"):
        task = getattr(app.state, task_attr, None)
        if task is None:
            continue
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Background task %s failed during shutdown.", task_attr)
        setattr(app.state, task_attr, None)

    if client is not None:
        await client.close()
        client = None
        db = None
        app.state.db = None
        logger.info("MongoDB client closed.")
