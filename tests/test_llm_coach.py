"""llm_coach 의 입력 압축과 실패 폴백을 네트워크 없이 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

from feedback.llm_coach import GOOD_SCORE, build_llm_input, generate_coaching

FIXTURE = Path(__file__).resolve().parent.parent / "api" / "fixtures" / "analysis_sample.json"


def _report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_build_llm_input_summarizes_parts():
    payload = build_llm_input(_report())

    assert payload["overall_score"] is not None
    assert payload["parts"], "믿을 만한 부위가 하나 이상 있어야 한다"

    for part in payload["parts"]:
        assert part["key"]
        assert part["status"] in ("잘함", "개선필요")
        # status 는 GOOD_SCORE 기준과 일치해야 한다.
        if part["score"] is not None:
            expected = "잘함" if part["score"] >= GOOD_SCORE else "개선필요"
            assert part["status"] == expected


def test_build_llm_input_drops_low_reliability():
    report = _report()
    # 모든 부위를 신뢰도 low 로 만들면 추려낸 부위가 없어야 한다.
    for group in report["overall"]["group_scores"]:
        group["reliability"] = "low"

    assert build_llm_input(report)["parts"] == []


def test_generate_coaching_without_key_returns_none():
    # 키가 없으면 네트워크를 타지 않고 바로 None.
    assert generate_coaching(_report(), api_key="", model="gemini-3.8-flash") is None


def test_generate_coaching_no_parts_returns_none():
    report = _report()
    report["overall"]["group_scores"] = []
    report["joints"] = []
    # 믿을 부위가 없으면 키가 있어도 LLM 을 부르지 않는다.
    assert generate_coaching(report, api_key="fake-key", model="gemini-3.8-flash") is None


# ---------------------------------------------------------------------------
# scope='full' (관절/구간까지) — 유료 전환 후 켤 휴면 기능. 네트워크 없이 입력/스키마만 검증.
# ---------------------------------------------------------------------------
def test_overall_scope_omits_joints_and_phases():
    payload = build_llm_input(_report(), scope="overall")
    assert "joints" not in payload
    assert "phases" not in payload


def test_full_scope_includes_joints_and_phases():
    payload = build_llm_input(_report(), scope="full")

    assert payload["joints"], "믿을 만한 관절이 하나 이상 있어야 한다"
    assert payload["phases"], "분석된 구간이 하나 이상 있어야 한다"

    # 관절은 key 를 반드시 포함해야 출력과 매핑된다.
    for joint in payload["joints"]:
        assert joint["key"]
    for phase in payload["phases"]:
        assert phase["key"]


def test_full_scope_joints_match_reliable_parts():
    payload = build_llm_input(_report(), scope="full")
    part_keys = {p["key"] for p in payload["parts"]}
    # 관절은 추려진 부위(신뢰도 ok)에 속한 것만 들어간다.
    for joint in payload["joints"]:
        assert joint["body_part"] in part_keys


def test_full_scope_drops_low_reliability_phases():
    report = _report()
    for phase in report["phases"]["phases"]:
        phase["reliability"] = "low"
    assert build_llm_input(report, scope="full")["phases"] == []


def test_coaching_full_schema_shape():
    # 확장 스키마가 joints/phases 를 요구하는지 확인 (Gemini response_schema 로 쓰임).
    from feedback.llm_coach import CoachingFull

    fields = CoachingFull.model_fields
    assert "joints" in fields
    assert "phases" in fields
    assert "overall_summary" in fields  # 기본 필드 상속
