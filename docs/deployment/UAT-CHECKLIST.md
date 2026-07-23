# UAT Checklist

## 1. Purpose

This checklist records the minimum user-acceptance and operational validation
required before the app2 deployment can be recommended for production
acceptance.

Package 10 is documentation-only. It does not change application code,
infrastructure, Compose behavior, secrets, certificates, monitoring, backup
jobs, or deployment scripts.

## 2. Current UAT status

**Status: NOT YET UAT-APPROVED.**

Reason: the repository now has production deployment controls, but the UAT
walkthrough and QA-report closure remain incomplete until all listed blockers
are either fixed and retested or explicitly risk-accepted by named owners.

## 3. Release under UAT

| Field | Value |
|---|---|
| Repository | `fahaded0/app2` |
| Main baseline after Package 9 | `7a2b32c91a826733f32e3418f1216a4a926d6ef7` |
| Package 10 branch | `feature/production-pkg10-uat-prod-runbooks` |
| Deployment policy | Explicit Git tag or full commit SHA only |
| Moving branch deployment | Prohibited by Package 9 scripts |
| UAT environment | PENDING |
| UAT release tag/SHA | PENDING |
| UAT approver | PENDING |

## 4. UAT environment setup checklist

| Gate | Required evidence | Status |
|---|---|---|
| Server information worksheet completed | `docs/deployment/SERVER-INFORMATION-WORKSHEET.md` has all target values | PENDING |
| `.env.production` prepared from template | File exists only on target host and is access-restricted | PENDING |
| Production/UAT secrets generated | JWT, Mongo root/app credentials, Mongo keyfile generated outside Git | PENDING |
| Internal CA installed | Approved certificate chain and key installed on target host | PENDING |
| Docker/Compose available | Version recorded in server worksheet | PENDING |
| Backup destination approved | Off-server path or service recorded | PENDING |
| Monitoring path approved | Scheduler, email, escalation, retention recorded | PARTIAL |
| Deployment script used | `deploy/scripts/deploy.sh` executed with explicit tag/SHA | PENDING |
| Health checks pass | `/api/healthz` and `/api/readyz` return 200 | PENDING |
| Rollback drill reviewed | Package 9 drill evidence reviewed | DONE |
| systemd boot/stop validated | VM boot starts stack; shutdown stops gracefully | PENDING TARGET VM |

## 5. Functional UAT walkthrough

| Area | Test | Expected result | Status |
|---|---|---|---|
| Authentication | Login with approved UAT users | Token issued; role shown correctly | PENDING |
| Authorization | Non-authorized routes | Access denied or redirect shown clearly | PENDING |
| Dashboard | KPI cards load | Values render without console/runtime error | PENDING |
| Items | Create/update item fields | Data persists and audit trail is acceptable | PENDING |
| Stock balance | Department-scoped stock view | User only sees authorized department data | PENDING |
| Stock issue | Normal issue path | Balance decreases, transaction recorded | PENDING |
| Stock issue override | Life-saving emergency override | Override requires reason and creates alert/audit | PENDING |
| Barcode scanner | Open/close with no camera | No React crash or white screen | BLOCKED |
| Alerts | Acknowledge/start/resolve/close | Lifecycle and escalation trail persist | PENDING |
| Reports | Report views and export/email | CSV/PDF/email behavior verified | PENDING |
| Settings | SLA and recipients | Changes save and restore as expected | PENDING |
| Audit logs | Restricted access | Unauthorized roles blocked with visible UX | PENDING |
| Arabic/RTL UI | Main pages | Layout, labels, and dialogs remain usable | PENDING |

## 6. QA report review

Package 10 reviewed the existing `test_reports/*.json` and
`test_reports/pytest/*.xml` artifacts. These reports are historical QA
artifacts and are not a replacement for a fresh target-environment UAT run.

| Report | Recorded result | Package 10 interpretation |
|---|---|---|
| `iteration_1.json` | Backend 24/25 after fix; lockout bug remains; logout/403 UX issues | UAT action remains open |
| `iteration_2.json` | JSON summary says Phase 2 backend/frontend regression complete | Must reconcile with XML result |
| `iteration_3.json` | Phase 3 backend 22/22; minor preview issue | Acceptable only if minor issue is risk-accepted or fixed later |
| `iteration_4.json` | Phase 4 backend 23/23 and Phase 3 22/22; high BarcodeScanner crash | UAT blocker until fixed or risk-accepted |
| `pytest/phase2_results.xml` | tests=20, failures=1, errors=2 | Not pass; requires rerun or documented supersession |
| `pytest/phase3_results.xml` | tests=22, failures=0, errors=0 | Pass |
| `pytest/phase4_results.xml` | tests=23, failures=0, errors=0 | Pass |
| `pytest/pytest_results.xml` | tests=25, failures=2, errors=0 | Not pass; requires rerun or documented supersession |

## 7. UAT blockers

| ID | Blocker | Required closure |
|---|---|---|
| UAT-01 | BarcodeScanner can crash React on close when camera is unavailable | Fix and retest, or named risk acceptance with compensating control |
| UAT-02 | Historical XML reports include failures/errors | Fresh full test run or written explanation superseding stale reports |
| UAT-03 | Brute-force lockout concern from iteration 1 | Confirm fixed by test or risk-accept |
| UAT-04 | Logout and forbidden-route UX issues from iteration 1 | Fix/retest or risk-accept |
| UAT-05 | Shared UAT seeded credentials must not use committed sample passwords | Confirm seeding disabled or generated unique credentials |
| UAT-06 | Real UAT deployment walkthrough not yet recorded | Complete Section 4 and Section 5 evidence |

## 8. UAT sign-off

| Role | Name | Decision | Date | Notes |
|---|---|---|---|---|
| System owner | PENDING | PENDING | PENDING |  |
| Application owner | PENDING | PENDING | PENDING |  |
| Cybersecurity / Information Security | PENDING | PENDING | PENDING |  |
| Infrastructure / Operations | PENDING | PENDING | PENDING |  |
| Quality / Internal Audit | PENDING | PENDING | PENDING |  |

## 9. UAT conclusion

UAT is not complete until all blockers in Section 7 are closed or explicitly
risk-accepted by named roles, and the walkthrough evidence in Sections 4 and 5
is completed against a real UAT deployment.