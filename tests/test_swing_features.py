"""스윙 피처가 체형(다리 길이) 차이에 흔들리지 않는지 합성 스켈레톤으로 검증한다."""

from __future__ import annotations

import numpy as np
import pytest

from feedback.events import (
    LEAD_ANKLE, LEAD_ELBOW, LEAD_HIP, LEAD_KNEE, LEAD_SHOULDER, LEAD_WRIST,
    REAR_ANKLE, REAR_ELBOW, REAR_HIP, REAR_KNEE, REAR_SHOULDER, REAR_WRIST,
)
from feedback.swing_features import FEATURE_NAMES, compute_features

FOOT_HEIGHT = FEATURE_NAMES.index("lead_ankle_y_from_hip")


def standing_pose(leg: float, frames: int = 30, lift: float = 0.0) -> np.ndarray:
    """정면에서 본 선 자세 (T, 12, 3) 픽셀 좌표. y 는 아래로 증가. lift 는 다리 길이 대비 앞발 높이."""
    hip_y, shoulder_y = 500.0, 320.0
    points = {
        LEAD_SHOULDER: (560, shoulder_y), REAR_SHOULDER: (440, shoulder_y),
        LEAD_ELBOW: (580, 400), REAR_ELBOW: (420, 400),
        LEAD_WRIST: (530, 360), REAR_WRIST: (470, 360),
        LEAD_HIP: (540, hip_y), REAR_HIP: (460, hip_y),
        LEAD_KNEE: (545, hip_y + leg / 2), REAR_KNEE: (455, hip_y + leg / 2),
        LEAD_ANKLE: (550, hip_y + leg * (1 - lift)), REAR_ANKLE: (450, hip_y + leg),
    }
    pose = np.zeros((12, 3))
    for joint, (x, y) in points.items():
        pose[joint, :2] = (x, y)
    return np.repeat(pose[None], frames, axis=0)


@pytest.mark.parametrize("leg", [300.0, 380.0, 460.0])
def test_foot_on_ground_reads_zero_for_any_leg_length(leg):
    height = compute_features(standing_pose(leg))[:, FOOT_HEIGHT]
    assert np.allclose(height, 0.0, atol=1e-6)


def test_lifted_foot_height_is_relative_to_leg_length():
    # 다리 길이가 달라도 다리 길이의 20% 만큼 들면 같은 값이 나와야 한다.
    short = compute_features(standing_pose(300.0, lift=0.2))[:, FOOT_HEIGHT]
    long = compute_features(standing_pose(460.0, lift=0.2))[:, FOOT_HEIGHT]
    assert np.allclose(short, long, atol=0.02)
    # 앞뒤 끝 프레임은 스무딩 가장자리라 값이 줄어든다. 가운데만 본다.
    assert np.all(short[5:-5] > 0.15)


def test_spread_floor_follows_feature_length_unit():
    # 하한은 어깨 너비 0.15 개에 해당하는 길이여야 한다. 몸통·다리 길이로 나눈 피처는 숫자가 작아지므로
    # 하한도 같은 비율로 작아져야 실제 편차가 하한에 묻히지 않는다.
    from feedback.reference_model import MIN_SPREAD, min_spread
    from feedback.swing_features import SHOULDER_WIDTHS_PER_SCALE

    floor = dict(zip(FEATURE_NAMES, min_spread(FEATURE_NAMES)))
    assert floor["lead_knee_angle"] == MIN_SPREAD
    assert floor["lead_ankle_x_from_hip"] == MIN_SPREAD
    assert floor["shoulder_y_from_hip"] == pytest.approx(MIN_SPREAD / SHOULDER_WIDTHS_PER_SCALE["torso"])
    assert floor["lead_ankle_y_from_hip"] == pytest.approx(MIN_SPREAD / SHOULDER_WIDTHS_PER_SCALE["leg"])
