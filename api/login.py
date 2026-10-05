"""2. 로그인.

[POST] /api/login
요청: id, password
응답: success, user(user_id)

순서
ID로 사용자 검색 → 비밀번호 검증 → 사용자 ID 반환
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import User, get_db
from api.security import verify_password

router = APIRouter()


class LoginRequest(BaseModel):
    id: str = Field(description="회원가입 시 정한 사용자 ID")
    password: str

    model_config = {"extra": "forbid", "coerce_numbers_to_str": True,
                    "json_schema_extra": {"examples": [{"id": "demo-user", "password": "example-password"}]}}


class LoginResponse(BaseModel):
    success: bool
    user: str  # user_id


@router.post("/api/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.get(User, req.id)
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 일치하지 않습니다.")
    return LoginResponse(success=True, user=user.user_id)
