"""프레임별 스윙 피처. 기준 모델과 사용자 분석이 같은 함수를 쓴다.

원본 프레임 좌표(픽셀)에서 계산하고, 길이는 모두 몸 크기(어깨 너비)로 나눈다.
각도는 그 자체로 크기와 무관하다. 좌타 영상은 추출 단계에서 좌우반전되어 우타 기준으로 통일돼 있다.

주의: 기울기 계열(상체/어깨/골반)은 화면 기준이라 카메라를 세워서 찍었다고 가정한다.

깊이(z): 저장된 z 는 MediaPipe 이미지 z 에 화면 너비를 곱한 값인데, x, y 보다 약 3배 크게 나온다.
같은 추론의 월드 좌표(미터)와 맞춰 보면 배율 하나로 거의 일치한다 (프로 49개: 상관 +0.98,
배율 중앙 0.305, 범위 0.265~0.346, 영상 간 변동 6%, 해상도·사람 크기·좌우타와 무관).
보정 없이 쓰면 뼈 길이가 프레임마다 20~38% 흔들려서 예전(0.1) 피처가 왜곡됐다.
프로 전체(890개)로 다시 재도 배율 중앙 0.301, 영상 간 변동 6.4% 였다.

회전(어깨/골반 회전, 꼬임)은 위에서 내려다본 방향(x, z)으로 잰다. 보정한 이미지 z 로 잰 값과
월드 좌표로 잰 값이 거의 같아서 (프로 743개: 상관 0.99, 차이 중앙값 3~4도) 사용자 영상에서
월드 좌표가 없어도 같은 값을 낼 수 있게 이미지 좌표로 계산한다.
절대 회전각은 카메라가 타자를 보는 방향에 따라 통째로 밀린다 (프로 간 편차 약 16도).
어깨와 골반의 차이(꼬임)는 카메라 방향과 무관하다 (편차 약 7도).
"""

from __future__ import annotations

from typing import Dict, List, Optional

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

# 이미지 z -> x, y 와 같은 단위로 맞추는 배율 (모듈 설명 참고)
DEPTH_SCALE = 0.30
# 영상별로 잰 배율이 이 범위를 벗어나면 그 영상의 깊이 추정을 믿지 않는다 (프로 영상 분포 바깥)
DEPTH_SCALE_RANGE = (0.25, 0.36)
# 깊이(z)를 쓰는 피처. 깊이 추정이 불안정한 영상에서는 측정 불가로 뺀다.
DEPTH_FEATURES = (
    "lead_elbow_angle", "rear_elbow_angle", "shoulder_turn", "hip_turn", "hip_shoulder_separation",
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
    "shoulder_turn",         # 어깨 회전 (위에서 본 어깨선 방향, +면 투수 쪽으로 열림)
    "hip_turn",              # 골반 회전
    "hip_shoulder_separation",  # 어깨 회전 - 골반 회전 (-면 어깨가 골반보다 닫혀 있음)
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
    "shoulder_turn": "어깨 회전",
    "hip_turn": "골반 회전",
    "hip_shoulder_separation": "어깨-골반 꼬임",
}

ROTATION_UNITS_DEG = ("torso_lean", "shoulder_tilt", "hip_tilt", "shoulder_turn", "hip_turn",
                      "hip_shoulder_separation")

FEATURE_UNITS: Dict[str, str] = {
    name: ("deg" if name.endswith("angle") or name in ROTATION_UNITS_DEG else "body")
    for name in FEATURE_NAMES
}


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """b를 꼭짓점으로 하는 a-b-c 각도(도)."""
    ba, bc = a - b, c - b
    denom = np.linalg.norm(ba, axis=1) * np.linalg.norm(bc, axis=1)
    cos = np.sum(ba * bc, axis=1) / np.where(denom < 1e-8, 1e-8, denom)
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def _fill(points: np.ndarray) -> np.ndarray:
    """(T, D) 좌표의 결측을 메우고 부드럽게 한다."""
    return np.stack([_smooth(_interpolate_nan(points[:, c])) for c in range(points.shape[1])], axis=1)


def depth_points(pixel_landmarks: np.ndarray, joint: int) -> np.ndarray:
    """(T, 3) 관절 좌표. z 에 DEPTH_SCALE 을 곱해 x, y 와 같은 픽셀 단위로 맞춘다."""
    return _fill(pixel_landmarks[:, joint, :3] * np.array([1.0, 1.0, DEPTH_SCALE]))


# 회전각을 -180~180 대신 이 값을 중심으로 한 바퀴 범위에 담는다.
# 프로 스윙은 착지 -20도 -> 임팩트 +35도 -> 팔로우 +85도 근처를 지나서, 0 중심으로 자르면 팔로우에서 끊긴다.
TURN_CENTER_DEG = 30.0


def _wrap(angle: np.ndarray, center: float = 0.0) -> np.ndarray:
    return (angle - center + 180.0) % 360.0 - 180.0 + center


def turn_angle(lead: np.ndarray, rear: np.ndarray) -> np.ndarray:
    """(T, 3) 두 관절을 잇는 선의 위에서 본 방향(도). 뒤 -> 앞 방향, x-z 평면. 스윙 동안 열리는 쪽이 +.

    프레임끼리 이어 붙이지(unwrap) 않는다. 어깨가 카메라 쪽으로 겹쳐 선이 거의 점이 되는 프레임에서
    방향이 튀면 한 바퀴(360도)가 통째로 더해져 이후 값이 모두 틀어진다 (프로 1개에서 발생).
    """
    d = lead - rear
    return _wrap(np.degrees(np.arctan2(d[:, 2], d[:, 0])), TURN_CENTER_DEG)


