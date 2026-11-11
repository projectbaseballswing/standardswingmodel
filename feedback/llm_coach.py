"""LLM(OpenAI) 기반 코칭 문장 생성.

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
# 출력 스키마 (OpenAI 가 이 모양의 JSON 만 돌려주도록 강제)
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


class CoachFeedback(BaseModel):
    """'AI 코치의 한마디'를 문제→원인→교정→추천훈련 4단으로 펼친 것."""

    problem: str  # 무엇이 아쉬운지 (부위 이름 넣어 쉬운 말로 1~2문장)
    cause: str  # 왜 그런지 (스윙 메커니즘 측면의 원인 1~2문장)
    fix: str  # 어떻게 고치면 되는지 (교정 포인트 1~2문장)
    drill: str  # 그에 맞는 추천 훈련(드릴) 한 가지 (이름 + 하는 방법 한두 문장)


class Coaching(BaseModel):
    overall_summary: str  # 스윙 전체를 2~3문장으로 요약
    overall_coach: str  # 가장 먼저 고치면 좋을 핵심 한 가지(짧은 헤드라인)
    coach_feedback: CoachFeedback  # 위 핵심 한 가지를 문제/원인/교정/추천훈련으로 펼친 것
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
                "direction": p.get("direction_text") or _direction_ko(p.get("direction", "")),
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
                "direction": top.get("direction_text") or _direction_ko(top.get("direction", "")),
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
        # 몸통 회전 확인. 통과 못 한 것만 넘긴다 (failed). 점수에 반영된 것은 affects_score=true.
        "rotation_issues": [
            {"name": c.get("name"), "message": c.get("message"), "affects_score": c.get("affects_score")}
            for c in overall.get("rotation_checks") or []
            if c.get("passed") is False
        ],
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
# 모든 코칭이 공통으로 지켜야 할 '독자' 규칙. 독자는 아마추어 야구 선수다(개발자가 아니다).
AUDIENCE_RULES = """\
독자는 취미로 야구를 하는 아마추어 선수다. 데이터 분석가나 개발자가 아니다.
- 반드시 한국어. 코치가 선수에게 말하듯 따뜻하고 쉽게, 존댓말로.
- 분석·개발 용어를 절대 쓰지 마라: '편차', '표준편차', 'z점수', 'z-score', '수치',
  '신뢰도', '입력(된)', 'range_of_motion', 'impact', 'diff', 'top_deviation' 등
  데이터 필드 이름이나 통계 용어. 선수가 들어본 적 없는 말은 금지.
- 부위·관절은 반드시 실제 이름으로 부른다(예: 몸통, 오른쪽 팔, 왼쪽 팔, 왼쪽 다리,
  오른쪽 다리, 앞팔꿈치). '입력된 네 부위', '측정된 부위들'처럼 개수로 뭉뚱그리지 말고
  이름을 직접 말해라. 예: "네 부위가 모두 개선됐고"(X) →
  "왼쪽 팔, 오른쪽 팔, 몸통, 왼쪽 다리가 모두 좋아졌고"(O).
- 각도·거리의 숫자(예: 10.0→6.9, 편차 12도)를 그대로 나열하지 마라. 그 숫자가 뜻하는
  것을 말로 풀어라. 예: "무릎 각도 편차가 10.0에서 6.9로 줄었다"(X) →
  "뒷다리 무릎이 기준 자세에 더 가까워졌어요"(O).
- 점수 숫자(예: 66.7→81.8)는 화면에 이미 크게 보이므로 그대로 반복하지 마라. 숫자 대신
  무엇이 좋아졌고 무엇을 더 다듬으면 좋은지를 말해라. (단 '상승/개선 필요' 같은 상태 표현은 좋다.)
"""


SYSTEM_INSTRUCTION = (
    """\
너는 야구 타격 스윙을 지도하는 전문 코치다. 선수의 스윙을 프로 기준과 비교한 분석
데이터를 받아서, 선수가 바로 이해하고 실천할 수 있는 한국어 코칭을 만든다.

"""
    + AUDIENCE_RULES
    + """
규칙:
- 데이터에 없는 내용은 지어내지 않는다. 단 숫자는 위 규칙대로 말로 풀어서 전한다.
- status 가 '잘함'인 부위는 keep_points 를 채우고 improve_points 는 비워도 된다.
  status 가 '개선필요'인 부위는 improve_points 를 1~2개 채운다.
