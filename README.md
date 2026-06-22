# Medical Stock Monitoring System

A FastAPI + MongoDB backend with a React frontend for tracking medical stock, alerts, and escalations.

## Quick start

### Prerequisites

- Tested with Python 3.11.15. Use Python 3.11.x for the verified local setup. Other Python versions have not been verified.
- Node.js and Yarn are required for frontend development. Frontend runtime-version validation is outside the scope of Package 0C1.
- MongoDB (local or Atlas)

### Backend

#### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r backend/requirements-dev.txt
cp .env.example backend/.env   # fill in MONGO_URL, DB_NAME, JWT_SECRET, etc.
cd backend
python3 -m uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

**Note:** The backend reads `backend/.env`. A root-level `.env` is not automatically loaded by the backend.

#### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.txt
Copy-Item .env.example backend\.env   # fill in MONGO_URL, DB_NAME, JWT_SECRET, etc.
cd backend
python -m uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

**Note:** The backend reads `backend\.env`. A root-level `.env` is not automatically loaded by the backend.

### Frontend

```bash
cd frontend
yarn install
yarn start
```

The React frontend reads `REACT_APP_BACKEND_URL` from `frontend/.env`.

#### Linux / macOS

```bash
printf 'REACT_APP_BACKEND_URL=http://localhost:8000\n' > frontend/.env
```

#### Windows (PowerShell)

```powershell
"REACT_APP_BACKEND_URL=http://localhost:8000" | Set-Content frontend\.env
```

## Dependency files

| File | Purpose |
|---|---|
| `backend/requirements.txt` | Emergent runtime image manifest. May contain private packages (`litellm`, `emergentintegrations`) not available on PyPI. **Not for local development.** |
| `backend/requirements.app.txt` | Direct runtime dependency manifest. Lists only packages directly imported by backend production source. Transitive dependencies are resolved by pip at install time. Use for local development. |
| `backend/requirements-dev.txt` | Extends `requirements.app.txt` with `pytest` and `requests` (used by integration tests). Use for local testing. |

Neither `requirements.app.txt` nor `requirements-dev.txt` is a lock file — pip resolves transitive dependencies at install time. A pinned lock file (`requirements.lock.txt`) will be added in a future package.

## Running tests

### Unit tests (no backend required)

```bash
python3 -m pytest backend/tests/ -m "not integration" -q
```

### Integration tests — Docker (recommended)

The integration-test environment uses Docker Compose with Python 3.11 and MongoDB 6
configured as a single-node replica set (`rs0`). MongoDB is run as a replica set to
support the transaction implementation introduced in Package 1. The test database is
disposable — tests mutate records. Always run `down -v` between clean full-suite runs.
Never run these tests against staging or production.

A green result requires all integration tests to execute. Skipped integration tests
are not considered success.

#### Linux / macOS

```bash
cp .env.test.example .env.test

# Validate the composed configuration
docker compose --env-file .env.test -f docker-compose.test.yml config

# Run the full stack (exits when the tests service exits)
docker compose --env-file .env.test -f docker-compose.test.yml \
  up --abort-on-container-exit --exit-code-from tests

# Tear down and remove volumes between runs
docker compose --env-file .env.test -f docker-compose.test.yml \
  down -v --remove-orphans
```

#### Windows (PowerShell)

```powershell
Copy-Item .env.test.example .env.test

# Validate the composed configuration
docker compose --env-file .env.test -f docker-compose.test.yml config

# Run the full stack
docker compose --env-file .env.test -f docker-compose.test.yml `
  up --abort-on-container-exit --exit-code-from tests

# Tear down and remove volumes between runs
docker compose --env-file .env.test -f docker-compose.test.yml `
  down -v --remove-orphans
```

Integration tests are marked `pytest.mark.integration` and are skipped automatically when
`REACT_APP_BACKEND_URL` is not set. See [DEVELOPMENT.md](DEVELOPMENT.md) for full details.

## Environment variables

Copy `.env.example` to `backend/.env` and fill in values. Key variables:

| Variable | Required | Description |
|---|---|---|
| `MONGO_URL` | Yes | MongoDB connection string |
| `DB_NAME` | Yes | Database name |
| `JWT_SECRET` | Yes | Minimum 32 characters |
| `REACT_APP_BACKEND_URL` | Yes (integration tests) | URL of the running backend |

See [DEVELOPMENT.md](DEVELOPMENT.md) for the complete variable reference.
