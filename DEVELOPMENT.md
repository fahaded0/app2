# Development Guide

## Python version

Python 3.11 or later is required.

## Backend startup

```bash
cd backend
pip install -r requirements.txt   # or requirements.app.txt if present
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

## Frontend startup

```bash
cd frontend
yarn install
yarn start
```

## Environment variables

Copy `.env.example` to `.env` in the project root and fill in real values:

```bash
cp .env.example .env
```

The backend loads `.env` automatically on startup via `python-dotenv`.

| Variable | Required | Description |
|---|---|---|
| `APP_ENV` | No | `development` or `production` (default: `development`) |
| `MONGO_URL` | Yes | MongoDB connection string |
| `DB_NAME` | Yes | MongoDB database name |
| `JWT_SECRET` | Yes | Long random secret for JWT signing |
| `ADMIN_EMAIL` | Yes (seeding) | Email address of the seeded admin account |
| `ADMIN_PASSWORD` | Yes (seeding) | Password of the seeded admin account |
| `SEED_DATA_ENABLED` | No | `true` to run seeder on startup (see below) |
| `COOKIE_SECURE` | No | `true` in production (requires HTTPS), `false` locally |
| `COOKIE_SAMESITE` | No | One of `lax`, `strict`, `none` (default: `lax`) |
| `CORS_ALLOWED_ORIGINS` | No | Comma-separated list of allowed origins |
| `REACT_APP_BACKEND_URL` | Yes (frontend/tests) | URL the frontend and tests use to reach the API |
| `RESEND_API_KEY` | No | Resend API key for outbound email |
| `SENDER_EMAIL` | No | From-address for outbound email |
| `APP_URL` | No | Public URL used in email links |
| `CI_INTEGRATION_TESTS_REQUIRED` | No | `true`/`false`/`1`/`0`/`yes`/`no` — abort CI when backend URL is missing (default: `false`) |

## SEED_DATA_ENABLED behavior

When `SEED_DATA_ENABLED=true` the backend inserts sample departments, items, stock entries, and users on every startup, using an **insert-if-missing** strategy:

- New records are created with `is_active=true`.
- Existing records are **never** deactivated or reactivated by the seeder.
- Name fields are normalized to English if they differ.
- No credentials or passwords are written to disk.

When `SEED_DATA_ENABLED` is absent or any value other than `true` (default), the seeder is skipped entirely and an informational log message is emitted.

**Do not set `SEED_DATA_ENABLED=true` against a production database.**

## Cookie configuration

`COOKIE_SECURE` controls the `Secure` flag on session cookies.

**Default: `true`** — cookies require HTTPS. This is the safe default for production and the value shown in `.env.example`.

For local HTTP development you must explicitly override it:

```
COOKIE_SECURE=false
```

Accepted values: `true`, `false`, `1`, `0`, `yes`, `no`. Any other value raises a configuration error at login time.

`COOKIE_SAMESITE` controls the `SameSite` attribute. Valid values: `lax` (default), `strict`, `none`. Any other value raises a configuration error. Setting `COOKIE_SAMESITE=none` while `COOKIE_SECURE=false` is also rejected — browsers ignore `SameSite=None` cookies that lack the `Secure` flag.

## CORS configuration

Set `CORS_ALLOWED_ORIGINS` to a comma-separated list of origins that the browser is allowed to send requests from:

```
CORS_ALLOWED_ORIGINS=https://app.example.com,https://staging.example.com
```

- Whitespace around commas is stripped; empty entries are ignored.
- If the list is non-empty, `allow_credentials=true` is set automatically.
- If the variable is empty or unset, all cross-origin requests are blocked and a warning is logged at startup. There is no wildcard fallback.

## Integration tests

### Architecture

Integration tests are marked with `pytest.mark.integration`. The centralized guard lives in
`backend/tests/conftest.py` — a single enforcement point that controls skip and CI-abort
behaviour for all four integration modules. No test module duplicates this logic.

Unit tests (`test_runtime_config.py`, `test_server_lifecycle.py`, `test_test_infrastructure.py`)
carry no `integration` marker and always run, regardless of `REACT_APP_BACKEND_URL`.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `REACT_APP_BACKEND_URL` | Yes (integration) | URL of the live backend, e.g. `http://localhost:8000` |
| `CI_INTEGRATION_TESTS_REQUIRED` | No | Accepted values: `true`, `false`, `1`, `0`, `yes`, `no` (default: `false`) |

`CI_INTEGRATION_TESTS_REQUIRED` is parsed case-insensitively. Any other non-empty value is
rejected with a clear configuration error.

### Guard behaviour

| `REACT_APP_BACKEND_URL` | `CI_INTEGRATION_TESTS_REQUIRED` | Result |
|---|---|---|
| Set | any | Integration tests run; backend is not contacted during collection |
| Unset | `false` or unset | Integration tests **skipped**; unit tests run normally |
| Unset | `true` | One clear `UsageError` aborts pytest; no collection errors |

**Skipped tests are not passing tests.** A skip is not success.

The backend URL is used only when integration test bodies execute — never at import or
collection time. No network request is made during `--collect-only`.

### Running tests

```bash
# All tests (unit + integration, with a live backend)
export REACT_APP_BACKEND_URL=http://localhost:8000
python3 -m pytest backend/tests/

# Unit tests only (no backend needed)
python3 -m pytest backend/tests/ -m "not integration"

# Integration tests only (live backend required)
export REACT_APP_BACKEND_URL=http://localhost:8000
python3 -m pytest backend/tests/ -m integration

# Collection-only validation (no tests executed, no network)
REACT_APP_BACKEND_URL=http://localhost:8000 \
  python3 -m pytest backend/tests/ --collect-only -q
```

