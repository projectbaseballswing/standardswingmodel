"""(80, 64) 스윙 피처의 인덱스/이름 정의.

피처 순서는 modules/utils/features_add.py 의 make_features_single_video 와 같다.
    0~47  : 관절 12개 x [x, y, z, visibility]
    48~56 : 상대 위치 3개 x [x, y, z]
    57~63 : 각도 7개 (degree)
    64~66 : 속도 3개 (DTW 템플릿에는 없음 -> 비교에서 제외)

좌타 영상은 좌우반전해서 우타 기준으로 맞추기 때문에
left_* 는 항상 투수 쪽(앞), right_* 는 포수 쪽(뒤)이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

SEQUENCE_LEN = 80
TEMPLATE_FEATURE_DIM = 64
PIPELINE_FEATURE_DIM = 67

# make_features_single_video 의 _align_sequence(target_len=80, pre_ratio=0.75)
# -> 임팩트 앞 60프레임, 뒤 20프레임
IMPACT_FRAME = 60

JOINT_NAMES: List[str] = [
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
]

JOINT_NAMES_KO: Dict[str, str] = {
    "left_shoulder": "앞 어깨", "right_shoulder": "뒤 어깨",
    "left_elbow": "앞 팔꿈치", "right_elbow": "뒤 팔꿈치",
    "left_wrist": "앞 손목", "right_wrist": "뒤 손목",
    "left_hip": "앞 골반", "right_hip": "뒤 골반",
    "left_knee": "앞 무릎", "right_knee": "뒤 무릎",
    "left_ankle": "앞 발목", "right_ankle": "뒤 발목",
}


def joint_xyz_indices(joint_idx: int) -> Tuple[int, int, int]:
    base = joint_idx * 4
    return base, base + 1, base + 2


def joint_visibility_index(joint_idx: int) -> int:
    return joint_idx * 4 + 3


# 거리 계산용 피처 그룹. visibility 는 동작이 아니라 검출 신뢰도라 제외한다.
FEATURE_GROUPS: Dict[str, np.ndarray] = {
    "pose": np.array([i for i in range(48) if i % 4 != 3]),
    "positions": np.arange(48, 57),
    "angles": np.arange(57, 64),
}

FEATURE_GROUP_NAMES_KO: Dict[str, str] = {
    "pose": "관절 위치",
    "positions": "몸 기준 상대 위치",
    "angles": "관절 각도",
}


@dataclass(frozen=True)
class AngleSpec:
    index: int
    key: str
    name: str
    body_part: str
    description: str


ANGLE_SPECS: List[AngleSpec] = [
    AngleSpec(57, "lead_elbow", "앞팔 팔꿈치 각도", "arm",
              "앞 어깨-팔꿈치-손목 사이 각도. 클수록 팔이 펴져 있다."),
    AngleSpec(58, "rear_elbow", "뒷팔 팔꿈치 각도", "arm",
              "뒤 어깨-팔꿈치-손목 사이 각도. 작을수록 팔이 접혀 있다."),
    AngleSpec(59, "lead_knee", "앞다리 무릎 각도", "leg",
              "앞 골반-무릎-발목 사이 각도. 클수록 다리가 펴져 있다."),
    AngleSpec(60, "rear_knee", "뒷다리 무릎 각도", "leg",
              "뒤 골반-무릎-발목 사이 각도. 작을수록 무릎이 굽혀져 있다."),
    AngleSpec(61, "torso_tilt", "상체 기울기", "torso",
              "골반 중심에서 어깨 중심을 향하는 선의 각도(몸 기준 좌우-상하 평면). 90°면 곧게 선 자세."),
    # 아래 두 각도는 좌우-상하 평면에서의 기울기다. 세로축 기준 회전량(몸통 꼬임)이 아니다.
    AngleSpec(62, "hip_line_tilt", "골반 라인 기울기", "torso",
              "양쪽 골반을 잇는 선의 기울기(몸 기준 좌우-상하 평면). 세로축 회전량은 아니다."),
    AngleSpec(63, "shoulder_line_tilt", "어깨 라인 기울기", "torso",
              "양쪽 어깨를 잇는 선의 기울기(몸 기준 좌우-상하 평면). 세로축 회전량은 아니다."),
]

ANGLE_SPECS_BY_KEY: Dict[str, AngleSpec] = {spec.key: spec for spec in ANGLE_SPECS}


def to_template_features(features: np.ndarray) -> np.ndarray:
    """파이프라인 출력 (80, 67) 또는 (80, 64)를 템플릿 비교용 (80, 64)로 맞춘다."""
    arr = np.asarray(features, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != SEQUENCE_LEN:
        raise ValueError(f"피처 shape 은 ({SEQUENCE_LEN}, 64) 또는 ({SEQUENCE_LEN}, 67) 이어야 합니다. 받은 값: {arr.shape}")
    if arr.shape[1] == PIPELINE_FEATURE_DIM:
        # 뒤 3개(골반/어깨 회전 속도, 손목 속도)는 템플릿에 없어서 뺀다
        return arr[:, :TEMPLATE_FEATURE_DIM]
    if arr.shape[1] == TEMPLATE_FEATURE_DIM:
        return arr
    raise ValueError(f"피처 shape 은 ({SEQUENCE_LEN}, 64) 또는 ({SEQUENCE_LEN}, 67) 이어야 합니다. 받은 값: {arr.shape}")
