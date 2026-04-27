from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np
import pandas as pd

from modules.utils.pose_landmarker import create_landmarker, DEFAULT_MEDIAPIPE_MODEL_PATH
from modules.utils.pose_utils import POSE_JOINTS
from modules.utils.pose_preprocessing import apply_preprocessing, pack_output_arrays


def _empty_row(frame_idx: int) -> Dict[str, float]:
    """
    포즈가 검출되지 않았을 때 반환할 빈 row
    """
    row = {
        "frame_idx": frame_idx,
        "pose_detected": 0,
        "frame_width": np.nan,
        "frame_height": np.nan,
    }

    for joint_name in POSE_JOINTS.keys():
        for suffix in ["_x", "_y", "_z", "_visibility", "_presence"]:
            row[f"{joint_name}{suffix}"] = np.nan

    return row


def _extract_raw_dataframe(
    landmarker: Any,
    roi_frames: List[Optional[np.ndarray]],
    roi_infos: List[Optional[dict]],
    fps: float,
) -> pd.DataFrame:
    """
    ROI 프레임들에 대해 MediaPipe raw landmark dataframe 생성
    """
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

        if len(result.pose_landmarks) == 0:
            for joint_name in POSE_JOINTS.keys():
                for suffix in ["_x", "_y", "_z", "_visibility", "_presence"]:
                    row[f"{joint_name}{suffix}"] = np.nan
            rows.append(row)
            continue

        landmarks = result.pose_landmarks[0]

        for joint_name, joint_idx in POSE_JOINTS.items():
            lm = landmarks[joint_idx]

            row[f"{joint_name}_x"] = float(lm.x * width)
            row[f"{joint_name}_y"] = float(lm.y * height)
            row[f"{joint_name}_z"] = float(lm.z)
            row[f"{joint_name}_visibility"] = float(getattr(lm, "visibility", np.nan))
            row[f"{joint_name}_presence"] = (
                float(getattr(lm, "presence", np.nan))
                if hasattr(lm, "presence") else np.nan
            )

        rows.append(row)

    return pd.DataFrame(rows)


def extract_pose_with_roi(
    roi_frames: List[Optional[np.ndarray]],
    roi_infos: List[Optional[dict]],
    fps: float,
    model_path: Optional[str] = None,
) -> Optional[Tuple[
    List[np.ndarray],
    List[np.ndarray],
    List[np.ndarray],
    List[np.ndarray],
]]:
    """
    ROI 프레임에서 pose를 추출하고,
    원본 프레임 좌표계로 복원한 landmark 리스트를 반환

    Returns:
        all_landmarks: frame마다 shape (12, 4)
        wrist_landmarks: frame마다 shape (2, 4)
        visibility: frame마다 shape (12,)
        bat_landmarks: frame마다 shape (6, 4)

    Notes:
        - 영상 1개 처리 시 landmarker는 내부에서 1회 생성됩니다.
    """
    if roi_frames is None or roi_infos is None:
        return None
    if len(roi_frames) == 0 or len(roi_infos) == 0:
        return None
    if len(roi_frames) != len(roi_infos):
        raise ValueError("roi_frames와 roi_infos의 길이가 같아야 합니다.")

    if model_path is None:
        model_path = DEFAULT_MEDIAPIPE_MODEL_PATH
    
    with create_landmarker(model_path) as local_landmarker:
        raw_df = _extract_raw_dataframe(local_landmarker, roi_frames, roi_infos, fps)

    pre_df = apply_preprocessing(raw_df, fps)
    if pre_df is None:
        return None

    return pack_output_arrays(pre_df, roi_infos)