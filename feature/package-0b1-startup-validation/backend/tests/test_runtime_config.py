"""Unit tests for backend/runtime_config.py.

No network, database, or filesystem access. Does not require REACT_APP_BACKEND_URL.
"""
import sys
import os

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest
from runtime_config import (
    parse_bool, parse_cors_origins, load_cookie_config, load_runtime_config,
    CookieConfig, RuntimeConfig,
)

# ---------------------------------------------------------------------------
# Minimal valid environments
# ---------------------------------------------------------------------------
_VALID_DEV = {
    "APP_ENV": "development",
    "MONGO_URL": "mongodb://localhost:27017",
    "DB_NAME": "medstock",
    "JWT_SECRET": "a" * 32,
    "COOKIE_SECURE": "false",
    "COOKIE_SAMESITE": "lax",
    "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
    "SEED_DATA_ENABLED": "false",
    "ADMIN_EMAIL": "",
    "ADMIN_PASSWORD": "",
}

_VALID_PROD = {
    "APP_ENV": "production",
    "MONGO_URL": "mongodb+srv://user:pass@cluster.example.net/db",
    "DB_NAME": "medstock",
    "JWT_SECRET": "b" * 64,
    "COOKIE_SECURE": "true",
    "COOKIE_SAMESITE": "lax",
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
    "SEED_DATA_ENABLED": "false",
    "ADMIN_EMAIL": "",
    "ADMIN_PASSWORD": "",
}


def _env(**overrides):
    base = dict(_VALID_DEV)
    base.update(overrides)
    return base


def _env_prod(**overrides):
    base = dict(_VALID_PROD)
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# parse_bool
# ---------------------------------------------------------------------------
class TestParseBool:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES"])
    def test_truthy_values(self, value):
        assert parse_bool(value, "X") is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "NO"])
    def test_falsy_values(self, value):
        assert parse_bool(value, "X") is False

    def test_invalid_raises_with_var_name(self):
        with pytest.raises(ValueError, match="MY_VAR"):
            parse_bool("maybe", "MY_VAR")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_bool("", "X")


# ---------------------------------------------------------------------------
# parse_cors_origins
# ---------------------------------------------------------------------------
class TestParseCorsOrigins:
    def test_empty_string_returns_empty_list(self):
        assert parse_cors_origins("") == []

    def test_single_origin(self):
        assert parse_cors_origins("https://app.example.com") == ["https://app.example.com"]

    def test_multiple_origins(self):
        result = parse_cors_origins("https://a.example.com,https://b.example.com")
        assert result == ["https://a.example.com", "https://b.example.com"]

    def test_whitespace_stripped(self):
        result = parse_cors_origins("  https://a.example.com  ,  https://b.example.com  ")
        assert result == ["https://a.example.com", "https://b.example.com"]

    def test_empty_segments_dropped(self):
        result = parse_cors_origins(",https://a.example.com,,")
        assert result == ["https://a.example.com"]

    def test_duplicate_removed_first_occurrence_kept(self):
        result = parse_cors_origins("https://a.com,https://b.com,https://a.com")
        assert result == ["https://a.com", "https://b.com"]

    def test_wildcard_rejected(self):
        with pytest.raises(ValueError, match=r"\*"):
            parse_cors_origins("*")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("ftp://example.com")

    def test_ws_scheme_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("ws://example.com")

    def test_missing_hostname_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://")

    def test_path_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://example.com/path")

    def test_bare_slash_path_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://example.com/")

    def test_query_string_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://example.com?q=1")

    def test_fragment_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://example.com#frag")

    def test_embedded_credentials_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://user:password@example.com")

    def test_malformed_port_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://example.com:notaport")

    def test_http_allowed_in_development(self):
        result = parse_cors_origins("http://app.example.com", production=False)
        assert result == ["http://app.example.com"]

    def test_production_http_origin_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("http://app.example.com", production=True)

    def test_production_localhost_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://localhost:3000", production=True)

    def test_production_ipv4_loopback_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://127.0.0.1:3000", production=True)

    def test_production_ipv6_loopback_rejected(self):
        with pytest.raises(ValueError):
            parse_cors_origins("https://[::1]:3000", production=True)

    def test_valid_production_https_accepted(self):
        result = parse_cors_origins("https://app.example.com", production=True)
        assert result == ["https://app.example.com"]


