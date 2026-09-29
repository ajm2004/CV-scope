"""Role-based access to the recognition API.

The open-source core has no login (it is meant to be reachable from one
computer), so the recognition modules bring their own access layer: bearer
tokens with a role. Tokens are stored hashed; the secret is shown once.

    viewer    read recognition events, registries and diagnostics (no images)
    operator  viewer + enroll / register / disable, view enrollment images
    admin     operator + delete, settings, licence, tokens, exports, audit

The first administrator token is created either with the CLI
(``cvscope recognition token --role admin --name ...``) or, when no token
exists yet, from the local machine through ``POST /api/recognition/access/bootstrap``.
Tokens are accepted in ``Authorization: Bearer <token>``, in the
``X-Recognition-Token`` header or as the ``rtoken`` query parameter (for
WebSocket and image URLs).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session
from pathscope.recognition.registry.models import RecognitionAccessToken

ROLES: dict[str, int] = {"viewer": 1, "operator": 2, "admin": 3}
TOKEN_PREFIX = "psr_"
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


@dataclass
class Principal:
    token_id: str
    name: str
    role: str

    def at_least(self, role: str) -> bool:
        return ROLES.get(self.role, 0) >= ROLES.get(role, 99)

    def to_dict(self) -> dict:
        return {"token_id": self.token_id, "name": self.name, "role": self.role}


def hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_secret() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def create_token(session: Session, name: str, role: str, created_by: str = "", expires_in_days: int | None = None) -> tuple[RecognitionAccessToken, str]:
    if role not in ROLES:
        raise ValueError(f"unknown role '{role}'")
    if not name.strip():
        raise ValueError("a token needs a name")
    secret = new_secret()
    row = RecognitionAccessToken(
        name=name.strip(), role=role, token_hash=hash_token(secret), active=True, created_by=created_by,
        expires_at=(datetime.now(UTC) + timedelta(days=expires_in_days)) if expires_in_days else None,
    )
    session.add(row)
    session.commit()
    return row, secret


def has_any_token(session: Session) -> bool:
    return session.scalar(select(RecognitionAccessToken.id).where(RecognitionAccessToken.active.is_(True)).limit(1)) is not None


def authenticate(session: Session, secret: str | None) -> Principal | None:
    if not secret or not secret.startswith(TOKEN_PREFIX):
        return None
    row = session.scalar(select(RecognitionAccessToken).where(RecognitionAccessToken.token_hash == hash_token(secret)))
    if row is None or not row.active:
        return None
    now = datetime.now(UTC)
    if row.expires_at is not None and row.expires_at < now:
        return None
    if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 60:
        row.last_used_at = now
        try:
            session.commit()
        except Exception:  # noqa: BLE001 - bookkeeping only
            session.rollback()
    return Principal(row.id, row.name, row.role)


def extract_secret(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header = request.headers.get("x-recognition-token")
    if header:
        return header.strip()
    q = request.query_params.get("rtoken")
    return q.strip() if q else None


def is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in _LOOPBACK


def require_role(role: str):
    """FastAPI dependency: a valid token with at least ``role``."""

    def dependency(request: Request, session: Session = Depends(db_session)) -> Principal:
        principal = authenticate(session, extract_secret(request))
        if principal is None:
            raise HTTPException(401, "A recognition access token is required (Authorization: Bearer <token>).")
        if not principal.at_least(role):
            raise HTTPException(403, f"This operation needs the '{role}' role.")
        return principal

    return dependency


def optional_principal(request: Request, session: Session = Depends(db_session)) -> Principal | None:
    return authenticate(session, extract_secret(request))
