"""LLM(Gemini) 기반 코칭 문장 생성.

`compare_v2` 가 만든 구조화 리포트(dict)를 받아서, 부위별 요약·유지점·개선점과
전체 요약 문장을 자연어로 만든다. 지금까지 프론트에서 규칙 기반(`_jointSummary`
`_jointPoints` `_buildSummary` 등)으로 채우던 자리를 대신한다.

설계 원칙:
- 이 모듈은 `api/` 에 의존하지 않는다. API 키와 모델명은 호출부(`api/jobs.py`)가
  설정에서 읽어 인자로 넘긴다.
- 실패(키 없음·네트워크 오류·파싱 실패 등)하면 예외를 삼키고 ``None`` 을 돌려준다.
  호출부는 ``None`` 이면 기존 규칙 기반 폴백을 쓰면 된다.
- 출력은 JSON 스키마로 강제해서(`response_schema`) 파싱을 안정화한다.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 부위 점수가 이 값 이상이면 "잘함", 미만이면 "개선필요" (프론트 _goodScore=80 과 맞춤).
GOOD_SCORE = 80


# ---------------------------------------------------------------------------
# 출력 스키마 (Gemini 가 이 모양의 JSON 만 돌려주도록 강제)
# ---------------------------------------------------------------------------
class PartCoaching(BaseModel):
    key: str  # 부위 key (예: front_arm). 입력으로 준 것 중 하나.
    summary: str  # 그 부위 상태를 1~2문장으로 요약
    keep_points: List[str]  # 유지하면 좋은 점 (잘하는 부위 위주)
    improve_points: List[str]  # 개선하면 좋은 점 (기준과 벌어진 부위 위주)


class JointCoaching(BaseModel):
    key: str  # 관절(피처) key (예: lead_elbow_angle). 입력으로 준 것 중 하나.
    comment: str  # 그 관절이 기준과 어떻게 다른지 1~2문장


class PhaseCoaching(BaseModel):
    key: str  # 구간 key (예: stride/load/swing/follow_through). 입력으로 준 것 중 하나.
    comment: str  # 그 구간의 타이밍·문제를 1~2문장


class Coaching(BaseModel):
    overall_summary: str  # 스윙 전체를 2~3문장으로 요약
    overall_coach: str  # 가장 먼저 고치면 좋을 핵심 한 가지를 코치 말투로
    parts: List[PartCoaching]


class CoachingFull(Coaching):
    """관절·구간 서술까지 포함하는 확장 스키마 (coaching_scope='full' 일 때 사용)."""

    joints: List[JointCoaching]
    phases: List[PhaseCoaching]


# ---------------------------------------------------------------------------
# 입력 다듬기: 리포트에서 LLM 에 넘길 핵심만 추린다
# ---------------------------------------------------------------------------
def _direction_ko(direction: str) -> str:
    return {"higher": "기준보다 큼", "lower": "기준보다 작음", "similar": "기준과 비슷"}.get(
        direction, direction
    )


def _phase_lines(phases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """구간별 내 각도 vs 기준 각도 중 측정된 것만 압축."""
    lines = []
    for p in phases:
        if not p.get("available") or p.get("z_score") is None:
            continue
        lines.append(
            {
                "phase": p.get("phase_name") or p.get("phase"),
                "user": p.get("user_mean"),
                "reference": p.get("reference_mean"),
                "diff": p.get("diff"),
                "level": p.get("level"),
                "direction": _direction_ko(p.get("direction", "")),
            }
        )
    return lines


def _joint_line(joint: Dict[str, Any]) -> Dict[str, Any]:
    """관절(피처) 하나를 LLM 입력용으로 압축. key 를 포함해 출력과 매핑한다."""
    impact = joint.get("impact") or {}
    rom = joint.get("range_of_motion") or {}
    return {
        "key": joint.get("key"),
        "name": joint.get("name"),
        "body_part": joint.get("body_part"),
        "unit": joint.get("unit"),
        "level": joint.get("level"),
        "description": joint.get("description"),
        "impact_diff": impact.get("diff"),
        "range_of_motion_diff": rom.get("diff"),
        "phases": _phase_lines(joint.get("phases") or []),
    }


def _phase_summary(phase: Dict[str, Any]) -> Dict[str, Any]:
    """구간 하나를 LLM 입력용으로 압축: 점수·템포·가장 벌어진 관절."""
    devs = phase.get("top_deviations") or []
    top = devs[0] if devs else None
    return {
        "key": phase.get("key"),
        "name": phase.get("name"),
        "score": phase.get("score"),
        "user_duration_ms": phase.get("user_duration_ms"),
        "reference_duration_ms": phase.get("reference_duration_ms"),
        "tempo_level": phase.get("tempo_level"),
        "top_deviation": (
            {
                "name": top.get("joint_name"),
                "diff": top.get("diff"),
                "direction": _direction_ko(top.get("direction", "")),
            }
            if top
            else None
        ),
    }


def build_llm_input(report: Dict[str, Any], *, scope: str = "overall") -> Dict[str, Any]:
    """리포트 dict → LLM 프롬프트에 넣을 압축 구조.

    신뢰도가 낮은(reliability=='low') 부위/피처는 뺀다(프론트와 동일 기준).
    ``scope='full'`` 이면 관절별/구간별 서술을 위한 ``joints``/``phases`` 도 함께 넣는다.
    """
    overall = report.get("overall") or {}
    joints = report.get("joints") or []

    # 부위(group) 요약
    parts: Dict[str, Dict[str, Any]] = {}
    for group in overall.get("group_scores") or []:
        if not group.get("available") or group.get("reliability") == "low":
            continue
        score = group.get("score")
        parts[group["key"]] = {
            "key": group["key"],
            "name": group.get("name"),
            "score": score,
            "status": "잘함" if (score is not None and score >= GOOD_SCORE) else "개선필요",
            "features": [],
        }

    # 믿을 만한 관절만 추린다(부위가 추려졌고, 관절 자체도 신뢰도 ok).
    reliable_joints = [
        joint
        for joint in joints
        if joint.get("available")
        and joint.get("reliability") != "low"
        and joint.get("body_part") in parts
    ]

    # 피처(관절)를 부위에 붙인다
    for joint in reliable_joints:
        parts[joint["body_part"]]["features"].append(
            {
                "name": joint.get("name"),
                "unit": joint.get("unit"),
                "level": joint.get("level"),
                "description": joint.get("description"),
                "impact_diff": (joint.get("impact") or {}).get("diff"),
                "range_of_motion_diff": (joint.get("range_of_motion") or {}).get("diff"),
                "phases": _phase_lines(joint.get("phases") or []),
            }
        )

    payload: Dict[str, Any] = {
        "overall_score": overall.get("score"),
        "reliability": overall.get("reliability"),
        "parts": list(parts.values()),
    }

    if scope == "full":
        payload["joints"] = [_joint_line(joint) for joint in reliable_joints]
        phase_block = report.get("phases") or {}
        payload["phases"] = [
            _phase_summary(p)
            for p in (phase_block.get("phases") or [])
            if p.get("available") and p.get("reliability") != "low"
        ]

    return payload


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTION = """\
너는 야구 타격 스윙을 지도하는 전문 코치다. 선수의 스윙을 프로 기준과 비교한 분석
데이터를 받아서, 선수가 바로 이해하고 실천할 수 있는 한국어 코칭을 만든다.

