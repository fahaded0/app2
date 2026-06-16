"""Pydantic models for the Critical Medical Stock Monitoring System."""
from __future__ import annotations
from typing import Optional, Literal
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field, EmailStr, ConfigDict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------- Roles ----------
Role = Literal[
    "super_admin",
    "digital_health_manager",
    "hospital_manager",
    "department_head",
    "department_stock_officer",
    "supply_officer",
    "procurement",
    "quality",
    "auditor",
    "viewer",
]

# ---------- User ----------
class UserPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: EmailStr
    full_name: str
    role: Role
    department_id: Optional[str] = None
    is_active: bool = True
    created_at: str

class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: Role
    department_id: Optional[str] = None

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[Role] = None
    department_id: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

class LoginBody(BaseModel):
    email: EmailStr
    password: str


# ---------- Department ----------
class Department(BaseModel):
    id: str = Field(default_factory=_new_id)
    code: str   # ER, ICU, LAB...
    name_ar: str
    name_en: str
    is_critical: bool = False
    created_at: str = Field(default_factory=_now_iso)

class DepartmentCreate(BaseModel):
    code: str
    name_ar: str
    name_en: str
    is_critical: bool = False


# ---------- Item ----------
ItemCategory = Literal["Airway", "PPE", "Lab", "IV", "Wound Care", "Equipment", "Medication", "Other"]
Unit = Literal["PCS", "BOX", "KIT", "VIAL", "PACK"]

class Item(BaseModel):
    id: str = Field(default_factory=_new_id)
    internal_code: str           # internal SKU
    barcode: Optional[str] = None
    udi: Optional[str] = None
    name_ar: str
    name_en: str
    category: ItemCategory = "Other"
    unit: Unit = "PCS"
    min_level: int = 0
    critical_threshold: int = 0
    max_level: int = 0
    is_life_saving: bool = False
    is_crash_cart: bool = False
    requires_expiry: bool = False
    supplier: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

class ItemCreate(BaseModel):
    internal_code: str
    barcode: Optional[str] = None
    udi: Optional[str] = None
    name_ar: str
    name_en: str
    category: ItemCategory = "Other"
    unit: Unit = "PCS"
    min_level: int = 0
    critical_threshold: int = 0
    max_level: int = 0
    is_life_saving: bool = False
    is_crash_cart: bool = False
    requires_expiry: bool = False
    supplier: Optional[str] = None
    notes: Optional[str] = None

class ItemUpdate(BaseModel):
    barcode: Optional[str] = None
    udi: Optional[str] = None
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    category: Optional[ItemCategory] = None
    unit: Optional[Unit] = None
    min_level: Optional[int] = None
    critical_threshold: Optional[int] = None
    max_level: Optional[int] = None
    is_life_saving: Optional[bool] = None
    is_crash_cart: Optional[bool] = None
    requires_expiry: Optional[bool] = None
    supplier: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


# ---------- Stock ----------
StockStatus = Literal["zero_level", "critical_level", "available", "back_in_stock", "backorder"]

class StockEntry(BaseModel):
    """Latest stock state per (department, item)."""
    id: str = Field(default_factory=_new_id)
    department_id: str
    item_id: str
    balance: int = 0
    status: StockStatus = "available"
    last_updated_by: str           # user id
    last_updated_by_name: str
    last_updated_at: str = Field(default_factory=_now_iso)
    shortage_start: Optional[str] = None
    notes: Optional[str] = None

class StockEntryUpdate(BaseModel):
    department_id: str
    item_id: str
    balance: int
    notes: Optional[str] = None


# ---------- Requests ----------
RequestStatus = Literal[
    "pending_approval",
    "approved",
    "rejected",
    "dispatched",
    "partially_received",
    "received",
    "closed",
    "backorder",
]
Priority = Literal["routine", "urgent", "stat"]

class StockRequest(BaseModel):
    id: str = Field(default_factory=_new_id)
    request_number: str            # human-friendly
    department_id: str
    item_id: str
    requested_qty: int
    approved_qty: Optional[int] = None
    dispatched_qty: int = 0
    received_qty: int = 0
    priority: Priority = "routine"
    reason: Optional[str] = None
    status: RequestStatus = "pending_approval"
    created_by: str
    created_by_name: str
    created_at: str = Field(default_factory=_now_iso)
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_reason: Optional[str] = None
    dispatched_at: Optional[str] = None
    received_at: Optional[str] = None
    closed_at: Optional[str] = None
    expected_supply_date: Optional[str] = None

class StockRequestCreate(BaseModel):
    department_id: str
    item_id: str
    requested_qty: int
    priority: Priority = "routine"
    reason: Optional[str] = None

class ApproveBody(BaseModel):
    approved_qty: int

class RejectBody(BaseModel):
    reason: str

class DispatchBody(BaseModel):
    dispatched_qty: int
    backorder: bool = False
    expected_supply_date: Optional[str] = None

class ReceiveBody(BaseModel):
    received_qty: int
    note: Optional[str] = None


# ---------- Alerts ----------
AlertSeverity = Literal["info", "warning", "danger", "critical"]
AlertType = Literal[
    "zero_level",
    "critical_level",
    "backorder",
    "no_update",
    "delay_receiving",
    "repeated_stockout",
    "life_saving_item",
    "missing_barcode",
]

class AlertEvent(BaseModel):
    id: str = Field(default_factory=_new_id)
    type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    department_id: Optional[str] = None
    item_id: Optional[str] = None
    request_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None


# ---------- Audit Log ----------
class AuditLog(BaseModel):
    id: str = Field(default_factory=_new_id)
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_role: Optional[str] = None
    action: str           # login, create_item, update_stock, approve_request...
    entity: str           # users, items, stock, requests, alerts
    entity_id: Optional[str] = None
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    ip: Optional[str] = None
    reason: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
