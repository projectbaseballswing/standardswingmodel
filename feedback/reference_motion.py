"""기준 동작: 프로 스윙들로 새로 조립한 대표 스켈레톤과, 같은 좌표로 맞춘 사용자 스켈레톤.

점수에는 쓰지 않는다. 화면에 "프로 대표 자세"를 그리고 사용자 자세와 겹쳐 보여주기 위한 데이터다.

만드는 방법 (산술, 학습 없음)
    1. 스윙마다 관절 좌표를 골반 중심 원점, 몸통 길이 1 로 맞춘다 (y 위, z 는 DEPTH_SCALE 보정).
    2. 이벤트로 나눈 구간을 0~100% 로 20등분해 시점을 맞춘다 (기준 모델과 같은 스윙, 같은 이벤트).
    3. 뼈(예: 앞 허벅지 = 앞 골반 -> 앞 무릎)마다 방향만 모아, 시점별로 가장 많이 몰린 방향을 고른다.
       평균 방향에서 시작해 몰린 쪽으로 옮겨 가는 방식(mean shift)이라 튀는 스윙에 덜 끌린다.
    4. 뼈 길이는 프로 전체의 중앙값(표준 체형)으로 고정하고, 골반 중심부터 뼈를 이어 붙여 조립한다.

좌표를 그대로 평균 내면 선수마다 다른 방향이 섞여 팔다리가 짧아지고 자세가 뭉개진다.
방향과 길이를 나눠서 고르면 뼈 길이가 늘 표준 체형과 같아서 실제로 가능한 자세가 된다.

좌표계 (기준과 사용자가 같다)
    원점   골반 중심 (매 시점)
    단위   몸통 길이 (어깨 중심 ~ 골반 중심, 화면 x-y 기준) = 1
    x      + 투수 쪽 (우타 기준. 좌타 영상은 분석 전에 좌우반전돼 있다)
    y      + 위
    z      + 카메라에서 멀어지는 쪽 (MediaPipe 이미지 z 에 DEPTH_SCALE 을 곱한 값)
    root   임팩트 순간 골반 중심을 원점으로 본 그 시점의 골반 중심 위치 (같은 단위)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from feedback.events import (
    SMOOTH_WINDOW,
    LEAD_ANKLE,
    LEAD_ELBOW,
    LEAD_HIP,
    LEAD_KNEE,
    LEAD_SHOULDER,
    LEAD_WRIST,
    REAR_ANKLE,
    REAR_ELBOW,
    REAR_HIP,
    REAR_KNEE,
    REAR_SHOULDER,
    REAR_WRIST,
    _interpolate_nan,
    find_zoom_frame,
)
from feedback.reference import PROJECT_ROOT
from feedback.reference_model import PHASE_EVENTS, PHASE_NAMES
from feedback.swing_features import DEPTH_SCALE, _torso_scale_per_frame

MOTION_VERSION = "reference-motion-v1"
METHOD = "bone_direction_mode"
DEFAULT_MOTION_PATH = PROJECT_ROOT / "data" / "reference_motion.npz"
PHASE_POINTS = 20

JOINT_KEYS: List[str] = [
    "lead_shoulder", "rear_shoulder", "lead_elbow", "rear_elbow", "lead_wrist", "rear_wrist",
    "lead_hip", "rear_hip", "lead_knee", "rear_knee", "lead_ankle", "rear_ankle",
]

# 조립에 쓰는 뼈. 골반과 어깨는 가운데를 기준으로 양쪽에 반씩 붙인다.
#   (이름, 시작, 끝)  시작/끝: 관절 번호, "hip_center", "shoulder_center"
BONES: List[tuple] = [
    ("pelvis", REAR_HIP, LEAD_HIP),
    ("spine", "hip_center", "shoulder_center"),
    ("shoulders", REAR_SHOULDER, LEAD_SHOULDER),
    ("lead_upper_arm", LEAD_SHOULDER, LEAD_ELBOW),
    ("lead_forearm", LEAD_ELBOW, LEAD_WRIST),
    ("rear_upper_arm", REAR_SHOULDER, REAR_ELBOW),
    ("rear_forearm", REAR_ELBOW, REAR_WRIST),
    ("lead_thigh", LEAD_HIP, LEAD_KNEE),
    ("lead_shin", LEAD_KNEE, LEAD_ANKLE),
    ("rear_thigh", REAR_HIP, REAR_KNEE),
    ("rear_shin", REAR_KNEE, REAR_ANKLE),
]
BONE_NAMES = [name for name, *_ in BONES]

# 화면에 그릴 선 (관절 번호 쌍)
DRAW_EDGES: List[List[int]] = [
    [LEAD_SHOULDER, REAR_SHOULDER], [LEAD_HIP, REAR_HIP],
    [LEAD_SHOULDER, LEAD_HIP], [REAR_SHOULDER, REAR_HIP],
    [LEAD_SHOULDER, LEAD_ELBOW], [LEAD_ELBOW, LEAD_WRIST],
    [REAR_SHOULDER, REAR_ELBOW], [REAR_ELBOW, REAR_WRIST],
    [LEAD_HIP, LEAD_KNEE], [LEAD_KNEE, LEAD_ANKLE],
    [REAR_HIP, REAR_KNEE], [REAR_KNEE, REAR_ANKLE],
]

COORDINATE_CONVENTION: Dict[str, str] = {
    "origin": "골반 중심 (매 시점)",
    "unit": "몸통 길이 (어깨 중심 ~ 골반 중심, 화면 x-y 기준) = 1",
    "x": "+ 투수 쪽 (우타 기준. 좌타 영상은 분석 전에 좌우반전되어 있음)",
    "y": "+ 위",
    "z": "+ 카메라에서 멀어지는 쪽 (MediaPipe 이미지 z x 0.30)",
    "root": "임팩트 순간 골반 중심을 원점으로 본 그 시점의 골반 중심 위치",
}

# 방향 고르기 (mean shift) 의 폭. 몰린 정도에 맞춰 이 범위 안에서 정한다.
MODE_BANDWIDTH_DEG = (8.0, 30.0)


# ----------------------------------------------------------------------
# 좌표 맞추기
# ----------------------------------------------------------------------
def _fill(points: np.ndarray, window: int = SMOOTH_WINDOW) -> np.ndarray:
    """(T, D) 결측을 메우고 부드럽게 한다. 점수용 swing_features._fill 과 같되, 영상 맨 앞뒤 프레임이
    0 쪽으로 줄어들지 않게 가장자리 값을 늘려 붙인 뒤 평균한다."""
    out = []
    for c in range(points.shape[1]):
        values = _interpolate_nan(points[:, c])
        if window >= 2 and len(values) >= window and np.isfinite(values).all():
            pad = window // 2
            values = np.convolve(np.pad(values, (pad, window - 1 - pad), mode="edge"), np.ones(window) / window, mode="valid")
        out.append(values)
    return np.stack(out, axis=1)


def normalize_skeleton(pixel_landmarks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(T, 12, 3) 픽셀 좌표 -> (골반 중심 원점 관절 좌표 (T, 12, 3), 골반 중심 위치 (T, 3)).

    둘 다 몸통 길이 단위, y 위. 골반 중심 위치는 화면 원점 기준이라 그대로는 의미가 없고
    두 시점의 차이(이동량)로만 쓴다.
    """
    arr = np.asarray(pixel_landmarks, dtype=float)
    scaled = arr * np.array([1.0, 1.0, DEPTH_SCALE])
    filled = np.stack([_fill(scaled[:, j]) for j in range(arr.shape[1])], axis=1)
    scale = _torso_scale_per_frame(arr, find_zoom_frame(arr))[:, None]
    hip = (filled[:, LEAD_HIP] + filled[:, REAR_HIP]) / 2
    joints = (filled - hip[:, None]) / scale[:, None]
    joints[..., 1] *= -1
    root = hip / scale
    root[:, 1] *= -1
    root[:, 2] = 0.0  # 이미지 z 는 골반 기준 상대값이라 골반 자체의 깊이 이동은 알 수 없다
    return joints, root


