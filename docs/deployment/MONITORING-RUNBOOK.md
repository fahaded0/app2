# Monitoring and Health-Check Runbook

## 1. Scope and acceptance status

This runbook covers Production Package 8 monitoring controls for the internal
single-server deployment.

Implemented controls:

- application liveness endpoint: `GET /api/healthz`;
- MongoDB-aware readiness endpoint: `GET /api/readyz`;
- Docker Compose backend healthcheck against readiness;
- Docker Compose HTTPS-edge healthcheck through readiness;
- host-level `deploy/scripts/health-check.sh` for deployment gates and monitoring.

Package 8 is locally accepted after the disposable failure drill in Section 8
completed successfully and its measured evidence was recorded. Production
monitoring operations still require approval of the scheduler, alert recipient,
retention period, escalation channel, and internal CA validation path.

## 2. Endpoint contract

### `GET /api/healthz`

Purpose: prove that the FastAPI process can receive and answer requests.

Expected response:

- HTTP status: `200`;
- body status: `ok`;
- MongoDB availability does not affect this endpoint.

This is a liveness probe. It must not be used as the sole deployment gate.

### `GET /api/readyz`

Purpose: prove that the application is ready to serve business traffic.

The endpoint performs a MongoDB `ping` with a two-second application timeout.

Ready response:

- HTTP status: `200`;
- body status: `ready`;
- MongoDB dependency status: `ready`.

Not-ready response:

- HTTP status: `503`;
- body status: `not_ready`;
- MongoDB dependency status: `unavailable`.

The response deliberately excludes connection strings, credentials, host
details, exception messages, and stack traces.

## 3. Docker Compose monitoring chain

The production Compose health model is:

1. MongoDB uses its authenticated database healthcheck.
2. The backend healthcheck calls `http://127.0.0.1:8000/api/readyz`.
3. The frontend remains dependent on a healthy backend during startup.
4. The HTTPS-edge healthcheck calls
   `https://127.0.0.1:8443/api/readyz`.

A MongoDB outage therefore makes the backend and HTTPS edge unhealthy while the
FastAPI liveness endpoint can remain available for diagnosis.

Docker health is an availability signal, not a complete monitoring platform.
Container restart policy does not repair a failed database, damaged storage,
certificate expiry, or exhausted host resources.

## 4. Host-level check

Production command using the approved internal CA certificate:

```bash
deploy/scripts/health-check.sh \
  --base-url https://app2.internal.example \
  --ca-certificate /usr/local/share/ca-certificates/hospital-root-ca.crt
```

Disposable validation with a self-signed certificate:

```bash
deploy/scripts/health-check.sh \
  --base-url https://127.0.0.1:8443 \
  --insecure
```

`--insecure` is prohibited for routine production monitoring.

The script checks `/api/healthz` and `/api/readyz` and exits non-zero when either
request fails. Package 9 may call this script as a deploy, update, and rollback
gate.

## 5. Recommended monitoring interval

Until an approved enterprise monitoring platform is connected:

- run the host-level check every minute;
- alert after two consecutive failures;
- record recovery after one successful readiness check;
- retain monitoring events according to the hospital operational-log policy.

The scheduler, alert recipient, retention period, and escalation channel must be
approved and recorded before production acceptance. This package does not
install a scheduler or configure an external notification service.

## 6. Response procedure

When readiness fails:

1. confirm the failure from the approved monitoring host;
2. inspect `docker compose ps`;
3. inspect backend and MongoDB container health without printing secrets;
4. check disk capacity, MongoDB logs, and recent deployment activity;
5. do not restart repeatedly without identifying the failure domain;
6. escalate according to the approved application support matrix;
7. record detection, acknowledgement, recovery, root cause, and corrective action.

Do not restore a backup into production merely because readiness failed.
Recovery and restore require the Package 7 authorization and runbook.

## 7. Security requirements

- Health endpoints require no authentication and expose only minimal state.
- Do not add version numbers, database names, hostnames, credentials, exception
  text, or stack traces to health responses.
- Production monitoring must validate the internal CA chain.
- Monitoring output and tickets must not contain secret values.
- Access to container logs and host diagnostics remains restricted to approved
  administrators.

## 8. Required disposable failure drill

The acceptance drill must demonstrate all of the following:

| Test | Expected result | Evidence |
|---|---|---|
| MongoDB available | `/api/healthz` returns `200` | PASSED - HTTP `200` |
| MongoDB available | `/api/readyz` returns `200` | PASSED - HTTP `200` |
| MongoDB stopped deliberately | `/api/healthz` remains `200` | PASSED - HTTP `200` |
| MongoDB stopped deliberately | `/api/readyz` returns `503` | PASSED - HTTP `503` |
| MongoDB stopped deliberately | backend becomes `unhealthy` | PASSED - 154 seconds |
| Failure state | `health-check.sh` exits non-zero | PASSED - exit code `1` |
| MongoDB restarted and ready | readiness returns `200` again | PASSED - 31 seconds to recover |
| Cleanup | disposable containers and volumes removed | PASSED |

Record timestamps, exit codes, Docker health transitions, and recovery duration.
Never perform this deliberate outage against production.

### Disposable failure drill evidence

Recorded local disposable validation:

- Project: `app2-pkg8-7567d11b5374`.
- Outage started UTC: `2026-07-22T11:01:46Z`.
- Recovery completed UTC: `2026-07-22T11:04:51Z`.
- Initial `/api/healthz`: HTTP `200`.
- Initial `/api/readyz`: HTTP `200`.
- Outage `/api/healthz`: HTTP `200`.
- Outage `/api/readyz`: HTTP `503`.
- Recovery `/api/healthz`: HTTP `200`.
- Recovery `/api/readyz`: HTTP `200`.
- Initial `health-check.sh` exit code: `0`.
- Failure `health-check.sh` exit code: `1`.
- Recovery `health-check.sh` exit code: `0`.
- Backend unhealthy transition: `154` seconds.
- Recovery duration: `31` seconds.
- Compose backend health transition: PASSED.
- Mongo-aware readiness behavior: PASSED.
- Liveness during deliberate MongoDB outage: PASSED.
- Host failure-exit behavior: PASSED.
- Resource cleanup: PASSED.
- Repository state during runtime gate: UNCHANGED.

This drill used a disposable local Docker Compose project and deliberately stopped
MongoDB only inside that disposable project. It was not performed against
production.

## 9. Acceptance statement

Package 8 closes control G-14 for local repository readiness after the Section 8
disposable drill passed and this evidence was committed to the runbook.
Production monitoring operations are approved and recorded in Section 10.
Implementation of the Windows scheduled task and email notification plumbing
remains an operational deployment activity.

## 10. Approved production monitoring operations

Approved operating decisions:

| Item | Approved value |
|---|---|
| Monitoring scheduler | Windows Task Scheduler every minute |
| Alerting path | Email |
| Escalation channel | Nursing Office -> Supply Chain Management -> Internal Audit -> Quality Control -> System Administrator (Owner) |
| Retention period | 180 days |
| Internal CA validation path | `C:\ProgramData\app2\certs\hospital-root-ca.crt` |

Operational notes:

- The Windows scheduled task must execute `deploy/scripts/health-check.sh`
  against the approved production base URL.
- Routine production monitoring must validate the internal CA chain using the
  approved CA certificate path.
- Email alerting must avoid secrets, connection strings, host credentials, and
  stack traces.
- Alert evidence and monitoring output must be retained for 180 days.
- System Administrator (Owner) remains accountable for operation of the
  monitoring task and escalation completion.