### CI configuration

```bash
export REACT_APP_BACKEND_URL=https://staging.example.com
export CI_INTEGRATION_TESTS_REQUIRED=true
python3 -m pytest backend/tests/
```

When `CI_INTEGRATION_TESTS_REQUIRED=true` and `REACT_APP_BACKEND_URL` is unset, pytest aborts
immediately with one error message rather than four separate module-level collection failures.

## Startup configuration validation

Before opening the MongoDB connection the backend calls `load_runtime_config()` from
`backend/runtime_config.py`. This validates every required environment variable and
enforces production safety rules. If validation fails the process exits immediately
with a descriptive error listing every problem found.

The module has no side effects on import — it can be imported in unit tests without
triggering any network calls, database connections, file writes, or secret logging.

All errors are collected and reported together in a single `ValueError`. Secret values
(`JWT_SECRET`, `ADMIN_PASSWORD`, `MONGO_URL` connection strings) never appear in error
messages or the startup log. `DB_NAME` is also excluded from the startup log summary.

### What is validated at startup

| Variable | Rules enforced |
|---|---|
| `APP_ENV` | Must be one of: `development`, `test`, `staging`, `production` |
| `MONGO_URL` | Required; must begin with `mongodb://` or `mongodb+srv://`; value never exposed in errors |
| `DB_NAME` | Required; must not contain `/`, `\`, or null characters |
| `JWT_SECRET` | Required; minimum 32 characters |
| `COOKIE_SECURE` | Must be a recognised boolean: `true`, `false`, `1`, `0`, `yes`, `no` (default: `true`) |
| `COOKIE_SAMESITE` | Must be `lax`, `strict`, or `none` (default: `lax`) |
| `COOKIE_SAMESITE=none` | Requires `COOKIE_SECURE=true` |
| `SEED_DATA_ENABLED=true` | Requires `ADMIN_EMAIL` and `ADMIN_PASSWORD` |
| `ADMIN_PASSWORD` | Minimum 12 characters; must not equal the `.env.example` placeholder |
| Production: `SEED_DATA_ENABLED` | Must not be `true` |
| Production: `COOKIE_SECURE` | Must be `true` |
| Production: CORS origins | All origins must use HTTPS; localhost, `127.x.x.x`, and `[::1]` are rejected |

### CORS origin validation

Each origin in `CORS_ALLOWED_ORIGINS` is parsed with `urllib.parse.urlsplit` and must satisfy:

- Scheme is `http` or `https` (no ftp, ws, etc.)
- Hostname is present and non-empty
- No embedded username or password
- No path component (including bare `/`)
- No query string
- No fragment
- Port, if present, must be a valid integer

Exact duplicate origins are removed, preserving the first occurrence and original order.

In production, additionally:

- Every origin must use HTTPS
- `localhost`, any `127.x.x.x` address, and `[::1]` are rejected

### Cookie validation

`COOKIE_SECURE` and `COOKIE_SAMESITE` are validated once in `runtime_config.py` via
`load_cookie_config()`. This shared helper is used by both startup validation and by
`auth.py`'s `set_auth_cookies()` — there is no duplicate implementation.

### Seed password requirements

When `SEED_DATA_ENABLED=true`:

- `ADMIN_EMAIL` must be non-empty
- `ADMIN_PASSWORD` must be at least 12 characters
- `ADMIN_PASSWORD` must not equal the `.env.example` placeholder `change-me-strong-password`
- `ADMIN_PASSWORD` never appears in error messages or logs

### MongoDB startup and shutdown lifecycle

1. `load_runtime_config()` runs first. Any error aborts startup before any connection is made.
2. `AsyncIOMotorClient` is created using the validated `MONGO_URL`.
3. All subsequent startup steps (database selection, index creation, seeding, migration,
   scheduler launch) run inside a `try/except BaseException` block.
4. If any step raises, the newly created MongoDB client is closed immediately, `server.client`,
   `server.db`, and `app.state.db` are all set to `None`, and the exception is re-raised.
   This prevents connection leaks on partial startup failure.
5. On normal shutdown, the client is closed exactly once, and `server.client`, `server.db`,
   and `app.state.db` are set to `None`. Calling shutdown when no client exists is safe.

### Startup log summary

The startup log includes only: `APP_ENV`, seed enabled status, `COOKIE_SECURE`, `COOKIE_SAMESITE`,
and CORS origin count. It never logs `DB_NAME`, `MONGO_URL`, `JWT_SECRET`, `ADMIN_PASSWORD`,
API keys, or individual CORS origin values.

## Verification levels

| Level | What it checks | Command |
|---|---|---|
| Static verification | Python syntax and imports compile | `python -m compileall backend` |
| Test collection verification | pytest can discover tests without errors | `pytest --collect-only backend/tests/` |
| Runtime integration verification | Tests execute against a live backend | `pytest backend/tests/` with `REACT_APP_BACKEND_URL` set |
| Passed tests | All collected tests return green | Reported by pytest exit code 0 |

Static verification passing does **not** imply tests will pass. Test collection not erroring does **not** imply tests will pass. Only a green pytest run against a configured backend constitutes passed integration tests.

## Warning

Never point `REACT_APP_BACKEND_URL` or `MONGO_URL` at a production database during testing. Integration tests create, modify, and delete data.