def resample_points(values: np.ndarray, start: int, end: int, points: int = PHASE_POINTS) -> np.ndarray:
    """(T, ...) 값의 구간 [start, end] 를 points 개 시점으로 맞춘다."""
    flat = values.reshape(len(values), -1)
    source = np.arange(start, end + 1)
    target = np.linspace(start, end, points)
    out = np.stack([np.interp(target, source, flat[start:end + 1, c]) for c in range(flat.shape[1])], axis=1)
    return out.reshape((points,) + values.shape[1:])


# ----------------------------------------------------------------------
# 뼈 방향 / 조립
# ----------------------------------------------------------------------
def _point(joints: np.ndarray, ref) -> np.ndarray:
    if ref == "hip_center":
        return (joints[..., LEAD_HIP, :] + joints[..., REAR_HIP, :]) / 2
    if ref == "shoulder_center":
        return (joints[..., LEAD_SHOULDER, :] + joints[..., REAR_SHOULDER, :]) / 2
    return joints[..., ref, :]


def bone_vectors(joints: np.ndarray) -> np.ndarray:
    """(..., 12, 3) -> (..., 뼈 수, 3) 뼈 벡터 (시작 -> 끝)."""
    return np.stack([_point(joints, b) - _point(joints, a) for _, a, b in BONES], axis=-2)


