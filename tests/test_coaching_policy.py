"""Policy checks use supplied dicts only; no model, API, DB, or credentials."""
import copy
import json
from pathlib import Path

import pytest

from feedback.coaching_policy import validate_coaching_output


def payload():
    return {
        "allowed": {"parts": ["lead_arm", "torso", "lead_leg", "rear_leg"], "joints": ["hand_y_from_shoulder"], "phases": ["stride"]},
        "score_basis": {"overall_score": 67.3, "posture_score": 80.4, "speed_score": 36.6,
                        "verified_composition": True, "weights": {"posture": .7, "speed": .3}},
        "comparison": {"available": False},
        "excluded": [{"kind": "joint", "key": "rear_elbow_angle", "name": "뒷팔 팔꿈치 각도", "reason": "low"}],
    }


def coaching():
    return {"overall_summary": "스트라이드 구간의 손 높이 차이를 확인해 보세요.",
            "overall_coach": "원본에서 해당 구간의 손 위치를 확인하세요.",
            "coach_feedback": {"problem": "손이 기준보다 낮게 측정됐어요.",
                               "cause": "현재 분석만으로 원인을 확인하기 어렵습니다.",
                               "fix": "차이가 실제로 보이면 편안한 범위에서 조금 조절해 보세요.",
                               "drill": "배트 없이 앞발을 옮긴 뒤 멈춰 촬영하는 일반적인 연습 제안입니다."},
            "parts": [{"key": "lead_arm", "summary": "손 높이를 원본에서 확인하세요.",
                       "keep_points": [], "improve_points": ["스트라이드 구간을 확인하세요."]}]}


def codes(result):return {f["code"] for f in result["findings"]}


def test_schema_compliance_does_not_certify_accuracy_or_mutate_response():
    c, p = coaching(), payload(); before = copy.deepcopy((c, p))
    result = validate_coaching_output(c, p)
    assert result["status"] == "review_required" and result["schema_valid"]
    assert result["blocking_count"] == 0
    assert not result["auto_publish_allowed"] and not result["semantic_accuracy_verified"]
    assert (c, p) == before


@pytest.mark.parametrize("change,code", [
    ("unknown", "unknown_key"), ("duplicate", "duplicate_key"),
    ("points", "part_point_limit"), ("schema", "schema_error"),
    ("extra", "unexpected_field"), ("nested_extra", "unexpected_field"),
])
def test_hard_constraints(change, code):
    c = coaching()
    if change == "unknown": c["parts"][0]["key"] = "rear_arm"
    if change == "duplicate": c["parts"].append(copy.deepcopy(c["parts"][0]))
    if change == "points": c["parts"][0]["keep_points"] = ["a", "b", "c"]
    if change == "schema": c["coach_feedback"]["problem"] = 42
    if change == "extra": c["joints"] = []
    if change == "nested_extra": c["parts"][0]["score"] = 99
    result = validate_coaching_output(c, payload())
    assert result["status"] == "blocked" and code in codes(result)


def test_full_and_extended_key_allowlists():
    c = coaching(); c.update(joints=[{"key": "hand_y_from_shoulder", "comment": "손 높이 확인"}],
                            phases=[{"key": "stride", "card_line": "앞발 이동", "comment": "원본 확인", "tip": "천천히 재현"}])
    assert validate_coaching_output(c, payload(), scope="full")["blocking_count"] == 0
    c["joints"][0]["key"] = "rear_elbow_angle"
    result = validate_coaching_output({"joints": c["joints"], "phases": c["phases"]}, payload(), extended=True)
    assert result["status"] == "blocked" and "unknown_key" in codes(result)


@pytest.mark.parametrize("text,code", [
    ("공을 보려는 동안 머리가 흔들리기 때문일 수 있어요.", "unmeasured_head_or_gaze"),
    ("골반이 먼저 돌고 어깨가 이어서 돌아가고 있어요.", "unmeasured_rotation_order"),
    ("다리의 힘이 풀리기 때문이에요.", "unsupported_causality"),
    ("체중 이동과 지면 반력이 좋아요.", "unmeasured_force_or_weight"),
    ("배트 궤적이 좋아요.", "unmeasured_bat_or_ball_path"),
    ("지난 스윙보다 자세가 좋아졌어요.", "history_without_comparison"),
    ("자세 점수는 50점이에요.", "score_value_conflict"),
    ("자세 60%와 속도 40%로 계산돼요.", "score_formula_conflict"),
    ("자세 80.4점의 60%와 속도 36.6점의 40%로 계산돼요.", "score_formula_conflict"),
    ("뒷팔 팔꿈치 각도를 펴 보세요.", "excluded_item_in_text"),
    ("지금의 리듬을 유지해 주세요.", "tempo_claim_review"),
])
def test_semantic_patterns_are_review_hints_not_proofs(text, code):
    c = coaching(); c["overall_summary"] = text
    result = validate_coaching_output(c, payload())
    assert result["status"] == "review_required" and code in codes(result)
    assert not result["semantic_accuracy_verified"]


