# PRD — Critical Medical Stock Monitoring & Alerting System
نظام إدارة ومراقبة توفر المخزون الطبي الحرج والتنبيهات

## Original Problem Statement
Build a real operational system (not just an Excel sheet) that converts hospital critical-stock tracking
into a digital workflow: stock entry → request → approval → dispatch → receiving → close, with RBAC,
audit log, alerts, escalation, and management dashboards. Aligned with NIST CSF 2.0 / OWASP ASVS guidance,
RTL Arabic-first UI, JWT auth, in-app notifications.

## Architecture
- **Backend**: FastAPI + Motor (MongoDB) — UUID string IDs, ISO datetimes (UTC).
  - `auth.py`: bcrypt hashing, JWT (access+refresh), brute-force lockout (email-based, K8s-safe), RBAC factory.
  - `models.py`: Pydantic models for Users, Departments, Items, StockEntry, StockRequest, Alert, AuditLog.
  - `seed.py`: idempotent seed of admin, 5 sample users, 5 departments, 12 items, 24 stock entries, alerts.
  - `server.py`: routes under `/api` — auth, users, departments, items, stock, requests, alerts, dashboard, audit-logs, reports (+ CSV export).
- **Frontend**: React 19 + Tailwind + shadcn/ui + recharts, RTL Arabic-first.
  - Fonts: Cairo (heading) + IBM Plex Sans Arabic (body).
  - Bearer token (localStorage) flow.
  - `RoleGuard` wraps admin-only routes.

## Core Requirements (static)
1. RBAC with 10 roles (super_admin, digital_health_manager, hospital_manager, department_head, department_stock_officer, supply_officer, procurement, quality, auditor, viewer).
2. Item Master with internal_code, barcode, UDI, min/critical/max levels, life-saving & crash-cart flags.
3. Stock entry per department with auto-computed status (zero/critical/available/back_in_stock).
4. Request lifecycle: pending_approval → approved/rejected → dispatched → received / closed → backorder.
5. Alerts on Zero Level / Critical Level / Backorder / Life-Saving items; ack workflow.
6. Audit Log (read-only) — every create/update/login/logout captured with old+new + IP.
7. Dashboard KPIs: zero/critical/backorder counts, life-saving items at risk, top affected departments, recent alerts.
8. CSV exports for 6 reports (zero, critical, backorder, open_requests, no_barcode, life_saving).
9. Security: bcrypt + JWT, brute-force lockout, HTTPS-only (handled by ingress), no deletes (only inverse moves).

## What's Implemented (2026-02 - day 1)
- ✅ Full backend with all endpoints listed above.
- ✅ Auto-seed on startup (idempotent).
- ✅ Login screen with RTL hospital imagery + demo credentials.
- ✅ Dashboard with stacked bar chart by department + pie chart distribution + recent alerts feed + top-departments.
- ✅ Items page with search + category filter + dialog for create/edit + life-saving / crash-cart badges.
- ✅ Stock page with dept + status filters, balance update dialog with auto-status, dept isolation for officers.
- ✅ Requests page with full lifecycle: create → approve/reject → dispatch/backorder → receive (partial OK).
- ✅ Alerts inbox with severity color coding + acknowledge flow.
- ✅ Reports page with 6 reports + CSV export.
- ✅ Audit Log table with entity filter (admin/auditor only).
- ✅ Users + Departments management (admin only).
- ✅ Role-based sidebar + RoleGuard component for /audit-logs, /users, /departments.

## Testing Status (Iteration 1)
- Backend: 24/25 tests passing (96%) — lockout bug fixed (email-only identifier).
- Frontend: All flows E2E verified — login, dashboard, RBAC sidebar, items, stock, requests lifecycle, alerts, reports, audit logs, forbidden screen.

## User Personas
- **Stock Officer (ER/ICU)**: updates department balances, raises requests, confirms receiving.
- **Department Head**: approves/rejects requests from their department.
- **Supply Officer**: reviews approved requests, dispatches or sets backorder.
- **Auditor / Digital Health Manager**: reads audit log + dashboards.
- **Super Admin**: manages users, departments, item master, all settings.

## Prioritized Backlog
### P0 (next)
- Email/SMS alert channels (Resend / Twilio).
- Stock transactions history page (UI for the existing /api/stock/transactions endpoint).
- Items: import via CSV / barcode-scanner field on stock entry screen.

### P1
- Escalation rules engine (auto-escalate Backorder > 24h to managers).
- Crash-cart checklist views.
- Power BI / Excel exports for management.
- Dark theme toggle.

### P2
- Mobile responsive views + native PWA shell.
- AD / Entra ID SSO integration.
- Consumption forecasting (Prophet / ARIMA).
- WhatsApp Business notifications.
