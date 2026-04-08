
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np
import pandas as pd
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from scipy.signal import savgol_filter

# =========================================================
# Common expressions / helper patterns used in this module
# =========================================================
#
# [NumPy / Pandas에서 자주 쓰는 표현 정리]
#
# 1) df["new_col"] = np.nan
#    - DataFrame에 새 컬럼을 만들고, 모든 행을 NaN(결측값)으로 초기화한다.
#    - 이후 계산 가능한 위치만 df.at[...] 등으로 채워 넣을 때 자주 사용한다.
#
# 2) np.nan
#    - 결측값(missing value)을 나타내는 특수한 float 값.
#    - "값이 없음", "계산 불가", "일단 비워 둠"을 표현할 때 사용한다.
#
# 3) np.isfinite(x)
#    - x가 정상적인 유한 실수인지 검사한다.
#    - NaN, inf, -inf 이면 False를 반환한다.
#    - 좌표/거리/스케일 값이 계산 가능한지 확인할 때 자주 사용한다.
#
# 4) np.all(np.isfinite(...))
#    - 배열 안의 모든 값이 정상 숫자인지 한 번에 검사한다.
#    - 하나라도 NaN/inf가 있으면 False.
#    - 예: 어떤 관절의 x,y,z가 모두 유효한지 확인할 때 사용.
#
# 5) np.any(...)
#    - 배열 안에 True가 하나라도 있으면 True.
#    - "하나라도 조건을 만족하는가?"를 확인할 때 사용.
#
# 6) np.concatenate([a, b, c])
#    - 여러 배열을 한 줄로 이어붙인다.
#    - 여러 관절 좌표를 한 번에 finite 검사할 때 자주 사용한다.
#
# 7) np.array([...], dtype=float)
#    - 리스트를 NumPy 배열로 만든다.
#    - dtype=float은 계산을 위해 실수형으로 맞춘다는 뜻이다.
#    - 예: [x, y, z] 형태의 좌표 벡터 생성.
#
# 8) np.linalg.norm(v)
#    - 벡터 v의 길이(크기)를 구한다.
#    - 두 점의 차 벡터에 적용하면 "거리"가 된다.
#    - 예: shoulder width, hip width, torso length 계산.
#
# 9) np.cross(a, b)
#    - 벡터 a와 b의 외적(cross product)을 구한다.
#    - 두 벡터에 모두 수직인 벡터를 만든다.
#    - 기준 좌표축(x, y, z axis) 구성할 때 사용.
#
# 10) np.stack([a, b, c], axis=1)
#     - 여러 벡터를 옆으로 쌓아 하나의 행렬로 만든다.
#     - 여기서는 x_axis, y_axis, z_axis를 열(column)로 쌓아 basis 행렬을 만든다.
#
# 11) np.linspace(start, end, n)
#     - start부터 end까지를 균등하게 n개로 나눈 값들을 만든다.
#     - 짧은 결측 구간을 선형 보간할 때 사용한다.
#
# 12) np.median(values)
#     - 중앙값을 구한다.
#     - 평균(mean)보다 이상치(outlier)에 덜 민감하다.
#     - robust body scale 계산 등에서 사용.
#
# 13) df.at[row_idx, col_name]
#     - DataFrame의 "한 칸" 값에 접근하거나 수정할 때 사용한다.
#     - 예: df.at[i, "left_hip_wx_filt"]
#
# 14) df.loc[row_selector, col_name]
#     - 조건에 맞는 여러 행/열을 한 번에 선택하거나 수정할 때 사용한다.
#     - 예: observed_mask.loc[interp_mask, joint] = 0
#
# 15) df.copy()
#     - 원본 DataFrame을 직접 바꾸지 않기 위해 복사본을 만든다.
#     - 함수 내부에서 안전하게 수정할 때 자주 사용한다.
#
# 16) continue
#     - 현재 반복을 중단하고 다음 반복으로 넘어간다.
#     - 값이 비정상이어서 현재 frame/joint를 건너뛸 때 사용한다.
#
# 17) return None
#     - 정상 결과를 만들 수 없을 때 "실패"를 반환한다.
#     - 예: 기준 프레임을 못 찾았거나, 시퀀스를 폐기해야 하는 경우.
#
# 18) Optional[pd.DataFrame]
#     - 반환값이 pd.DataFrame일 수도 있고 None일 수도 있다는 뜻.
#
# 19) f"{joint}_wx_filt"
#     - f-string(포매팅 문자열) 문법.
#     - 변수값을 문자열 안에 넣어 컬럼명을 동적으로 만든다.
#     - 예: joint="left_hip"이면 "left_hip_wx_filt"가 된다.
#
# 20) raw / filt / norm 접미사 의미
#     - raw  : MediaPipe에서 바로 나온 원본 값
#     - _filt: 결측 처리 / 보간 / smoothing 후의 값
#     - _norm: 기준 좌표계 변환 + body scale 정규화 후 값
#
# 21) observed_mask
#     - 1: 원래 관측된 유효값 기반
#     - 0: interpolation / edge fill / unresolved missing
#     - 주의: smoothing만 된 값은 observed_mask=1일 수 있다.
#
# 22) NaN이 남는 경우
#     - 모든 영상이 폐기되지 않았더라도,
#       특정 joint 또는 특정 frame은 보간 실패로 NaN이 남을 수 있다.
#     - 즉 "시퀀스 유지"와 "모든 좌표 완전 복구"는 같은 뜻이 아니다.
#
# 23) shape[:2]
#     - image/frame의 (height, width)만 가져온다.
#     - OpenCV frame은 보통 (height, width, channel) 형태다.
#
# 24) cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
#     - OpenCV의 BGR 이미지를 RGB로 바꾼다.
#     - MediaPipe 입력 전에 색상 채널 순서를 맞출 때 사용한다.
#
# 25) with create_landmarker(...) as landmarker:
#     - context manager 문법.
#     - 사용 후 리소스를 자동 정리한다.


