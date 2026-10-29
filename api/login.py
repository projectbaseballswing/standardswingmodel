"""2. 로그인.

[POST] /api/login
요청: id, password
응답: success, user(user_id), access_token, token_type, expires_in

순서
기존 users에서 ID 검색 → bcrypt 검증 → 해시로 저장하는 Bearer 세션 발급
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import User, get_db
from api.security import verify_password
from api.auth import current_user, issue_session, now
from api.database import AuthSession

router = APIRouter()


class LoginRequest(BaseModel):
    id: str = Field(description="회원가입 시 정한 사용자 ID")
    password: str

    model_config = {"extra": "forbid", "coerce_numbers_to_str": True,
                    "json_schema_extra": {"examples": [{"id": "demo-user", "password": "example-password"}]}}


class LoginResponse(BaseModel):
    success: bool
    user: str  # user_id
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/api/login", response_model=LoginResponse)
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.get(User, req.id)
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 일치하지 않습니다.")
    token, ttl = issue_session(db, user.user_id)
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(success=True, user=user.user_id, access_token=token, expires_in=ttl)


@router.post('/api/logout')
def logout(request: Request, user=Depends(current_user), db: Session=Depends(get_db)):
    row=db.get(AuthSession,request.state.token_hash)
    row.revoked_at=now();db.commit()
    return {'success':True}
