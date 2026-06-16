from typing import Dict, List, Optional, Tuple
import numpy as np


# pose인식 thresholds
VISIBILITY_TH = 0.45  # fallback/default
VISIBILITY_THRESHOLDS: Dict[str, float] = {
    "left_ankle": 0.45,
    "left_elbow": 0.50,
    "left_hip": 0.45,
    "left_index": 0.75,
    "left_knee": 0.45,
    "left_pinky": 0.75,
    "left_shoulder": 0.65,
    "left_wrist": 0.10,
    "right_ankle": 0.45,
    "right_elbow": 0.50,
    "right_hip": 0.45,
    "right_index": 0.75,
    "right_knee": 0.45,
    "right_pinky": 0.75,
    "right_shoulder": 0.65,
    "right_wrist": 0.10,
}

MAX_INTERP_GAP_FRAMES = 4  # fallback/default
MAX_INTERP_GAP_FRAMES_BY_JOINT: Dict[str, int] = {
    "left_ankle": 4,
    "left_elbow": 2,
    "left_hip": 4,
    "left_index": 0,
    "left_knee": 4,
    "left_pinky": 0,
    "left_shoulder": 4,
    "left_wrist": 1,
    "right_ankle": 4,
    "right_elbow": 2,
    "right_hip": 4,
    "right_index": 0,
    "right_knee": 4,
    "right_pinky": 0,
    "right_shoulder": 4,
    "right_wrist": 1,
}

MAX_EDGE_FILL_FRAMES = 4

# Motion jump ratio thresholds (relative to shoulder width) for each joint.
# 기준은 현재 보유한 스윙 영상에서 관절별 jump ratio 분포를 확인한 뒤 설정한 초기값입니다.
# 데이터셋이 확정되면 다시 검증하고 조정할 예정입니다.
HIP_JUMP_RATIO_TH = 0.27
SHOULDER_JUMP_RATIO_TH = 0.42
ELBOW_JUMP_RATIO_TH = 0.81
WRIST_JUMP_RATIO_TH = 0.90
FINGER_JUMP_RATIO_TH = 0.75
KNEE_JUMP_RATIO_TH = 0.48
ANKLE_JUMP_RATIO_TH = 0.72

MOTION_JUMP_RATIO_THRESHOLDS: Dict[str, float] = {
    "left_hip": HIP_JUMP_RATIO_TH,
    "right_hip": HIP_JUMP_RATIO_TH,
    "left_shoulder": SHOULDER_JUMP_RATIO_TH,
    "right_shoulder": SHOULDER_JUMP_RATIO_TH,
    "left_elbow": ELBOW_JUMP_RATIO_TH,
    "right_elbow": ELBOW_JUMP_RATIO_TH,
    "left_wrist": WRIST_JUMP_RATIO_TH,
    "right_wrist": WRIST_JUMP_RATIO_TH,
    "left_pinky": FINGER_JUMP_RATIO_TH,
    "right_pinky": FINGER_JUMP_RATIO_TH,
    "left_index": FINGER_JUMP_RATIO_TH,
    "right_index": FINGER_JUMP_RATIO_TH,
    "left_knee": KNEE_JUMP_RATIO_TH,
    "right_knee": KNEE_JUMP_RATIO_TH,
    "left_ankle": ANKLE_JUMP_RATIO_TH,
    "right_ankle": ANKLE_JUMP_RATIO_TH,
}

# Savitzky-Golay filter settings for smoothing after interpolation.
SG_POLYORDER = 2
SG_MIN_WINDOW = 5
SG_MAX_WINDOW = 11
SG_WINDOW_SEC = 0.12


# =========================
# Landmark definitions
# =========================
# 후단 정규화/feature 단계에서 기본으로 사용하는 12개 핵심 관절입니다.
CORE_JOINTS: Dict[str, int] = {
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}

# 배트 각도/손 위치 보조 feature용 손 landmark입니다.
# wrist는 CORE_JOINTS에 이미 있으므로 여기에는 추가 손가락 landmark만 둡니다.
HAND_EXTRA_JOINTS: Dict[str, int] = {
    "left_pinky": 17,
    "right_pinky": 18,
    "left_index": 19,
    "right_index": 20,
}

# MediaPipe에서 실제로 추출하고 전처리할 전체 landmark 집합입니다.
POSE_JOINTS: Dict[str, int] = {
    **CORE_JOINTS,
    **HAND_EXTRA_JOINTS,
}

# all_landmarks 출력 순서: shape (T, 12, 3)
OUTPUT_JOINT_ORDER: List[str] = [
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
]


# left/right swap index pairs for each output array.
OUTPUT_LEFT_RIGHT_PAIRS: List[Tuple[int, int]] = [
    (0, 1),    # shoulder
    (2, 3),    # elbow
    (4, 5),    # wrist
    (6, 7),    # hip
    (8, 9),    # knee
    (10, 11),  # ankle
]

BAT_LEFT_RIGHT_PAIRS: List[Tuple[int, int]] = [
    (0, 3),  # wrist
    (1, 4),  # pinky
    (2, 5),  # index
]

 
def contiguous_true_segments(mask: np.ndarray) -> List[Tuple[int, int]]:
    segments = []
    start = None
    for i, val in enumerate(mask):
        if bool(val) and start is None:
            start = i
        elif (not bool(val)) and start is not None:
            segments.append((start, i - 1))
            start = None
    if start is not None:
        segments.append((start, len(mask) - 1))
    return segments

def choose_savgol_window(fps: float, valid_len: int) -> Optional[int]:
    """
    fps에 따라 Savitzky-Golay window length를 선택
    """
    if not np.isfinite(fps) or fps <= 0:
        window = SG_MIN_WINDOW
    else:
        window = int(round(fps * SG_WINDOW_SEC))
        window = max(SG_MIN_WINDOW, min(SG_MAX_WINDOW, window))

    if window % 2 == 0:
        window += 1
    if window > valid_len:
        window = valid_len if valid_len % 2 == 1 else valid_len - 1
    if window < max(SG_MIN_WINDOW, SG_POLYORDER + 2):
        return None
    return window

def euclidean_2d(p1, p2) -> float:
    """
    jump ratio 계산을 위해 2D 유클리드 거리 계산   
    """
    if p1 is None or p2 is None:
        return np.nan
    if np.any(np.isnan(p1)) or np.any(np.isnan(p2)):
        return np.nan
    return float(np.linalg.norm(p1 - p2))