def assemble(directions: np.ndarray, lengths: np.ndarray) -> np.ndarray:
    """(..., 뼈 수, 3) 단위 방향 + (뼈 수,) 길이 -> (..., 12, 3) 관절 좌표. 골반 중심이 원점."""
    d = directions / np.linalg.norm(directions, axis=-1, keepdims=True)
    v = d * np.asarray(lengths)[:, None]
    index = {name: i for i, name in enumerate(BONE_NAMES)}
    out = np.zeros(directions.shape[:-2] + (12, 3))
    out[..., LEAD_HIP, :] = v[..., index["pelvis"], :] / 2
    out[..., REAR_HIP, :] = -v[..., index["pelvis"], :] / 2
    shoulder_center = v[..., index["spine"], :]
    out[..., LEAD_SHOULDER, :] = shoulder_center + v[..., index["shoulders"], :] / 2
    out[..., REAR_SHOULDER, :] = shoulder_center - v[..., index["shoulders"], :] / 2
    for name, start, end in BONES[3:]:
        out[..., end, :] = out[..., start, :] + v[..., index[name], :]
    return out


def direction_mode(units: np.ndarray, iterations: int = 30) -> tuple[np.ndarray, float]:
    """(N, 3) 단위 벡터들에서 가장 많이 몰린 방향과, 그 방향에서 떨어진 각도의 중앙값(도).

    평균 방향에서 시작해, 가까운 벡터에 큰 가중을 주는 평균을 되풀이한다 (구면 위 mean shift).
    """
    units = units[np.isfinite(units).all(axis=1)]
    units = units / np.linalg.norm(units, axis=1, keepdims=True)
    if not len(units):
        return np.full(3, np.nan), float("nan")
    center = units.mean(axis=0)
    if np.linalg.norm(center) < 1e-9:
        center = units[0]
    center = center / np.linalg.norm(center)

    def angles(c: np.ndarray) -> np.ndarray:
        return np.arccos(np.clip(units @ c, -1.0, 1.0))

    low, high = np.radians(MODE_BANDWIDTH_DEG)
    bandwidth = float(np.clip(np.median(angles(center)), low, high))
    for _ in range(iterations):
        weights = np.exp(-0.5 * (angles(center) / bandwidth) ** 2)
        moved = (units * weights[:, None]).sum(axis=0)
        moved = moved / np.linalg.norm(moved)
        done = np.arccos(np.clip(moved @ center, -1.0, 1.0)) < np.radians(0.01)
        center = moved
        if done:
            break
    return center, float(np.degrees(np.median(angles(center))))


# ----------------------------------------------------------------------
# 기준 동작 파일
# ----------------------------------------------------------------------
@dataclass
class MotionPhase:
    key: str
    joints: np.ndarray  # (points, 12, 3)
    root: np.ndarray  # (points, 3)
    spread_deg: np.ndarray  # (points, 뼈 수)  뼈 방향이 프로들 사이에서 퍼진 정도
    count: int


class ReferenceMotion:
    def __init__(self, path: Path = DEFAULT_MOTION_PATH):
        data = np.load(Path(path), allow_pickle=True)
        self.metadata: Dict[str, Any] = json.loads(str(data["metadata_json"]))
        self.points = int(data["phase_points"])
        self.bone_lengths = np.asarray(data["bone_lengths"], dtype=float)
        self.phases: Dict[str, MotionPhase] = {}
        for key in [str(k) for k in data["phase_keys"]]:
            if f"{key}_joints" not in data.files:
                continue
            self.phases[key] = MotionPhase(
                key=key,
                joints=np.asarray(data[f"{key}_joints"], dtype=float),
                root=np.asarray(data[f"{key}_root"], dtype=float),
                spread_deg=np.asarray(data[f"{key}_spread_deg"], dtype=float),
                count=int(data[f"{key}_count"]),
            )