# ---------------------------------------------------------------------------
# load_cookie_config
# ---------------------------------------------------------------------------
class TestLoadCookieConfig:
    def test_defaults(self):
        cfg = load_cookie_config({})
        assert cfg.secure is True
        assert cfg.samesite == "lax"

    def test_cookie_config_is_frozen(self):
        cfg = load_cookie_config({})
        with pytest.raises((AttributeError, TypeError)):
            cfg.secure = False  # type: ignore[misc]

    def test_secure_false_accepted(self):
        cfg = load_cookie_config({"COOKIE_SECURE": "false", "COOKIE_SAMESITE": "lax"})
        assert cfg.secure is False

    def test_samesite_strict_accepted(self):
        cfg = load_cookie_config({"COOKIE_SECURE": "true", "COOKIE_SAMESITE": "strict"})
        assert cfg.samesite == "strict"

    def test_samesite_none_with_secure_accepted(self):
        cfg = load_cookie_config({"COOKIE_SECURE": "true", "COOKIE_SAMESITE": "none"})
        assert cfg.samesite == "none"

    def test_invalid_samesite_raises(self):
        with pytest.raises(ValueError, match="COOKIE_SAMESITE"):
            load_cookie_config({"COOKIE_SAMESITE": "invalid"})

    def test_samesite_none_without_secure_raises(self):
        with pytest.raises(ValueError, match="SameSite=None"):
            load_cookie_config({"COOKIE_SECURE": "false", "COOKIE_SAMESITE": "none"})


# ---------------------------------------------------------------------------
# load_runtime_config — APP_ENV
# ---------------------------------------------------------------------------
class TestAppEnv:
    def test_development_accepted(self):
        cfg = load_runtime_config(_env(APP_ENV="development"))
        assert cfg.app_env == "development"

    def test_test_accepted(self):
        cfg = load_runtime_config(_env(APP_ENV="test"))
        assert cfg.app_env == "test"

    def test_staging_accepted(self):
        cfg = load_runtime_config(_env(APP_ENV="staging"))
        assert cfg.app_env == "staging"

    def test_production_accepted(self):
        cfg = load_runtime_config(_VALID_PROD)
        assert cfg.app_env == "production"

    def test_unknown_value_rejected(self):
        with pytest.raises(ValueError, match="APP_ENV"):
            load_runtime_config(_env(APP_ENV="qa"))

    def test_invalid_value_rejected(self):
        with pytest.raises(ValueError, match="APP_ENV"):
            load_runtime_config(_env(APP_ENV="live"))

    def test_random_invalid_rejected(self):
        with pytest.raises(ValueError, match="APP_ENV"):
            load_runtime_config(_env(APP_ENV="qa"))


# ---------------------------------------------------------------------------
# load_runtime_config — DB_NAME
# ---------------------------------------------------------------------------
class TestDbName:
    def test_valid_db_name_accepted(self):
        cfg = load_runtime_config(_env(DB_NAME="medstock"))
        assert cfg.db_name == "medstock"

    def test_missing_db_name_rejected(self):
        with pytest.raises(ValueError, match="DB_NAME"):
            load_runtime_config(_env(DB_NAME=""))

    def test_slash_rejected(self):
        with pytest.raises(ValueError, match="DB_NAME"):
            load_runtime_config(_env(DB_NAME="db/name"))

    def test_backslash_rejected(self):
        with pytest.raises(ValueError, match="DB_NAME"):
            load_runtime_config(_env(DB_NAME="db\\name"))

    def test_null_character_rejected(self):
        with pytest.raises(ValueError, match="DB_NAME"):
            load_runtime_config(_env(DB_NAME="db\x00name"))

    def test_slash_error_does_not_print_db_value(self):
        with pytest.raises(ValueError) as exc_info:
            load_runtime_config(_env(DB_NAME="secret/dbname"))
        assert "secret/dbname" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# load_runtime_config — MONGO_URL secret redaction
