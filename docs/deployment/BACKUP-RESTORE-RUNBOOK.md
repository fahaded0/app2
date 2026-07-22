# MongoDB Backup and Restore Runbook

## Status

**Package 7 tooling implemented; production acceptance remains blocked until an
approved off-server destination and schedule are configured on the target host,
and a target-host restore drill is recorded.**

This runbook covers the application database only. It does not back up MongoDB
administrative users, the replica-set key, TLS material, or any other secret.
Those items must be protected separately by the approved secrets-management
process.

## Files

- `deploy/scripts/backup-mongodb.sh`
- `deploy/scripts/restore-mongodb.sh`
- `deploy/scripts/verify-backup.sh`

## Backup design

The backup script:

1. requires the production Compose environment file;
2. confirms that the production MongoDB container is running and healthy;
3. authenticates inside the MongoDB container using its root secret files;
4. captures the application database collection counts and `dbHash`;
5. creates a compressed MongoDB archive using the pinned MongoDB 8 tools;
6. creates a SHA-256 sidecar and manifest; and
7. publishes the files atomically only after every step succeeds.

Credential values are not passed on the host command line or printed.

### Consistency requirement

The archive covers one application database. Application writes must be
quiesced during the backup window. This package does not claim an online
point-in-time backup based on an oplog. Schedule the backup during an approved
maintenance window or stop write-producing application services before the
backup starts.

## Production prerequisites

Before enabling the schedule:

- mount an approved off-server destination on the Ubuntu host;
- restrict the mount and backup files to the backup/service account;
- enable encryption at rest and in transit according to organizational policy;
- define retention, immutability, and deletion rules;
- confirm available capacity and alerting;
- record the backup owner and restore authority; and
- confirm that the destination is not located on the same VM or the same
  underlying virtual disk as MongoDB.

A local folder is permitted only for a disposable drill and is not accepted as
the production backup destination.

## Create a backup

From the repository root on the target host:

```bash
./deploy/scripts/backup-mongodb.sh \
  --env-file .env.production \
  --destination /mnt/approved-offserver-backup/app2
```

Expected files share the same UTC timestamp:

- `*.archive.gz`
- `*.sha256`
- `*.source-state.json`
- `*.manifest`

The script must exit zero and print all four final paths.

## Verify a backup with a disposable restore

```bash
./deploy/scripts/verify-backup.sh \
  --archive /mnt/approved-offserver-backup/app2/<backup>.archive.gz \
  --sha256 /mnt/approved-offserver-backup/app2/<backup>.sha256 \
  --source-state /mnt/approved-offserver-backup/app2/<backup>.source-state.json
```

Verification starts an isolated, unpublished, disposable MongoDB container,
restores the archive, compares SHA-256, `dbHash`, and collection counts, then
removes the container. A zero exit code and `PASSED` are required.

## Restore procedure

A production restore is a controlled change and must not be executed merely to
test the script.

Required controls:

1. incident/change authorization is recorded;
2. the application is placed in maintenance mode and writes are stopped;
3. the target database name is confirmed independently;
4. a fresh pre-restore backup is taken when the source remains readable;
5. the exact archive SHA-256 is verified;
6. the restore target and authentication secret-file paths are reviewed; and
7. post-restore application and audit-log validation is assigned.

Example against a running MongoDB container whose root credentials are mounted
at the production secret paths:

```bash
./deploy/scripts/restore-mongodb.sh \
  --container <mongo-container-name> \
  --archive <backup>.archive.gz \
  --source-db medstock \
  --target-db medstock \
  --confirm-target-db medstock \
  --username-file /run/secrets/mongo_root_username \
  --password-file /run/secrets/mongo_root_password \
  --authentication-db admin \
  --drop
```

`--confirm-target-db` is mandatory and must exactly match `--target-db`.
`--drop` removes each restored target collection before import. Do not use it
until the target has been independently confirmed.

## Scheduling

Configure the target host scheduler only after the off-server destination is
approved. Example daily cron entry at 02:15:

```cron
15 2 * * * cd /opt/app2 && ./deploy/scripts/backup-mongodb.sh --env-file .env.production --destination /mnt/approved-offserver-backup/app2 >> /var/log/app2-backup.log 2>&1
```

The scheduler must alert on a non-zero exit code. At least one disposable
restore verification must run on a separate schedule, and after any material
MongoDB or backup-tooling change.

## Retention

Retention values require approval. Do not delete the only known-good backup.
A production policy should define at least daily, weekly, and monthly retention,
legal/privacy requirements, and secure deletion.

## Disposable development restore drill evidence

The following drill validates the Package 7 tooling in a disposable local
environment. It does **not** replace the required target-host drill or approve
the production backup destination, schedule, retention, RPO, or RTO.

- Drill date (UTC): `2026-07-22`
- Environment: Windows host, Docker Engine `29.5.3`, Git Bash
- Source database: `medstock`
- Source fixture: 2 collections and 4 documents
- Archive identifier: `app2-medstock-20260722T060411Z.archive.gz`
- Archive size: `535` bytes
- Measured backup duration: `2` seconds
- Measured disposable restore-verification duration: `4` seconds
- Archive SHA-256 verification: **PASSED**
- Disposable isolated restore: **PASSED**
- Restored documents: `4`; failures: `0`
- `dbHash` comparison: **PASSED**
- Per-collection record-count comparison: **PASSED**
- Disposable container cleanup: **PASSED**
- Disposable Compose container/volume cleanup: **PASSED**
- Repository state after drill: unchanged; no staged files, commits, or push
- Drill result: **PASSED**

Production acceptance remains blocked until an approved off-server destination,
approved schedule and retention policy, approved RPO, and a target-host backup
and restore drill are recorded.
## RPO and RTO evidence

- Approved backup frequency: **PENDING**
- Approved off-server destination: **PENDING**
- Measured backup duration: **PENDING**
- Measured disposable restore-verification duration: **PENDING**
- Approved RPO: **PENDING**
- Measured/approved RTO: **PENDING**
- Drill date and operator: **PENDING**
- Drill archive identifier and SHA-256 reference: **PENDING**
- Drill result: **PENDING**

Package 7 is closed only after these fields are completed from an actual
target-host backup and restore drill, not estimates.

## Rollback

The scripts are additive and do not change the running stack. Stop using the
new schedule and scripts to roll back this package. Never delete existing
backups during rollback. A restore operation is destructive when `--drop` is
used and requires its own recovery plan and fresh pre-restore backup.