# =========================
# User-editable settings
# =========================

MODEL_PATH = r"./reference_swing/models/pose_landmarker.task"

# Landmark is considered missing if visibility is below this threshold or non-finite.

VISIBILITY_TH = 0.45   
MAX_INTERP_GAP_FRAMES = 4
MAX_EDGE_FILL_FRAMES = 4
DISCARD_FULL_MISSING_RUN = 4

# Savitzky-Golay filter settings for smoothing after interpolation.
SG_POLYORDER = 2
SG_MIN_WINDOW = 5
SG_MAX_WINDOW = 11
SG_WINDOW_SEC = 0.12

# Motion jump ratio thresholds (relative to shoulder width) for each joint.
# 기준은 배정대, 허경민, 강백호, 김강민, 정훈, 한동희 영상 데이터셋에서 구한 결과를 기반으로 jump ratio의 threshold를 joint별로 다르게 설정한 것입니다. 일단은 일괄적으로 0.5로 설정하려다가, 관절별로 jump ratio의 분포가 꽤 달라서 joint별로 다르게 설정하는 것이 낫겠다고 판단해서 이렇게 설정함. 향후 데이터셋이 많아질수록 조정이 필요할 수 있음.
HIP_JUMP_RATIO_TH = 0.22
SHOULDER_JUMP_RATIO_TH = 0.40
ELBOW_JUMP_RATIO_TH = 0.80
WRIST_JUMP_RATIO_TH = 1.10
KNEE_JUMP_RATIO_TH = 0.50
ANKLE_JUMP_RATIO_TH = 0.65

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

REFERENCE_JOINTS = ["left_hip", "right_hip", "left_shoulder", "right_shoulder"]
OUTPUT_JOINT_COLUMNS = [f"norm_{joint}" for joint in CORE_JOINTS.keys()]


# =========================
# MediaPipe
# =========================
# Note: MediaPipe PoseLandmarker is used only for raw landmark extraction.
# mediapipe에서 제공하는 landmarker 모델 파일이 필요합니다. 모델 파일은 mediapipe 공식 github에서 다운로드할 수 있습니다:
# https://github.com/google/mediapipe/blob/master/mediapipe/models/pose_landmarker.task

def create_landmarker(model_path: str = MODEL_PATH):
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"모델 파일을 찾지 못했어: {model_path}")

    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1, # ROI 프레임에서 하나의 포즈(사람)만 추출하도록 설정
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_segmentation_masks=False,
    )
    return vision.PoseLandmarker.create_from_options(options)


# =========================
# Utils
# =========================
# Helper functions for processing boolean masks, interpolation, smoothing, and geometric computations.

# 연속 결측 구간 찾기: boolean mask에서 True인 구간들의 (start_idx, end_idx) 리스트 반환

def contiguous_true_segments(mask: np.ndarray) -> List[Tuple[int, int]]:
    segments: List[Tuple[int, int]] = []
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



def max_consecutive_true(mask: np.ndarray) -> int:
    max_len = 0
    cur = 0
    for val in mask:
        if bool(val):
            cur += 1
            max_len = max(max_len, cur)
        else:
            cur = 0
    return max_len


def choose_savgol_window(fps: float, valid_len: int) -> Optional[int]:
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

# Savitzky-Golay은 NaN을 처리하지 못하므로, NaN이 포함된 배열에서 NaN이 아닌 구간마다 따로 적용하는 함수입니다. fps에 따라 window size가 달라집니다. 
def savgol_smooth_with_nans(arr: np.ndarray, fps: float) -> np.ndarray:
    out = arr.astype(float).copy()
    valid = np.isfinite(out)
    for s, e in contiguous_true_segments(valid):
        seg = out[s:e + 1]
        window = choose_savgol_window(fps, len(seg))
        if window is None or len(seg) < window or window <= SG_POLYORDER:
            continue
        try:
            out[s:e + 1] = savgol_filter(seg, window_length=window, polyorder=SG_POLYORDER, mode="interp")
        except Exception:
            continue
    return out


def euclidean_2d(p1: Optional[np.ndarray], p2: Optional[np.ndarray]) -> float:
    if p1 is None or p2 is None:
        return np.nan
    if np.any(np.isnan(p1)) or np.any(np.isnan(p2)):
        return np.nan
    return float(np.linalg.norm(p1 - p2))


def normalize_vec(v: np.ndarray, eps: float = 1e-8) -> Optional[np.ndarray]:
    n = float(np.linalg.norm(v))
    if not np.isfinite(n) or n < eps:
        return None
    return v / n