# ---------------------------------------------------------------------------
class TestMongoUrlRedaction:
    def test_invalid_scheme_rejected(self):
        with pytest.raises(ValueError, match="MONGO_URL"):
            load_runtime_config(_env(MONGO_URL="http://localhost:27017"))

    def test_missing_mongo_url_rejected(self):
        with pytest.raises(ValueError, match="MONGO_URL"):
            load_runtime_config(_env(MONGO_URL=""))

    def test_credentials_absent_from_error(self):
        fake_user = "myuser"
        fake_pass = "mysupersecretpass"
        with pytest.raises(ValueError) as exc_info:
            load_runtime_config(_env(
                MONGO_URL=f"http://{fake_user}:{fake_pass}@host:27017/db"
            ))
        msg = str(exc_info.value)
        assert fake_user not in msg, "username appeared in error message"
        assert fake_pass not in msg, "password appeared in error message"

    def test_mongodb_scheme_accepted(self):
        cfg = load_runtime_config(_env(MONGO_URL="mongodb://localhost:27017"))
        assert cfg.mongo_url == "mongodb://localhost:27017"

    def test_mongodb_srv_scheme_accepted(self):
        cfg = load_runtime_config(_env(MONGO_URL="mongodb+srv://u:p@cluster.example.net"))
        assert cfg.mongo_url.startswith("mongodb+srv://")


# ---------------------------------------------------------------------------
# load_runtime_config — JWT_SECRET
# ---------------------------------------------------------------------------
class TestJwtSecret:
    def test_missing_rejected(self):
        with pytest.raises(ValueError, match="JWT_SECRET"):
            load_runtime_config(_env(JWT_SECRET=""))

    def test_short_rejected(self):
        with pytest.raises(ValueError, match="JWT_SECRET"):
            load_runtime_config(_env(JWT_SECRET="tooshort"))

    def test_exactly_32_chars_accepted(self):
        cfg = load_runtime_config(_env(JWT_SECRET="x" * 32))
        assert len(cfg.jwt_secret) == 32

    def test_value_not_in_error(self):
        secret = "s3cr3t_but_short"
        with pytest.raises(ValueError) as exc_info:
            load_runtime_config(_env(JWT_SECRET=secret))
        # Only length should be in the message, not the value itself
        assert secret not in str(exc_info.value)


# ---------------------------------------------------------------------------
# load_runtime_config — seed validation
# ---------------------------------------------------------------------------
class TestSeedValidation:
    def test_seed_disabled_no_credentials_ok(self):
        cfg = load_runtime_config(_env(SEED_DATA_ENABLED="false", ADMIN_EMAIL="", ADMIN_PASSWORD=""))
        assert cfg.seed_enabled is False

    def test_seed_enabled_with_valid_credentials_ok(self):
        cfg = load_runtime_config(_env(
            SEED_DATA_ENABLED="true",
            ADMIN_EMAIL="admin@example.com",
            ADMIN_PASSWORD="StrongPassword1!",
        ))
        assert cfg.seed_enabled is True

    def test_seed_missing_email_rejected(self):
        with pytest.raises(ValueError, match="ADMIN_EMAIL"):
            load_runtime_config(_env(
                SEED_DATA_ENABLED="true", ADMIN_EMAIL="", ADMIN_PASSWORD="StrongPassword1!",
            ))

    def test_seed_missing_password_rejected(self):
        with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
            load_runtime_config(_env(
                SEED_DATA_ENABLED="true", ADMIN_EMAIL="admin@ex.com", ADMIN_PASSWORD="",
            ))

    def test_seed_short_password_rejected(self):
        with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
            load_runtime_config(_env(
                SEED_DATA_ENABLED="true", ADMIN_EMAIL="admin@ex.com", ADMIN_PASSWORD="short",
            ))

    def test_seed_placeholder_password_rejected(self):
        with pytest.raises(ValueError, match="placeholder"):
            load_runtime_config(_env(
                SEED_DATA_ENABLED="true",
                ADMIN_EMAIL="admin@ex.com",
                ADMIN_PASSWORD="change-me-strong-password",
            ))

    def test_password_absent_from_error_text(self):
        secret_pwd = "MySecretPass!"
        with pytest.raises(ValueError) as exc_info:
            load_runtime_config(_env(
                SEED_DATA_ENABLED="true", ADMIN_EMAIL="", ADMIN_PASSWORD=secret_pwd,
            ))
        assert secret_pwd not in str(exc_info.value)

    def test_production_seed_rejected(self):
        with pytest.raises(ValueError, match="SEED_DATA_ENABLED"):
            load_runtime_config(_env_prod(
                SEED_DATA_ENABLED="true",
                ADMIN_EMAIL="admin@ex.com",
                ADMIN_PASSWORD="StrongPassword1!",
            ))


