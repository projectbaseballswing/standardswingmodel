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



# =========================
# User-editable settings
# =========================


# Landmark is considered missing if visibility is below this threshold or non-finite.

VISIBILITY_TH = 0.45   
MAX_INTERP_GAP_FRAMES = 4
MAX_EDGE_FILL_FRAMES = 4

# Savitzky-Golay filter settings for smoothing after interpolation.
SG_POLYORDER = 2
SG_MIN_WINDOW = 5
SG_MAX_WINDOW = 11
SG_WINDOW_SEC = 0.12

# Motion jump ratio thresholds (relative to shoulder width) for each joint.
# 기준은 배정대, 허경민, 강백호, 김강민, 정훈, 한동희 영상 데이터셋에서 구한 결과를 기반으로 jump ratio의 threshold를 joint별로 다르게 설정한 것입니다. 일단은 일괄적으로 0.5로 설정하려다가, 관절별로 jump ratio의 분포가 꽤 달라서 joint별로 다르게 설정하는 것이 낫겠다고 판단해서 이렇게 설정함. 향후 데이터셋이 확정되면 다시 검증해보고 조정하겠습니다.

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

OUTPUT_JOINT_ORDER: List[str] = [
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
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


# =========================
# MediaPipe
# =========================

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



# =========================
# Raw extraction
# =========================

# 프레임에서 포즈가 감지되지 않은 경우, 모든 관절에 대해 NaN과 0으로 채운 행을 반환
def _empty_row(frame_idx: int) -> Dict[str, float]:
    row = {
        "frame_idx": frame_idx,
        "pose_detected": 0,
        "frame_width": np.nan,
        "frame_height": np.nan,
    }
    for joint_name in CORE_JOINTS.keys():
        for suffix in ["_x", "_y", "_z", "_visibility", "_presence"]:
            row[f"{joint_name}{suffix}"] = np.nan
    return row



def _extract_raw_dataframe(
    landmarker,
    roi_frames: List[np.ndarray],
    roi_infos: List[Optional[dict]],
    fps: float,
) -> pd.DataFrame:
    rows = []
    for frame_idx, (frame, roi_info) in enumerate(zip(roi_frames, roi_infos)):
        if frame is None or roi_info is None:
            rows.append(_empty_row(frame_idx))
            continue

        height, width = frame.shape[:2]
        timestamp_ms = int((frame_idx / fps) * 1000) if fps > 0 else frame_idx * 33

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
        )
        result = landmarker.detect_for_video(mp_image, timestamp_ms)

        row = {
            "frame_idx": frame_idx,
            "pose_detected": int(len(result.pose_landmarks) > 0),
            "frame_width": width,
            "frame_height": height,
        }
        
        # 포즈가 검출되지 않으면 해당 프레임의 모든 핵심 관절 값을 NaN으로 채운다.
        if len(result.pose_landmarks) == 0:
            for joint_name in CORE_JOINTS.keys():
                for suffix in ["_x", "_y", "_z", "_visibility", "_presence"]:
                    row[f"{joint_name}{suffix}"] = np.nan
            rows.append(row)
            continue

        landmarks = result.pose_landmarks[0]
        for joint_name, joint_idx in CORE_JOINTS.items():
            lm = landmarks[joint_idx]
            # mediapipe의 x, y는 프레임의 normalized 좌표이므로 ROI frame 크기를 곱해 픽셀 좌표로 변환한다
            row[f"{joint_name}_x"] = float(lm.x * width)
            row[f"{joint_name}_y"] = float(lm.y * height)
            row[f"{joint_name}_z"] = float(lm.z)
            row[f"{joint_name}_visibility"] = float(getattr(lm, "visibility", np.nan))
            row[f"{joint_name}_presence"] = float(getattr(lm, "presence", np.nan)) if hasattr(lm, "presence") else np.nan

        rows.append(row)

    return pd.DataFrame(rows)



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
        z = df[f"{joint}_z"].to_numpy(dtype=float)
        vis = df[f"{joint}_visibility"].to_numpy(dtype=float)

        coords_exist = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
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


