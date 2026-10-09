"""프레임별 스윙 피처. 기준 모델과 사용자 분석이 같은 함수를 쓴다.

원본 프레임 좌표(픽셀)에서 계산하고, 길이는 모두 몸 크기(어깨 너비)로 나눈다.
각도는 그 자체로 크기와 무관하다. 좌타 영상은 추출 단계에서 좌우반전되어 우타 기준으로 통일돼 있다.

주의: 기울기 계열(상체/어깨/골반)은 화면 기준이라 카메라를 세워서 찍었다고 가정한다.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from feedback.events import (
    LEAD_ANKLE,
    LEAD_ELBOW,
    LEAD_HIP,
    LEAD_KNEE,
    LEAD_SHOULDER,
    LEAD_WRIST,
    REAR_ANKLE,
    REAR_ELBOW,
    REAR_HIP,
    REAR_KNEE,
    REAR_SHOULDER,
    REAR_WRIST,
    _interpolate_nan,
    _scale_per_frame,
    _smooth,
    find_zoom_frame,
)

FEATURE_NAMES: List[str] = [
    "lead_elbow_angle",      # 앞팔 팔꿈치 각도
    "rear_elbow_angle",      # 뒷팔 팔꿈치 각도
    "lead_knee_angle",       # 앞다리 무릎 각도
    "rear_knee_angle",       # 뒷다리 무릎 각도
    "torso_lean",            # 상체 기울기 (화면 수직 기준)
    "shoulder_tilt",         # 어깨 라인 기울기 (화면 수평 기준)
    "hip_tilt",              # 골반 라인 기울기
    "hand_x_from_shoulder",  # 어깨 중심 기준 손 앞뒤 위치
    "hand_y_from_shoulder",  # 어깨 중심 기준 손 높이
    "lead_ankle_x_from_hip",  # 골반 기준 앞발 앞뒤 위치 (스트라이드)
    "lead_ankle_y_from_hip",  # 골반 기준 앞발 높이
    "shoulder_x_from_hip",   # 골반 기준 어깨 앞뒤 위치 (상체 쏠림)
    "shoulder_y_from_hip",   # 골반 기준 어깨 높이
]

FEATURE_NAMES_KO: Dict[str, str] = {
    "lead_elbow_angle": "앞팔 팔꿈치 각도",
    "rear_elbow_angle": "뒷팔 팔꿈치 각도",
    "lead_knee_angle": "앞다리 무릎 각도",
    "rear_knee_angle": "뒷다리 무릎 각도",
    "torso_lean": "상체 기울기",
    "shoulder_tilt": "어깨 라인 기울기",
    "hip_tilt": "골반 라인 기울기",
    "hand_x_from_shoulder": "손 앞뒤 위치",
    "hand_y_from_shoulder": "손 높이",
    "lead_ankle_x_from_hip": "앞발 앞뒤 위치",
    "lead_ankle_y_from_hip": "앞발 높이",
    "shoulder_x_from_hip": "상체 앞뒤 쏠림",
    "shoulder_y_from_hip": "상체 높이",
}

FEATURE_UNITS: Dict[str, str] = {
    name: ("deg" if name.endswith("angle") or name in ("torso_lean", "shoulder_tilt", "hip_tilt") else "body")
    for name in FEATURE_NAMES
}


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """b를 꼭짓점으로 하는 a-b-c 각도(도)."""
    ba, bc = a - b, c - b
    denom = np.linalg.norm(ba, axis=1) * np.linalg.norm(bc, axis=1)
    cos = np.sum(ba * bc, axis=1) / np.where(denom < 1e-8, 1e-8, denom)
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def _fill(points: np.ndarray) -> np.ndarray:
    """(T, 2) 좌표의 결측을 메우고 부드럽게 한다."""
    return np.stack([_smooth(_interpolate_nan(points[:, c])) for c in range(2)], axis=1)


def compute_features(pixel_landmarks: np.ndarray) -> np.ndarray:
    """(T, 12, 3) 픽셀 좌표 -> (T, len(FEATURE_NAMES)) 피처."""
    arr = np.asarray(pixel_landmarks, dtype=float)
    scale = _scale_per_frame(arr, find_zoom_frame(arr)).reshape(-1, 1)

    joint = {idx: _fill(arr[:, idx, :2]) for idx in range(12)}
    shoulder_center = (joint[LEAD_SHOULDER] + joint[REAR_SHOULDER]) / 2
    hip_center = (joint[LEAD_HIP] + joint[REAR_HIP]) / 2
    hand_center = (joint[LEAD_WRIST] + joint[REAR_WRIST]) / 2

    def tilt(vector: np.ndarray) -> np.ndarray:
        """화면 수평 기준 기울기(도). 픽셀 y축이 아래로 향하므로 부호를 뒤집는다."""
        return np.degrees(np.arctan2(-vector[:, 1], vector[:, 0]))

    def line_tilt(vector: np.ndarray) -> np.ndarray:
        """선분의 기울기(-90~90도). 방향(어느 쪽 끝이 앞인지)은 무시한다."""
        return (tilt(vector) + 90.0) % 180.0 - 90.0

    torso = shoulder_center - hip_center
    columns = [
        _angle(joint[LEAD_SHOULDER], joint[LEAD_ELBOW], joint[LEAD_WRIST]),
        _angle(joint[REAR_SHOULDER], joint[REAR_ELBOW], joint[REAR_WRIST]),
        _angle(joint[LEAD_HIP], joint[LEAD_KNEE], joint[LEAD_ANKLE]),
        _angle(joint[REAR_HIP], joint[REAR_KNEE], joint[REAR_ANKLE]),
        90.0 - tilt(torso),  # 0이면 똑바로 선 자세, +면 투수 쪽으로 기울어짐
        line_tilt(joint[REAR_SHOULDER] - joint[LEAD_SHOULDER]),
        line_tilt(joint[REAR_HIP] - joint[LEAD_HIP]),
        (hand_center[:, 0] - shoulder_center[:, 0]) / scale[:, 0],
        -(hand_center[:, 1] - shoulder_center[:, 1]) / scale[:, 0],
        (joint[LEAD_ANKLE][:, 0] - hip_center[:, 0]) / scale[:, 0],
        -(joint[LEAD_ANKLE][:, 1] - hip_center[:, 1]) / scale[:, 0],
        (shoulder_center[:, 0] - hip_center[:, 0]) / scale[:, 0],
        -(shoulder_center[:, 1] - hip_center[:, 1]) / scale[:, 0],
    ]
    return np.stack(columns, axis=1)


def hand_speed(pixel_landmarks: np.ndarray, fps: float) -> np.ndarray:
    """손 중심 속도 (몸 크기 / 초). 프레임 수와 같은 길이로 맞춘다."""
    arr = np.asarray(pixel_landmarks, dtype=float)
    scale = _scale_per_frame(arr, find_zoom_frame(arr))
    hand = (arr[:, LEAD_WRIST, :2] + arr[:, REAR_WRIST, :2]) / 2
    x = _smooth(_interpolate_nan(hand[:, 0])) / scale
    y = _smooth(_interpolate_nan(hand[:, 1])) / scale
    speed = np.hypot(np.diff(x), np.diff(y)) * fps
    return np.concatenate([[speed[0] if len(speed) else 0.0], speed])