# ---------------------------------------------------------------------------
# load_runtime_config — production safety
# ---------------------------------------------------------------------------
class TestProductionSafety:
    def test_production_insecure_cookie_rejected(self):
        with pytest.raises(ValueError, match="COOKIE_SECURE"):
            load_runtime_config(_env_prod(COOKIE_SECURE="false"))

    def test_production_localhost_cors_rejected(self):
        with pytest.raises(ValueError):
            load_runtime_config(_env_prod(CORS_ALLOWED_ORIGINS="https://localhost:3000"))

    def test_production_ipv4_loopback_cors_rejected(self):
        with pytest.raises(ValueError):
            load_runtime_config(_env_prod(CORS_ALLOWED_ORIGINS="https://127.0.0.1:3000"))

    def test_production_ipv6_loopback_cors_rejected(self):
        with pytest.raises(ValueError):
            load_runtime_config(_env_prod(CORS_ALLOWED_ORIGINS="http://[::1]:3000"))

    def test_production_http_cors_rejected(self):
        with pytest.raises(ValueError):
            load_runtime_config(_env_prod(CORS_ALLOWED_ORIGINS="http://app.example.com"))

    def test_production_wildcard_cors_rejected(self):
        with pytest.raises(ValueError):
            load_runtime_config(_env_prod(CORS_ALLOWED_ORIGINS="*"))

    def test_production_empty_cors_allowed(self):
        # Empty CORS in production is allowed (just means no cross-origin requests)
        cfg = load_runtime_config(_env_prod(CORS_ALLOWED_ORIGINS=""))
        assert cfg.cors_origins == []

    def test_production_seed_rejection_independent_of_credentials(self):
        with pytest.raises(ValueError, match="SEED_DATA_ENABLED"):
            load_runtime_config(_env_prod(
                SEED_DATA_ENABLED="true",
                ADMIN_EMAIL="admin@ex.com",
                ADMIN_PASSWORD="StrongPassword1!",
            ))


# ---------------------------------------------------------------------------
# load_runtime_config — happy paths and immutability
# ---------------------------------------------------------------------------
class TestHappyPaths:
    def test_valid_dev_returns_runtime_config(self):
        cfg = load_runtime_config(_VALID_DEV)
        assert isinstance(cfg, RuntimeConfig)

    def test_valid_prod_returns_runtime_config(self):
        cfg = load_runtime_config(_VALID_PROD)
        assert cfg.app_env == "production"

    def test_config_is_frozen(self):
        cfg = load_runtime_config(_VALID_DEV)
        with pytest.raises((AttributeError, TypeError)):
            cfg.app_env = "other"  # type: ignore[misc]

    def test_cookie_config_embedded(self):
        cfg = load_runtime_config(_env(COOKIE_SECURE="true", COOKIE_SAMESITE="strict"))
        assert isinstance(cfg.cookie, CookieConfig)
        assert cfg.cookie.secure is True
        assert cfg.cookie.samesite == "strict"

    def test_convenience_aliases(self):
        cfg = load_runtime_config(_env(COOKIE_SECURE="true", COOKIE_SAMESITE="lax"))
        assert cfg.cookie_secure is True
        assert cfg.cookie_samesite == "lax"

    def test_multiple_errors_aggregated(self):
        with pytest.raises(ValueError) as exc_info:
            load_runtime_config(_env(MONGO_URL="", DB_NAME="", JWT_SECRET=""))
        msg = str(exc_info.value)
        assert "MONGO_URL" in msg
        assert "DB_NAME" in msg
        assert "JWT_SECRET" in msg

    def test_cors_duplicate_removed(self):
        cfg = load_runtime_config(_env(
            CORS_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:3000"
        ))
        assert cfg.cors_origins == ["http://localhost:3000"]

    def test_cors_order_preserved(self):
        cfg = load_runtime_config(_env(
            CORS_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:4000"
        ))
        assert cfg.cors_origins == ["http://localhost:3000", "http://localhost:4000"]