# 한 프레임에서 절반 이상 관절이 missing이면 그 프레임 전체를 나쁜 프레임으로 본다는 기준으로 missing_mask를 보정하는 함수입니다. 절반 이상 missing이면 그 프레임 전체를 missing으로 처리합니다. 이렇게 하면 이후에 edge fill이나 interpolation이 더 안정적으로 작동할 수 있습니다. 

def _collapse_bad_frames(missing_mask: pd.DataFrame) -> pd.DataFrame:
    out = missing_mask.copy()
    joint_n = len(CORE_JOINTS)
    cutoff = math.ceil(joint_n / 2)  # 12 -> 6, i.e. "절반 이상"
    bad_frames = (out.sum(axis=1) >= cutoff)
    out.loc[bad_frames, :] = True
    return out

# 앞,뒤 쪽 full-missing 구간이 MAX_EDGE_FILL_FRAMES 이하인 경우, 가장 가까운 valid frame의 관절 좌표로 채워주는 함수입니다. edge fill은 프레임 시퀀스의 시작과 끝에서 발생하는 결측을 보완하기 위한 간단한 방법입니다. 너무 긴 구간은 채우지 않고 그대로 missing으로 남겨둡니다. 

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
        for dst_idx in range(lead_len):
            for joint in CORE_JOINTS.keys():
                for suffix in ["_x", "_y", "_z"]:
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
                for suffix in ["_x", "_y", "_z"]:
                    df.at[dst_idx, f"{joint}{suffix}"] = df.at[src_idx, f"{joint}{suffix}"]
                missing_mask.at[dst_idx, joint] = False
                observed_mask.at[dst_idx, joint] = 0

    return df, missing_mask, observed_mask

# 관절별로 missing이 True인 구간에서, max_gap 이하인 경우에만 양쪽 valid frame을 선형 보간하여 채워주는 함수입니다. 너무 긴 구간은 채우지 않고 그대로 missing으로 남겨둡니다.

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


# 위 함수들을 조합하여, raw DataFrame에서 visibility missing과 motion missing을 계산하여 combined missing을 구한 후, edge fill과 interpolation을 적용하여 보정된 좌표를 "_filt" suffix로 추가하는 함수입니다. 또한 observed_mask를 업데이트하여, 원래 valid이었지만 edge fill이나 interpolation이 적용된 프레임은 0으로 표시합니다. 최종적으로 보정된 DataFrame을 반환합니다. 

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


    for joint in CORE_JOINTS.keys():
        joint_missing = combined_missing[joint].to_numpy(dtype=bool)

        for suffix in ["_x", "_y", "_z"]:
            raw = df[f"{joint}{suffix}"].to_numpy(dtype=float)
            raw[joint_missing] = np.nan
            interp_values, interp_mask = _interpolate_short_gaps(raw, joint_missing, MAX_INTERP_GAP_FRAMES)
            smooth_values = savgol_smooth_with_nans(interp_values, fps)
            df[f"{joint}{suffix}_filt"] = smooth_values


            # interpolation이 적용된 프레임은 observed_mask를 0으로 설정
            # _x, _y, _z 모두 같은 구간이 보간되므로, _x에서 한 번 업데이트하면 됩니다.
            if suffix == "_x":
                observed_mask.loc[interp_mask, joint] = 0

        # unresolved missing stays 0
        unresolved = ~np.isfinite(df[f"{joint}_x_filt"].to_numpy(dtype=float))
        observed_mask.loc[unresolved, joint] = 0

        df[f"{joint}_observed_mask"] = observed_mask[joint].to_numpy(dtype=int)

    return df


