# PRD — Critical Medical Stock Monitoring & Alerting System
> Hospital operational oversight system (not just a spreadsheet replacement).

## Phase 2 (current)
Goal: turn the inventory tool into an **operational oversight system** — prevent shortages, detect delays, assign responsibility, and support decisions.

### Implemented (2026-02, day 2)
- **State Machine** for Requests: pending_approval → approved/rejected → dispatched/backorder → partially_received/received → closed. Illegal transitions return HTTP **409** (uniform).
- **Alert Lifecycle**: open → acknowledged → in_progress → resolved → closed, with `resolution_note`, `escalations[]` trail, `escalation_level`, `escalated_to`. Endpoints: `/acknowledge`, `/start`, `/resolve`, `/close`.
- **Background SLA Scheduler** (`scheduler.py`): runs every N minutes; escalates open alerts past their SLA, opens no-update data-quality alerts, escalates overdue backorders.
- **SLA Settings screen** at `/settings`: 6 editable thresholds (Zero/normal, Zero/life-saving, Critical, Backorder, No-Update, Scheduler interval).
- **Excel Import** (`/items/import`): upload .xlsx → preview (created / updated / manual review / errors) → commit. Matching priority: **Barcode → Internal Code → Name → Manual Review**. Empty template download at `/api/items/import/template.xlsx`.
- **Item Master extended**: `udi`, `gtin`, `reorder_qty`, `lead_time_days`, `alternative_item_id`.
- **Dashboard KPIs (new)**: Stock Availability %, Fulfillment Rate (30d), Avg Days Out of Stock, No-Barcode count, Backorder Aging buckets, Top Repeated Stockouts.
- A11y: DialogDescription added to Resolve & Item dialogs.

### Test Status (Iteration 2)
- Backend: **20/20** Phase-2 tests pass + Phase-1 regressions hold. All illegal state transitions return 409 uniformly.
- Frontend: 100% — Alerts lifecycle, Settings, Items extended fields, Excel Import, new Dashboard KPIs verified.
- Background scheduler running, life-saving alerts auto-escalating to L1 → L2 on management.

## Phase 1 (recap — already shipped)
- JWT/RBAC with 10 roles, Item Master, Stock Entry, Requests, Receiving, in-app alerts, Reports + CSV export, Audit Log, English LTR UI.

## Architecture
```
/app/backend
├── server.py          – FastAPI routes (auth, users, items, stock, requests, alerts, reports, settings, import, dashboard)
├── auth.py            – JWT + bcrypt + RBAC + lockout
├── models.py          – Pydantic + extended Item fields
├── state_machine.py   – REQUEST_TRANSITIONS / ALERT_TRANSITIONS + validators (409)
├── settings_store.py  – SLA settings CRUD (Mongo collection 'settings')
├── scheduler.py       – Async background SLA engine (escalations, stale stock, overdue backorder)
├── excel_import.py    – .xlsx parser, preview/commit, match strategy
└── seed.py            – Idempotent seed (admin, depts, items, users, stock, alerts)

/app/frontend/src/pages
├── Dashboard, Items, ImportItems, Stock, Requests, Alerts, Reports,
├── Settings, AuditLog, Users, Departments
└── Login
```

## Backlog
### P0 (next session)
- Email/SMS escalation channels (Resend / Twilio) — bind to the existing escalation engine.
- Stock transactions history page (`/api/stock/transactions` already returns the data).
- Barcode scanner field on Stock Entry (camera or USB HID).

### P1
- Item consumption forecasting (predict shortage X days ahead, suggest reorder qty).
- Mobile/PWA view for ward staff.
- Crash-cart checklist screen.
- Power BI / Tableau read-only API key.

### P2
- AD / Entra ID SSO.
- Anomaly detection (unusual request size from a department).
- WhatsApp Business notifications.
- Auto-suggest alternative item when primary is on backorder.