_CACHE: Dict[str, Optional[ReferenceMotion]] = {}


def load_reference_motion(path: Path = DEFAULT_MOTION_PATH) -> Optional[ReferenceMotion]:
    """파일이 없으면 None."""
    key = str(path)
    if key not in _CACHE:
        try:
            _CACHE[key] = ReferenceMotion(path)
        except (FileNotFoundError, KeyError, ValueError):
            _CACHE[key] = None
    return _CACHE[key]


# ----------------------------------------------------------------------
# 사용자 동작 (분석할 때 결과에 함께 저장)
# ----------------------------------------------------------------------
def _round(values: np.ndarray, digits: int = 3) -> list:
    return np.round(np.nan_to_num(np.asarray(values, dtype=float), nan=0.0), digits).tolist()


def user_motion(pixel_landmarks: np.ndarray, fps: float, events: Dict[str, Optional[int]],
                points: int = PHASE_POINTS) -> Dict[str, Any]:
    """사용자 스켈레톤을 기준 동작과 같은 좌표·같은 시점으로 맞춘다.

    구간은 비교(compare_v2)와 같은 조건으로 고른다: 양쪽 이벤트가 있고 순서가 맞는 구간만.
    """
    arr = np.asarray(pixel_landmarks, dtype=float)
    joints, root = normalize_skeleton(arr)
    anchor = events.get("impact")
    origin = root[anchor] if anchor is not None and 0 <= anchor < len(root) else None

    phases: Dict[str, Any] = {}
    for key, (start_key, end_key) in PHASE_EVENTS.items():
        start, end = events.get(start_key), events.get(end_key)
        if start is None or end is None or end <= start or end >= len(arr):
            continue
        frames = np.linspace(start, end, points)
        phases[key] = {
            "start_frame": int(start),
            "end_frame": int(end),
            "frames": _round(frames, 2),
            "timestamps_s": _round(frames / fps, 4),
            "joints": _round(resample_points(joints, start, end, points)),
            "root": None if origin is None else _round(resample_points(root - origin, start, end, points)),
        }
    return {
        "version": MOTION_VERSION,
        "fps": round(float(fps), 3),
        "frame_count": int(len(arr)),
        "events": {k: (None if v is None else int(v)) for k, v in events.items()},
        "phases": phases,
    }


def motion_response(analysis_id: str, stored: Dict[str, Any], motion: ReferenceMotion,
                    handedness: Optional[str] = None) -> Dict[str, Any]:
    """저장된 사용자 동작 + 기준 동작 -> API 응답."""
    progress = np.linspace(0.0, 1.0, motion.points)
    phases = []
    for key in PHASE_EVENTS:
        ref = motion.phases.get(key)
        user = (stored.get("phases") or {}).get(key)
        phases.append({
            "key": key,
            "name": PHASE_NAMES.get(key, key),
            "start_event": PHASE_EVENTS[key][0],
            "end_event": PHASE_EVENTS[key][1],
            "progress": _round(progress, 4),
            "reference": None if ref is None else {
                "joints": _round(ref.joints),
                "root": _round(ref.root),
                "spread_deg": _round(ref.spread_deg, 1),
                "swings_used": ref.count,
            },
            "user": user,
        })
    return {
        "analysis_id": analysis_id,
        "version": MOTION_VERSION,
        "method": motion.metadata.get("method", METHOD),
        "reference_model_version": motion.metadata.get("reference_model_version"),
        "handedness": handedness,
        "coordinate_convention": COORDINATE_CONVENTION,
        "joint_names": JOINT_KEYS,
        "draw_edges": DRAW_EDGES,
        "bones": [
            {"name": name, "length": round(float(length), 4)}
            for name, length in zip(BONE_NAMES, motion.bone_lengths)
        ],
        "fps": stored.get("fps"),
        "frame_count": stored.get("frame_count"),
        "events": stored.get("events") or {},
        "phases": phases,
    }
