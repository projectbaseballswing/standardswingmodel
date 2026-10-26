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
    key: str  # 구간 key (예: stride/transition/swing/follow). 입력으로 준 것 중 하나.
    card_line: str  # 구간 카드용 짧은 한 줄 요약(상태 중심, "~해요" 말투)
    comment: str  # 그 구간의 타이밍·문제를 1~2문장 (수치·top_deviation 근거)
    tip: str  # 그 구간을 개선할 실천 팁 한 문장


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
- phases: 입력으로 받은 구간(key)마다 아래 3가지를 모두 채운다. 근거는 템포와
  그 구간에서 가장 벌어진 관절(top_deviation). top_deviation 의 관절 이름으로 어느
  부위가 문제인지 말하고, 입력에 없는 부위는 지어내지 않는다.
  - card_line: 구간 카드에 들어갈 짧은 한 줄. 상태 중심, 부드러운 "~해요" 말투.
  - comment: 왜 그런지(템포·가장 벌어진 관절) 1~2문장으로 설명.
  - tip: 그 구간을 개선할 실천 팁 한 문장.
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
          "phases": [{"key", "card_line", "comment", "tip"}],
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


# ===========================================================================
# 이전 스윙 대비 비교 코칭 (2번째+ 피드백)
# ===========================================================================
# 분석 자체는 항상 프로 기준이지만(점수가 프로 대비로 매겨짐), 2번째 스윙부터는
# "지난 스윙 대비 개선/악화" 관점으로 코칭한다. 근거는 점수 변화 + 기준과의 차이 변화.
# 프론트는 종합+부위만 소비하고, 관절/구간 비교는 scope='full' 일 때만 생성(휴면).

# |delta| 가 이 값 이하면 "유지"로 본다 (프론트 maintainBand=2 와 맞춤).
_MAINTAIN_BAND = 2


