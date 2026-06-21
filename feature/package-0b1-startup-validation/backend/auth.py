"""JWT-based authentication helpers with RBAC support."""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, Request, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from runtime_config import load_cookie_config

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60 * 8  # 8 hours - hospital shift
REFRESH_TOKEN_DAYS = 7
FAIL_LIMIT = 5
LOCK_MINUTES = 15


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookies(response, access_token: str, refresh_token: str) -> None:
    cfg = load_cookie_config()
    secure, samesite = cfg.secure, cfg.samesite
    response.set_cookie(
        key="access_token", value=access_token, httponly=True,
        secure=secure, samesite=samesite, max_age=ACCESS_TOKEN_MINUTES * 60, path="/"
    )
    response.set_cookie(
        key="refresh_token", value=refresh_token, httponly=True,
        secure=secure, samesite=samesite, max_age=REFRESH_TOKEN_DAYS * 86400, path="/"
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


def _extract_token(request: Request) -> Optional[str]:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return token


async def get_current_user(request: Request) -> dict:
    db: AsyncIOMotorDatabase = request.app.state.db
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated. Please sign in.")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user or not user.get("is_active", True):
            raise HTTPException(status_code=401, detail="User not found or disabled")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_roles(*allowed_roles: str):
    """Dependency factory enforcing role-based access."""
    async def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed_roles and user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
        return user
    return _checker


# ------- Brute force lockout helpers -------
async def check_lockout(db: AsyncIOMotorDatabase, identifier: str) -> None:
    rec = await db.login_attempts.find_one({"identifier": identifier})
    if rec and rec.get("locked_until"):
        locked_until = rec["locked_until"]
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > datetime.now(timezone.utc):
            mins = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
            raise HTTPException(status_code=429, detail=f"Account locked. Try again in {mins} minute(s).")


async def register_failed_attempt(db: AsyncIOMotorDatabase, identifier: str) -> None:
    rec = await db.login_attempts.find_one({"identifier": identifier})
    attempts = (rec.get("attempts", 0) if rec else 0) + 1
    update = {"attempts": attempts, "last_attempt": datetime.now(timezone.utc).isoformat()}
    if attempts >= FAIL_LIMIT:
        update["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)).isoformat()
        update["attempts"] = 0
    await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)


async def clear_failed_attempts(db: AsyncIOMotorDatabase, identifier: str) -> None:
    await db.login_attempts.delete_one({"identifier": identifier})
