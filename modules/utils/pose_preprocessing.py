from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

from modules.utils.pose_utils import (
    BAT_JOINT_ORDER,
    CORE_JOINTS,
    POSE_JOINTS,
    MOTION_JUMP_RATIO_THRESHOLDS,
    OUTPUT_JOINT_ORDER,
    VISIBILITY_TH,
    VISIBILITY_THRESHOLDS,
    MAX_EDGE_FILL_FRAMES,
    MAX_INTERP_GAP_FRAMES,
    MAX_INTERP_GAP_FRAMES_BY_JOINT,
    SG_POLYORDER,
    contiguous_true_segments,
    choose_savgol_window,
    euclidean_2d,
)


def savgol_smooth_with_nans(arr: np.ndarray, fps: float) -> np.ndarray:
    """
    NaN이 포함된 배열에서 NaN이 아닌 연속 구간마다 Savitzky-Golay smoothing 적용
    """
    out = arr.astype(float).copy()
    valid = np.isfinite(out)

    for s, e in contiguous_true_segments(valid):
        seg = out[s:e + 1]
        window = choose_savgol_window(fps, len(seg))
        if window is None or len(seg) < window or window <= SG_POLYORDER:
            continue

        try:
            out[s:e + 1] = savgol_filter(
                seg,
                window_length=window,
                polyorder=SG_POLYORDER,
                mode="interp",
            )
        except Exception:
            continue

    return out


def compute_visibility_missing(df: pd.DataFrame) -> pd.DataFrame:
    """
    visibility가 낮거나 좌표가 NaN이면 missing 처리
    pose_detected == 0 인 프레임은 모든 관절 missing 처리
    """
    out = pd.DataFrame(index=df.index)
    pose_detected = df["pose_detected"].fillna(0).to_numpy(dtype=int)

    for joint in POSE_JOINTS.keys():
        x = df[f"{joint}_x"].to_numpy(dtype=float)
        y = df[f"{joint}_y"].to_numpy(dtype=float)
        z = df[f"{joint}_z"].to_numpy(dtype=float)
        vis = df[f"{joint}_visibility"].to_numpy(dtype=float)

        coords_exist = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
        visibility_th = VISIBILITY_THRESHOLDS.get(joint, VISIBILITY_TH)

        vis_missing = (
            (pose_detected == 0)
            | (~coords_exist)
            | (~np.isfinite(vis))
            | (vis < visibility_th)
        )
        out[joint] = vis_missing

    return out


def compute_shoulder_width_median(df: pd.DataFrame, vis_missing: pd.DataFrame) -> float:
    """
    양쪽 어깨가 valid한 프레임들에서 어깨 너비 중앙값 계산
    jump ratio 정규화용
    """
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


def compute_motion_missing(
    df: pd.DataFrame,
    vis_missing: pd.DataFrame,
    shoulder_width_median: float,
) -> pd.DataFrame:
    """
    프레임 간 이동이 너무 큰 점을 motion missing으로 처리
    jump_ratio = 이동거리 / 어깨너비 중앙값
    """
    out = pd.DataFrame(False, index=df.index, columns=POSE_JOINTS.keys(), dtype=bool)

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
                    continue

            prev_valid_pt = cur_pt

    return out


def collapse_bad_frames(missing_mask: pd.DataFrame) -> pd.DataFrame:
    """
    한 프레임에서 절반 이상 관절이 missing이면 해당 프레임 전체를 missing 처리
    pinky/index 같은 보조 hand landmark는 이 판정 기준에는 포함하지 않습니다.
    """
    out = missing_mask.copy()
    core_cols = list(CORE_JOINTS.keys())
    cutoff = math.ceil(len(core_cols) / 2)
    bad_frames = (out[core_cols].sum(axis=1) >= cutoff)
    out.loc[bad_frames, :] = True
    return out


