"""이벤트 기반 비교(0.2)를 스켈레톤 데이터로 직접 검증한다.

사용자 경로에서 '영상 -> 스켈레톤 추출' 단계만 건너뛴다. 그 뒤 과정(이벤트 검출 -> 구간 정규화
-> 기준 모델 비교)은 실제와 같은 코드다. 영상 디코딩과 모델 추론이 없어 빠르다.

스켈레톤(data/skeletons)은 저장소에 없으므로, 없으면 건너뛴다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from api.schemas import AnalysisReport
from feedback.compare_v2 import SwingComparisonV2
from feedback.reference_model import PHASE_EVENTS, load_reference_model

# Independent experiment can read an existing dataset without copying or writing it.
SKELETON_DIR = Path(os.getenv('SWING_TEST_SKELETON_DIR', 'data/skeletons'))


@pytest.fixture(scope="module")
def model():
    reference = load_reference_model()
    if reference is None:
        pytest.skip("기준 모델(data/reference_model.npz)이 없습니다.")
    return reference


@pytest.fixture(scope="module")
def skeleton():
    files = sorted(SKELETON_DIR.glob("*.npz")) if SKELETON_DIR.exists() else []
    if not files:
        pytest.skip("스켈레톤 데이터(data/skeletons)가 없습니다.")
    data = np.load(files[0], allow_pickle=True)
    meta = json.loads(str(data["meta_json"]))
    return data["landmarks_pixel"].astype(float), float(meta["fps"])


def _compare(model, skeleton, **kwargs) -> SwingComparisonV2:
    landmarks, fps = skeleton
    return SwingComparisonV2(model, landmarks, fps, quality={"nan_ratio": 0.0, "joint_visibility": {}}, **kwargs)


def test_report_matches_api_schema(model, skeleton):
    """응답이 API 스키마에 그대로 들어맞아야 한다 (프론트 계약 유지)."""
    report = _compare(model, skeleton).report(include_series=True)
    parsed = AnalysisReport.model_validate(report)
    assert parsed.model_version.startswith("0.2")
    assert parsed.overall.model_version == parsed.model_version


def test_reference_swing_scores_reasonably(model, skeleton):
    """기준 모델을 만든 스윙 중 하나이므로 점수가 지나치게 낮으면 안 된다."""
    overall = _compare(model, skeleton).overall()
    assert overall["available"] is True
    assert overall["score"] is not None and overall["score"] >= 50
    assert overall["distance"] is not None


def test_speed_metrics_are_filled(model, skeleton):
    """0.1 에서 비어 있던 속도 지표가 0.2 에서는 값을 가진다."""
    speed = _compare(model, skeleton).speed_feedback()
    assert speed["available"] is True
    filled = [m for m in speed["metrics"] if m["available"]]
    assert filled, "속도 지표가 하나도 채워지지 않았습니다."
    for metric in filled:
        assert metric["user"] is not None and metric["reference"] is not None


def test_phase_durations_are_compared_in_time(model, skeleton):
    """구간 길이를 실제 시간(ms)으로 비교한다. 0.1 은 DTW 때문에 항상 1.0 에 붙어 있었다."""
    phases = _compare(model, skeleton).phases()
    measured = [p for p in phases["phases"] if p["available"]]
    assert measured
    for phase in measured:
        assert phase["user_duration_ms"] is not None
        assert phase["reference_duration_ms"] is not None
        assert phase["tempo_ratio"] is not None
    assert set(phases["events"]) >= {"foot_plant", "swing_start", "follow_end"}


def test_missing_phase_is_marked_unavailable(model, skeleton):
    """스윙 뒷부분만 남기면 앞 구간은 '분석 불가'로 내려가야 한다 (복사 프레임으로 채우지 않는다)."""
    landmarks, fps = skeleton
    impact = _compare(model, skeleton).events.impact
    comparison = SwingComparisonV2(                       # 임팩트 앞뒤만 남겨 앞 구간을 잘라낸다
        model, landmarks, fps,
        quality={"nan_ratio": 0.0, "joint_visibility": {}},
        clip_start=max(0, impact - 6),
        clip_end=impact + 3,
    )
    phases = {p["key"]: p for p in comparison.phases()["phases"]}
    assert set(phases) == set(PHASE_EVENTS)
    unavailable = [p for p in phases.values() if not p["available"]]
    assert unavailable, "앞 구간이 잘렸는데도 모두 분석 가능으로 나왔습니다."
    for phase in unavailable:
        assert phase["unavailable_reason"]
        assert phase["user_duration_ms"] is None
    # 분석 불가 구간이 있어도 신뢰도만 낮아질 뿐 전체 응답은 유효해야 한다
    AnalysisReport.model_validate(comparison.report())
    assert comparison.reliability in ("low", "medium")


def test_report_survives_joint_missing_whole_video(model, skeleton):
    """관절 하나가 영상 내내 1프레임만 잡혀도 분석이 실패하지 않고, 그 항목만 측정 불가로 내려간다."""
    landmarks, fps = skeleton
    broken = landmarks.copy()
    broken[1:, 2, :] = np.nan  # 앞 팔꿈치
    comparison = SwingComparisonV2(model, broken, fps, quality={"nan_ratio": 0.0, "joint_visibility": {}})
    report = comparison.report(include_series=True)
    AnalysisReport.model_validate(report)

    elbow = next(j for j in report["joints"] if j["key"] == "lead_elbow_angle")
    assert elbow["available"] is False
    assert report["overall"]["score"] is not None
    assert any("앞팔 팔꿈치" in w for w in report["overall"]["quality"]["warnings"])


def _world_with_depth_scale(landmarks, depth_scale):
    """x, y 는 그대로 두고 z 만 배율을 바꾼 가짜 월드 좌표. 이미지 z -> 월드 z 배율이 depth_scale 이 된다."""
    world = landmarks.copy()
    world[..., 2] *= depth_scale
    return world


def test_depth_check_keeps_elbows_when_scale_is_normal(model, skeleton):
    landmarks, fps = skeleton
    comparison = SwingComparisonV2(model, landmarks, fps, world_landmarks=_world_with_depth_scale(landmarks, 0.30))
    report = comparison.report()
    assert report["overall"]["quality"]["depth_scale"] == pytest.approx(0.30, abs=0.01)
    elbow = next(j for j in report["joints"] if j["key"] == "lead_elbow_angle")
    assert elbow["available"] is True


def test_depth_check_drops_elbows_when_scale_is_abnormal(model, skeleton):
    """배율이 프로 범위 밖이면 팔꿈치 각도만 측정 불가로 빼고, 나머지는 그대로 분석한다."""
    landmarks, fps = skeleton
    comparison = SwingComparisonV2(model, landmarks, fps, world_landmarks=_world_with_depth_scale(landmarks, 1.0))
    report = comparison.report(include_series=True)
    AnalysisReport.model_validate(report)

    available = {j["key"]: j["available"] for j in report["joints"]}
    assert available["lead_elbow_angle"] is False and available["rear_elbow_angle"] is False
    assert available["lead_knee_angle"] is True
    assert report["overall"]["score"] is not None
    assert any("3D 깊이" in w for w in report["overall"]["quality"]["warnings"])