# 최종 출력용 튜플 생성 함수입니다. 좌표 중 하나라도 유한하지 않으면 (None, None, None, 0)을 반환합니다. 그렇지 않으면 (x, y, z, mask) 튜플을 반환합니다.

def tuple_or_missing(x: float, y: float, z: float, mask: int):
    if not (np.isfinite(x) and np.isfinite(y) and np.isfinite(z)):
        return (None, None, None, 0)
    return (float(x), float(y), float(z), int(mask))




# =========================
# Raw extraction
# =========================

# =========================
# Raw extraction
# =========================

def _extract_raw_dataframe(roi_frames: List[np.ndarray], fps: float) -> pd.DataFrame:
    """
    ROI 프레임 리스트에서 MediaPipe Pose landmark를 추출해
    프레임 단위 raw DataFrame으로 정리한다.

    입력:
        roi_frames:
            ROI crop이 이미 적용된 OpenCV BGR 프레임 리스트
        fps:
            입력 시퀀스의 frame rate

    반환:
        pd.DataFrame:
            각 row은 프레임 1개를 의미한다.
            각 column에는 해당 프레임의 메타정보와
            core joint landmark 정보가 저장된다.

            주요 컬럼 예시:
                - frame_idx: 프레임 인덱스
                - pose_detected: pose 검출 여부 (0 or 1)
                - frame_width, frame_height: ROI 프레임 크기
                - {joint}_x, {joint}_y, {joint}_z:
                    image/ROI 기준 landmark 좌표
                - {joint}_visibility, {joint}_presence:
                    MediaPipe confidence 계열 값
                - {joint}_wx, {joint}_wy, {joint}_wz:
                    MediaPipe world landmark 좌표

    내부 동작:
        - 각 프레임마다 먼저 row(dict) 하나를 만든다.
        - 이 row는 "프레임 1개에 대한 landmark 정보"를 담는 임시 자료구조다.
        - 모든 frame의 row(dict)를 rows 리스트에 append한 뒤,
          마지막에 pd.DataFrame(rows)로 변환해 반환한다.

    row(dict) 예시:
        {
            "frame_idx": 0,
            "pose_detected": 1,
            "frame_width": 320,
            "frame_height": 256,
            "left_shoulder_x": 121.4,
            "left_shoulder_y": 88.2,
            "left_shoulder_z": -0.12,
            "left_shoulder_visibility": 0.93,
            "left_shoulder_presence": 0.97,
            "left_shoulder_wx": -0.18,
            "left_shoulder_wy": -0.32,
            "left_shoulder_wz": 0.11,
            ...
        }

    최종 DataFrame 형태:
        - row  : 프레임
        - column: 메타정보 + joint별 raw landmark 값
    """
def _extract_raw_dataframe(roi_frames: List[np.ndarray], fps: float) -> pd.DataFrame:
    rows = []
    with create_landmarker(MODEL_PATH) as landmarker:
        for frame_idx, frame in enumerate(roi_frames):
            if frame is None:
                rows.append(_empty_row(frame_idx))
                continue

            height, width = frame.shape[:2]
            timestamp_ms = int((frame_idx / fps) * 1000) if fps > 0 else frame_idx * 33

            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            )
            
            # pose_landmark와 pose_world_landmark는 각각 2D와 3D landmark를 담고 있고 이 값이 result에 저장됩니다. pose_landmark는 ROI 프레임 기준의 2D 좌표와 visibility/presence/confidence 정보를 담고 있고, pose_world_landmark는 원본 프레임 기준의 3D 좌표를 담고 있습니다. 이후 처리에서는 pose_world_landmark의 3D 좌표를 주로 사용하지만, visibility 정보는 pose_landmark에서 가져옵니다.

            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            row = {
                "frame_idx": frame_idx,
                "pose_detected": int(len(result.pose_landmarks) > 0),
                
                # MediaPipe PoseLandmarker는 ROI 프레임에서 동작하므로, frame_width와 frame_height는 ROI 프레임의 크기를 나타냅니다. 이후 좌표들을 정규화하거나 필터링할 때 이 크기를 참고할 수 있습니다.
                "frame_width": width, 
                "frame_height": height,
            }

            # MediaPipe가 포즈를 감지하지 못한 경우, 모든 관절에 대해 NaN과 0으로 채운 행을 추가하고 다음 프레임으로 넘어갑니다.
            if len(result.pose_landmarks) == 0:
                for joint_name in CORE_JOINTS.keys():
                    for suffix in ["_x", "_y", "_z", "_visibility", "_presence", "_wx", "_wy", "_wz"]:
                        row[f"{joint_name}{suffix}"] = np.nan
                rows.append(row)
                continue

            
            landmarks = result.pose_landmarks[0]
            world_landmarks = result.pose_world_landmarks[0] if len(result.pose_world_landmarks) > 0 else None

            # 사용할 landmark 인덱스는 CORE_JOINTS 딕셔너리에 정의되어 있습니다. 각 관절에 대해 ROI 프레임 기준의 2D 좌표(x, y), z 좌표, visibility, presence 정보를 row에 저장합니다. 또한 원본 프레임 기준의 3D 좌표(wx, wy, wz)도 저장합니다. 만약 world_landmarks가 제공되지 않는 경우에는 3D 좌표를 NaN으로 채웁니다.
            
            for joint_name, joint_idx in CORE_JOINTS.items():
                lm = landmarks[joint_idx]
                row[f"{joint_name}_x"] = float(lm.x * width)
                row[f"{joint_name}_y"] = float(lm.y * height)
                row[f"{joint_name}_z"] = float(lm.z)
                row[f"{joint_name}_visibility"] = float(getattr(lm, "visibility", np.nan))
                row[f"{joint_name}_presence"] = float(getattr(lm, "presence", np.nan)) if hasattr(lm, "presence") else np.nan

                if world_landmarks is not None:
                    wlm = world_landmarks[joint_idx]
                    row[f"{joint_name}_wx"] = float(wlm.x)
                    row[f"{joint_name}_wy"] = float(wlm.y)
                    row[f"{joint_name}_wz"] = float(wlm.z)
                else:
                    row[f"{joint_name}_wx"] = np.nan
                    row[f"{joint_name}_wy"] = np.nan
                    row[f"{joint_name}_wz"] = np.nan

            rows.append(row)

    return pd.DataFrame(rows)


