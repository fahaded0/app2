"""Runtime configuration loader — pure module, no side effects on import.

Call load_runtime_config() or load_cookie_config() explicitly. This module
never connects to a database, makes network calls, writes files, or logs
secret values.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# Minimum acceptable JWT secret length (characters)
_JWT_MIN_LEN = 32

# Minimum acceptable seed ADMIN_PASSWORD length
_SEED_PWD_MIN_LEN = 12

# Placeholder password from .env.example — must be replaced before use
_SEED_PWD_PLACEHOLDER = "change-me-strong-password"

_BOOL_TRUE = {"true", "1", "yes"}
_BOOL_FALSE = {"false", "0", "no"}

_VALID_APP_ENVS = {"development", "test", "staging", "production"}

# IPv4 loopback range 127.0.0.0/8 — any 127.x.x.x
_IPV4_LOOPBACK_RE = re.compile(r"^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def parse_bool(value: str, var_name: str) -> bool:
    """Parse a boolean env-var string. Raises ValueError for unrecognised values."""
    v = value.lower().strip()
    if v in _BOOL_TRUE:
        return True
    if v in _BOOL_FALSE:
        return False
    raise ValueError(
        f"Invalid {var_name}={value!r}. Accepted values: true, false, 1, 0, yes, no."
    )


def _validate_cors_origin(origin: str) -> str:
    """Validate a single CORS origin string. Returns the origin unchanged if valid.

    Raises ValueError describing the violation without echoing secret values.
    Accepts only http or https, requires a hostname, rejects credentials, paths,
    query strings, fragments, and malformed ports.
    """
    if origin == "*":
        raise ValueError("Wildcard '*' is not an acceptable CORS origin.")

    try:
        parsed = urlsplit(origin)
    except Exception:
        raise ValueError(f"CORS origin is not a valid URL: rejected.")

    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"CORS origin scheme must be 'http' or 'https' (got {parsed.scheme!r})."
        )

    # Require a non-empty hostname
    hostname = parsed.hostname  # urlsplit strips brackets from IPv6, e.g. [::1] → ::1
    if not hostname:
        raise ValueError("CORS origin must include a hostname.")

    # Reject embedded credentials
    if parsed.username or parsed.password:
        raise ValueError("CORS origin must not include username or password.")

    # Reject any path component including bare /
    if parsed.path not in ("",):
        raise ValueError("CORS origin must not include a path.")

    # Reject query strings
    if parsed.query:
        raise ValueError("CORS origin must not include a query string.")

    # Reject fragments
    if parsed.fragment:
        raise ValueError("CORS origin must not include a fragment.")

    # Validate port is an integer when present
    try:
        parsed.port  # raises ValueError if port is non-numeric
    except ValueError:
        raise ValueError("CORS origin contains an invalid port number.")

    return origin


def _is_loopback_hostname(hostname: str) -> bool:
    """Return True if hostname is a loopback address."""
    if hostname.lower() == "localhost":
        return True
    if _IPV4_LOOPBACK_RE.match(hostname):
        return True
    # urlsplit strips brackets: [::1] → ::1
    if hostname == "::1":
        return True
    return False


def parse_cors_origins(raw: str, production: bool = False) -> list[str]:
    """Parse, validate, and deduplicate a comma-separated CORS origin string.

    Strips whitespace, drops empty segments, rejects structurally invalid
    origins, and removes exact duplicates (first occurrence kept).

    When production=True, also requires HTTPS and rejects loopback addresses.
    Raises ValueError listing all violations found.
    """
    candidates = [o.strip() for o in raw.split(",") if o.strip()]

    errors: list[str] = []
    valid: list[str] = []
    seen: set[str] = set()

    for origin in candidates:
        try:
            _validate_cors_origin(origin)
        except ValueError as exc:
            errors.append(f"  - {origin!r}: {exc}")
            continue

        parsed = urlsplit(origin)
        hostname = parsed.hostname or ""

        if production:
            if parsed.scheme != "https":
                errors.append(
                    f"  - {origin!r}: production origins must use HTTPS."
                )
                continue
            if _is_loopback_hostname(hostname):
                errors.append(
                    f"  - {origin!r}: loopback addresses are not allowed in production."
                )
                continue

        if origin not in seen:
            seen.add(origin)
            valid.append(origin)

    if errors:
        raise ValueError("Invalid CORS origins:\n" + "\n".join(errors))

    return valid


@dataclass(frozen=True)
class CookieConfig:
    secure: bool
    samesite: str


def load_cookie_config(env: dict[str, str] | None = None) -> CookieConfig:
    """Parse and validate cookie-related env vars. Raises ValueError on error."""
    if env is None:
        env = os.environ  # type: ignore[assignment]

    errors: list[str] = []

    try:
        secure = parse_bool(env.get("COOKIE_SECURE", "true"), "COOKIE_SECURE")
    except ValueError as exc:
        secure = True
        errors.append(str(exc))

    samesite = env.get("COOKIE_SAMESITE", "lax").lower().strip()
    if samesite not in ("lax", "strict", "none"):
        errors.append(
            f"COOKIE_SAMESITE={samesite!r} is not valid. Must be one of: lax, strict, none."
        )
    elif samesite == "none" and not secure:
        errors.append(
            "COOKIE_SAMESITE=none requires COOKIE_SECURE=true. "
            "Browsers reject SameSite=None cookies without the Secure flag."
        )

    if errors:
        raise ValueError("\n".join(errors))

    return CookieConfig(secure=secure, samesite=samesite)


@dataclass(frozen=True)
class RuntimeConfig:
    app_env: str
    mongo_url: str
    db_name: str
    jwt_secret: str
    cookie: CookieConfig
    cors_origins: list[str]
    seed_enabled: bool
    admin_email: str
    admin_password: str

    # Convenience aliases kept for callers that used the flat fields
    @property
    def cookie_secure(self) -> bool:
        return self.cookie.secure

    @property
    def cookie_samesite(self) -> str:
        return self.cookie.samesite


def load_runtime_config(env: dict[str, str] | None = None) -> RuntimeConfig:
    """Validate environment variables and return an immutable RuntimeConfig.

    Raises ValueError with a descriptive message for any invalid configuration.
    Pass *env* in tests to avoid touching os.environ directly.
    """
    if env is None:
        env = os.environ  # type: ignore[assignment]

    errors: list[str] = []

    # APP_ENV
    app_env = env.get("APP_ENV", "development").lower().strip()
    if app_env not in _VALID_APP_ENVS:
        errors.append(
            f"APP_ENV={app_env!r} is not valid. "
            f"Must be one of: {', '.join(sorted(_VALID_APP_ENVS))}."
        )

    # MONGO_URL — never include URL value in error message
    mongo_url = env.get("MONGO_URL", "").strip()
    if not mongo_url:
        errors.append("MONGO_URL is required.")
    elif not (mongo_url.startswith("mongodb://") or mongo_url.startswith("mongodb+srv://")):
        errors.append(
            "MONGO_URL must begin with mongodb:// or mongodb+srv://."
        )

    # DB_NAME
    db_name = env.get("DB_NAME", "").strip()
    if not db_name:
        errors.append("DB_NAME is required.")
    else:
        if "/" in db_name:
            errors.append("DB_NAME must not contain '/'.")
        if "\\" in db_name:
            errors.append("DB_NAME must not contain '\\'.")
        if "\x00" in db_name:
            errors.append("DB_NAME must not contain null characters.")

    # JWT_SECRET
    jwt_secret = env.get("JWT_SECRET", "").strip()
    if not jwt_secret:
        errors.append("JWT_SECRET is required.")
    elif len(jwt_secret) < _JWT_MIN_LEN:
        errors.append(
            f"JWT_SECRET is too short ({len(jwt_secret)} chars). "
            f"Minimum: {_JWT_MIN_LEN} characters."
        )

    # Cookie config — delegate to shared loader
    try:
        cookie = load_cookie_config(env)
    except ValueError as exc:
        cookie = CookieConfig(secure=True, samesite="lax")  # placeholder
        for line in str(exc).splitlines():
            if line.strip():
                errors.append(line.strip())

    # CORS_ALLOWED_ORIGINS
    is_production = app_env == "production"
    try:
        cors_origins = parse_cors_origins(
            env.get("CORS_ALLOWED_ORIGINS", ""),
            production=is_production,
        )
    except ValueError as exc:
        cors_origins = []
        errors.append(str(exc))

    # SEED_DATA_ENABLED
    seed_raw = env.get("SEED_DATA_ENABLED", "false")
    try:
        seed_enabled = parse_bool(seed_raw, "SEED_DATA_ENABLED")
    except ValueError as exc:
        seed_enabled = False
        errors.append(str(exc))

    # Seed credential requirements
    admin_email = env.get("ADMIN_EMAIL", "").strip()
    admin_password = env.get("ADMIN_PASSWORD", "")  # do NOT strip — length matters
    if seed_enabled:
        if not admin_email:
            errors.append("ADMIN_EMAIL is required when SEED_DATA_ENABLED=true.")
        if not admin_password:
            errors.append("ADMIN_PASSWORD is required when SEED_DATA_ENABLED=true.")
        elif len(admin_password) < _SEED_PWD_MIN_LEN:
            errors.append(
                f"ADMIN_PASSWORD is too short. Minimum: {_SEED_PWD_MIN_LEN} characters."
            )
        elif admin_password == _SEED_PWD_PLACEHOLDER:
            errors.append(
                "ADMIN_PASSWORD is still set to the placeholder value. "
                "Replace it with a strong password before enabling seeding."
            )

    # Production safety rules
    if app_env == "production":
        if seed_enabled:
            errors.append("SEED_DATA_ENABLED must not be true in production.")
        if not cookie.secure:
            errors.append("COOKIE_SECURE must be true in production.")

    if errors:
        raise ValueError("Runtime configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))

    return RuntimeConfig(
        app_env=app_env,
        mongo_url=mongo_url,
        db_name=db_name,
        jwt_secret=jwt_secret,
        cookie=cookie,
        cors_origins=cors_origins,
        seed_enabled=seed_enabled,
        admin_email=admin_email,
        admin_password=admin_password,
    )