def _status_ko(delta: Optional[float]) -> str:
    if delta is None:
        return "비교불가"
    if delta > _MAINTAIN_BAND:
        return "개선"
    if delta < -_MAINTAIN_BAND:
        return "악화"
    return "유지"


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _groups_by_key(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    overall = report.get("overall") or {}
    return {
        g["key"]: g
        for g in (overall.get("group_scores") or [])
        if isinstance(g, dict) and isinstance(g.get("key"), str) and g.get("key")
    }


def _joints_by_key(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        j["key"]: j
        for j in (report.get("joints") or [])
        if isinstance(j, dict) and isinstance(j.get("key"), str) and j.get("key")
    }


def _compare_joints(
    current: Dict[str, Any], previous: Dict[str, Any], part_keys: set
) -> List[Dict[str, Any]]:
    """관절별 '기준과의 차이' 변화. 차이 절대값이 줄면(gap_narrowed>0) 프로에 가까워진 것."""
    prev = _joints_by_key(previous)
    out = []
    for key, j in _joints_by_key(current).items():
        if j.get("reliability") == "low" or not j.get("available") or j.get("body_part") not in part_keys:
            continue
        cur_diff = _num((j.get("impact") or {}).get("diff"))
        p = prev.get(key)
        prev_diff = _num((p.get("impact") or {}).get("diff")) if p else None
        gap_narrowed = (
            round(abs(prev_diff) - abs(cur_diff), 1)
            if cur_diff is not None and prev_diff is not None
            else None
        )
        out.append(
            {
                "key": key,
                "name": j.get("name"),
                "body_part": j.get("body_part"),
                "current_diff": cur_diff,
                "previous_diff": prev_diff,
                "gap_narrowed": gap_narrowed,  # +면 프로에 가까워짐=개선, −면 멀어짐=악화
            }
        )
    return out


def _compare_phases(current: Dict[str, Any], previous: Dict[str, Any]) -> List[Dict[str, Any]]:
    """구간 점수의 이전 대비 변화."""
    prev = {
        p["key"]: p
        for p in ((previous.get("phases") or {}).get("phases") or [])
        if isinstance(p, dict) and isinstance(p.get("key"), str) and p.get("key")
    }
    out = []
    for p in ((current.get("phases") or {}).get("phases") or []):
        if not isinstance(p, dict) or not p.get("key"):
            continue
        if not p.get("available") or p.get("reliability") == "low":
            continue
        cur_score = _num(p.get("score"))
        pp = prev.get(p["key"])
        prev_score = _num(pp.get("score")) if pp and pp.get("available") is not False else None
        delta = round(cur_score - prev_score, 1) if cur_score is not None and prev_score is not None else None
        # 그 구간에서 기준과 가장 벌어진 관절(현재 스윙 기준) → "팔/하체 중 뭐가 문제"의 근거.
        devs = p.get("top_deviations") or []
        top = devs[0] if devs else None
        out.append(
            {
                "key": p["key"],
                "name": p.get("name"),
                "current_score": cur_score,
                "previous_score": prev_score,
                "delta": delta,
                "status": _status_ko(delta),
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
        )
    return out


def build_comparison_input(
    current: Dict[str, Any], previous: Dict[str, Any], *, scope: str = "overall"
) -> Dict[str, Any]:
    """현재 vs 직전 리포트 → 비교 코칭용 압축 구조.

    부위 점수 delta(메인)와, scope='full' 이면 관절 diff 변화·구간 점수 delta(근거)를 담는다.
    신뢰도 낮은 부위/관절은 뺀다(프론트와 동일 기준).
    """
    cur_overall = current.get("overall") or {}
    prev_overall = previous.get("overall") or {}
    prev_groups = _groups_by_key(previous)

    parts = []
    part_keys = set()
    for key, g in _groups_by_key(current).items():
        if not g.get("available") or g.get("reliability") == "low":
            continue
        part_keys.add(key)
        cur_score = _num(g.get("score"))
        pg = prev_groups.get(key)
        prev_score = _num(pg.get("score")) if pg and pg.get("available") is not False else None
        delta = round(cur_score - prev_score, 1) if cur_score is not None and prev_score is not None else None
        parts.append(
            {
                "key": key,
                "name": g.get("name"),
                "current_score": cur_score,
                "previous_score": prev_score,
                "delta": delta,
                "status": _status_ko(delta),
            }
        )

    cur_total, prev_total = _num(cur_overall.get("score")), _num(prev_overall.get("score"))
    payload: Dict[str, Any] = {
        "overall": {
            "current_score": cur_total,
            "previous_score": prev_total,
            "delta": round(cur_total - prev_total, 1) if cur_total is not None and prev_total is not None else None,
        },
        "parts": parts,
    }
    if scope == "full":
        payload["joints"] = _compare_joints(current, previous, part_keys)
        payload["phases"] = _compare_phases(current, previous)
    return payload


COMPARISON_SYSTEM_INSTRUCTION = """\
너는 야구 타격 스윙을 지도하는 전문 코치다. 선수의 이번 스윙을 '지난 스윙'과 비교한
데이터를 받아서, 무엇이 좋아지고 나빠졌는지 한국어 코칭을 만든다.

규칙:
- 반드시 한국어. 따뜻하지만 군더더기 없는 코치 말투(존댓말).
- '잘함/개선필요'(프로 기준)가 아니라 **지난 스윙 대비** 관점으로 쓴다.
- status 가 '개선'이면 좋아진 점을, '악화'면 나빠진 점을, '유지'면 비슷함을 말한다.
  점수 변화(예: 60→64)와 수치를 근거로 구체적으로. 데이터에 없는 내용은 지어내지 않는다.
- parts: status 가 '개선'인 부위는 keep_points(유지), '악화'/'유지'인 부위는 improve_points 를
  1~2개. 각 point 는 한 문장, 부위당 합쳐 최대 3개. summary 는 그 부위의 이전 대비 변화 1~2문장.
- overall_summary 는 전체가 지난 스윙 대비 어떻게 변했는지 2~3문장, overall_coach 는
  지난번보다 특히 신경 쓰면 좋을 핵심 한 가지를 짧게.
- 입력으로 받은 부위(key)에 대해서만 쓴다. 없는 부위를 만들지 않는다.
"""


COMPARISON_FULL_INSTRUCTION = """\

추가로 joints, phases 도 채운다:
- joints: 각 관절이 지난 스윙 대비 기준(프로)에 더 가까워졌는지 1~2문장.
  gap_narrowed 가 +면 프로에 가까워짐(개선), −면 멀어짐(악화)이다.
- phases: 입력으로 받은 구간(key)마다 아래 3가지를 '지난 스윙 대비' 관점으로 모두 채운다.
  근거는 delta(점수 변화)·status 와 그 구간에서 가장 벌어진 관절(top_deviation).
  top_deviation 의 관절 이름으로 어느 부위(예: 팔/하체)가 불안정한지 말하고,
  입력에 없는 부위는 지어내지 않는다.
  - card_line: 구간 카드용 짧은 한 줄. 개선/악화/유지 상태 중심, 부드러운 "~해요" 말투.
  - comment: 지난 스윙 대비 무엇이 좋아지거나 나빠졌는지(delta·top_deviation 근거) 1~2문장.
  - tip: 그 구간을 위한 실천 팁 한 문장.
- 입력에 없는 관절·구간 key 는 만들지 않는다.
"""


def generate_comparison_coaching(
    current: Dict[str, Any],
    previous: Dict[str, Any],
    *,
    api_key: str,
    model: str,
    scope: str = "overall",
    timeout_s: float = 30.0,
) -> Optional[Dict[str, Any]]:
    """현재 리포트를 직전 리포트와 비교한 '이전 대비' 코칭 dict. 실패하면 ``None``.

    출력 형태는 `generate_coaching` 과 같다(overall + parts, scope='full' 이면 +joints/phases).
    단 내용이 '지난 스윙 대비 개선/악화' 관점이다.
    """
    if not api_key:
        return None

    full = scope == "full"
    payload = build_comparison_input(current, previous, scope=scope)
    if not payload.get("parts"):
        return None

    schema = CoachingFull if full else Coaching
    system_instruction = COMPARISON_SYSTEM_INSTRUCTION + (COMPARISON_FULL_INSTRUCTION if full else "")

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
            logger.warning("Gemini 비교 코칭 응답을 파싱하지 못했습니다.")
            return None
        return parsed.model_dump()
    except Exception:
        logger.exception("Gemini 비교 코칭 생성 실패 — 폴백으로 넘어갑니다.")
        return None
