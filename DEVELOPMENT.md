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
| `CI_INTEGRATION_TESTS_REQUIRED` | No | `true` to fail test collection when backend URL is missing |

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

Tests in `backend/tests/` require a running backend. They are controlled by two environment variables:

### `REACT_APP_BACKEND_URL`

URL of the backend the tests will hit, e.g. `http://localhost:8000`.

### `CI_INTEGRATION_TESTS_REQUIRED`

Controls what happens when `REACT_APP_BACKEND_URL` is absent:

| `REACT_APP_BACKEND_URL` | `CI_INTEGRATION_TESTS_REQUIRED` | Result |
|---|---|---|
| Set | any | Tests run normally |
| Unset | `false` or unset | Module is **skipped** with an informational message — no tests reported as passed |
| Unset | `true` | Collection **fails** with a configuration error — CI pipeline is blocked |

**Skipped tests are not passing tests.** A skip suppresses the module; it does not count as success.

### Running tests locally

```bash
export REACT_APP_BACKEND_URL=http://localhost:8000
cd backend
pytest tests/
```

### Running tests in CI

Set both variables before running pytest:

```bash
export REACT_APP_BACKEND_URL=https://staging.example.com
export CI_INTEGRATION_TESTS_REQUIRED=true
pytest backend/tests/
```

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
