# Server Information Worksheet

## 1. Purpose

This worksheet records the target-host values required to deploy, operate,
monitor, back up, and roll back app2. It must be completed before production
acceptance.

Package 10 finalizes this worksheet as a sign-off artifact. Unknown values must
remain marked as `PENDING`; they must not be guessed.

## 2. Server identity

| Field | Value |
|---|---|
| Environment | PENDING |
| Server hostname | PENDING |
| VM platform | Hyper-V target expected; exact host PENDING |
| Operating system | Linux target expected for systemd unit; exact distro/version PENDING |
| CPU | PENDING |
| RAM | PENDING |
| Disk layout | PENDING |
| Static IP | PENDING |
| DNS name | PENDING |
| Network zone/VLAN | PENDING |
| Firewall owner | PENDING |
| System owner | PENDING |
| Operations owner | PENDING |

## 3. Repository and deployment paths

| Field | Value |
|---|---|
| Repository URL | `https://github.com/fahaded0/app2` |
| Application directory | `/opt/app2` |
| Production env file | `/etc/app2/.env.production` |
| systemd environment file | `/etc/app2/app2-service.env` |
| Compose file | `/opt/app2/docker-compose.production.yml` |
| Deployment script | `/opt/app2/deploy/scripts/deploy.sh` |
| Update script | `/opt/app2/deploy/scripts/update.sh` |
| Rollback script | `/opt/app2/deploy/scripts/rollback.sh` |
| Health-check script | `/opt/app2/deploy/scripts/health-check.sh` |
| Backup script | `/opt/app2/deploy/scripts/backup-mongodb.sh` |
| Restore script | `/opt/app2/deploy/scripts/restore-mongodb.sh` |
| Verify-backup script | `/opt/app2/deploy/scripts/verify-backup.sh` |

## 4. Runtime configuration

| Field | Value |
|---|---|
| Compose project name | PENDING |
| HTTPS bind address | PENDING |
| HTTPS port | PENDING |
| App URL | PENDING |
| CORS origin | PENDING |
| Database name | `medstock` unless changed by approved env file |
| Seed data | Must be disabled for production and shared hospital-network UAT |
| Release identifier | Explicit Git tag or full commit SHA only |
| Moving branch deployment | Prohibited |

## 5. Secrets and certificates

| Secret/certificate | Target location | Owner | Rotation | Status |
|---|---|---|---|---|
| JWT secret | Target host or approved secrets manager | PENDING | PENDING | PENDING |
| Mongo root username | File-backed secret | PENDING | PENDING | PENDING |
| Mongo root password | File-backed secret | PENDING | PENDING | PENDING |
| Mongo app username | File-backed secret | PENDING | PENDING | PENDING |
| Mongo app password | File-backed secret | PENDING | PENDING | PENDING |
| Mongo replica-set keyfile | File-backed secret | PENDING | PENDING | PENDING |
| TLS certificate | Target host | PENDING | PENDING | PENDING |
| TLS private key | Target host | PENDING | PENDING | PENDING |
| Internal CA certificate | `C:\ProgramData\app2\certs\hospital-root-ca.crt` for Windows monitoring clients; Linux trust path PENDING | PENDING | PENDING | PARTIAL |

## 6. Backup and restore

| Field | Value |
|---|---|
| Backup destination | PENDING |
| Off-server copy method | PENDING |
| Backup schedule | PENDING |
| Retention | PENDING |
| RPO | PENDING |
| RTO | PENDING |
| Last disposable restore drill | Package 7 completed in disposable environment |
| Target-host restore drill | PENDING |
| Production restore authorization rule | Never restore to production without explicit authorization |

## 7. systemd service

| Field | Value |
|---|---|
| Unit file | `deploy/systemd/app2-compose.service` |
| Installed unit path | `/etc/systemd/system/app2-compose.service` |
| Working directory | `/opt/app2` |
| ExecStart | `docker compose --env-file /etc/app2/.env.production -f docker-compose.production.yml up -d --remove-orphans` |
| ExecStop | `docker compose --env-file /etc/app2/.env.production -f docker-compose.production.yml down --timeout 60` |
| Service type | `oneshot` with `RemainAfterExit=yes` |
| Boot validation | PENDING TARGET VM |
| Graceful stop validation | PENDING TARGET VM |

## 8. Monitoring and alerting values

These values were approved in the Package 8 operations addendum and must be
implemented during target deployment.

| Field | Value |
|---|---|
| Monitoring scheduler | Windows Task Scheduler |
| Monitoring frequency | Every 1 minute |
| Alerting path | Email |
| Escalation channel | Nursing Office - Supply Chain Management - Internal Audit - Quality Control - System Administrator (Owner) |
| Log/evidence retention | 180 days |
| Internal CA validation path | `C:\ProgramData\app2\certs\hospital-root-ca.crt` |
| Scheduled task implementation | PENDING DEPLOYMENT |
| Email plumbing implementation | PENDING DEPLOYMENT |
| First production alert test | PENDING |

## 9. Network and access controls

| Field | Value |
|---|---|
| Inbound client source networks | PENDING |
| Admin source networks | PENDING |
| Docker host firewall policy | PENDING |
| Remote administration method | PENDING |
| Service account model | PENDING |
| File permission evidence | PENDING |
| Log access owner | PENDING |
| Backup access owner | PENDING |

## 10. Final worksheet approval

| Role | Name | Decision | Date |
|---|---|---|---|
| System owner | PENDING | PENDING | PENDING |
| Infrastructure / Operations | PENDING | PENDING | PENDING |
| Cybersecurity / Information Security | PENDING | PENDING | PENDING |
| Application owner | PENDING | PENDING | PENDING |