규칙:
- 반드시 한국어. 따뜻하지만 군더더기 없는 코치 말투(존댓말).
- 데이터에 있는 수치·구간을 근거로 구체적으로 말한다. 데이터에 없는 내용은 지어내지 않는다.
- status 가 '잘함'인 부위는 keep_points 를 채우고 improve_points 는 비워도 된다.
  status 가 '개선필요'인 부위는 improve_points 를 1~2개 채운다.
- 각 point 는 한 문장. 부위당 keep/improve 합쳐 최대 3개.
- summary 는 그 부위 상태를 1~2문장으로.
- overall_summary 는 스윙 전체를 2~3문장으로, overall_coach 는 가장 먼저 고치면
  좋을 핵심 한 가지를 짧게.
- 입력으로 받은 부위(key)에 대해서만 쓴다. 없는 부위를 만들지 않는다.
"""


# scope='full' 일 때만 덧붙이는 규칙 (관절별/구간별 서술).
FULL_SCOPE_INSTRUCTION = """\

추가로 joints, phases 도 채운다:
- joints: 입력으로 받은 관절(key)마다 그 각도가 기준과 어떻게 다른지 1~2문장. 수치를 근거로.
- phases: 입력으로 받은 구간(key)마다 타이밍(템포)과 그 구간에서 가장 벌어진 관절을 묶어 1~2문장.
- 입력에 없는 관절·구간 key 는 만들지 않는다. 받은 key 에 대해서만 쓴다.
"""


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def generate_coaching(
    report: Dict[str, Any],
    *,
    api_key: str,
    model: str,
    scope: str = "overall",
    timeout_s: float = 30.0,
) -> Optional[Dict[str, Any]]:
    """리포트로부터 코칭 dict 를 만든다. 실패하면 ``None``.

    ``scope``:
      - ``'overall'``(기본): 종합 요약 + 부위별 요약/포인트만 생성.
      - ``'full'``: 관절별(joints)·구간별(phases) 서술까지 한 번의 호출로 함께 생성.
        (유료 등급 전환 후 켤 용도. 프론트는 아직 소비하지 않는다.)

    반환 형태(성공 시)::

        {
          "overall_summary": str,
          "overall_coach": str,
          "parts": [{"key", "summary", "keep_points": [...], "improve_points": [...]}],
          # scope='full' 일 때만:
          "joints": [{"key", "comment"}],
          "phases": [{"key", "comment"}],
        }
    """
    if not api_key:
        return None

    full = scope == "full"
    payload = build_llm_input(report, scope=scope)
    if not payload.get("parts"):
        # 믿을 만한 부위가 하나도 없으면 LLM 을 부를 것도 없다.
        return None

    schema = CoachingFull if full else Coaching
    system_instruction = SYSTEM_INSTRUCTION + (FULL_SCOPE_INSTRUCTION if full else "")

    try:
        import json

        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
        )
        response = client.models.generate_content(
            model=model,
            contents=json.dumps(payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.4,
            ),
        )
        parsed = response.parsed
        if parsed is None:
            logger.warning("Gemini 코칭 응답을 파싱하지 못했습니다.")
            return None
        return parsed.model_dump()
    except Exception:
        logger.exception("Gemini 코칭 생성 실패 — 규칙 기반 폴백으로 넘어갑니다.")
        return None
