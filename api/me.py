"""3. 내 정보 조회.

[POST] /api/me
요청: user(user_id)
응답: id, email

순서
사용자 ID로 DB 검색 → 해당 사용자의 ID와 이메일 반환
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import User, get_db
from api.auth import current_user

router = APIRouter()


class MyInfoRequest(BaseModel):
    user: str  # user_id


class MyInfoResponse(BaseModel):
    id: str
    email: EmailStr


@router.post("/api/me", response_model=MyInfoResponse)
def my_info(req: MyInfoRequest, db: Session = Depends(get_db), authenticated=Depends(current_user)):
    if req.user != authenticated.user_id:
        raise HTTPException(403, '다른 사용자의 정보를 조회할 수 없습니다.')
    user = db.scalar(select(User).where(User.user_id == req.user))
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return MyInfoResponse(id=user.user_id, email=user.email)
