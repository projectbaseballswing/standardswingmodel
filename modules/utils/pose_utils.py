from typing import Dict, List, Optional, Tuple
import numpy as np


# pose인식 thresholds
VISIBILITY_TH = 0.45
MAX_INTERP_GAP_FRAMES = 4
MAX_EDGE_FILL_FRAMES = 4

# Motion jump ratio thresholds (relative to shoulder width) for each joint.
# 기준은 배정대, 허경민, 강백호, 김강민, 정훈, 한동희 영상 데이터셋에서 구한 결과를 기반으로 jump ratio의 threshold를 joint별로 다르게 설정한 것입니다. 일단은 일괄적으로 0.5로 설정하려다가, 관절별로 jump ratio의 분포가 꽤 달라서 joint별로 다르게 설정하는 것이 낫겠다고 판단해서 이렇게 설정함. 향후 데이터셋이 확정되면 다시 검증해보고 조정하겠습니다.
HIP_JUMP_RATIO_TH = 0.22
SHOULDER_JUMP_RATIO_TH = 0.40
ELBOW_JUMP_RATIO_TH = 0.80
WRIST_JUMP_RATIO_TH = 1.10
KNEE_JUMP_RATIO_TH = 0.50
ANKLE_JUMP_RATIO_TH = 0.65

# Savitzky-Golay filter settings for smoothing after interpolation.
SG_POLYORDER = 2
SG_MIN_WINDOW = 5
SG_MAX_WINDOW = 11
SG_WINDOW_SEC = 0.12

MOTION_JUMP_RATIO_THRESHOLDS: Dict[str, float] = {
    "left_hip": HIP_JUMP_RATIO_TH,
    "right_hip": HIP_JUMP_RATIO_TH,
    "left_shoulder": SHOULDER_JUMP_RATIO_TH,
    "right_shoulder": SHOULDER_JUMP_RATIO_TH,
    "left_elbow": ELBOW_JUMP_RATIO_TH,
    "right_elbow": ELBOW_JUMP_RATIO_TH,
    "left_wrist": WRIST_JUMP_RATIO_TH,
    "right_wrist": WRIST_JUMP_RATIO_TH,
    "left_knee": KNEE_JUMP_RATIO_TH,
    "right_knee": KNEE_JUMP_RATIO_TH,
    "left_ankle": ANKLE_JUMP_RATIO_TH,
    "right_ankle": ANKLE_JUMP_RATIO_TH,
}

OUTPUT_JOINT_ORDER: List[str] = [
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
]

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