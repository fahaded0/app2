# Production Deployment Runbook

## 1. Scope

This runbook covers Production Package 9 deployment automation for the internal
single-server Docker Compose deployment.

Package 9 adds deploy, update, and rollback scripts, a systemd service unit, and
production deployment and rollback runbooks. No application code, Docker Compose
service definition, MongoDB backup tooling, monitoring endpoint, or frontend
behavior is changed by this package.

## 2. Release pinning policy

Production deployment must use one of the following only:

- an explicit Git tag; or
- a full 40-character commit SHA.

The scripts reject moving references such as `main`, `master`, `HEAD`,
`origin/main`, `refs/heads/*`, `feature/*`, `bugfix/*`, `hotfix/*`, and
`release/*`.

## 3. Required target-host prerequisites

| Item | Required value or evidence |
|---|---|
| Repository path | Approved deployment directory, for example `/opt/app2` |
| Environment file | Approved ignored file, for example `/etc/app2/.env.production` |
| Service environment file | Approved ignored file, for example `/etc/app2/app2-service.env` |
| Internal CA certificate | Approved CA certificate path |
| Backup destination | Approved off-server mounted path |
| Docker access | Deployment account can run Docker Compose |
| Release identity | Approved tag or full 40-character commit SHA |
| Health endpoint | Approved internal HTTPS base URL |

Never commit `.env.production`, generated secrets, TLS private keys, or service
environment files.

## 4. First deployment procedure

```bash
deploy/scripts/deploy.sh \
  --env-file /etc/app2/.env.production \
  --release v2026.07.22-prod.1 \
  --base-url https://app2.internal.example \
  --ca-certificate /usr/local/share/ca-certificates/hospital-root-ca.crt \
  --service-env-file /etc/app2/app2-service.env
```

The script refuses tracked/staged changes, rejects moving refs, resolves the tag
or SHA to a concrete commit, checks out detached HEAD, builds backend and
frontend images with a release-derived `APP_IMAGE_TAG`, starts the Compose stack,
runs the Package 8 health gate, and records the deployed release state.

## 5. Update procedure

```bash
deploy/scripts/update.sh \
  --env-file /etc/app2/.env.production \
  --release v2026.07.22-prod.2 \
  --base-url https://app2.internal.example \
  --backup-destination /mnt/app2-backups \
  --ca-certificate /usr/local/share/ca-certificates/hospital-root-ca.crt \
  --service-env-file /etc/app2/app2-service.env
```

The update script requires a backup destination and runs the Package 7 MongoDB
backup before changing the checked-out release. It records the pre-update release
under `deploy/state/previous-release.env`.

If the update health gate fails, follow the rollback runbook.

## 6. systemd installation

```bash
sudo cp deploy/systemd/app2-compose.service /etc/systemd/system/app2-compose.service
sudo systemctl daemon-reload
sudo systemctl enable app2-compose.service
```

Start the stack through systemd only after a successful scripted deployment:

```bash
sudo systemctl start app2-compose.service
sudo systemctl status app2-compose.service
```

The unit uses `/opt/app2`, `/etc/app2/.env.production`, and
`/etc/app2/app2-service.env` by default. Adjust only through approved
infrastructure change control.

## 7. Production evidence log

| Field | Value |
|---|---|
| Date/time UTC | PENDING |
| Operator | PENDING |
| Change ticket | PENDING |
| Release tag or SHA | PENDING |
| Resolved commit SHA | PENDING |
| Backup artifact before update | PENDING |
| Health gate result | PENDING |
| Rollback required | PENDING |
| Final decision | PENDING |

## 8. Disposable Package 9 drill evidence

A full deploy-update-rollback drill must be run in a disposable environment
before production acceptance.

| Test | Expected result | Evidence |
|---|---|---|
| Deploy from explicit tag/SHA | deployment succeeds | PENDING |
| Deploy/update using `main` | script refuses moving ref | PENDING |
| Update from explicit tag/SHA | update succeeds after backup | PENDING |
| Bad update | health gate fails | PENDING |
| Rollback script | previous release restored | PENDING |
| Post-rollback health gate | liveness/readiness pass | PENDING |
| systemd unit syntax/path review | unit reviewed for target VM | PENDING |
| systemd boot/stop test on target VM | starts on boot, stops gracefully | PENDING TARGET VM |

## 9. Acceptance status

Package 9 repository readiness is pending until the deploy-update-rollback drill
is executed and recorded in the rollback runbook.

Target-host production acceptance remains pending until the systemd boot and
graceful-stop behavior is validated on the approved Linux VM.

## Package 9 Disposable Drill Evidence - 2026-07-23

- Result: PASSED.
- Project: app2-pkg9-1740931066.
- HTTPS port: 23698.
- Base release: pkg9-drill-base / 07ad7e3e08d382fc266b824b30e35ae58930ffc8.
- Good update release: pkg9-drill-good / 614a15b47651140316f12d70ccdb1dfe53f14f56.
- Deliberate bad release: cbf768528b4350e809b40d55cc84e0743783c1ef.
- Moving branch rejection: PASSED.
- Baseline deploy: PASSED.
- Pre-update backup: PASSED, 1 archive file.
- Good update: PASSED.
- Bad update health-gate failure: PASSED.
- Rollback to previous release: PASSED.
- Post-rollback liveness/readiness/application health: PASSED.
- systemd unit static review: PASSED.
- Target VM systemd boot/stop validation: PENDING TARGET VM.