def test_explicit_unmeasured_disclaimer_is_not_treated_as_diagnosis():
    c = coaching(); c["overall_summary"] = "머리와 시선은 측정하지 않았습니다. 현재 분석만으로 원인을 확인하기 어렵습니다."
    result = validate_coaching_output(c, payload())
    assert "unmeasured_head_or_gaze" not in codes(result)
    assert "unsupported_causality" not in codes(result)
    assert result["status"] == "review_required"


def test_verified_score_explanation_and_real_history_not_false_conflicts():
    c = coaching(); c["overall_summary"] = "자세 80.4점 × 70%와 속도 36.6점 × 30%를 합쳐 종합 67.3점입니다. 지난 스윙보다 점수가 좋아졌어요."
    p = payload(); p["comparison"]["available"] = True
    result = validate_coaching_output(c, p)
    assert not {"score_value_conflict", "score_formula_conflict", "history_without_comparison"} & codes(result)
    assert result["status"] == "review_required"


def test_absent_formula_does_not_allow_unverified_percentage():
    c = coaching(); c["overall_summary"] = "자세 70%와 속도 30%로 계산해요."
    p = payload(); p["score_basis"]["verified_composition"] = False
    assert "score_formula_conflict" in codes(validate_coaching_output(c, p))


def test_stage3b_saved_response_violations_and_preservation():
    path = Path(__file__).resolve().parents[2] / "swing-feedback-stage3b/.local/feedback-stage3b/current-run/coaching.json"
    if not path.exists(): pytest.skip("Local stage-3B actual response is not part of the repository")
    original = path.read_bytes(); c = json.loads(original); before = copy.deepcopy(c)
    result = validate_coaching_output(c, payload())
    assert result["status"] == "blocked" and result["schema_valid"]
    assert {"part_point_limit", "unmeasured_head_or_gaze", "unmeasured_rotation_order", "unsupported_causality", "tempo_claim_review"} <= codes(result)
    assert c == before and path.read_bytes() == original


@pytest.mark.parametrize("text", [
    "손 속도 점수는 배트나 타구 속도를 뜻하지 않습니다.",
    "배트 속도나 타구 속도를 측정한 결과가 아닙니다.",
    "머리와 시선은 측정하지 않았습니다.",
    "회전 시작 순서는 현재 분석만으로 확인할 수 없습니다.",
])
def test_local_negation_does_not_flag_unmeasured_diagnosis(text):
    c=coaching();c["overall_summary"]=text
    result=validate_coaching_output(c,payload())
    assert not any(x.startswith("unmeasured_") for x in codes(result))
    assert result["status"]=="review_required"


@pytest.mark.parametrize("text,code", [
    ("시선은 측정하지 않았지만 머리가 흔들리고 있어요.", "unmeasured_head_or_gaze"),
    ("배트 속도를 뜻하지 않습니다. 그러나 배트 궤적이 좋습니다.", "unmeasured_bat_or_ball_path"),
    ("힘은 측정하지 않았고 지지력이 좋아졌습니다.", "unmeasured_force_or_weight"),
    ("원인은 확인할 수 없지만 체중 이동 때문입니다.", "unsupported_causality"),
])
def test_disclaimer_does_not_whitelist_later_positive_claim(text,code):
    c=coaching();c["overall_summary"]=text
    assert code in codes(validate_coaching_output(c,payload()))