def estimate_depth_scale(pixel_landmarks: np.ndarray, world_landmarks: np.ndarray) -> Optional[float]:
    """이 영상의 이미지 z -> 월드 z 배율. 둘 다 골반 중심을 원점, 몸통 길이를 1로 맞춘 뒤 최소제곱으로 구한다.

    MediaPipe 월드 좌표(미터, 골반 중심 원점)는 같은 추론에서 나온 깊이라, 배율이 프로 영상 범위를
    벗어나면 그 영상의 깊이 추정이 평소와 다르게 동작한 것으로 본다. 프레임 수가 다르면 None.
    """
    pixel = np.asarray(pixel_landmarks, dtype=float)
    world = np.asarray(world_landmarks, dtype=float)
    if pixel.shape != world.shape or pixel.ndim != 3 or pixel.shape[2] != 3:
        return None

    def depth(points: np.ndarray) -> np.ndarray:
        filled = np.stack([_fill(points[:, j]) for j in range(points.shape[1])], axis=1)
        hip = (filled[:, LEAD_HIP] + filled[:, REAR_HIP]) / 2
        shoulder = (filled[:, LEAD_SHOULDER] + filled[:, REAR_SHOULDER]) / 2
        # 기준 길이는 x, y 로만 잰다. z 를 넣으면 재려는 배율이 기준 길이에 섞인다.
        torso = float(np.nanmedian(np.linalg.norm((shoulder - hip)[:, :2], axis=1)))
        if not np.isfinite(torso) or torso <= 0:
            return np.full(filled.shape[:2], np.nan)
        return (filled[..., 2] - hip[:, None, 2]) / torso

    image_z, world_z = depth(pixel), depth(world)
    ok = np.isfinite(image_z) & np.isfinite(world_z)
    denom = float(np.sum(image_z[ok] ** 2))
    if ok.sum() < 12 or denom <= 0:
        return None
    return float(np.sum(image_z[ok] * world_z[ok]) / denom)


def compute_features(pixel_landmarks: np.ndarray) -> np.ndarray:
    """(T, 12, 3) 픽셀 좌표 -> (T, len(FEATURE_NAMES)) 피처."""
    arr = np.asarray(pixel_landmarks, dtype=float)
    scale = _scale_per_frame(arr, find_zoom_frame(arr)).reshape(-1, 1)

    joint = {idx: _fill(arr[:, idx, :2]) for idx in range(12)}
    # 팔꿈치 각도만 3D 로 잰다. 팔은 몸에 가려지고 카메라 쪽으로 뻗어서 2D 각도가 크게 틀어진다.
    # 무릎은 2D 가 더 안정적이었다 (프로 49개: 임팩트 앞 무릎 편차 2D 9.1도, 3D 12.6도).
    arm = {idx: depth_points(arr, idx) for idx in (LEAD_SHOULDER, REAR_SHOULDER, LEAD_ELBOW, REAR_ELBOW,
                                                  LEAD_WRIST, REAR_WRIST, LEAD_HIP, REAR_HIP)}
    shoulder_turn = turn_angle(arm[LEAD_SHOULDER], arm[REAR_SHOULDER])
    hip_turn = turn_angle(arm[LEAD_HIP], arm[REAR_HIP])
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
        _angle(arm[LEAD_SHOULDER], arm[LEAD_ELBOW], arm[LEAD_WRIST]),
        _angle(arm[REAR_SHOULDER], arm[REAR_ELBOW], arm[REAR_WRIST]),
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
        shoulder_turn,
        hip_turn,
        _wrap(shoulder_turn - hip_turn),
    ]
    return np.stack(columns, axis=1)


def _torso_scale_per_frame(pixel_landmarks: np.ndarray, zoom_frame) -> np.ndarray:
    """프레임별 몸통 길이(어깨 중심 ~ 골반 중심) 중앙값. 확대 지점이 있으면 앞뒤를 따로 계산한다.

    어깨 너비는 카메라가 타자를 비스듬히 볼수록 좁게 찍혀서, 그걸로 나눈 속도는 촬영 각도에 따라
    달라진다 (프로 887개: 각도 지표와 상관 -0.31). 몸통 길이는 각도에 둔감하다 (상관 +0.06).
    """
    shoulder = (pixel_landmarks[:, LEAD_SHOULDER, :2] + pixel_landmarks[:, REAR_SHOULDER, :2]) / 2
    hip = (pixel_landmarks[:, LEAD_HIP, :2] + pixel_landmarks[:, REAR_HIP, :2]) / 2
    length = np.linalg.norm(shoulder - hip, axis=1)

    def median(values: np.ndarray) -> float:
        value = float(np.nanmedian(values)) if np.isfinite(values).any() else float("nan")
        return value if np.isfinite(value) and value > 1 else 1.0

    scale = np.full(len(pixel_landmarks), median(length), dtype=float)
    if zoom_frame is not None:
        scale[:zoom_frame] = median(length[:zoom_frame])
        scale[zoom_frame:] = median(length[zoom_frame:])
    return scale


def hand_speed(pixel_landmarks: np.ndarray, fps: float) -> np.ndarray:
    """손 중심 속도 (몸통 길이 / 초). 프레임 수와 같은 길이로 맞춘다."""
    arr = np.asarray(pixel_landmarks, dtype=float)
    scale = _torso_scale_per_frame(arr, find_zoom_frame(arr))
    hand = (arr[:, LEAD_WRIST, :2] + arr[:, REAR_WRIST, :2]) / 2
    x = _smooth(_interpolate_nan(hand[:, 0])) / scale
    y = _smooth(_interpolate_nan(hand[:, 1])) / scale
    speed = np.hypot(np.diff(x), np.diff(y)) * fps
    return np.concatenate([[speed[0] if len(speed) else 0.0], speed])
