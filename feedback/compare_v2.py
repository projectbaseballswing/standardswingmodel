"""사용자 스윙을 이벤트 기반 기준 모델(0.2)과 비교한다.

0.1 과의 차이
    0.1  임팩트 기준 80프레임으로 자르고 DTW 로 정렬한 뒤 프레임 번호끼리 비교
    0.2  동작 사건으로 구간을 나누고, 구간마다 0~100% 로 시간 정규화해서 비교

따라서
    - 영상에 담기지 않은 구간은 available=false 로 내려가고, 있는 구간만 비교한다
    - 구간 길이(템포)를 실제 시간으로 비교한다
    - 속도 지표(스윙 시간, 최대 손 속도 등)를 실제로 채운다

응답 구조는 0.1 과 같다. 프론트는 model_version 만 보고 구분하면 된다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from feedback.events import SwingEvents, detect_events
from feedback.reference_model import PHASE_EVENTS, SPEED_METRICS, TIMING_NAMES, ReferenceModel
from feedback.swing_features import FEATURE_NAMES_KO, FEATURE_UNITS, compute_features, hand_speed

# 점수: 기준 스윙이 평균에서 떨어진 거리(typical_distance)를 80점으로 둔다
SCORE_AT_TYPICAL = 0.8

# 자세 차이 판정 (단위: 기준 스윙들의 편차)
LEVEL_CAUTION, LEVEL_WARNING = 1.0, 2.0
# 구간 길이 판정 (단위: 기준 길이 편차)
TEMPO_CAUTION, TEMPO_WARNING = 1.0, 2.0
# 템포를 판정할 수 있는 조건.
# 30fps 에서 스윙 구간은 중앙값이 4프레임(133ms)뿐이라 1프레임 차이가 25% 변동으로 보인다.
# 이렇게 짧거나 기준 분포가 넓은 구간은 수치만 보여주고 판정은 하지 않는다.
TEMPO_MIN_FRAMES = 5  # 기준 길이가 이보다 짧으면 판정 보류
TEMPO_MAX_SPREAD = 0.6  # 기준 분포(IQR/중앙값)가 이보다 넓으면 판정 보류

# 피처를 어느 부위로 묶어 보여줄지
BODY_PARTS = {
    "lead_elbow_angle": "arm", "rear_elbow_angle": "arm",
    "lead_knee_angle": "leg", "rear_knee_angle": "leg",
    "torso_lean": "torso", "shoulder_tilt": "torso", "hip_tilt": "torso",
    "hand_x_from_shoulder": "arm", "hand_y_from_shoulder": "arm",
    "lead_ankle_x_from_hip": "leg", "lead_ankle_y_from_hip": "leg",
    "shoulder_x_from_hip": "torso", "shoulder_y_from_hip": "torso",
}

FEATURE_DESCRIPTIONS = {
    "lead_elbow_angle": "앞 어깨-팔꿈치-손목 각도. 클수록 팔이 펴져 있다.",
    "rear_elbow_angle": "뒤 어깨-팔꿈치-손목 각도. 작을수록 팔이 접혀 있다.",
    "lead_knee_angle": "앞 골반-무릎-발목 각도. 클수록 앞다리가 펴져 있다.",
    "rear_knee_angle": "뒤 골반-무릎-발목 각도. 작을수록 무릎이 굽혀져 있다.",
    "torso_lean": "상체가 수직에서 기울어진 정도. +면 투수 쪽으로 기울어짐.",
    "shoulder_tilt": "어깨 선의 기울기. 화면 수평 기준(세로축 회전량이 아님).",
    "hip_tilt": "골반 선의 기울기. 화면 수평 기준(세로축 회전량이 아님).",
    "hand_x_from_shoulder": "어깨 중심 기준 손의 앞뒤 위치.",
    "hand_y_from_shoulder": "어깨 중심 기준 손의 높이.",
    "lead_ankle_x_from_hip": "골반 기준 앞발의 앞뒤 위치. 스트라이드 폭.",
    "lead_ankle_y_from_hip": "골반 기준 앞발의 높이.",
    "shoulder_x_from_hip": "골반 기준 상체의 앞뒤 쏠림.",
    "shoulder_y_from_hip": "골반 기준 상체의 높이.",
}


def _r(value: float, digits: int = 2) -> Optional[float]:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def distance_to_score(distance: float, typical: float) -> Optional[float]:
    if not np.isfinite(distance) or typical <= 0:
        return None
    return round(100.0 * SCORE_AT_TYPICAL ** (distance / typical), 1)


def level_of(z: float, caution: float = LEVEL_CAUTION, warning: float = LEVEL_WARNING) -> str:
    z = abs(z)
    if z < caution:
        return "good"
    return "caution" if z < warning else "warning"


def _direction(diff: float, level: str) -> str:
    if level == "good":
        return "similar"
    return "higher" if diff > 0 else "lower"


def resample(values: np.ndarray, start: int, end: int, points: int) -> np.ndarray:
    """구간 [start, end] 을 points 개로 늘이거나 줄인다."""
    source = np.arange(start, end + 1)
    target = np.linspace(start, end, points)
    return np.stack([np.interp(target, source, values[start:end + 1, col]) for col in range(values.shape[1])], axis=1)


class SwingComparisonV2:
    def __init__(
        self,
        model: ReferenceModel,
        pixel_landmarks: np.ndarray,
        fps: float,
        quality: Optional[Dict[str, Any]] = None,
        clip_start: int = 0,
        clip_end: Optional[int] = None,
    ):
        self.model = model
        self.landmarks = np.asarray(pixel_landmarks, dtype=float)
        self.fps = float(fps)
        self.quality = dict(quality or {})
        self.events: SwingEvents = detect_events(self.landmarks, self.fps, clip_start, clip_end)
        self.features = compute_features(self.landmarks)
        self.speed = hand_speed(self.landmarks, self.fps)

        self.user_curves: Dict[str, np.ndarray] = {}
        self.diff_z: Dict[str, np.ndarray] = {}
        for key, (start_key, end_key) in PHASE_EVENTS.items():
            phase = model.phases.get(key)
            start, end = getattr(self.events, start_key), getattr(self.events, end_key)
            if phase is None or start is None or end is None or end <= start or end >= len(self.features):
                continue
            curve = resample(self.features, start, end, model.points)
            self.user_curves[key] = curve
            self.diff_z[key] = (curve - phase.mean) / phase.std

        self.reliability = self._reliability()

    # ------------------------------------------------------------------
    def _reliability(self) -> str:
        nan_ratio = float(self.quality.get("nan_ratio", 0) or 0)
        visibility = self.quality.get("joint_visibility") or {}
        worst = min(visibility.values()) if visibility else 1.0
        missing = len(PHASE_EVENTS) - len(self.user_curves)
        if missing >= 2 or nan_ratio >= 0.2 or worst < 0.4:
            return "low"
        if missing >= 1 or nan_ratio >= 0.05 or worst < 0.6 or self.events.zoom_frame is not None:
            return "medium"
        return "high"

    @property
    def available(self) -> bool:
        return bool(self.user_curves)

    def _overall_distance(self) -> float:
        if not self.diff_z:
            return float("nan")
        return float(np.sqrt(np.mean(np.concatenate([z.ravel() for z in self.diff_z.values()]) ** 2)))

    # ------------------------------------------------------------------
    # 종합
    # ------------------------------------------------------------------
    def overall(self, joints: Optional[List[Dict]] = None) -> Dict[str, Any]:
        joints = joints if joints is not None else self.joints()
        distance = self._overall_distance()

        groups: Dict[str, List[float]] = {}
        for key, z in self.diff_z.items():
            for index, name in enumerate(self.model.feature_names):
                groups.setdefault(BODY_PARTS.get(name, "other"), []).extend(np.abs(z[:, index]).tolist())
        group_names = {"arm": "팔", "leg": "다리", "torso": "몸통", "other": "기타"}
        group_scores = [
            {
                "key": part,
                "name": group_names.get(part, part),
                "distance": _r(float(np.sqrt(np.mean(np.square(values)))), 3),
                "score": distance_to_score(float(np.sqrt(np.mean(np.square(values)))), self.model.typical_distance),
            }
            for part, values in sorted(groups.items())
        ]

        # 구간을 순서대로 이어붙인 시간축에서 지점별 차이 (구간 4개 × 20등분)
        frame_distances, worst = [], None
        for key in PHASE_EVENTS:
            z = self.diff_z.get(key)
            values = np.sqrt(np.mean(z**2, axis=1)) if z is not None else np.full(self.model.points, np.nan)
            frame_distances.extend(values.tolist())
            if z is not None:
                peak = float(np.nanmax(values))
                if worst is None or peak > worst[1]:
                    worst = (key, peak, int(np.nanargmax(values)))

        quality = dict(self.quality)
        warnings = list(quality.get("warnings") or [])
        warnings.extend(self.events.warnings)
        missing = [self.model.phases[k].name for k in PHASE_EVENTS if k not in self.user_curves and k in self.model.phases]
        if missing:
            warnings.append(f"영상에 담기지 않아 분석하지 못한 구간: {', '.join(missing)}")
        quality["warnings"] = warnings

        return {
            "model_version": self.model.model_version,
            "available": self.available,
            "reliability": self.reliability,
            "score": distance_to_score(distance, self.model.typical_distance),
            "distance": _r(distance, 3),
            "typical_pro_distance": _r(self.model.typical_distance, 3),
            "group_scores": group_scores,
            "worst_segment": None if worst is None else {
                "start_frame": worst[2],
                "end_frame": worst[2] + 1,
                "phase": worst[0],
                "distance": _r(worst[1], 3),
            },
            "frame_distances": [_r(v, 3) for v in frame_distances],
            "top_issues": self._top_issues(joints),
            "quality": quality,
        }

    def _top_issues(self, joints: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        issues = []
        for joint in joints:
            for phase in joint["phases"]:
                if phase["level"] == "good" or phase["z_score"] is None:
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
    # 관절별
    # ------------------------------------------------------------------
    def joints(self, include_series: bool = False) -> List[Dict[str, Any]]:
        results = []
        for index, name in enumerate(self.model.feature_names):
            phases = []
            for key in PHASE_EVENTS:
                phase = self.model.phases.get(key)
                curve = self.user_curves.get(key)
                if phase is None:
                    continue
                if curve is None:
                    phases.append({
                        "phase": key, "phase_name": phase.name, "available": False,
                        "user_mean": None, "reference_mean": _r(float(phase.mean[:, index].mean()), 1),
                        "reference_std": _r(float(phase.std[:, index].mean()), 1),
                        "diff": None, "z_score": None, "direction": "similar", "level": "good",
                    })
                    continue
                user_mean = float(curve[:, index].mean())
                ref_mean = float(phase.mean[:, index].mean())
                z = float(np.mean(self.diff_z[key][:, index]))
                level = level_of(z)
                phases.append({
                    "phase": key, "phase_name": phase.name, "available": True,
                    "user_mean": _r(user_mean, 1), "reference_mean": _r(ref_mean, 1),
                    "reference_std": _r(float(phase.std[:, index].mean()), 1),
                    "diff": _r(user_mean - ref_mean, 1), "z_score": _r(z),
                    "direction": _direction(user_mean - ref_mean, level), "level": level,
                })

            measured = [p for p in phases if p["available"]]
            worst = max(measured, key=lambda p: abs(p["z_score"]), default=None)

            # 임팩트 순간 = 스윙 구간의 마지막 지점
            impact = None
            if "swing" in self.user_curves:
                user_value = float(self.user_curves["swing"][-1, index])
                ref_value = float(self.model.phases["swing"].mean[-1, index])
                z = float(self.diff_z["swing"][-1, index])
                impact = {
                    "user": _r(user_value, 1), "reference": _r(ref_value, 1),
                    "diff": _r(user_value - ref_value, 1), "z_score": _r(z), "level": level_of(z),
                }

            rom = None
            if self.user_curves:
                user_all = np.concatenate([c[:, index] for c in self.user_curves.values()])
                ref_all = np.concatenate([self.model.phases[k].mean[:, index] for k in self.user_curves])
                rom = {
                    "user": _r(float(user_all.max() - user_all.min()), 1),
                    "reference": _r(float(ref_all.max() - ref_all.min()), 1),
                    "diff": _r(float((user_all.max() - user_all.min()) - (ref_all.max() - ref_all.min())), 1),
                }

            joint: Dict[str, Any] = {
                "key": name,
                "name": FEATURE_NAMES_KO.get(name, name),
                "body_part": BODY_PARTS.get(name, "other"),
                "description": FEATURE_DESCRIPTIONS.get(name, ""),
                "unit": FEATURE_UNITS.get(name, "deg"),
                "available": bool(measured),
                "reliability": self.reliability,
                "level": worst["level"] if worst else "good",
                "worst_phase": worst["phase"] if worst else None,
                "impact": impact,
                "range_of_motion": rom,
                "phases": phases,
            }
            if include_series:
                joint["series"] = {
                    "user": [_r(v, 1) for key in PHASE_EVENTS
                             for v in (self.user_curves[key][:, index] if key in self.user_curves
                                       else [np.nan] * self.model.points)],
                    "reference": [_r(v, 1) for key in PHASE_EVENTS if key in self.model.phases
                                  for v in self.model.phases[key].mean[:, index]],
                    "reference_std": [_r(v, 1) for key in PHASE_EVENTS if key in self.model.phases
                                      for v in self.model.phases[key].std[:, index]],
                }
            results.append(joint)
        return results

    # ------------------------------------------------------------------
    # 구간별
    # ------------------------------------------------------------------
    def phases(self, joints: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        joints = joints if joints is not None else self.joints()
        rows = []
        for key, (start_key, end_key) in PHASE_EVENTS.items():
            phase = self.model.phases.get(key)
            if phase is None:
                continue
            start, end = getattr(self.events, start_key), getattr(self.events, end_key)
            if key not in self.user_curves:
                rows.append({
                    "key": key, "name": phase.name, "available": False,
                    "reliability": self.reliability,
                    "unavailable_reason": f"{start_key} 또는 {end_key} 를 영상에서 찾지 못했습니다.",
                    "reference_frames": None, "user_frames": None,
                    "reference_duration_ms": _r(phase.duration_mean, 0),
                    "user_duration_ms": None, "tempo_ratio": None, "tempo_level": None,
                    "distance": None, "score": None, "top_deviations": [], "warnings": [],
                })
                continue

            user_ms = (end - start) / self.fps * 1000
            # 중앙값과 사분위 범위로 본다. 평균/표준편차는 검출이 틀린 소수 스윙에 끌려간다.
            # IQR/1.35 는 정규분포에서 표준편차에 해당하는 값이다.
            spread = max(phase.duration_iqr / 1.35, phase.duration_median * 0.1, 1e-6)
            tempo_z = (user_ms - phase.duration_median) / spread

            # 판정이 가능한 구간인지 확인한다
            reference_frames = phase.duration_median * self.fps / 1000
            relative_spread = phase.duration_iqr / max(phase.duration_median, 1e-6)
            phase_warnings: List[str] = []
            if reference_frames < TEMPO_MIN_FRAMES:
                tempo_level = None
                phase_warnings.append(
                    f"구간이 짧아({reference_frames:.0f}프레임) 템포를 판정하지 않았습니다. "
                    f"더 높은 fps 로 촬영하면 판정할 수 있습니다.")
            elif relative_spread > TEMPO_MAX_SPREAD:
                tempo_level = None
                phase_warnings.append("선수마다 편차가 커서 템포를 판정하지 않았습니다. 수치만 참고하세요.")
            else:
                tempo_level = level_of(tempo_z, TEMPO_CAUTION, TEMPO_WARNING)
            distance = float(np.sqrt(np.mean(self.diff_z[key] ** 2)))

            deviations = []
            for joint in joints:
                row = next((p for p in joint["phases"] if p["phase"] == key), None)
                if row is None or row["z_score"] is None:
                    continue
                deviations.append({
                    "joint": joint["key"], "joint_name": joint["name"], "diff": row["diff"],
                    "z_score": row["z_score"], "direction": row["direction"], "level": row["level"],
                })
            deviations.sort(key=lambda item: abs(item["z_score"]), reverse=True)

            rows.append({
                "key": key, "name": phase.name, "available": True,
                "reliability": self.reliability, "unavailable_reason": None,
                "reference_frames": [0, self.model.points],
                "user_frames": [int(start), int(end)],
                "reference_duration_ms": _r(phase.duration_median, 0),
                "user_duration_ms": _r(user_ms, 0),
                "tempo_ratio": _r(user_ms / phase.duration_median if phase.duration_median else None),
                "tempo_level": tempo_level,
                "distance": _r(distance, 3),
                "score": distance_to_score(distance, self.model.typical_distance),
                "top_deviations": deviations[:3],
                "warnings": phase_warnings,
            })

        # 리듬: 스트라이드와 스윙 길이의 비
        def ratio(source) -> Optional[float]:
            stride = source.get("stride")
            swing = source.get("swing")
            if not stride or not swing:
                return None
            return _r(stride / swing)

        user_durations = {
            key: (getattr(self.events, PHASE_EVENTS[key][1]) - getattr(self.events, PHASE_EVENTS[key][0])) / self.fps * 1000
            for key in self.user_curves
        }
        reference_durations = {key: phase.duration_median for key, phase in self.model.phases.items()}

        return {
            "model_version": self.model.model_version,
            "impact_frame": self.events.impact if self.events.impact is not None else 0,
            "user_fps": _r(self.fps, 2),
            "reference_fps": _r(self.fps, 2),  # 0.2 는 시간(ms)으로 비교하므로 fps 를 맞출 필요가 없다
            "rhythm": {
                "description": "스트라이드 길이 / 스윙 길이",
                "user": ratio(user_durations),
                "reference": ratio(reference_durations),
            },
            "phases": rows,
            "events": {
                key: {
                    "frame": getattr(self.events, key),
                    "ms_from_impact": _r(((getattr(self.events, key) - self.events.impact) / self.fps * 1000), 0)
                    if getattr(self.events, key) is not None and self.events.impact is not None else None,
                    "reference_ms_from_impact": _r(self.model.timings[key][0], 0) if key in self.model.timings else None,
                    "reference_std_ms": _r(self.model.timings[key][1], 0) if key in self.model.timings else None,
                    "name": TIMING_NAMES[key],
                }
                for key in TIMING_NAMES
            },
        }

    # ------------------------------------------------------------------
    # 속도
    # ------------------------------------------------------------------
    def speed_feedback(self) -> Dict[str, Any]:
        events = self.events
        measured: Dict[str, Optional[float]] = {"swing_time_ms": None, "peak_hand_speed": None, "plant_to_impact_ms": None}
        if events.impact is not None and events.swing_start is not None:
            measured["swing_time_ms"] = (events.impact - events.swing_start) / self.fps * 1000
        if events.impact is not None:
            window = self.speed[max(0, events.impact - 5):min(len(self.speed), events.impact + 3)]
            if len(window):
                measured["peak_hand_speed"] = float(np.max(window))
        if events.impact is not None and events.foot_plant is not None:
            measured["plant_to_impact_ms"] = (events.impact - events.foot_plant) / self.fps * 1000

        metrics = []
        for key, (name, unit, _) in SPEED_METRICS.items():
            reference = self.model.speed.get(key)
            value = measured.get(key)
            if reference is None or value is None:
                metrics.append({
                    "key": key, "name": name, "unit": unit, "available": False,
                    "reliability": self.reliability, "user": None, "reference": None,
                    "reference_std": None, "diff": None, "z_score": None, "level": None,
                })
                continue
            ref_mean, ref_std, _count = reference
            z = (value - ref_mean) / max(ref_std, 1e-6)
            metrics.append({
                "key": key, "name": name, "unit": unit, "available": True,
                "reliability": self.reliability,
                "user": _r(value, 1), "reference": _r(ref_mean, 1), "reference_std": _r(ref_std, 1),
                "diff": _r(value - ref_mean, 1), "z_score": _r(z), "level": level_of(z),
            })
        return {
            "model_version": self.model.model_version,
            "available": any(m["available"] for m in metrics),
            "metrics": metrics,
        }

    # ------------------------------------------------------------------
    def report(self, include_series: bool = False) -> Dict[str, Any]:
        joints = self.joints(include_series=include_series)
        return {
            "model_version": self.model.model_version,
            "overall": self.overall(joints=joints),
            "joints": joints,
            "phases": self.phases(joints=joints),
            "speed": self.speed_feedback(),
        }
