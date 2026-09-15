"""JWT-based auth utilities for the reasoning API server.

Credentials are loaded from environment variables (set via .env.local):
  AUTH_USERNAME              — the single authorised username
  AUTH_PASSWORD_HASH         — bcrypt hash (generate with scripts/hash_password.py)
  AUTH_JWT_SECRET            — HS256 signing secret (random hex, 32+ bytes)
  AUTH_TOKEN_EXPIRE_MINUTES  — session duration in minutes (default: 480)

Login tokens are issued by POST /api/auth/login on this server.
The ingestion server (:8002) verifies the same tokens using the shared secret.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)
# Module-level dependency instance avoids B008 (function call in default arg)
_bearer_dep: HTTPAuthorizationCredentials | None = Security(_bearer)


def _get_secret() -> str:
    secret = os.environ.get("AUTH_JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "AUTH_JWT_SECRET must be set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return secret


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored bcrypt *hashed* password."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        logger.error("AUTH_PASSWORD_HASH is not a valid bcrypt hash")
        return False


def create_access_token(sub: str) -> str:
    """Create a signed HS256 JWT for *sub* with the configured expiry."""
    expire_minutes = int(os.environ.get("AUTH_TOKEN_EXPIRE_MINUTES", "480"))
    expire = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    return jwt.encode({"sub": sub, "exp": expire}, _get_secret(), algorithm=_ALGORITHM)


def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = _bearer_dep,
) -> str:
    """FastAPI dependency — accept JWT from Authorization or X-Auth-Token header.

    RunPod nginx strips Authorization; X-Auth-Token is the fallback.
    Returns the sub claim on success, raises HTTP 401 otherwise.
    """
    token: str | None = None
    if credentials is not None:
        token = credentials.credentials
    if not token:
        token = request.headers.get("X-Auth-Token")
    if not token:
        # Final fallback: cookie (survives RunPod/Cloudflare header stripping)
        token = request.cookies.get("auth_token")
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"code": "missing_token", "message": "Authentication required.", "retryable": False},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[_ALGORITHM])
        sub: str | None = payload.get("sub")
        if not sub:
            raise JWTError("missing sub claim")
        return sub
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_token", "message": "Invalid or expired token. Please log in again.", "retryable": False},
            headers={"WWW-Authenticate": "Bearer"},
        )
