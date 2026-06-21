"""Unit tests for backend/tests/conftest.py infrastructure helpers.

No live backend, no MongoDB, no network, no subprocess.
All helpers accept an explicit env mapping so os.environ is never touched.
"""
from __future__ import annotations

import dataclasses
import pytest

from conftest import (
    IntegrationConfig,
    load_integration_config,
    normalize_backend_url,
    parse_ci_required,
)


# ---------------------------------------------------------------------------
# normalize_backend_url
# ---------------------------------------------------------------------------
class TestNormalizeBackendUrl:
    def test_missing_key_returns_empty(self):
        assert normalize_backend_url({}) == ""

    def test_empty_value_returns_empty(self):
        assert normalize_backend_url({"REACT_APP_BACKEND_URL": ""}) == ""

    def test_whitespace_stripped(self):
        assert normalize_backend_url({"REACT_APP_BACKEND_URL": "  http://localhost:8000  "}) == "http://localhost:8000"

    def test_one_trailing_slash_removed(self):
        assert normalize_backend_url({"REACT_APP_BACKEND_URL": "http://localhost:8000/"}) == "http://localhost:8000"

    def test_multiple_trailing_slashes_removed(self):
        assert normalize_backend_url({"REACT_APP_BACKEND_URL": "http://localhost:8000///"}) == "http://localhost:8000"

    def test_valid_url_otherwise_unchanged(self):
        url = "http://localhost:8000"
        assert normalize_backend_url({"REACT_APP_BACKEND_URL": url}) == url


# ---------------------------------------------------------------------------
# parse_ci_required
# ---------------------------------------------------------------------------
class TestParseCiRequired:
    def test_default_is_false_when_missing(self):
        assert parse_ci_required({}) is False

    def test_default_is_false_when_empty(self):
        assert parse_ci_required({"CI_INTEGRATION_TESTS_REQUIRED": ""}) is False

    @pytest.mark.parametrize("val", ["true", "1", "yes"])
    def test_accepted_true_values(self, val):
        assert parse_ci_required({"CI_INTEGRATION_TESTS_REQUIRED": val}) is True

    @pytest.mark.parametrize("val", ["false", "0", "no"])
    def test_accepted_false_values(self, val):
        assert parse_ci_required({"CI_INTEGRATION_TESTS_REQUIRED": val}) is False

    @pytest.mark.parametrize("val", ["TRUE", "YES", "True", "False", "NO"])
    def test_parsing_is_case_insensitive(self, val):
        result = parse_ci_required({"CI_INTEGRATION_TESTS_REQUIRED": val})
        assert isinstance(result, bool)

    def test_invalid_value_raises_usage_error(self):
        with pytest.raises(pytest.UsageError) as exc_info:
            parse_ci_required({"CI_INTEGRATION_TESTS_REQUIRED": "maybe"})
        msg = str(exc_info.value)
        assert "CI_INTEGRATION_TESTS_REQUIRED" in msg
        assert "maybe" in msg

    def test_error_message_does_not_expose_other_env_values(self):
        env = {
            "CI_INTEGRATION_TESTS_REQUIRED": "oops",
            "JWT_SECRET": "supersecret",
            "MONGO_URL": "mongodb://user:pass@host/db",
        }
        with pytest.raises(pytest.UsageError) as exc_info:
            parse_ci_required(env)
        msg = str(exc_info.value)
        assert "supersecret" not in msg
        assert "mongodb" not in msg


# ---------------------------------------------------------------------------
# load_integration_config
# ---------------------------------------------------------------------------
class TestLoadIntegrationConfig:
    def test_missing_url_is_unconfigured(self):
        cfg = load_integration_config({})
        assert cfg.configured is False

    def test_missing_url_is_not_ci_required_by_default(self):
        cfg = load_integration_config({})
        assert cfg.ci_required is False

    def test_missing_url_provides_skip_reason(self):
        cfg = load_integration_config({})
        assert cfg.skip_reason != ""
        assert "REACT_APP_BACKEND_URL" in cfg.skip_reason

    def test_configured_url_is_marked_configured(self):
        cfg = load_integration_config({"REACT_APP_BACKEND_URL": "http://localhost:8000"})
        assert cfg.configured is True

    def test_configured_url_stored_normalized(self):
        cfg = load_integration_config({"REACT_APP_BACKEND_URL": "http://localhost:8000/"})
        assert cfg.backend_url == "http://localhost:8000"

    def test_config_is_immutable(self):
        cfg = load_integration_config({})
        assert dataclasses.is_dataclass(cfg)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            cfg.configured = True  # type: ignore[misc]
