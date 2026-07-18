#
# Production image for the FastAPI backend.
#
# Build context: backend/
#   docker build --tag app2-backend:<tag> backend
#
# Exactly one Uvicorn worker is used deliberately: server.py's startup
# lifecycle launches in-process scheduler and reconciliation background
# tasks (asyncio.create_task in the "startup" event). Running more than one
# worker process would start those loops multiple times and duplicate SLA
# checks, alerts, and reconciliation runs. Horizontal scaling of this image
# is out of scope for this package.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dedicated non-root account with a fixed numeric UID/GID, suitable for
# deployment on hosts that map container users to a known host identity.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser

# Dependency layer first, for build caching. Installed exclusively from the
# hash-locked manifest — never requirements.txt (Emergent runtime manifest)
# or requirements-dev.txt / requirements.app.txt (development manifests).
COPY requirements.lock.txt ./
RUN python -m pip install --require-hashes -r requirements.lock.txt

# Application source: only the backend's own top-level runtime modules.
# This glob does not match the tests/ directory, requirements*.txt, .env
# files, or any Git metadata, so no .dockerignore exclusion is needed to
# keep them out of the image — they are simply never copied in.
COPY --chown=appuser:appuser *.py ./

USER appuser

EXPOSE 8000

# Uvicorn runs as PID 1 (exec-form CMD, no shell, no wrapper script), so it
# receives Docker's SIGTERM directly and performs its own graceful shutdown
# sequence, which invokes the FastAPI "shutdown" event handler — cancelling
# and awaiting the scheduler/reconciliation tasks and closing the MongoDB
# client before the process exits.
STOPSIGNAL SIGTERM

# Python standard library only — no curl/wget installed solely for this.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request as u; r=u.urlopen('http://127.0.0.1:8000/api/', timeout=2); sys.exit(0 if r.status==200 else 1)"]

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
