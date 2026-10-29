"""서버 진입점

실행 (프로젝트 루트에서):
    uvicorn api.main:app --reload

문서: http://127.0.0.1:8000/docs
모든 경로는 /api 로 시작한다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from api import login, me, register, swings, pose3d
from api.analyses import lifespan
from api.analyses import router as analyses_router
from api.settings import settings

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

# 개발용 CORS 설정.
# Flutter 웹(flutter run -d chrome)은 서버와 다른 origin(포트)에서 돌기 때문에
# 이 설정이 없으면 브라우저가 API 요청을 차단한다.
# 배포 시에는 allow_origins 를 실제 프론트 도메인으로 제한할 것.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    # 와일드카드(*) origin 과 credentials 는 브라우저가 함께 허용하지 않는다.
    # Bearer 헤더는 allow_headers로 허용하며 쿠키 인증은 사용하지 않는다.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 회원 (/api/register, /api/login, /api/me, /api/check-email)
app.include_router(register.router)
app.include_router(login.router)
app.include_router(me.router)

# 스윙 피드백 (/api/analyses, /api/health)
app.include_router(analyses_router)

# 회원별 스윙 기록 목록 (달력/목록 화면용)
app.include_router(swings.router)
app.include_router(pose3d.router)


@app.get('/api/local-video', include_in_schema=False)
def local_video(request: Request, path: str, expires: int, signature: str):
    """Explicit dev storage only; short-lived capability issued after ownership."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from api.analyses import _storage
    from api.storage import LocalPrivateStorage, StorageError
    storage = _storage(request)
    if not isinstance(storage, LocalPrivateStorage):
        raise HTTPException(404, 'Not available')
    try:
        target = storage.capability_path(path, expires, signature)
    except StorageError:
        raise HTTPException(403, '유효한 영상 접근 권한이 없습니다.') from None
    if not target.is_file():raise HTTPException(404, '저장된 영상을 찾을 수 없습니다.')
    return FileResponse(target, headers={'Cache-Control':'private, no-store'})


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request, exc):
    # SQL 파라미터에는 회원/비밀번호 해시가 포함될 수 있어 응답·로그에 출력하지 않는다.
    logging.getLogger(__name__).error("Database operation failed: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "DB 요청에 실패했습니다. 연결과 migration 상태를 확인하세요."})
