# Production Acceptance Checklist

This file is started by Production Readiness Package 6 and will be finalized
by Package 10. It records the secrets and environment-hardening evidence and
the governance decisions that must be signed before production deployment.

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

## Required sign-offs

| Role | Name | Decision | Date |
|---|---|---|---|
| System owner | PENDING | PENDING | PENDING |
| Cybersecurity / Information Security | PENDING | PENDING | PENDING |
| Infrastructure / Operations | PENDING | PENDING | PENDING |
| Application owner | PENDING | PENDING | PENDING |

## Package 6 closure rule

Package 6 may be closed only when:

1. the target-host production secrets have been generated and access-restricted;
2. the repository-history findings remain triaged with no unresolved real
   secret;
3. G-04 and G-19 have signed decisions with named owners;
4. any required follow-up code package or time-bound risk acceptance is
   recorded; and
5. no production secret value has been committed, staged, printed, or pushed.
