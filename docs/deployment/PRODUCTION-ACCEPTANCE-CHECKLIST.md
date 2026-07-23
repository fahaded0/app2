# Production Acceptance Checklist

This file is started by Production Readiness Package 6 and finalized by
Package 10 as the consolidated production sign-off checklist. It records the
secrets and environment-hardening evidence, remaining blockers, and governance
decisions that must be signed before production deployment.

## Executive conclusion

**Current conclusion: NOT READY FOR PRODUCTION.**

The repository has completed the infrastructure-readiness packages through
Package 9, including deployment and rollback automation. However, production
acceptance remains blocked until target-host values, secrets, internal CA,
backup destination, monitoring implementation, systemd boot/stop validation,
QA/UAT closure, and named governance sign-offs are completed.

## Package 6 status

**Status: BLOCKED pending governance sign-off and target-host secret
provisioning.**

Package 6 does not place production secret values in Git. Actual values must be
generated and stored on the approved target host or in an approved secrets
manager.

## Repository-history secret scan

Manual read-only scan performed against:

- Branch: `feature/production-pkg6-secrets-env-hardening`
- Baseline commit: `72cf4edb503237500dd2616cb07a165499b3b2ec`
- History lines read: 66,914
- Historical candidate instances semantically triaged: 1,225
- Unique semantic findings: 175
- Potential literal-secret findings: **0**
- Secret values printed by the scan: **0**
- Repository files modified by the scan: **0**

Result: no potential real literal secret was identified by the completed
pattern and semantic triage. This is manual evidence, not an automated CI
secret-scanning control.

## Secret-storage controls

- [x] `.env.production` is ignored by Git.
- [x] Generated MongoDB `*.key` files are ignored by Git.
- [x] TLS `*.pem` and `*.key` files are ignored by Git.
- [x] The committed production environment template contains no secret value.
- [x] MongoDB application credentials are separated from MongoDB root
      credentials.
- [ ] Generate a fresh production `JWT_SECRET` on the approved target host or
      in the approved secrets manager.
- [ ] Generate the five MongoDB production secret files on the approved target
      host.
- [ ] Install the approved internal-CA certificate chain and private key.
- [ ] Create `.env.production` from `.env.production.example` on the target
      host and review every variable.
- [ ] Restrict `.env.production` and secret files to the deployment/service
      accounts according to the approved operating-system access model.
- [ ] Verify `git status --ignored` and `git check-ignore` on the target host
      before first deployment.
- [ ] Record the secret owner, rotation authority, rotation interval, and
      emergency-revocation process in the production runbook.
- [ ] Confirm that no secret value appears in Compose output, Docker inspect
      metadata, image layers, application logs, tickets, email, or chat.

## Consolidated production blocker register

| ID | Area | Current status | Required closure |
|---|---|---|---|
| G-04 | Browser token storage | PENDING SIGN-OFF | Replace localStorage token model in a reviewed app-security package, or obtain named time-bound risk acceptance |
| G-09 | Backup/restore | REPOSITORY EVIDENCE COMPLETE; OPERATIONS PENDING | Approve off-server destination, schedule, retention, RPO, target-host restore drill, and measured RTO |
| G-14 | Monitoring | REPOSITORY EVIDENCE COMPLETE; IMPLEMENTATION PENDING | Implement Windows scheduled task, email plumbing, retention, escalation, and first alert test |
| G-18 | Release/versioning | CLOSED BY PACKAGE 9 | Use explicit tag/full SHA; Package 9 scripts reject moving branch refs |
| G-19 | Seed credentials | PENDING SIGN-OFF | Confirm seeding prohibited in production/shared UAT, or approve separate generated-credential package |
| G-24 | QA/UAT evidence | NOT CLOSED | Reconcile failing historical XML reports, close high frontend issue, and complete real UAT walkthrough |
| OPS-01 | Target-host secrets | PENDING | Generate and access-restrict production secrets on approved host |
| OPS-02 | Internal CA/TLS | PENDING | Install approved certificate chain and private key; validate client trust path |
| OPS-03 | systemd boot/stop | PENDING TARGET VM | Validate VM boot starts stack and shutdown stops gracefully |
| OPS-04 | Server worksheet | PENDING | Complete `SERVER-INFORMATION-WORKSHEET.md` with actual values |
| OPS-05 | Final sign-off | PENDING | Named role approvals recorded below |

## G-19 decision: sample seed credentials

**Recommended decision: seeding is prohibited in production and in every
shared UAT/staging environment reachable from the hospital network.**

`SEED_DATA_ENABLED` must remain `false` in those environments. The sample
credentials committed in `backend/seed.py` are development-only. If shared
UAT requires seeded users, that work must be a separate reviewed code package
that generates unique non-public credentials and includes its own rollback
plan.

- Decision owner: **PENDING**
- Decision: **PENDING SIGN-OFF**
- Sign-off date: **PENDING**
- Evidence/reference: **PENDING**

## G-04 decision: browser token storage

**Recommended decision: browser access tokens stored in `localStorage` are not
approved for production.**

A separate reviewed application-security package must remove or replace this
storage model before production approval, or a named risk owner must formally
accept the residual risk with an expiry date and compensating controls.
Package 6 makes no frontend code change.

- Decision owner: **PENDING**
- Decision: **PENDING SIGN-OFF**
- Required follow-up package or risk-acceptance reference: **PENDING**
- Sign-off date: **PENDING**

## QA and UAT evidence summary

Existing historical reports were reviewed during Package 10.

| Evidence | Result | Production interpretation |
|---|---|---|
| `iteration_1.json` | 24/25 backend after fix; lockout bug and UX issues noted | Not final production evidence |
| `iteration_2.json` | JSON says Phase 2 complete | Must reconcile with XML failures/errors |
| `iteration_3.json` | 22/22 backend; minor preview issue | Acceptable only with minor issue disposition |
| `iteration_4.json` | 23/23 Phase 4 and 22/22 Phase 3; high BarcodeScanner issue | Production blocker until fixed or risk-accepted |
| `pytest/phase2_results.xml` | tests=20, failures=1, errors=2 | Not pass |
| `pytest/phase3_results.xml` | tests=22, failures=0, errors=0 | Pass |
| `pytest/phase4_results.xml` | tests=23, failures=0, errors=0 | Pass |
| `pytest/pytest_results.xml` | tests=25, failures=2, errors=0 | Not pass |

Conclusion: G-24 is not closed until a fresh target-environment UAT/test record
supersedes the failing historical XML reports and disposes of the high
BarcodeScanner issue.

## Required production sign-offs

| Role | Name | Decision | Date | Required scope |
|---|---|---|---|---|
| System owner | PENDING | PENDING | PENDING | Overall production acceptance |
| Cybersecurity / Information Security | PENDING | PENDING | PENDING | G-04, G-19, secrets, TLS, access controls |
| Infrastructure / Operations | PENDING | PENDING | PENDING | VM, Docker, systemd, monitoring, backup |
| Application owner | PENDING | PENDING | PENDING | Functional UAT and application risk |
| Quality / Internal Audit | PENDING | PENDING | PENDING | QA evidence and production blocker disposition |

## Final production acceptance rule

Production deployment is not approved until:

1. every row in the consolidated production blocker register is closed or
   explicitly risk-accepted by a named owner;
2. the server information worksheet is completed with actual target-host values;
3. production secrets and TLS materials are generated and access-restricted on
   the approved target host;
4. backup, restore, monitoring, and alerting are operationally implemented;
5. systemd boot and graceful stop are validated on the target VM;
6. UAT is completed and signed; and
7. no production secret value has been committed, staged, printed, or pushed.