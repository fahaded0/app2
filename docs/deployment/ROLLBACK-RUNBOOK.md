# Rollback Runbook

## 1. Scope

This runbook covers rollback behavior for Production Package 9.

Rollback restores the application containers to a previously approved tag or full
40-character commit SHA. It does not restore MongoDB data by default. Database
restoration remains governed by the Package 7 backup and restore runbook and
requires separate authorization.

## 2. When to rollback

Consider rollback when readiness fails after deployment, the host-level
`health-check.sh` gate exits non-zero, critical users cannot complete core
workflow, or the change owner confirms the release should be backed out.

Do not rollback repeatedly without identifying the failure domain.

## 3. Standard rollback command

Rollback to the previous release recorded by `update.sh`:

```bash
deploy/scripts/rollback.sh \
  --env-file /etc/app2/.env.production \
  --base-url https://app2.internal.example \
  --ca-certificate /usr/local/share/ca-certificates/hospital-root-ca.crt \
  --service-env-file /etc/app2/app2-service.env
```

Rollback to a specific approved release:

```bash
deploy/scripts/rollback.sh \
  --env-file /etc/app2/.env.production \
  --to-release v2026.07.22-prod.1 \
  --base-url https://app2.internal.example \
  --ca-certificate /usr/local/share/ca-certificates/hospital-root-ca.crt \
  --service-env-file /etc/app2/app2-service.env
```

## 4. Optional pre-rollback backup

When MongoDB is healthy and the incident commander wants a final pre-rollback
snapshot, add `--backup-destination /mnt/app2-backups`. Do not use rollback as a
substitute for authorized database restore.

## 5. Rollback gates

The rollback script rejects moving refs, resolves the target release, checks out
detached HEAD, rebuilds application images, starts the Compose stack, runs the
Package 8 health gate, records the restored release as current, and updates the
service environment file when configured.

## 6. Disposable rollback drill evidence

| Drill item | Expected result | Evidence |
|---|---|---|
| Baseline deploy from explicit release | Success | PENDING |
| Moving branch rejected | `main` rejected | PENDING |
| Good update from explicit release | Success after backup | PENDING |
| Bad update from explicit release | Health gate fails | PENDING |
| Rollback to previous release | Success | PENDING |
| Post-rollback `/api/healthz` | HTTP `200` | PENDING |
| Post-rollback `/api/readyz` | HTTP `200` | PENDING |
| Previous release state file | Used or verified | PENDING |
| Cleanup | Disposable resources removed | PENDING |

## 7. Production rollback record

| Field | Value |
|---|---|
| Date/time UTC | PENDING |
| Incident or change ticket | PENDING |
| Operator | PENDING |
| Failed release | PENDING |
| Rollback target release | PENDING |
| Backup artifact before rollback | PENDING |
| Health gate after rollback | PENDING |
| Business validation owner | PENDING |
| Final decision | PENDING |

## 8. Acceptance status

Rollback automation is not considered production-accepted until a successful
bad-update rollback drill is recorded in this runbook.
