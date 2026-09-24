"""영상 1개 -> (80, 67) 스윙 피처.

modules/open_cv.py 의 process_video 와 같은 순서로 처리한다.
서버에서 쓰기 위해 cv2.imshow 확인 창을 없애고, 실패하면 PipelineError 를 던진다.
"""

from __future__ import annotations

import contextlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np

from feedback.features import IMPACT_FRAME, JOINT_NAMES, SEQUENCE_LEN
from feedback.reference import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_YOLO_WEIGHTS = PROJECT_ROOT / "weights" / "custom_yolo_model5.pt"
DEFAULT_POSE_MODEL = PROJECT_ROOT / "models" / "pose_landmarker.task"

# process_video 와 같은 기준: 타자 bbox 가 30프레임 이상 연속으로 비면 분석하지 않는다
MAX_MISSING_GAP = 30
LOW_VISIBILITY = 0.5


class PipelineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PipelineResult:
    features: np.ndarray  # (80, 67)
    fps: float
    quality: Dict[str, Any] = field(default_factory=dict)


def _resample(sequence: np.ndarray, src_fps: float, dst_fps: float) -> np.ndarray:
    """(T, ...) 시퀀스를 선형 보간으로 dst_fps 에 맞춘다."""
    n_src = sequence.shape[0]
    duration = (n_src - 1) / src_fps
    n_dst = int(round(duration * dst_fps)) + 1
    src_t = np.arange(n_src) / src_fps
    dst_t = np.arange(n_dst) / dst_fps
    flat = sequence.reshape(n_src, -1)
    out = np.empty((n_dst, flat.shape[1]), dtype=float)
    for col in range(flat.shape[1]):
        values = flat[:, col]
        valid = np.isfinite(values)
        out[:, col] = np.interp(dst_t, src_t[valid], values[valid]) if valid.any() else np.nan
    return out.reshape((n_dst,) + sequence.shape[1:])


class SwingPipeline:
    def __init__(
        self,
        yolo_weights: Path = DEFAULT_YOLO_WEIGHTS,
        pose_model: Path = DEFAULT_POSE_MODEL,
        target_fps: Optional[float] = 30.0,
    ):
        # 무거운 의존성은 영상 분석을 실제로 쓸 때만 import 한다
        from ultralytics import YOLO

        self.yolo_model = YOLO(str(yolo_weights))
        self.pose_model = str(pose_model)
        self.target_fps = target_fps

    def run(
        self,
        video_path: str,
        is_left: bool,
        on_stage: Optional[Callable[[str], None]] = None,
    ) -> PipelineResult:
        import cv2

        from modules.extract_pose_with_roi import extract_pose_with_roi
        from modules.preprocessing import preprocess_player
        from modules.utils.features_add import _find_impact_frame, make_features_single_video
        from modules.utils.video_roi_left import normalize_landmarks_sequence, process_roi, read_video
        from modules.yolo_obb_tracker import track_target_player

        def stage(name: str) -> None:
            logger.info("[pipeline] %s", name)
            if on_stage:
                on_stage(name)

        # 기존 모듈의 확인용 print 는 서버 로그에서 숨기고 debug 로만 남긴다
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stage("reading_video")
            try:
                frames, fps = read_video(video_path)
            except ValueError as exc:
                raise PipelineError("INVALID_VIDEO", str(exc)) from exc
            if not frames:
                raise PipelineError("INVALID_VIDEO", "영상에서 프레임을 읽지 못했습니다.")
            if is_left:
                frames = [cv2.flip(frame, 1) for frame in frames]
            height, width = frames[0].shape[:2]

            stage("tracking_player")
            player_df = track_target_player(self.yolo_model, frames)
            if player_df is None:
                raise PipelineError("PLAYER_NOT_FOUND", "영상에서 타자를 찾지 못했습니다.")
            player_np, max_missing_gap = preprocess_player(player_df, width, height)
            if max_missing_gap >= MAX_MISSING_GAP:
                raise PipelineError(
                    "TRACKING_GAP_TOO_LONG",
                    f"타자를 {max_missing_gap}프레임 연속으로 놓쳤습니다 (기준 {MAX_MISSING_GAP}프레임).",
                )

            stage("extracting_pose")
            roi_frames, roi_infos = [], []
            for frame, bbox in zip(frames, player_np):
                roi, roi_info = process_roi(frame, bbox, target_size=256, pad=20)
                roi_frames.append(roi)
                roi_infos.append(roi_info)
            del frames

            pose_result = extract_pose_with_roi(roi_frames, roi_infos, fps, model_path=self.pose_model)
            if pose_result is None:
                raise PipelineError("POSE_NOT_DETECTED", "관절을 검출하지 못했습니다.")
            all_landmarks, visibility = pose_result
            all_landmarks = np.asarray(normalize_landmarks_sequence(all_landmarks, visibility))

            stage("building_features")
            # 기준 템플릿과 같은 fps 로 맞춰야 80프레임이 같은 시간 길이를 담는다
            feature_fps = float(fps)
            if self.target_fps and abs(fps - self.target_fps) / self.target_fps > 0.05:
                all_landmarks = _resample(all_landmarks, fps, self.target_fps)
                visibility = _resample(visibility, fps, self.target_fps)
                feature_fps = float(self.target_fps)

            n_frames = all_landmarks.shape[0]
            hand_center = (all_landmarks[:, 4, :2] + all_landmarks[:, 5, :2]) / 2
            impact_idx = int(_find_impact_frame(hand_center))
            features = make_features_single_video(all_landmarks, visibility, 1.0 / feature_fps)

        logger.debug(buffer.getvalue())

        if features.shape[0] != SEQUENCE_LEN:
            raise PipelineError("FEATURE_ERROR", f"피처 길이가 {SEQUENCE_LEN}이 아닙니다: {features.shape}")

        pre_len, post_len = IMPACT_FRAME, SEQUENCE_LEN - IMPACT_FRAME
        visibility_mean = np.nanmean(visibility, axis=0)
        quality = {
            "source_fps": round(float(fps), 2),
            "feature_fps": round(feature_fps, 2),
            "n_frames": int(n_frames),
            "impact_frame_in_video": impact_idx,
            "pad_left_frames": max(0, pre_len - impact_idx),
            "pad_right_frames": max(0, post_len - (n_frames - impact_idx)),
            "max_missing_gap": int(max_missing_gap),
            "nan_ratio": round(float(np.mean(~np.isfinite(features))), 4),
            "joint_visibility": {
                name: round(float(value), 3) for name, value in zip(JOINT_NAMES, visibility_mean)
            },
        }

        warnings = []
        low_visibility = [name for name, value in quality["joint_visibility"].items() if value < LOW_VISIBILITY]
        if low_visibility:
            warnings.append(f"검출 신뢰도가 낮은 관절이 있습니다: {', '.join(low_visibility)}")
        if quality["pad_left_frames"] or quality["pad_right_frames"]:
            warnings.append("영상 길이가 부족해 일부 프레임을 반복해서 채웠습니다. 구간 길이 비교를 신뢰하기 어렵습니다.")
        if feature_fps != float(fps):
            warnings.append(f"영상 fps({fps:.1f})를 기준 fps({feature_fps:.1f})로 변환해서 분석했습니다.")
        quality["warnings"] = warnings

        return PipelineResult(features=features, fps=feature_fps, quality=quality)
