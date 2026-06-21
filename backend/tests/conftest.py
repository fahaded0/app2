"""Centralized pytest integration-test infrastructure.

Single enforcement point for integration-test availability.
No network calls, no database calls, no filesystem writes, no secret logging.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

# ---------------------------------------------------------------------------
# Accepted boolean strings (case-insensitive)
# ---------------------------------------------------------------------------
_BOOL_TRUE = {"true", "1", "yes"}
_BOOL_FALSE = {"false", "0", "no"}

_CI_VAR = "CI_INTEGRATION_TESTS_REQUIRED"
_URL_VAR = "REACT_APP_BACKEND_URL"

_SKIP_REASON = (
    "REACT_APP_BACKEND_URL is not set — "
    "set it to run integration tests against a live backend"
)

_CI_MISSING_URL_MSG = (
    "CI_INTEGRATION_TESTS_REQUIRED=true but REACT_APP_BACKEND_URL is not set. "
    "Configure REACT_APP_BACKEND_URL before running integration tests in CI."
)


# ---------------------------------------------------------------------------
# Pure helpers (accept explicit env mapping for unit testing)
# ---------------------------------------------------------------------------

def normalize_backend_url(env: dict[str, str] | None = None) -> str:
    """Return REACT_APP_BACKEND_URL stripped of whitespace and trailing slashes."""
    if env is None:
        env = os.environ  # type: ignore[assignment]
    return env.get(_URL_VAR, "").strip().rstrip("/")


def parse_ci_required(env: dict[str, str] | None = None) -> bool:
    """Parse CI_INTEGRATION_TESTS_REQUIRED. Raises pytest.UsageError for invalid values."""
    if env is None:
        env = os.environ  # type: ignore[assignment]
    raw = env.get(_CI_VAR, "").strip().lower()
    if not raw or raw in _BOOL_FALSE:
        return False
    if raw in _BOOL_TRUE:
        return True
    raise pytest.UsageError(
        f"{_CI_VAR}={env.get(_CI_VAR)!r} is not valid. "
        f"Accepted values: true, false, 1, 0, yes, no."
    )


@dataclass(frozen=True)
class IntegrationConfig:
    backend_url: str
    ci_required: bool
    configured: bool
    skip_reason: str


def load_integration_config(env: dict[str, str] | None = None) -> IntegrationConfig:
    """Load and validate integration-test environment configuration."""
    url = normalize_backend_url(env)
    ci = parse_ci_required(env)
    configured = bool(url)
    return IntegrationConfig(
        backend_url=url,
        ci_required=ci,
        configured=configured,
        skip_reason=_SKIP_REASON if not configured else "",
    )


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    cfg = load_integration_config()
    config._integration_cfg = cfg  # type: ignore[attr-defined]

    if not cfg.configured and cfg.ci_required:
        raise pytest.UsageError(_CI_MISSING_URL_MSG)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    cfg: IntegrationConfig = config._integration_cfg  # type: ignore[attr-defined]
    if cfg.configured:
        return

    skip = pytest.mark.skip(reason=cfg.skip_reason)
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)
