"""사용자 스윙 피처와 전체 선수 기준(global) 템플릿을 비교해서 종합/관절별/구간별 수치를 만든다.

모든 비교는 DTW 모듈과 같은 방식으로 한다.
    1. 사용자 피처를 템플릿 scaler 로 표준화
    2. dtw_distance 로 템플릿과의 거리와 프레임 대응 경로 계산
    3. 경로를 따라 사용자 시퀀스를 템플릿 시간축(80프레임)에 정렬
    4. 정렬된 시퀀스와 템플릿을 프레임/피처 단위로 비교
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from feedback.features import (
    ANGLE_SPECS,
    FEATURE_GROUP_NAMES_KO,
    FEATURE_GROUPS,
    IMPACT_FRAME,
    to_template_features,
)
from feedback.reference import MIN_SPREAD, ReferenceStore, dtw_utils

# 프로 선수 스윙 1개가 기준과 보통 떨어진 거리(typical_distance)를 80점으로 둔다.
SCORE_AT_TYPICAL = 0.8
WORST_SEGMENT_LEN = 5


def distance_to_score(distance: float, typical_distance: float) -> float:
    """거리 -> 0~100점. 0이면 100점, 프로 평균 거리면 80점, 멀어질수록 0에 가까워진다."""
    return round(100.0 * SCORE_AT_TYPICAL ** (distance / typical_distance), 1)


def z_level(z: float) -> str:
    z = abs(z)
    if z < 1.0:
        return "good"
    if z < 2.0:
        return "caution"
    return "warning"


def tempo_level(ratio: float) -> str:
    gap = abs(ratio - 1.0)
    if gap < 0.15:
        return "good"
    if gap < 0.3:
        return "caution"
    return "warning"


def _direction(diff: float, level: str) -> str:
    if level == "good":
        return "similar"
    return "higher" if diff > 0 else "lower"


def _weighted_rms(values: np.ndarray, weights: np.ndarray, axis=None) -> np.ndarray:
    return np.sqrt(np.sum(weights * values**2, axis=axis) / np.sum(weights))


def _r(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


class SwingComparison:
    """사용자 피처 1개와 기준 템플릿의 비교 결과를 계산하고 들고 있는다."""

    def __init__(
        self,
        store: ReferenceStore,
        features: np.ndarray,
        user_fps: float = 30.0,
        reference_fps: float = 30.0,
        quality: Optional[Dict[str, Any]] = None,
    ):
        self.store = store
        self.template = store.template
        self.user_fps = float(user_fps)
        self.reference_fps = float(reference_fps)
        self.quality = dict(quality or {})

        self.user_raw = to_template_features(features)
        self.user_scaled = store.scale(self.user_raw)
        self.distance, self.path = dtw_utils.dtw_distance(
            self.user_scaled,
            self.template.mean,
            feature_weights=store.feature_weights,
            sakoe_chiba_ratio=store.sakoe_chiba_ratio,
        )
        self.aligned_scaled, _ = dtw_utils.align_sequence_to_template_timeline(
            self.user_scaled, self.template.mean.shape[0], self.path
        )
        self.aligned_raw = store.to_raw(self.aligned_scaled)
        self.template_raw = store.to_raw(self.template.mean)
        self.template_std_raw = store.std_to_raw(self.template.std)

        self.diff_scaled = self.aligned_scaled - self.template.mean
        self.spread = np.maximum(self.template.std, MIN_SPREAD)
        self.frame_distances = _weighted_rms(self.diff_scaled, store.feature_weights, axis=1)

    # ------------------------------------------------------------------
    # 종합
    # ------------------------------------------------------------------
    def overall(self, joints: Optional[List[Dict]] = None) -> Dict[str, Any]:
        store = self.store
        groups = []
        for group, idx in FEATURE_GROUPS.items():
            distance = float(_weighted_rms(self.diff_scaled[:, idx], store.feature_weights[idx]))
            groups.append({
                "key": group,
                "name": FEATURE_GROUP_NAMES_KO[group],
                "distance": _r(distance, 3),
                "score": distance_to_score(distance, store.typical_group_distance[group]),
            })

        window = np.convolve(self.frame_distances, np.ones(WORST_SEGMENT_LEN) / WORST_SEGMENT_LEN, mode="valid")
        worst_start = int(np.argmax(window))
        worst_center = worst_start + WORST_SEGMENT_LEN // 2

        result: Dict[str, Any] = {
            "score": distance_to_score(self.distance, store.typical_distance),
            "distance": _r(self.distance, 3),
            "typical_pro_distance": _r(store.typical_distance, 3),
            "group_scores": groups,
            "worst_segment": {
                "start_frame": worst_start,
                "end_frame": worst_start + WORST_SEGMENT_LEN,
                "phase": self._phase_of_frame(worst_center),
                "distance": _r(float(window[worst_start]), 3),
            },
            "frame_distances": [_r(v, 3) for v in self.frame_distances],
            "top_issues": self._top_issues(joints if joints is not None else self.joints()),
            "quality": self.quality,
        }
        return result

    def _top_issues(self, joints: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        issues = []
        for joint in joints:
            for phase in joint["phases"]:
                if phase["level"] == "good":
                    continue
                issues.append({
                    "type": "joint_angle",
                    "joint": joint["key"],
                    "joint_name": joint["name"],
                    "phase": phase["phase"],
                    "phase_name": phase["phase_name"],
                    "user": phase["user_mean"],
                    "reference": phase["reference_mean"],
                    "diff": phase["diff"],
                    "z_score": phase["z_score"],
                    "direction": phase["direction"],
                    "level": phase["level"],
                })
        issues.sort(key=lambda item: abs(item["z_score"]), reverse=True)
        return issues[:top_k]

    # ------------------------------------------------------------------
    # 관절별 (각도)
    # ------------------------------------------------------------------
    def joints(self, include_series: bool = False) -> List[Dict[str, Any]]:
        results = []
        for spec in ANGLE_SPECS:
            idx = spec.index
            user = self.aligned_raw[:, idx]
            ref = self.template_raw[:, idx]

            phases = []
            for phase in self.store.phases:
                frames = slice(phase.start, phase.end)
                z = float(np.mean(self.diff_scaled[frames, idx]) / np.mean(self.spread[frames, idx]))
                diff = float(np.mean(user[frames]) - np.mean(ref[frames]))
                level = z_level(z)
                phases.append({
                    "phase": phase.key,
                    "phase_name": phase.name,
                    "user_mean": _r(np.mean(user[frames]), 1),
                    "reference_mean": _r(np.mean(ref[frames]), 1),
                    "reference_std": _r(np.mean(self.template_std_raw[frames, idx]), 1),
                    "diff": _r(diff, 1),
                    "z_score": _r(z),
                    "direction": _direction(diff, level),
                    "level": level,
                })

            impact_z = float(self.diff_scaled[IMPACT_FRAME, idx] / self.spread[IMPACT_FRAME, idx])
            impact_diff = float(user[IMPACT_FRAME] - ref[IMPACT_FRAME])
            worst = max(phases, key=lambda item: abs(item["z_score"]))

            joint: Dict[str, Any] = {
                "key": spec.key,
                "name": spec.name,
                "body_part": spec.body_part,
                "description": spec.description,
                "unit": "deg",
                "level": worst["level"],
                "worst_phase": worst["phase"],
                "impact": {
                    "user": _r(user[IMPACT_FRAME], 1),
                    "reference": _r(ref[IMPACT_FRAME], 1),
                    "diff": _r(impact_diff, 1),
                    "z_score": _r(impact_z),
                    "level": z_level(impact_z),
                },
                "range_of_motion": {
                    "user": _r(np.max(user) - np.min(user), 1),
                    "reference": _r(np.max(ref) - np.min(ref), 1),
                    "diff": _r((np.max(user) - np.min(user)) - (np.max(ref) - np.min(ref)), 1),
                },
                "phases": phases,
            }
            if include_series:
                joint["series"] = {
                    "user": [_r(v, 1) for v in user],
                    "reference": [_r(v, 1) for v in ref],
                    "reference_std": [_r(v, 1) for v in self.template_std_raw[:, idx]],
                }
            results.append(joint)
        return results

    # ------------------------------------------------------------------
    # 구간별
    # ------------------------------------------------------------------
    def phases(self, joints: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        joints = joints if joints is not None else self.joints()
        path = np.asarray(self.path)
        pad_left = int(self.quality.get("pad_left_frames", 0) or 0)
        pad_right = int(self.quality.get("pad_right_frames", 0) or 0)
        seq_len = self.aligned_scaled.shape[0]

        results = []
        for phase in self.store.phases:
            in_phase = (path[:, 1] >= phase.start) & (path[:, 1] < phase.end)
            user_frames = path[in_phase, 0]
            user_start, user_end = int(user_frames.min()), int(user_frames.max()) + 1
            user_ms = (user_end - user_start) / self.user_fps * 1000
            ref_ms = (phase.end - phase.start) / self.reference_fps * 1000
            ratio = user_ms / ref_ms if ref_ms > 0 else 1.0
            distance = float(np.mean(self.frame_distances[phase.start:phase.end]))

            deviations = []
            for joint in joints:
                row = next(item for item in joint["phases"] if item["phase"] == phase.key)
                deviations.append({
                    "joint": joint["key"],
                    "joint_name": joint["name"],
                    "diff": row["diff"],
                    "z_score": row["z_score"],
                    "direction": row["direction"],
                    "level": row["level"],
                })
            deviations.sort(key=lambda item: abs(item["z_score"]), reverse=True)

            warnings = []
            if pad_left > 0 and user_start < pad_left:
                warnings.append("영상이 임팩트 전 60프레임보다 짧아 앞부분이 반복 프레임으로 채워졌습니다. 구간 길이를 신뢰하기 어렵습니다.")
            if pad_right > 0 and user_end > seq_len - pad_right:
                warnings.append("영상이 임팩트 후 20프레임보다 짧아 뒷부분이 반복 프레임으로 채워졌습니다. 구간 길이를 신뢰하기 어렵습니다.")

            results.append({
                "key": phase.key,
                "name": phase.name,
                "reference_frames": [phase.start, phase.end],
                "user_frames": [user_start, user_end],
                "reference_duration_ms": _r(ref_ms, 0),
                "user_duration_ms": _r(user_ms, 0),
                "tempo_ratio": _r(ratio),
                "tempo_level": tempo_level(ratio),
                "distance": _r(distance, 3),
                "score": distance_to_score(distance, self.store.typical_distance),
                "top_deviations": deviations[:3],
                "warnings": warnings,
            })

        load = next(item for item in results if item["key"] == "load")
        swing = next(item for item in results if item["key"] == "swing")
        rhythm = {
            "description": "로딩 구간 길이 / 스윙 구간 길이",
            "user": _r(load["user_duration_ms"] / max(swing["user_duration_ms"], 1e-6)),
            "reference": _r(load["reference_duration_ms"] / max(swing["reference_duration_ms"], 1e-6)),
        }
        return {
            "impact_frame": IMPACT_FRAME,
            "user_fps": _r(self.user_fps, 2),
            "reference_fps": _r(self.reference_fps, 2),
            "rhythm": rhythm,
            "phases": results,
        }

    # ------------------------------------------------------------------
    def report(self, include_series: bool = False) -> Dict[str, Any]:
        joints = self.joints(include_series=include_series)
        return {
            "overall": self.overall(joints=joints),
            "joints": joints,
            "phases": self.phases(joints=joints),
        }

    def _phase_of_frame(self, frame: int) -> str:
        for phase in self.store.phases:
            if phase.start <= frame < phase.end:
                return phase.key
        return self.store.phases[-1].key
