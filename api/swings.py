"""회원별 스윙 목록 조회. 목록 화면용 경량 응답이며 새 DB 테이블은 만들지 않는다.

주의: 현재 프로젝트에는 인증 토큰/접근 권한 검사가 없다.
user_id 경로 파라미터는 개발용 필터일 뿐 소유자 인증 수단이 아니다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import Swing, User, get_db
from api.schemas import (
    ComparisonJoint,
    ComparisonPart,
    ComparisonPhase,
    ComparisonResponse,
    SwingListItem,
    SwingListResponse,
)
from api.settings import settings
from feedback.llm_coach import generate_comparison_coaching

logger = logging.getLogger(__name__)

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


def _part_scores(row: Swing) -> dict[str, float]:
    """done 리포트의 부위(group)별 점수. available이고 숫자인 것만 key→score로 모은다."""
    if row.status != "done" or not isinstance(row.result, dict):
        return {}
    overall = row.result.get("overall")
    if not isinstance(overall, dict):
        return {}
    out: dict[str, float] = {}
    for group in overall.get("group_scores") or []:
        if not isinstance(group, dict):
            continue
        key = group.get("key")
        score = group.get("score")
        if (
            isinstance(key, str)
            and key
            and group.get("available") is not False
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
        ):
            out[key] = float(score)
    return out


def _phase_scores(row: Swing) -> dict[str, float]:
    """done 리포트의 구간(phase)별 점수. available이고 신뢰도 ok인 것만 key→score."""
    if row.status != "done" or not isinstance(row.result, dict):
        return {}
    block = row.result.get("phases")
    if not isinstance(block, dict):
        return {}
    out: dict[str, float] = {}
    for p in block.get("phases") or []:
        if not isinstance(p, dict):
            continue
        key = p.get("key")
        score = p.get("score")
        if (
            isinstance(key, str)
            and key
            and p.get("available") is not False
            and p.get("reliability") != "low"
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
        ):
            out[key] = float(score)
    return out


def _joint_diffs(row: Swing) -> dict[str, dict]:
    """done 리포트의 관절별 '기준(프로)과의 차이'(impact.diff). available+신뢰도 ok만.

    key → {"body_part", "diff"}. 그래프용 시계열은 무거워서 넣지 않는다.
    """
    if row.status != "done" or not isinstance(row.result, dict):
        return {}
    out: dict[str, dict] = {}
    for j in row.result.get("joints") or []:
        if not isinstance(j, dict):
            continue
        key = j.get("key")
        if not (isinstance(key, str) and key):
            continue
        if j.get("available") is False or j.get("reliability") == "low":
            continue
        diff = (j.get("impact") or {}).get("diff")
        if isinstance(diff, (int, float)) and not isinstance(diff, bool):
            out[key] = {"body_part": j.get("body_part"), "diff": float(diff)}
    return out


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


def _comparison_coaching(db: Session, current: Swing, previous: Swing) -> dict | None:
    """이전 대비 LLM 코칭. 성공분은 current.result['comparison']에 캐시해 재호출을 막는다.

    키가 없거나 생성 실패하면 None → 프론트는 규칙 기반으로 폴백한다.
    """
    if not settings.gemini_api_key:
        return None
    if not isinstance(current.result, dict) or not isinstance(previous.result, dict):
        return None

    cache = current.result.get("comparison")
    if (
        isinstance(cache, dict)
        and cache.get("previous_analysis_id") == previous.analysis_id
        and isinstance(cache.get("coaching"), dict)
    ):
        return cache["coaching"]  # 같은 직전 분석에 대해 이미 생성됨

    coaching = generate_comparison_coaching(
        current.result,
        previous.result,
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        scope=settings.coaching_scope,
    )
    if coaching is not None:
        # JSON 컬럼이라 전체 dict를 재할당해야 변경이 감지된다.
        new_result = dict(current.result)
        new_result["comparison"] = {
            "previous_analysis_id": previous.analysis_id,
            "coaching": coaching,
        }
        current.result = new_result
        try:
            db.commit()
        except Exception:
            logger.exception("비교 코칭 캐시 저장 실패 — 응답은 그대로 반환한다.")
            db.rollback()
    return coaching


@router.get(
    "/users/{user_id}/analyses/{analysis_id}/comparison",
    response_model=ComparisonResponse,
)
def compare_with_previous(
    user_id: str,
    analysis_id: str,
    db: Session = Depends(get_db),
):
    """현재 분석을 같은 회원의 직전 분석과 비교한다(반복 피드백용).

    "직전"은 같은 회원의 done 분석 중 표시 시각(recorded_at 우선, 없으면 created_at)이
    현재보다 이전인 가장 최근 1건이다. 결과는 DB(Swing.result)에서 읽으므로 서버
    재시작과 무관하게 조회된다. 직전 분석이 없으면 has_previous=false.

    JWT 인증/소유권 검사는 없으며 user_id는 조회 필터일 뿐 인증 수단이 아니다.
    """
    if db.get(User, user_id) is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    current = db.get(Swing, analysis_id)
    if current is None or current.user_id != user_id:
        raise HTTPException(404, "분석 결과를 찾을 수 없습니다.")
    if current.status != "done" or not isinstance(current.result, dict):
        raise HTTPException(409, "아직 분석이 완료되지 않았습니다.")

    display_time = func.coalesce(Swing.recorded_at, Swing.created_at)
    current_time = current.recorded_at or current.created_at
    previous = db.scalars(
        select(Swing)
        .where(
            Swing.user_id == user_id,
            Swing.status == "done",
            Swing.analysis_id != analysis_id,
            display_time < current_time,
        )
        .order_by(display_time.desc(), Swing.created_at.desc(), Swing.analysis_id.desc())
        .limit(1)
    ).first()

    if previous is None or not isinstance(previous.result, dict):
        return ComparisonResponse(has_previous=False)

    cur_overall = _overall_score(current)
    prev_overall = _overall_score(previous)
    cur_parts = _part_scores(current)
    prev_parts = _part_scores(previous)

    parts = [
        ComparisonPart(
            key=key,
            previous_score=prev_parts.get(key),
            delta=round(cur - prev_parts[key], 1) if key in prev_parts else None,
        )
        for key, cur in cur_parts.items()
    ]
    overall_delta = (
        round(cur_overall - prev_overall, 1)
        if cur_overall is not None and prev_overall is not None
        else None
    )

    # 구간별 점수 이전 대비.
    cur_phase, prev_phase = _phase_scores(current), _phase_scores(previous)
    phases = [
        ComparisonPhase(
            key=key,
            current_score=cur,
            previous_score=prev_phase.get(key),
            delta=round(cur - prev_phase[key], 1) if key in prev_phase else None,
        )
        for key, cur in cur_phase.items()
    ]

    # 관절별 '기준과의 차이' 이전 대비. gap_narrowed = |이전| − |이번| (+면 프로에 가까워짐).
    cur_joint, prev_joint = _joint_diffs(current), _joint_diffs(previous)
    joints = []
    for key, j in cur_joint.items():
        pj = prev_joint.get(key)
        prev_diff = pj["diff"] if pj else None
        gap = round(abs(prev_diff) - abs(j["diff"]), 1) if prev_diff is not None else None
        joints.append(
            ComparisonJoint(
                key=key,
                body_part=j["body_part"],
                previous_diff=prev_diff,
                current_diff=j["diff"],
                gap_narrowed=gap,
            )
        )

    return ComparisonResponse(
        has_previous=True,
        previous_analysis_id=previous.analysis_id,
        previous_recorded_at=_utc_datetime(previous.recorded_at or previous.created_at),
        overall_previous_score=prev_overall,
        overall_delta=overall_delta,
        parts=parts,
        phases=phases,
        joints=joints,
        coaching=_comparison_coaching(db, current, previous),
    )
