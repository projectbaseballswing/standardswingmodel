"""llm_coach 의 입력 압축과 실패 폴백을 네트워크 없이 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import copy

from feedback.llm_coach import (
    GOOD_SCORE,
    build_comparison_input,
    build_llm_input,
    generate_coaching,
    generate_comparison_coaching,
)

FIXTURE = Path(__file__).resolve().parent.parent / "api" / "fixtures" / "analysis_sample.json"


def _report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _worse_previous(current: dict) -> dict:
    """현재보다 점수가 낮고 기준과 더 벌어진 '직전' 리포트를 만든다 → 현재가 '개선'으로 나와야 한다."""
    prev = copy.deepcopy(current)
    prev["overall"]["score"] = (current["overall"]["score"] or 0) - 10
    for g in prev["overall"].get("group_scores") or []:
        if isinstance(g.get("score"), (int, float)):
            g["score"] = g["score"] - 8
    for j in prev.get("joints") or []:
        impact = j.get("impact") or {}
        if isinstance(impact.get("diff"), (int, float)):
            impact["diff"] = impact["diff"] * 2  # 기준과 더 벌어짐
    for p in (prev.get("phases") or {}).get("phases") or []:
        if isinstance(p.get("score"), (int, float)):
            p["score"] = p["score"] - 10
    return prev


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


def test_phase_coaching_has_card_line_comment_tip():
    # 구간 코칭은 카드 짧은 줄 + 상세 서술 + 실천 팁 3종을 요구한다(목업 1:1).
    from feedback.llm_coach import PhaseCoaching

    fields = PhaseCoaching.model_fields
    assert {"key", "card_line", "comment", "tip"} <= set(fields)


# ---------------------------------------------------------------------------
# 비교(이전 대비) 코칭 — 네트워크 없이 입력/단락만 검증
# ---------------------------------------------------------------------------
def test_comparison_input_part_deltas_and_status():
    current = _report()
    prev = _worse_previous(current)
    payload = build_comparison_input(current, prev, scope="overall")

    assert payload["overall"]["delta"] == 10.0  # 현재가 10점 높음
    assert payload["parts"], "비교할 부위가 있어야 한다"
    for part in payload["parts"]:
        assert part["previous_score"] is not None
        assert part["delta"] == round(part["current_score"] - part["previous_score"], 1)
        # 이전이 8점 낮으므로 전부 '개선'(delta>2).
        assert part["status"] == "개선"
    # overall scope 는 관절/구간을 넣지 않는다.
    assert "joints" not in payload and "phases" not in payload


def test_comparison_input_full_includes_joints_and_phases():
    current = _report()
    prev = _worse_previous(current)
    payload = build_comparison_input(current, prev, scope="full")

    assert payload["joints"], "관절 비교가 있어야 한다"
    assert payload["phases"], "구간 비교가 있어야 한다"
    # 이전 diff를 2배로 벌려놨으니 현재가 프로에 더 가까움 → gap_narrowed > 0.
    narrowed = [j["gap_narrowed"] for j in payload["joints"] if j["gap_narrowed"] is not None]
    assert narrowed and all(v > 0 for v in narrowed)
    # 구간 점수는 이전이 10점 낮으므로 '개선'.
    for ph in payload["phases"]:
        if ph["delta"] is not None:
            assert ph["status"] == "개선"
    # 구간마다 '가장 벌어진 관절'(top_deviation)이 입력에 실려야 부위를 콕 집어 말할 수 있다.
    assert any(ph.get("top_deviation") for ph in payload["phases"])
    for ph in payload["phases"]:
        top = ph.get("top_deviation")
        if top is not None:
            assert top["name"] and "diff" in top and "direction" in top


def test_comparison_input_missing_previous_part_gives_null_delta():
    current = _report()
    prev = _worse_previous(current)
    # 이전에서 한 부위를 통째로 제거 → 그 부위는 previous_score/delta null, status 비교불가.
    prev["overall"]["group_scores"] = [
        g for g in prev["overall"]["group_scores"] if g.get("key") != "torso"
    ]
    payload = build_comparison_input(current, prev, scope="overall")
    torso = next((p for p in payload["parts"] if p["key"] == "torso"), None)
    if torso is not None:  # torso 가 현재 신뢰도 ok일 때만 검증
        assert torso["previous_score"] is None
        assert torso["delta"] is None
        assert torso["status"] == "비교불가"


def test_generate_comparison_coaching_without_key_returns_none():
    current = _report()
    assert generate_comparison_coaching(
        current, _worse_previous(current), api_key="", model="gemini-flash-lite-latest"
    ) is None
