"""2. 로그인.

[POST] /api/login
요청: e-mail, password  (목업 기준 이메일 로그인)
응답: success, user(user_id)

순서
이메일로 사용자 검색 → 비밀번호 검증 → 사용자 ID 반환
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import User, get_db
from backend.security import verify_password

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr = Field(alias="e-mail")
    password: str

    model_config = {"populate_by_name": True, "coerce_numbers_to_str": True}


class LoginResponse(BaseModel):
    success: bool
    user: str  # user_id


@router.post("/api/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == req.email))
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 일치하지 않습니다.")
    return LoginResponse(success=True, user=user.user_id)
