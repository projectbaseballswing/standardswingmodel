"""회원별 스윙 목록 조회. 목록 화면용 경량 응답이며 새 DB 테이블은 만들지 않는다.

주의: 현재 프로젝트에는 인증 토큰/접근 권한 검사가 없다.
user_id 경로 파라미터는 개발용 필터일 뿐 소유자 인증 수단이 아니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import Swing, User, get_db
from api.schemas import SwingListItem, SwingListResponse

router = APIRouter(prefix="/api", tags=["swings"])


def _utc_datetime(value: datetime) -> datetime:
    """SQLite가 시간대 정보를 제거하더라도 저장 시각을 UTC로 해석한다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _overall_score(row: Swing) -> float | None:
    if row.status != "done" or not isinstance(row.result, dict):
        return None
    overall = row.result.get("overall")
    if not isinstance(overall, dict):
        return None
    score = overall.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return float(score)
    return None


@router.get("/users/{user_id}/swings", response_model=SwingListResponse)
def list_user_swings(
    user_id: str,
    year: int | None = Query(None, ge=1900, le=9998, description="월별 조회 시 month와 함께 전달"),
    month: int | None = Query(None, ge=1, le=12, description="월별 조회 시 year와 함께 전달"),
    tz_offset_minutes: int = Query(540, ge=-720, le=840, description="달력 기준 UTC 오프셋(분). 기본 한국시간 +09:00"),
    db: Session = Depends(get_db),
):
    """회원 ID 기준 스윙 기록 조회. year/month를 모두 생략하면 전체 기록 반환.

    UI 표시 시각은 recorded_at이 우선이고 없으면 created_at(업로드 시각)을 사용한다.
    분석 전체 JSON과 Storage 객체 경로는 목록 응답에 포함하지 않는다.
    JWT 인증/소유권 검사는 없으며 user_id는 조회 필터일 뿐 인증 수단이 아니다.
    """
    if (year is None) != (month is None):
        raise HTTPException(422, "월별 조회에는 year와 month가 모두 필요합니다.")
    if db.get(User, user_id) is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")

    display_time = func.coalesce(Swing.recorded_at, Swing.created_at)
    stmt = select(Swing).where(Swing.user_id == user_id)
    year_month = None
    if year is not None and month is not None:
        # 사용자가 보는 달력(기본 KST)의 월 경계를 UTC로 변환하여 필터링한다.
        offset = timezone(timedelta(minutes=tz_offset_minutes))
        start = datetime(year, month, 1, tzinfo=offset).astimezone(timezone.utc)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        end = datetime(next_year, next_month, 1, tzinfo=offset).astimezone(timezone.utc)
        stmt = stmt.where(display_time >= start, display_time < end)
        year_month = f"{year:04d}-{month:02d}"

    rows = db.scalars(
        stmt.order_by(display_time.desc(), Swing.created_at.desc(), Swing.analysis_id.desc())
    ).all()
    return SwingListResponse(
        user_id=user_id,
        year_month=year_month,
        count=len(rows),
        items=[
            SwingListItem(
                analysis_id=row.analysis_id,
                recorded_at=_utc_datetime(row.recorded_at or row.created_at),
                status=row.status,
                score=_overall_score(row),
                thumbnail_url=None,
            )
            for row in rows
        ],
    )