# =========================
# ROI -> original frame restoration
# =========================
def restore_landmarks_to_original_frame(
    landmarks: np.ndarray,
    roi_info: Optional[dict],
) -> np.ndarray:
   
    restored = np.full_like(landmarks, np.nan, dtype=float)
    if landmarks.size == 0:
        return restored

    if roi_info is None:
        restored[:, 3] = 0.0
        return restored

    scale = float(roi_info.get("scale", np.nan))
    x1 = float(roi_info.get("x1", np.nan))
    y1 = float(roi_info.get("y1", np.nan))
    x_offset = float(roi_info.get("x_offset", np.nan))
    y_offset = float(roi_info.get("y_offset", np.nan))

    if not (np.isfinite(scale) and scale > 1e-8 and np.isfinite(x1) and np.isfinite(y1) and np.isfinite(x_offset) and np.isfinite(y_offset)):
        restored[:, 3] = 0.0
        return restored

    for i, row in enumerate(landmarks):
        x, y, z, observed_mask = row
        if not (np.isfinite(x) and np.isfinite(y) and np.isfinite(z)):
            restored[i] = np.array([np.nan, np.nan, np.nan, 0.0], dtype=float)
            continue

        original_x = (x - x_offset) / scale + x1
        original_y = (y - y_offset) / scale + y1
        original_z = z / scale
        restored[i] = np.array([original_x, original_y, original_z, float(observed_mask)], dtype=float)

    return restored


# =========================
# Final packing
# =========================

def _pack_output_arrays(
    df: pd.DataFrame,
    roi_infos: List[Optional[dict]],
) -> Tuple[List[np.ndarray], List[np.ndarray]]:
    
    all_landmarks: List[np.ndarray] = []
    wrist_landmarks: List[np.ndarray] = []

    for i in range(len(df)):
        frame_landmarks = []
        for joint in OUTPUT_JOINT_ORDER:
            x = float(df.at[i, f"{joint}_x_filt"])
            y = float(df.at[i, f"{joint}_y_filt"])
            z = float(df.at[i, f"{joint}_z_filt"])
            observed_mask = int(df.at[i, f"{joint}_observed_mask"])

            if not (np.isfinite(x) and np.isfinite(y) and np.isfinite(z)):
                frame_landmarks.append(np.array([np.nan, np.nan, np.nan, 0.0], dtype=float))
            else:
                frame_landmarks.append(np.array([x, y, z, float(observed_mask)], dtype=float))

        frame_landmarks_arr = np.stack(frame_landmarks, axis=0)
        restored_frame_landmarks = restore_landmarks_to_original_frame(frame_landmarks_arr, roi_infos[i])

        all_landmarks.append(restored_frame_landmarks)
        wrist_landmarks.append(restored_frame_landmarks[4:6].copy())

    return all_landmarks, wrist_landmarks


# =========================
# Public API
# =========================
def extract_pose_with_roi(
    roi_frames: List[np.ndarray],
    roi_infos: List[Optional[dict]],
    fps: float,
) -> Optional[Tuple[List[np.ndarray], List[np.ndarray]]]:
    """
    Returns:
        all_landmarks: List[np.ndarray]
            each frame -> shape (12, 4)
            row order:
                left_shoulder, right_shoulder,
                left_elbow, right_elbow,
                left_wrist, right_wrist,
                left_hip, right_hip,
                left_knee, right_knee,
                left_ankle, right_ankle
            columns:
                [x_restored, y_restored, z_restored, observed_mask]

        wrist_landmarks: List[np.ndarray]
            each frame -> shape (2, 4)
            row order:
                left_wrist, right_wrist
            columns:
                [x_restored, y_restored, z_restored, observed_mask]

        None if the sequence should be discarded.
    """
    if roi_frames is None or roi_infos is None:
        return None
    if len(roi_frames) == 0 or len(roi_infos) == 0:
        return None
    if len(roi_frames) != len(roi_infos):
        raise ValueError("roi_frames와 roi_infos의 길이가 같아야 합니다.")

    with create_landmarker(MODEL_PATH) as landmarker :
        raw_df = _extract_raw_dataframe(landmarker, roi_frames, roi_infos, fps)
    pre_df = _apply_preprocessing(raw_df, fps)
    if pre_df is None:
        return None

    return _pack_output_arrays(pre_df, roi_infos)