- 각 point 는 한 문장. 부위당 keep/improve 합쳐 최대 3개.
- summary 는 그 부위 상태를 1~2문장으로, 부위 이름을 넣어서.
- overall_summary 는 스윙 전체를 2~3문장으로(어느 부위가 좋고 어디를 다듬으면 좋은지),
  overall_coach 는 가장 먼저 고치면 좋을 핵심 한 가지를 짧은 한 줄로.
- coach_feedback 은 overall_coach 로 고른 그 '핵심 한 가지'를 네 단계로 풀어 쓴다(아마추어
  선수가 바로 따라 할 수 있게, 위 독자 규칙 그대로):
  - problem: 무엇이 아쉬운지. 가장 개선이 필요한 부위를 이름으로 짚어 1~2문장.
  - cause: 왜 그런지. 그 문제를 만드는 스윙 동작(예: 체중 이동, 손목·팔 각도, 회전 타이밍)을
    쉬운 말로 1~2문장. 확실하지 않으면 단정하지 말고 "~때문일 수 있어요".
  - fix: 어떻게 고치면 되는지. 구체적인 교정 포인트 1~2문장.
  - drill: 그 교정을 익히는 추천 훈련(드릴) 한 가지. 드릴 이름과 하는 방법을 한두 문장으로.
    드릴은 일반적인 야구 타격 코칭 지식에서 가져와도 된다(데이터에 없어도 됨). 단 problem·
    fix 와 맞아떨어지는 것으로 고른다.
- 입력으로 받은 부위(key)에 대해서만 쓴다. 없는 부위를 만들지 않는다.
- rotation_issues 는 착지부터 임팩트까지 몸통 회전에서 걸린 항목이다. 있으면 몸통(torso)
  부위 improve_points 에 반영하고, affects_score 가 true 인 항목(몸통이 거의 돌지 않음)은
  가장 먼저 고칠 점이라 overall_coach 로 삼는다.
"""
)


# scope='full' 일 때만 덧붙이는 규칙 (관절별/구간별 서술).
FULL_SCOPE_INSTRUCTION = """\

추가로 joints, phases 도 채운다(위 독자 규칙 그대로: 용어·숫자 나열 금지, 부위 이름 사용):
- joints: 입력으로 받은 관절(key)마다 그 부위가 기준 자세와 어떻게 다른지 쉬운 말로 1~2문장.
  각도 숫자를 나열하지 말고 "팔이 조금 더 펴져 있어요"처럼 느낌으로 풀어라.
- phases: 입력으로 받은 구간(key)마다 아래 3가지를 모두 채운다. 근거는 타이밍과
  그 구간에서 가장 벌어진 관절(top_deviation). 그 관절 이름으로 어느 부위가 아쉬운지
  말하고, 입력에 없는 부위는 지어내지 않는다.
  - card_line: 구간 카드에 들어갈 짧은 한 줄. 상태 중심, 부드러운 "~해요" 말투.
  - comment: 왜 그런지(타이밍·가장 아쉬운 부위) 쉬운 말로 1~2문장.
  - tip: 그 구간을 개선할 실천 팁 한 문장.
- 입력에 없는 관절·구간 key 는 만들지 않는다. 받은 key 에 대해서만 쓴다.
"""


# ---------------------------------------------------------------------------
# OpenAI 호출 (structured outputs 로 Pydantic 스키마 강제)
# ---------------------------------------------------------------------------
def _call_openai(
    *,
    api_key: str,
    model: str,
    system_instruction: str,
    payload: Dict[str, Any],
    schema: type[BaseModel],
    timeout_s: float,
) -> Optional[Dict[str, Any]]:
    """OpenAI chat.completions 로 코칭 JSON 을 받아 dict 로 돌려준다. 실패하면 ``None``.

    ``response_format=schema`` 로 모델이 정확히 그 Pydantic 모양의 JSON 만 내도록 강제한다.
    """
    try:
        import json

        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=timeout_s)
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format=schema,
            # gpt-6-luna 등 일부 모델은 temperature 기본값(1)만 허용한다. 지정하지 않는다.
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            logger.warning("OpenAI 코칭 응답을 파싱하지 못했습니다.")
            return None
        return parsed.model_dump()
    except Exception:
        logger.exception("OpenAI 코칭 생성 실패 — 규칙 기반 폴백으로 넘어갑니다.")
        return None


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

    return _call_openai(
        api_key=api_key,
        model=model,
        system_instruction=system_instruction,
        payload=payload,
        schema=schema,
        timeout_s=timeout_s,
    )


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
                        "direction": top.get("direction_text") or _direction_ko(top.get("direction", "")),
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


COMPARISON_SYSTEM_INSTRUCTION = (
    """\
