"""Opaque bearer sessions for the existing bcrypt accounts.

Not Supabase Auth JWTs: only the backend resolves token hashes to users.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.database import AuthSession, Swing, User, get_db
from api.settings import settings


def now():
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def issue_session(db: Session, user_id: str):
    ttl = settings.session_ttl_seconds
    if not 60 <= ttl <= 86400:
        raise RuntimeError("Session TTL must be 60..86400 seconds")
    token = secrets.token_urlsafe(32)
    created = now()
    db.add(AuthSession(
        token_hash=token_hash(token), user_id=user_id, created_at=created,
        expires_at=created + timedelta(seconds=ttl),
    ))
    db.commit()
    return token, ttl


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    invalid = HTTPException(
        401, "로그인이 필요하거나 인증이 만료되었습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if scheme.lower() != "bearer" or not 32 <= len(token) <= 128 or not token.isascii():
        raise invalid
    row = db.get(AuthSession, token_hash(token))
    if row is None or row.revoked_at is not None:
        raise invalid
    expiry = row.expires_at
    if expiry.tzinfo is None:  # SQLite returns naive UTC in local tests.
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= now():
        raise invalid
    user = db.get(User, row.user_id)
    if user is None:
        raise invalid
    request.state.user_id = user.user_id
    request.state.token_hash = row.token_hash
    return user


def analysis_access(request: Request, db: Session = Depends(get_db)):
    if request.url.path == "/api/health":
        return
    user = current_user(request, db)
    analysis_id = request.path_params.get("analysis_id")
    if analysis_id is not None:
        row = db.get(Swing, analysis_id)
        if row is None:
            raise HTTPException(404, "분석 결과를 찾을 수 없습니다.")
        if row.user_id != user.user_id:
            raise HTTPException(403, "이 분석에 접근할 권한이 없습니다.")


def user_path_access(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if request.path_params.get("user_id") != user.user_id:
        raise HTTPException(403, "다른 사용자의 기록에 접근할 수 없습니다.")