def apply_edge_fill(
    df: pd.DataFrame,
    missing_mask: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    영상 시작/끝의 짧은 full-missing 구간은 가장 가까운 valid 프레임 값으로 채움.
    """
    df = df.copy()
    missing_mask = missing_mask.copy()

    full_missing = missing_mask.all(axis=1).to_numpy(dtype=bool)
    n = len(full_missing)

    if n == 0:
        return df, missing_mask

    # 시작 부분 full-missing
    lead_len = 0
    while lead_len < n and full_missing[lead_len]:
        lead_len += 1

    if 0 < lead_len <= MAX_EDGE_FILL_FRAMES and lead_len < n:
        src_idx = lead_len
        for dst_idx in range(lead_len):
            for joint in POSE_JOINTS.keys():
                for suffix in ["_x", "_y", "_z"]:
                    df.at[dst_idx, f"{joint}{suffix}"] = df.at[src_idx, f"{joint}{suffix}"]
                missing_mask.at[dst_idx, joint] = False

    # 끝 부분 full-missing
    full_missing = missing_mask.all(axis=1).to_numpy(dtype=bool)
    tail_len = 0
    idx = n - 1
    while idx >= 0 and full_missing[idx]:
        tail_len += 1
        idx -= 1

    if 0 < tail_len <= MAX_EDGE_FILL_FRAMES and idx >= 0:
        src_idx = idx
        for dst_idx in range(src_idx + 1, n):
            for joint in POSE_JOINTS.keys():
                for suffix in ["_x", "_y", "_z"]:
                    df.at[dst_idx, f"{joint}{suffix}"] = df.at[src_idx, f"{joint}{suffix}"]
                missing_mask.at[dst_idx, joint] = False

    return df, missing_mask


def interpolate_short_gaps(
    values: np.ndarray,
    missing: np.ndarray,
    max_gap: int,
) -> np.ndarray:
    """
    짧은 missing 구간만 선형 보간.
    """
    out = values.astype(float).copy()
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

    return out


def apply_preprocessing(df: pd.DataFrame, fps: float) -> Optional[pd.DataFrame]:
    """
    raw landmark dataframe에 대해
    visibility missing + motion missing + edge fill + interpolation + smoothing 적용.
    """
    df = df.copy()

    vis_missing = compute_visibility_missing(df)
    shoulder_width_median = compute_shoulder_width_median(df, vis_missing)
    motion_missing = compute_motion_missing(df, vis_missing, shoulder_width_median)

    combined_missing = vis_missing | motion_missing
    combined_missing = collapse_bad_frames(combined_missing)

    df, combined_missing = apply_edge_fill(df, combined_missing)

    for joint in POSE_JOINTS.keys():
        joint_missing = combined_missing[joint].to_numpy(dtype=bool)

        for suffix in ["_x", "_y", "_z"]:
            raw = df[f"{joint}{suffix}"].to_numpy(dtype=float).copy()
            raw[joint_missing] = np.nan

            max_interp_gap = MAX_INTERP_GAP_FRAMES_BY_JOINT.get(
                joint,
                MAX_INTERP_GAP_FRAMES,
            )

            interp_values = interpolate_short_gaps(
                raw,
                joint_missing,
                max_interp_gap,
            )
            smooth_values = savgol_smooth_with_nans(interp_values, fps)
            df[f"{joint}{suffix}_filt"] = smooth_values

    return df


def restore_landmarks_to_original_frame(
    landmarks: np.ndarray,
    roi_info: Optional[dict],
) -> np.ndarray:
    """
    ROI 좌표계를 원본 프레임 좌표계로 복원.

    Input/Output shape:
        (N, 3) = [x, y, z]
    """
    landmarks = np.asarray(landmarks, dtype=float)

    if landmarks.ndim != 2 or landmarks.shape[1] != 3:
        raise ValueError("landmarks는 shape (N, 3)인 배열이어야 합니다.")

    restored = np.full_like(landmarks, np.nan, dtype=float)

    if landmarks.size == 0:
        return restored

    if roi_info is None:
        return restored

    scale = float(roi_info.get("scale", np.nan))
    x1 = float(roi_info.get("x1", np.nan))
    y1 = float(roi_info.get("y1", np.nan))
    x_offset = float(roi_info.get("x_offset", np.nan))
    y_offset = float(roi_info.get("y_offset", np.nan))

    if not (
        np.isfinite(scale) and scale > 1e-8
        and np.isfinite(x1) and np.isfinite(y1)
        and np.isfinite(x_offset) and np.isfinite(y_offset)
    ):
        return restored

    for i, row in enumerate(landmarks):
        x, y, z = row

        if not (np.isfinite(x) and np.isfinite(y) and np.isfinite(z)):
            restored[i] = np.array([np.nan, np.nan, np.nan], dtype=float)
            continue

        original_x = (x - x_offset) / scale + x1
        original_y = (y - y_offset) / scale + y1
        original_z = z / scale

        restored[i] = np.array([original_x, original_y, original_z], dtype=float)

    return restored


def _pack_joint_array(df: pd.DataFrame, frame_idx: int, joint_order: List[str]) -> np.ndarray:
    """
    지정된 joint_order에 맞춰 한 프레임의 [x_filt, y_filt, z_filt] 배열 생성.
    """
    frame_landmarks = []

    for joint in joint_order:
        x = float(df.at[frame_idx, f"{joint}_x_filt"])
        y = float(df.at[frame_idx, f"{joint}_y_filt"])
        z = float(df.at[frame_idx, f"{joint}_z_filt"])

        if not (np.isfinite(x) and np.isfinite(y) and np.isfinite(z)):
            frame_landmarks.append(np.array([np.nan, np.nan, np.nan], dtype=float))
        else:
            frame_landmarks.append(np.array([x, y, z], dtype=float))

    return np.stack(frame_landmarks, axis=0)

def _pack_visibility_array(df: pd.DataFrame, frame_idx: int, joint_order: List[str]) -> np.ndarray:
    """
    normalize_landmarks_sequence에 넘길 visibility 배열 생성.
    보간/채움/결측 좌표는 reference frame 선택에 쓰이지 않도록 visibility를 0으로 둡니다.
    """
    values = []

    for joint in joint_order:
        vis = float(df.at[frame_idx, f"{joint}_visibility"])

        if not np.isfinite(vis):
            values.append(0.0)
        else:
            values.append(vis)

    return np.asarray(values, dtype=float)



def pack_output_arrays(
    df: pd.DataFrame,
    roi_infos: List[Optional[dict]],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    후처리된 dataframe을 최종 출력 형식으로 변환
    """
    all_landmarks: List[np.ndarray] = []
    visibility: List[np.ndarray] = []
    bat_landmarks: List[np.ndarray] = []

    for i in range(len(df)):
        core_arr = _pack_joint_array(df, i, OUTPUT_JOINT_ORDER)
        restored_core = restore_landmarks_to_original_frame(core_arr, roi_infos[i])

        bat_arr = _pack_joint_array(df, i, BAT_JOINT_ORDER)
        restored_bat = restore_landmarks_to_original_frame(bat_arr, roi_infos[i])

        all_landmarks.append(restored_core)
        visibility.append(_pack_visibility_array(df, i, OUTPUT_JOINT_ORDER))
        bat_landmarks.append(restored_bat)

    return (
        np.asarray(all_landmarks, dtype=float),
        np.asarray(visibility, dtype=float),
        np.asarray(bat_landmarks, dtype=float),
    )