def test_comparison_not_provided_is_not_record_absence():
    c=coaching();p=payload();p["comparison"]={"available":False,"reason":"previous_report_not_provided"}
    c["overall_summary"]="이전 기록이 없어 개선·악화는 판단할 수 없습니다."
    assert "history_absence_not_confirmed" in codes(validate_coaching_output(c,p))
    c["overall_summary"]="이번 분석에 이전 비교가 제공되지 않아 개선·악화는 판단할 수 없습니다."
    assert "history_absence_not_confirmed" not in codes(validate_coaching_output(c,p))
    c["overall_summary"]="비교 미제공은 이전 기록이 없다는 뜻이 아닙니다."
    assert "history_absence_not_confirmed" not in codes(validate_coaching_output(c,p))
    c["overall_summary"]="이전 기록이 없습니다."
    p["comparison"]["absence_confirmed"]=True
    assert "history_absence_not_confirmed" not in codes(validate_coaching_output(c,p))


def test_mean_to_exact_target_drill_is_reviewed_not_certified():
    c=coaching();c["coach_feedback"]["drill"]="손이 기준 위치에 도달한 순간 멈춰 촬영하세요."
    assert "average_as_exact_target" in codes(validate_coaching_output(c,payload()))
    c["coach_feedback"]["drill"]="구간 평균은 정확히 맞춰야 할 목표 자세가 아닙니다. 구간을 천천히 재현해 확인하세요."
    assert "average_as_exact_target" not in codes(validate_coaching_output(c,payload()))


def test_normalized_body_values_are_not_confused_with_scores():
    p=payload();p["observations"]=[{"part":"lead_arm","name":"손 높이","unit":"body","level":"warning","phase":"stride","phase_name":"스트라이드"}]
    c=coaching();c["coach_feedback"]["problem"]="손 높이는 사용자 -0.6, 기준 0.0으로 측정됐습니다."
    assert "normalized_body_value_exposed" in codes(validate_coaching_output(c,p))
    c["coach_feedback"]["problem"]="스트라이드에서 손 높이가 기준보다 낮게 측정됐습니다."
    c["overall_summary"]="자세 80.4점과 속도 36.6점을 반영한 종합 67.3점입니다."
    assert "normalized_body_value_exposed" not in codes(validate_coaching_output(c,p))


def test_praising_part_does_not_hide_other_adverse_phases_without_review():
    p=payload();p["observations"]=[{"part":"rear_leg","name":"뒷다리 무릎 각도","phase":"swing","phase_name":"스윙","level":"caution"}]
    c=coaching();c["parts"]=[{"key":"rear_leg","summary":"스트라이드에서 기준과 비슷합니다.","keep_points":["준비 자세가 비슷합니다."],"improve_points":[]}]
    result=validate_coaching_output(c,p)
    assert "part_adverse_phase_omitted" in codes(result)
    assert result["blocking_count"]==0 and result["status"]=="review_required"
    c["parts"][0]["summary"]+=" 다만 스윙 구간의 무릎 차이를 확인해야 합니다."
    assert "part_adverse_phase_omitted" not in codes(validate_coaching_output(c,p))


def test_stage3d_actual_B_is_preserved_and_previously_missed_issues_are_reviewed():
    root=Path(__file__).resolve().parents[2]/"swing-feedback-stage3d/.local/feedback-stage3d/b-run"
    if not root.exists():pytest.skip("Local stage-3D actual response is not part of the repository")
    files=[root/"coaching.json",root/"candidate-input.json"]
    before=[x.read_bytes() for x in files];c,p=map(json.loads,before)
    result=validate_coaching_output(c,p)
    found=codes(result)
    assert result["status"]=="review_required" and result["blocking_count"]==0
    assert "unmeasured_bat_or_ball_path" not in found
    assert {"history_absence_not_confirmed","average_as_exact_target","normalized_body_value_exposed","part_adverse_phase_omitted"}<=found
    assert [x.read_bytes() for x in files]==before


def test_comparison_uses_canonical_measurements_but_actual_history_state():
    evidence=payload();evidence["observations"]=[{"part":"lead_arm","name":"손 높이","unit":"body","phase":"stride","phase_name":"스트라이드","level":"warning"}]
    p={"allowed":evidence["allowed"],"canonical_evidence":evidence,"comparison":{"available":True}}
    c=coaching();c["overall_summary"]="지난 스윙보다 점수가 좋아졌어요."
    c["coach_feedback"]["problem"]="손 높이는 사용자 -0.6, 기준 0.0입니다."
    found=codes(validate_coaching_output(c,p))
    assert "normalized_body_value_exposed" in found
    assert "history_without_comparison" not in found
