# PRD — Critical Medical Stock Monitoring & Alerting System
> Hospital operational oversight system (not just a spreadsheet replacement).

## Phase 3 (current) — Stock Issue with Reserve Control & Escalation

### Implemented (2026-02, day 3)
- **Stock Issue Workflow** with all 5 decision rules enforced by backend:
  1. `normal` — projected ≥ minimum → allow
  2. `below_minimum` — critical < projected < minimum → allow + warning alert
  3. `below_critical` — no_issue ≤ projected ≤ critical → allow + danger alert (escalate to supply + dept head)
  4. `blocked_no_issue` — projected < no_issue & not life-saving → BLOCK
  5. `emergency_override` — projected < no_issue, life-saving, override_reason provided → allow + critical alert + email escalation
- **Per-department thresholds** collection `item_department_thresholds` with strict ordering (`no_issue ≤ reserve ≤ critical ≤ minimum`), managed via Items page → Sliders icon dialog.
- **Resend Email Integration** (`email_service.py`) — escalation emails sent via FastAPI BackgroundTasks (non-blocking), recipients resolved from active users by role + optional pinned recipients (`escalation_recipients` collection).
- **New API endpoints**:
  - `GET /api/stock-balance/{department_id}/{item_id}`
  - `POST /api/stock/issue/preview` (now accepts override_reason)
  - `POST /api/stock/issue`
  - `GET /api/items/{id}/thresholds` and `GET/PUT /api/items/{id}/thresholds/{department_id}`
  - `GET/PUT /api/settings/escalation-recipients`
- **Frontend pages/components**:
  - `/stock/issue` page with RiskBadge + IssuePreviewCard, Emergency Override panel for life-saving items
  - Settings page now has two tabs: SLA & Escalation, Escalation Recipients
  - Items page now has per-row thresholds editor (Sliders icon)
- **Audit log** entries for `upsert_threshold`, `stock_issue`, `stock_issue_override`, `set_escalation_recipient`.

### Test Status (Iteration 3)
- Backend: **22/22** Phase 3 tests pass (test_phase3_stock_issue.py). Phase 1 & 2 regressions hold (one Phase 2 test fails on pre-existing duplicate seed data, unrelated to Phase 3).
- Frontend: data-testids confirmed present on `/stock/issue` (issue-department-select, issue-item-select, preview-issue-button, override-reason-input, emergency-issue-button, confirm-issue-button, issue-result-card), `/items` thresholds dialog (th-dept-select, th-min/crit/reserve/noissue-input, save-threshold-button), `/settings` recipients tab (recipient-input/save/clear per role).
- Resend integration installed and configured; emails fire on `escalate_to` roles via BackgroundTasks.

## Phase 2 (recap — already shipped)
- State Machine for Requests (illegal transitions return 409)
- Alert Lifecycle (open → acknowledged → in_progress → resolved → closed) + Background SLA Scheduler
- Excel Import (.xlsx) with preview/commit + matching priority Barcode→Code→Name→Manual
- Dashboard KPIs with click-to-drill modals
- Item Master extended fields (udi, gtin, reorder_qty, lead_time_days, alternative_item_id)
- 10 formal Reports with PDF (reportlab) + Excel export

## Phase 1 (recap — already shipped)
- JWT/RBAC with 10 roles, Item Master, Stock Entry, Requests, Receiving, in-app alerts, Reports + CSV export, Audit Log, English LTR UI.

## Architecture
```
/app/backend
├── server.py            – FastAPI routes (≈1700 lines, see refactor backlog below)
├── auth.py              – JWT + bcrypt + RBAC + lockout
├── models.py            – Pydantic models incl. Phase 3 payloads
├── state_machine.py     – REQUEST_TRANSITIONS / ALERT_TRANSITIONS validators (409)
├── settings_store.py    – SLA settings CRUD
├── scheduler.py         – Async background SLA engine
├── excel_import.py      – .xlsx parser
├── reports_data.py      – Report aggregations
├── reports_export.py    – PDF/Excel generators
├── stock_issue.py       – Decision engine + threshold helpers (Phase 3)
├── email_service.py     – Resend integration + recipient resolver (Phase 3)
├── seed.py              – Idempotent seed
└── tests/               – pytest suites (Phase 2 + Phase 3)

/app/frontend/src/pages
├── Dashboard, Items, ImportItems, Stock, StockIssue, Requests, Alerts,
├── Reports, Settings (SLA + Recipients tabs), AuditLog, Users, Departments
└── Login
/app/frontend/src/components
├── Layout, RoleGuard, StatusBadge, KpiDetailDialog,
└── IssuePreviewCard, RiskBadge   (Phase 3)
```

## Backlog
### P0 (next session)
- Barcode/QR scanner for Stock Entry (mobile + USB HID).
- Stock transactions history page (`/api/stock/transactions` already returns the data).
- One-click "Email PDF to manager" inside the Reports page.

### P1
- Refactor `server.py` (≈1700 lines) into `backend/routes/` modules: `stock_issue.py`, `thresholds.py`, `escalation.py`, `requests.py`, `alerts.py`, `dashboard.py`, `audit.py`.
- Idempotency / reconciliation job for the 3 sequential writes in `stock_issue_execute` (Mongo standalone has no transactions).
- Item consumption forecasting (predict shortage X days ahead, suggest reorder qty).
- Mobile/PWA view for ward staff. Crash-cart checklist screen.

### P2
- AI features: anomaly detection on consumption, suggest alternative item when on backorder.
- AD/Entra ID SSO, WhatsApp Business notifications.
- Power BI / Tableau read-only API key.
- External integration with HIS/EHR + Central Warehouse.

### Known minor issues
- Preview→execute consistency: ✅ FIXED in iteration 3 — preview now accepts `override_reason` and returns the correct rule (`emergency_override` vs `blocked_no_issue`).
- `email_service.set_escalation_recipient` lowercases emails before storing — frontend should expect lowercased values on read (already handled in UI).
- `calc_status` returns `below_minimum` but `stock_entries.status` only allows {available, critical_level, zero_level, back_in_stock} — minor duplication, runtime correct.