# 프레임에서 포즈가 감지되지 않은 경우, 모든 관절에 대해 NaN과 0으로 채운 행을 반환하는 함수입니다. 이 함수는 _extract_raw_dataframe에서 사용됩니다.

def _empty_row(frame_idx: int) -> Dict[str, float]:
    row = {
        "frame_idx": frame_idx,
        "pose_detected": 0,
        "frame_width": np.nan,
        "frame_height": np.nan,
    }
    for joint_name in CORE_JOINTS.keys():
        for suffix in ["_x", "_y", "_z", "_visibility", "_presence", "_wx", "_wy", "_wz"]:
            row[f"{joint_name}{suffix}"] = np.nan
    return row


# =========================
# Missing / interpolation / smoothing
# =========================

# 관절별로 visibility가 낮거나 좌표가 하나라도 nan인 경우를 missing으로 간주하여 boolean mask로 반환하는 함수입니다. pose_detected가 0인 프레임은 모든 관절이 missing으로 처리됩니다. 

def _compute_visibility_missing(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    pose_detected = df["pose_detected"].fillna(0).to_numpy(dtype=int)
    for joint in CORE_JOINTS.keys():
        x = df[f"{joint}_x"].to_numpy(dtype=float)
        y = df[f"{joint}_y"].to_numpy(dtype=float)
        wx = df[f"{joint}_wx"].to_numpy(dtype=float)
        wy = df[f"{joint}_wy"].to_numpy(dtype=float)
        wz = df[f"{joint}_wz"].to_numpy(dtype=float)
        vis = df[f"{joint}_visibility"].to_numpy(dtype=float)

        coords_exist = np.isfinite(x) & np.isfinite(y) & np.isfinite(wx) & np.isfinite(wy) & np.isfinite(wz)
        vis_missing = (pose_detected == 0) | (~coords_exist) | (~np.isfinite(vis)) | (vis < VISIBILITY_TH)
        out[joint] = vis_missing
    return out

# 신체 크기 정규화를 위해 어깨 너비의 중앙값을 계산하는 함수입니다. 양쪽 어깨가 모두 valid한 프레임에서 어깨 너비를 계산하여 중앙값을 구합니다. 만약 유효한 어깨 너비가 하나도 없다면 1.0을 반환합니다. 

def _compute_shoulder_width_median(df: pd.DataFrame, vis_missing: pd.DataFrame) -> float:
    l_ok = ~vis_missing["left_shoulder"].to_numpy(dtype=bool)
    r_ok = ~vis_missing["right_shoulder"].to_numpy(dtype=bool)
    both_ok = l_ok & r_ok

    lx = df["left_shoulder_x"].to_numpy(dtype=float)
    ly = df["left_shoulder_y"].to_numpy(dtype=float)
    rx = df["right_shoulder_x"].to_numpy(dtype=float)
    ry = df["right_shoulder_y"].to_numpy(dtype=float)

    widths = np.sqrt((rx - lx) ** 2 + (ry - ly) ** 2)
    widths = widths[both_ok & np.isfinite(widths)]
    if widths.size == 0:
        return 1.0
    med = float(np.median(widths))
    return med if med > 1e-6 else 1.0

# visibility missing과 어깨 너비 중앙값을 기반으로, 관절별로 프레임 간 이동이 너무 큰 경우를 motion missing으로 간주하여 boolean mask로 반환하는 함수입니다. 이동이 너무 큰 경우는 jump ratio (이동 거리 / 어깨 너비)가 joint별로 설정된 threshold를 초과하는 경우로 정의됩니다. visibility 기반 검사 통과 후에 검사합니다.

def _compute_motion_missing(df: pd.DataFrame, vis_missing: pd.DataFrame, shoulder_width_median: float) -> pd.DataFrame:
    out = pd.DataFrame(False, index=df.index, columns=CORE_JOINTS.keys(), dtype=bool)

    denom = shoulder_width_median if np.isfinite(shoulder_width_median) and shoulder_width_median > 1e-6 else 1.0

    for joint, th in MOTION_JUMP_RATIO_THRESHOLDS.items():
        prev_valid_pt: Optional[np.ndarray] = None
        xs = df[f"{joint}_x"].to_numpy(dtype=float)
        ys = df[f"{joint}_y"].to_numpy(dtype=float)
        joint_vis_missing = vis_missing[joint].to_numpy(dtype=bool)

        for i in range(len(df)):
            cur_pt = np.array([xs[i], ys[i]], dtype=float)

            if joint_vis_missing[i] or not np.all(np.isfinite(cur_pt)):
                continue

            if prev_valid_pt is not None:
                jump_px = euclidean_2d(prev_valid_pt, cur_pt)
                jump_ratio = jump_px / denom if np.isfinite(jump_px) else np.nan
                if np.isfinite(jump_ratio) and jump_ratio > th:
                    out.at[i, joint] = True
                    # current point is rejected -> do not update prev_valid_pt
                    continue

            prev_valid_pt = cur_pt

    return out


# 한 프레임에서 절반 이상 관절이 missing이면 그 프레임 전체를 나쁜 프레임으로 본다는 기준으로 missing_mask를 보정하는 함수입니다. 관절 몇개만 이상한지 보다는 프레임 전체가 너무 이상한 경우를 걸러내기 위한 것입니다. 절반 이상 missing이면 그 프레임 전체를 missing으로 처리합니다. 이렇게 하면 이후에 edge fill이나 interpolation이 더 안정적으로 작동할 수 있습니다. 

def _collapse_bad_frames(missing_mask: pd.DataFrame) -> pd.DataFrame:
    out = missing_mask.copy()
    joint_n = len(CORE_JOINTS)
    cutoff = math.ceil(joint_n / 2)  # 12 -> 6, i.e. "절반 이상"
    bad_frames = (out.sum(axis=1) >= cutoff)
    out.loc[bad_frames, :] = True
    return out

# 앞,뒤 쪽 full-missing 구간이 MAX_EDGE_FILL_FRAMES 이하인 경우, 가장 가까운 valid frame의 관절 좌표로 채워주는 함수입니다. edge fill은 프레임 시퀀스의 시작과 끝에서 발생하는 결측을 보완하기 위한 간단한 방법입니다. 너무 긴 구간은 채우지 않고 그대로 missing으로 남겨둡니다. edge fill이 적용된 프레임의 observed_mask는 0으로 설정하여 downstream에서 구분할 수 있도록 합니다.

def _apply_edge_fill(
    df: pd.DataFrame,
    missing_mask: pd.DataFrame,
    observed_mask: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    missing_mask = missing_mask.copy()
    observed_mask = observed_mask.copy()

    full_missing = missing_mask.all(axis=1).to_numpy(dtype=bool)
    n = len(full_missing)
    if n == 0:
        return df, missing_mask, observed_mask

    # leading full-missing run
    lead_len = 0
    while lead_len < n and full_missing[lead_len]:
        lead_len += 1
    if 0 < lead_len <= MAX_EDGE_FILL_FRAMES and lead_len < n:
        src_idx = lead_len
        for dst_idx in range(0, lead_len):
            for joint in CORE_JOINTS.keys():
                for suffix in ["_x", "_y", "_z", "_wx", "_wy", "_wz"]:
                    df.at[dst_idx, f"{joint}{suffix}"] = df.at[src_idx, f"{joint}{suffix}"]
                missing_mask.at[dst_idx, joint] = False
                observed_mask.at[dst_idx, joint] = 0

    # trailing full-missing run
    full_missing = missing_mask.all(axis=1).to_numpy(dtype=bool)
    tail_len = 0
    idx = n - 1
    while idx >= 0 and full_missing[idx]:
        tail_len += 1
        idx -= 1
    if 0 < tail_len <= MAX_EDGE_FILL_FRAMES and idx >= 0:
        src_idx = idx
        for dst_idx in range(src_idx + 1, n):
            for joint in CORE_JOINTS.keys():
                for suffix in ["_x", "_y", "_z", "_wx", "_wy", "_wz"]:
                    df.at[dst_idx, f"{joint}{suffix}"] = df.at[src_idx, f"{joint}{suffix}"]
                missing_mask.at[dst_idx, joint] = False
                observed_mask.at[dst_idx, joint] = 0

    return df, missing_mask, observed_mask

# 관절별로 missing이 True인 구간에서, max_gap 이하인 경우에만 양쪽 valid frame을 선형 보간하여 채워주는 함수입니다. 너무 긴 구간은 채우지 않고 그대로 missing으로 남겨둡니다. interpolation이 적용된 프레임의 observed_mask는 0으로 설정하여 downstream에서 구분할 수 있도록 합니다.

def _interpolate_short_gaps(values: np.ndarray, missing: np.ndarray, max_gap: int) -> Tuple[np.ndarray, np.ndarray]:
    out = values.astype(float).copy()
    interp_mask = np.zeros(len(out), dtype=bool)

    segments = contiguous_true_segments(missing)
    for s, e in segments:
        seg_len = e - s + 1
        left = s - 1
        right = e + 1
        if seg_len > max_gap:
            continue
        if left < 0 or right >= len(out):
            continue
        if missing[left] or missing[right]:
            continue
        if not (np.isfinite(out[left]) and np.isfinite(out[right])):
            continue
        out[s:e + 1] = np.linspace(out[left], out[right], seg_len + 2)[1:-1]
        interp_mask[s:e + 1] = True

    return out, interp_mask


# 위 함수들을 조합하여, raw DataFrame에서 visibility missing과 motion missing을 계산하여 combined missing을 구한 후, edge fill과 interpolation을 적용하여 보정된 좌표를 "_filt" suffix로 추가하는 함수입니다. 또한 observed_mask를 업데이트하여, 원래 valid이었지만 edge fill이나 interpolation이 적용된 프레임은 0으로 표시합니다. 최종적으로 보정된 DataFrame을 반환합니다. 만약 full-missing이 너무 긴 구간이 존재하면 None을 반환하여 시퀀스 전체를 폐기하도록 합니다.

def _apply_preprocessing(df: pd.DataFrame, fps: float) -> Optional[pd.DataFrame]:
    df = df.copy()

    vis_missing = _compute_visibility_missing(df)
    shoulder_width_median = _compute_shoulder_width_median(df, vis_missing)
    motion_missing = _compute_motion_missing(df, vis_missing, shoulder_width_median)

    combined_missing = vis_missing | motion_missing
    combined_missing = _collapse_bad_frames(combined_missing)

    # observed_mask: 1 = original valid observation, 0 = not original / filled / interpolated
    observed_mask = (~combined_missing).astype(int)

    # edge fill first 
    df, combined_missing, observed_mask = _apply_edge_fill(df, combined_missing, observed_mask)

    # discard if there are still >= 4 consecutive full-missing frames
    full_missing = combined_missing.all(axis=1).to_numpy(dtype=bool)
    if max_consecutive_true(full_missing) >= DISCARD_FULL_MISSING_RUN:
        return None

    for joint in CORE_JOINTS.keys():
        joint_missing = combined_missing[joint].to_numpy(dtype=bool)

        for suffix in ["_x", "_y", "_z", "_wx", "_wy", "_wz"]:
            raw = df[f"{joint}{suffix}"].to_numpy(dtype=float)
            raw[joint_missing] = np.nan
            interp_values, interp_mask = _interpolate_short_gaps(raw, joint_missing, MAX_INTERP_GAP_FRAMES)
            smooth_values = savgol_smooth_with_nans(interp_values, fps)
            df[f"{joint}{suffix}_filt"] = smooth_values

            # interpolation이 적용된 프레임은 observed_mask를 0으로 설정
            # _x만 하는 이유는 중복 업데이트를 굳이 안하고 joint 단위로 한 번만 업데이트하면 되기 때문입니다. _x, _y, _z, _wx, _wy, _wz 모두 같은 구간이 보간되므로, 하나의 suffix에서만 observed_mask를 0으로 설정해도 충분합니다.
            if suffix == "_x":
                observed_mask.loc[interp_mask, joint] = 0

        # unresolved missing stays 0
        unresolved = ~np.isfinite(df[f"{joint}_wx_filt"].to_numpy(dtype=float))
        observed_mask.loc[unresolved, joint] = 0

    # keep for downstream packing
    for joint in CORE_JOINTS.keys():
        df[f"{joint}_observed_mask"] = observed_mask[joint].to_numpy(dtype=int)

    return df


# =========================
# Normalization
# =========================

# 정규화를 위해 각 프레임에서 양쪽 엉덩이와 어깨 좌표를 사용하여 robust한 신체 크기 scale을 계산하는 함수입니다. 

def _robust_body_scale(df: pd.DataFrame) -> float:
    scales = []
   
    for i in range(len(df)):
        # 각 프레임에서 양쪽 엉덩이와 어깨 좌표를 가져옵니다. 이 좌표들은 이미 _apply_preprocessing에서 보정된 "_filt" 버전을 사용합니다. 

        lhip = np.array([
            df.at[i, "left_hip_wx_filt"],
            df.at[i, "left_hip_wy_filt"],
            df.at[i, "left_hip_wz_filt"],
        ], dtype=float)
        rhip = np.array([
            df.at[i, "right_hip_wx_filt"],
            df.at[i, "right_hip_wy_filt"],
            df.at[i, "right_hip_wz_filt"],
        ], dtype=float)
        lsho = np.array([
            df.at[i, "left_shoulder_wx_filt"],
            df.at[i, "left_shoulder_wy_filt"],
            df.at[i, "left_shoulder_wz_filt"],
        ], dtype=float)
        rsho = np.array([
            df.at[i, "right_shoulder_wx_filt"],
            df.at[i, "right_shoulder_wy_filt"],
            df.at[i, "right_shoulder_wz_filt"],
        ], dtype=float)

        # 양쪽 엉덩이와 어깨가 모두 valid한 프레임에서만 계산합니다.
        if not np.all(np.isfinite(np.concatenate([lhip, rhip, lsho, rsho]))):
            continue
        
        # 엉덩이 너비, 어깨 너비, 몸통 길이 (어깨-엉덩이 거리)을 계산하여 후보로 추가합니다. 이 세 가지 척도는 모두 신체 크기를 나타내는 지표로 사용할 수 있으며, 프레임마다 하나씩 계산하여 후보 리스트에 추가합니다. 이후에 중앙값을 구할 때, 이 세 가지 척도 중 유효한 값들을 모두 고려하여 보다 robust한 결과를 얻을 수 있습니다.

        hip_center = (lhip + rhip) / 2.0
        shoulder_center = (lsho + rsho) / 2.0
        hip_width = np.linalg.norm(rhip - lhip)
        shoulder_width = np.linalg.norm(rsho - lsho)
        torso_len = np.linalg.norm(shoulder_center - hip_center)

        # 유한한 값과 0에 가까운 값을 제외한 척도들을 후보로 추가합니다. 
        candidates = [v for v in [hip_width, shoulder_width, torso_len] if np.isfinite(v) and v > 1e-6]

        if len(candidates) >= 2:
            scales.append(float(np.median(candidates)))
    # 모든 프레임에서 유효한 척도가 하나도 없는 경우, 기본값으로 1.0을 반환합니다. 그렇지 않으면 후보 척도들의 중앙값을 반환합니다. 따라서 프레임의 중앙값들의 중앙값이 최종 body scale로 사용됩니다. 
    
    if len(scales) == 0:
        return 1.0
    return float(np.median(scales))

# 시퀀스에서 가장 좋은 reference frame을 선택하는 함수입니다. reference frame은 양쪽 엉덩이와 어깨가 모두 valid하고, visibility 평균이 가장 높은 프레임으로 선택합니다. 이 프레임의 좌표를 기준으로 나머지 프레임들의 좌표를 정규화할 때 사용할 기준 좌표계의 basis를 구축합니다.
 
def _select_reference_frame(df: pd.DataFrame) -> Optional[int]:
    # Simplified from the audit version: search all frames, not just the first 20%.
    best_idx = None
    best_score = -np.inf

    for i in range(len(df)):
        vals = []
        ok = True
        for joint in REFERENCE_JOINTS:
            coords = np.array([
                df.at[i, f"{joint}_wx_filt"],
                df.at[i, f"{joint}_wy_filt"],
                df.at[i, f"{joint}_wz_filt"],
            ], dtype=float)
            if not np.all(np.isfinite(coords)):
                ok = False
                break
            vis = float(df.at[i, f"{joint}_visibility"]) if f"{joint}_visibility" in df.columns else np.nan
            vals.append(vis)

        if not ok:
            continue
        mean_vis = float(np.nanmean(vals)) if len(vals) > 0 else -np.inf
        # 기준 좌표 축을 만들기 위해 양쪽 엉덩이와 어깨가 모두 valid한 프레임 중에서 visibility 평균이 가장 높은 프레임을 reference frame으로 선택합니다.
        if mean_vis > best_score:
            best_idx = i
            best_score = mean_vis

    return best_idx

# select_reference_frame에서 선택된 reference frame의 좌표를 사용하여 기준 좌표계의 basis를 구축하는 함수입니다. 기준 좌표계는 x축이 양쪽 엉덩이를 잇는 방향, y축이 어깨-엉덩이 방향, z축이 이 둘의 외적 방향이 되도록 정의됩니다. 만약 reference frame이 유효하지 않거나, basis 벡터가 제대로 계산되지 않는 경우에는 None을 반환합니다.

def _build_reference_basis(df: pd.DataFrame, ref_idx: int) -> Optional[np.ndarray]:
    lhip = np.array([
        df.at[ref_idx, "left_hip_wx_filt"],
        df.at[ref_idx, "left_hip_wy_filt"],
        df.at[ref_idx, "left_hip_wz_filt"],
    ], dtype=float)
    rhip = np.array([
        df.at[ref_idx, "right_hip_wx_filt"],
        df.at[ref_idx, "right_hip_wy_filt"],
        df.at[ref_idx, "right_hip_wz_filt"],
    ], dtype=float)
    lsho = np.array([
        df.at[ref_idx, "left_shoulder_wx_filt"],
        df.at[ref_idx, "left_shoulder_wy_filt"],
        df.at[ref_idx, "left_shoulder_wz_filt"],
    ], dtype=float)
    rsho = np.array([
        df.at[ref_idx, "right_shoulder_wx_filt"],
        df.at[ref_idx, "right_shoulder_wy_filt"],
        df.at[ref_idx, "right_shoulder_wz_filt"],
    ], dtype=float)

    if not np.all(np.isfinite(np.concatenate([lhip, rhip, lsho, rsho]))):
        return None

    hip_center = (lhip + rhip) / 2.0
    shoulder_center = (lsho + rsho) / 2.0

    x_axis = normalize_vec(rhip - lhip)
    if x_axis is None:
        return None

    y_temp = shoulder_center - hip_center
    z_axis = normalize_vec(np.cross(x_axis, y_temp))
    if z_axis is None:
        return None
    
    # z_axis와 x_axis가 유효하면, y_axis는 이 둘의 외적 방향이 됩니다. 이렇게 하면 기준 좌표계의 세 축이 서로 직교하도록 보장됩니다.
    y_axis = normalize_vec(np.cross(z_axis, x_axis))
    if y_axis is None:
        return None

    return np.stack([x_axis, y_axis, z_axis], axis=1)

# _build_reference_basis에서 만든 기준 좌표계를 사용하여, 각 프레임의 관절 좌표를 엉덩이 중심을 원점으로 하는 기준 좌표계로 변환한 후, robust body scale로 나누어 정규화하는 함수입니다. 정규화된 좌표는 "_norm_x", "_norm_y", "_norm_z" suffix로 저장됩니다. 만약 reference frame이 없거나, body scale이 유효하지 않으면 None을 반환하여 시퀀스 전체를 폐기하도록 합니다.

def _compute_normalized_landmarks(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    df = df.copy()

    ref_idx = _select_reference_frame(df)
    if ref_idx is None:
        return None

    ref_basis = _build_reference_basis(df, ref_idx)
    body_scale = _robust_body_scale(df)
    if ref_basis is None or not np.isfinite(body_scale) or body_scale <= 1e-8:
        return None
    
    for joint in CORE_JOINTS.keys():
        df[f"{joint}_norm_x"] = np.nan
        df[f"{joint}_norm_y"] = np.nan
        df[f"{joint}_norm_z"] = np.nan

    for i in range(len(df)):
        lhip = np.array([
            df.at[i, "left_hip_wx_filt"],
            df.at[i, "left_hip_wy_filt"],
            df.at[i, "left_hip_wz_filt"],
        ], dtype=float)
        rhip = np.array([
            df.at[i, "right_hip_wx_filt"],
            df.at[i, "right_hip_wy_filt"],
            df.at[i, "right_hip_wz_filt"],
        ], dtype=float)

        if not np.all(np.isfinite(np.concatenate([lhip, rhip]))):
            continue
        
        # 상대좌표의 원점을 엉덩이 중심으로 설정합니다 
        hip_center = (lhip + rhip) / 2.0

        for joint in CORE_JOINTS.keys():
            p = np.array([
                df.at[i, f"{joint}_wx_filt"],
                df.at[i, f"{joint}_wy_filt"],
                df.at[i, f"{joint}_wz_filt"],
            ], dtype=float)
            if not np.all(np.isfinite(p)):
                continue
        
        # rel_world(mediapipe의 3d좌표계)에서 ref_basis(기준 좌표계의 basis)를 곱하여, rel(기준 좌표계에서의 상대좌표)을 구합니다. 이렇게 하면 기준 좌표계의 x, y, z 축에 대한 상대좌표가 계산됩니다. 이후에 body scale로 나누어 정규화된 좌표를 얻습니다. 
        # 원래는 world(mediapipe 3d)의 기준좌표계를 벡터로 표현하면 (0,0,0)이고 build_reference_basis에서 선택된 basis를 world 기준 좌표계를 벡터로 표현하면 [x_axis], [y_axis], [z_axis]]이 됩니다. 그런데 basis의 벡터를 (0,0,0)인 world 좌표계에서의 좌표로 생각하면, basis.T @ rel_world는 rel_world를 basis의 좌표계로 변환하는 연산이 됩니다. 즉, basis의 x_axis 방향으로 rel_world가 얼마나 있는지, y_axis 방향으로는 얼마나 있는지, z_axis 방향으로는 얼마나 있는지를 계산하는 것입니다. 
            rel_world = p - hip_center
            rel = ref_basis.T @ rel_world
            norm = rel / body_scale
            df.at[i, f"{joint}_norm_x"] = float(norm[0])
            df.at[i, f"{joint}_norm_y"] = float(norm[1])
            df.at[i, f"{joint}_norm_z"] = float(norm[2])

    return df



# =========================
# Final packing
# =========================

# 최종 출력 DataFrame을 패킹하는 함수입니다. 각 관절에 대해 "_norm_x", "_norm_y", "_norm_z", "_observed_mask" 컬럼을 사용하여 (norm_x, norm_y, norm_z, observed_mask) 튜플을 만들어 "norm_{joint}" 컬럼에 저장합니다.
def _pack_output_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)

    for joint in CORE_JOINTS.keys():
        tuples = []
        xs = df[f"{joint}_norm_x"].to_numpy(dtype=float)
        ys = df[f"{joint}_norm_y"].to_numpy(dtype=float)
        zs = df[f"{joint}_norm_z"].to_numpy(dtype=float)
        ms = df[f"{joint}_observed_mask"].to_numpy(dtype=int)

        for x, y, z, m in zip(xs, ys, zs, ms):
            tuples.append(tuple_or_missing(x, y, z, m))

        out[f"norm_{joint}"] = tuples

    return out


# =========================
# Public API
# =========================

def extract_pose(roi_frames: List[np.ndarray], fps: float) -> Optional[pd.DataFrame]:
    """
    Extract normalized pose tuples from ROI frames.

    Returns:
        pd.DataFrame with columns:
            norm_left_shoulder, norm_right_shoulder,
            norm_left_elbow, norm_right_elbow,
            norm_left_wrist, norm_right_wrist,
            norm_left_hip, norm_right_hip,
            norm_left_knee, norm_right_knee,
            norm_left_ankle, norm_right_ankle

        Each cell is:
            (norm_x, norm_y, norm_z, observed_mask)

        If the sequence should be discarded, returns None.
    """
    if roi_frames is None or len(roi_frames) == 0:
        return None

    raw_df = _extract_raw_dataframe(roi_frames, fps)
    pre_df = _apply_preprocessing(raw_df, fps)
    if pre_df is None:
        return None

    norm_df = _compute_normalized_landmarks(pre_df)
    if norm_df is None:
        return None

    return _pack_output_dataframe(norm_df)


