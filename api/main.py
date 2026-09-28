"""서버 진입점

실행 (프로젝트 루트에서):
    uvicorn api.main:app --reload

문서: http://127.0.0.1:8000/docs
모든 경로는 /api 로 시작한다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from api import login, me, register
from api.analyses import lifespan
from api.analyses import router as analyses_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Swing Analysis API",
    description=(
        "회원 기능과 스윙 피드백 기능을 제공합니다. "
        "피드백은 사용자 스윙 영상을 전체 선수 기준 스윙 템플릿과 비교해 종합/관절별/구간별 수치를 돌려줍니다."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# 회원 (/api/register, /api/login, /api/me, /api/check-email)
app.include_router(register.router)
app.include_router(login.router)
app.include_router(me.router)

# 스윙 피드백 (/api/analyses, /api/health)
app.include_router(analyses_router)