너는 야구 타격 스윙을 지도하는 전문 코치다. 선수의 이번 스윙을 '지난 스윙'과 비교한
데이터를 받아서, 무엇이 좋아지고 나빠졌는지 한국어 코칭을 만든다.

"""
    + AUDIENCE_RULES
    + """
규칙:
- '잘함/개선필요'(프로 기준)가 아니라 **지난 스윙 대비** 관점으로 쓴다.
- status 가 '개선'이면 좋아진 점을, '악화'면 아쉬운 점을, '유지'면 비슷함을 말한다.
  "상승했어요 / 좋아졌어요 / 비슷해요 / 조금 아쉬워요" 같은 쉬운 상태 표현으로.
  데이터에 없는 내용은 지어내지 않는다.
- parts: status 가 '개선'인 부위는 keep_points(유지), '악화'/'유지'인 부위는 improve_points 를
  1~2개. 각 point 는 한 문장, 부위당 합쳐 최대 3개. summary 는 그 부위(이름 넣어서)의
  이전 대비 변화를 1~2문장으로.
- overall_summary 는 전체가 지난 스윙 대비 어떻게 변했는지 2~3문장. 어느 부위가 좋아졌는지
  이름으로 말하고, 점수 숫자는 반복하지 않는다. overall_coach 는 지난번보다 특히 신경 쓰면
  좋을 핵심 한 가지를 짧은 한 줄로.
- coach_feedback 은 overall_coach 로 고른 '핵심 한 가지'를 네 단계로 풀어 쓴다('지난 스윙 대비'
  관점, 위 독자 규칙 그대로):
  - problem: 지난번보다 아직 아쉽거나 다시 신경 써야 할 점을 부위 이름으로 1~2문장.
  - cause: 왜 그런지(그 동작이 흔들리는 이유)를 쉬운 말로 1~2문장.
  - fix: 다음 스윙에서 어떻게 고치면 되는지 1~2문장.
  - drill: 그 교정을 익히는 추천 훈련(드릴) 한 가지. 이름 + 하는 방법 한두 문장.
    일반적인 야구 타격 코칭 지식에서 가져와도 된다. problem·fix 와 맞는 것으로 고른다.
- 입력으로 받은 부위(key)에 대해서만 쓴다. 없는 부위를 만들지 않는다.
"""
)


COMPARISON_FULL_INSTRUCTION = """\

추가로 joints, phases 도 채운다(위 독자 규칙 그대로: 용어·숫자 나열 금지, 부위 이름 사용):
- joints: 각 관절이 지난 스윙 대비 기준 자세에 더 가까워졌는지 쉬운 말로 1~2문장.
  gap_narrowed 가 +면 기준에 가까워진 것(좋아짐), −면 멀어진 것(아쉬움)이다. 숫자는
  말하지 말고 "더 안정적으로 바뀌었어요"처럼 느낌으로.
- phases: 입력으로 받은 구간(key)마다 아래 3가지를 '지난 스윙 대비' 관점으로 모두 채운다.
  근거는 타이밍 변화·상태(status)와 그 구간에서 가장 아쉬운 관절(top_deviation).
  그 관절 이름으로 어느 부위(예: 팔/다리)가 아쉬운지 말하고, 입력에 없는 부위는
  지어내지 않는다.
  - card_line: 구간 카드용 짧은 한 줄. 좋아짐/아쉬움/비슷함 상태 중심, 부드러운 "~해요" 말투.
  - comment: 지난 스윙 대비 무엇이 좋아지거나 아쉬운지 쉬운 말로 1~2문장.
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

    return _call_openai(
        api_key=api_key,
        model=model,
        system_instruction=system_instruction,
        payload=payload,
        schema=schema,
        timeout_s=timeout_s,
    )
