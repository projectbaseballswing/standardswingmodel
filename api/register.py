"""1. 회원가입.

[POST] /api/register
요청: id, password, email, nickname
응답: id-uniqueness, nickname-uniqueness, registered
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.database import User, get_db
from api.security import hash_password

router = APIRouter()


class RegisterRequest(BaseModel):
    id: str
    password: str  # 숫자로 와도 문자열로 처리
    email: EmailStr
    nickname: str

    # coerce_numbers_to_str: 스펙 예시처럼 password가 숫자로 와도 문자열로 변환
    model_config = {"extra": "forbid", "coerce_numbers_to_str": True}


class RegisterResponse(BaseModel):
    # 1 = 사용 가능(중복 아님), 0 = 중복
    id_uniqueness: int = Field(serialization_alias="id-uniqueness")
    nickname_uniqueness: int = Field(serialization_alias="nickname-uniqueness")
    registered: bool


@router.post(
    "/api/register",
    response_model=RegisterResponse,
    response_model_by_alias=True,
)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    id_taken = db.scalar(select(User).where(User.user_id == req.id)) is not None
    nickname_taken = db.scalar(select(User).where(User.nickname == req.nickname)) is not None
    email_taken = db.scalar(select(User).where(User.email == req.email)) is not None

    # 하나라도 중복이면 등록하지 않고 중복 여부만 알려준다.
    if id_taken or nickname_taken or email_taken:
        return RegisterResponse(
            id_uniqueness=0 if id_taken else 1,
            nickname_uniqueness=0 if nickname_taken else 1,
            registered=False,
        )

    try:
        password_hash = hash_password(req.password)
    except ValueError:
        raise HTTPException(422, "비밀번호는 UTF-8 기준 1~72바이트여야 합니다.") from None
    db.add(
        User(
            user_id=req.id,
            email=req.email,
            nickname=req.nickname,
            password_hash=password_hash,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # 동시에 같은 회원을 등록해도 500 대신 기존 중복 응답을 유지한다.
        db.rollback()
        id_taken = db.get(User, req.id) is not None
        nickname_taken = db.scalar(select(User).where(User.nickname == req.nickname)) is not None
        email_taken = db.scalar(select(User).where(User.email == req.email)) is not None
        if not (id_taken or nickname_taken or email_taken):
            raise
        return RegisterResponse(id_uniqueness=int(not id_taken),
                                nickname_uniqueness=int(not nickname_taken), registered=False)

    return RegisterResponse(id_uniqueness=1, nickname_uniqueness=1, registered=True)


# 이메일 중복확인 (목업의 "중복확인" 버튼용)
@router.get("/api/check-email")
def check_email(email: EmailStr, db: Session = Depends(get_db)):
    taken = db.scalar(select(User).where(User.email == email)) is not None
    return {"email-uniqueness": 0 if taken else 1}  # 1 = 사용 가능, 0 = 중복
