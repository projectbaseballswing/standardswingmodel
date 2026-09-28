"""스켈레톤 시퀀스에서 스윙 동작 사건(이벤트)을 찾는다.

고정 프레임(임팩트 앞 60 / 뒤 20)으로 자르는 대신, 동작 사건으로 구간을 나누기 위한 모듈이다.
사용자 영상과 기준 영상에 같은 규칙을 적용해야 비교가 공정해진다.

입력은 **원본 프레임 좌표(픽셀)** 를 쓰고, 어깨 너비 중앙값으로 나눠 크기를 맞춘다.
몸 기준 좌표계로 정규화한 좌표는 스윙 중 기준축이 흔들려 신호가 왜곡되므로 쓰지 않는다
(라벨 27개 비교: 임팩트 ±3프레임 정확도 56% -> 81%).

임계값은 사람이 라벨링한 27개 스윙에 맞춰 정했다. 표본이 적어 아직 바뀔 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# landmarks 인덱스 (modules/utils/pose_utils.py 의 OUTPUT_JOINT_ORDER)
LEAD_SHOULDER, REAR_SHOULDER = 0, 1
LEAD_ELBOW, REAR_ELBOW = 2, 3
LEAD_WRIST, REAR_WRIST = 4, 5
LEAD_HIP, REAR_HIP = 6, 7
LEAD_ANKLE, REAR_ANKLE = 10, 11

SMOOTH_WINDOW = 3
EDGE_MARGIN = 2  # 영상 맨 앞뒤 프레임은 튀는 값이 많아 검출에서 제외

# 라벨 27개로 맞춘 임계값 (모두 어깨 너비 대비 프레임당 이동량)
SWING_START_RATIO = 0.15  # 스윙 시작: 최대 손 속도의 이 비율 미만인 마지막 프레임
FOOT_PLANT_SPEED = 0.04  # 앞발 착지: 발목이 내려오는 속도가 이 값을 넘는 마지막 프레임
FOOT_LIFT_SPEED = 0.03  # 앞발 들기: 발목이 올라가는 속도가 이 값을 넘는 첫 프레임
LOAD_SPEED_RATIO = 0.15  # 로딩 시작: 손이 투수 반대쪽으로 이 비율 이상 움직이는 첫 프레임
FOLLOW_END_RATIO = 0.3  # 팔로우 종료: 임팩트 후 손 속도가 이 비율 미만으로 떨어지는 첫 프레임


@dataclass
class SwingEvents:
    """검출된 이벤트의 프레임 번호. 찾지 못한 이벤트는 None."""

    load_start: Optional[int] = None
    foot_lift: Optional[int] = None
    foot_plant: Optional[int] = None
    swing_start: Optional[int] = None
    impact: Optional[int] = None
    follow_end: Optional[int] = None
    fps: float = 30.0
    n_frames: int = 0
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Optional[int]]:
        return {
            "load_start": self.load_start,
            "foot_lift": self.foot_lift,
            "foot_plant": self.foot_plant,
            "swing_start": self.swing_start,
            "impact": self.impact,
            "follow_end": self.follow_end,
        }

    def phase_durations_ms(self) -> Dict[str, Optional[float]]:
        """이벤트 사이 구간 길이(ms). 양쪽 이벤트가 없으면 None."""

        def gap(start: Optional[int], end: Optional[int]) -> Optional[float]:
            if start is None or end is None or self.fps <= 0:
                return None
            return round((end - start) / self.fps * 1000, 1)

        return {
            "load": gap(self.load_start, self.foot_lift),
            "stride": gap(self.foot_lift, self.foot_plant),
            "swing": gap(self.swing_start, self.impact),
            "follow_through": gap(self.impact, self.follow_end),
        }


def _interpolate_nan(values: np.ndarray) -> np.ndarray:
    """짧은 결측을 선형 보간한다. 전부 결측이면 그대로 돌려준다."""
    out = np.asarray(values, dtype=float).copy()
    valid = np.isfinite(out)
    if valid.sum() < 2:
        return out
    idx = np.arange(len(out))
    out[~valid] = np.interp(idx[~valid], idx[valid], out[valid])
    return out


def _smooth(values: np.ndarray, window: int = SMOOTH_WINDOW) -> np.ndarray:
    if window < 2 or len(values) < window:
        return values
    return np.convolve(values, np.ones(window) / window, mode="same")


def _body_scale(pixel_landmarks: np.ndarray) -> float:
    """어깨 너비 중앙값(픽셀). 확대/축소와 사람 크기 차이를 보정하는 기준."""
    width = np.linalg.norm(pixel_landmarks[:, LEAD_SHOULDER, :2] - pixel_landmarks[:, REAR_SHOULDER, :2], axis=1)
    scale = float(np.nanmedian(width))
    return scale if np.isfinite(scale) and scale > 1 else 1.0


def _track(pixel_landmarks: np.ndarray, joints: Tuple[int, ...], scale: float) -> Tuple[np.ndarray, np.ndarray]:
    """관절 평균 위치의 (x, y) 궤적. 어깨 너비로 나눠 크기를 맞춘다."""
    point = np.mean([pixel_landmarks[:, j, :2] for j in joints], axis=0)
    x = _smooth(_interpolate_nan(point[:, 0])) / scale
    y = _smooth(_interpolate_nan(point[:, 1])) / scale
    return x, y


def detect_events(
    pixel_landmarks: np.ndarray,
    fps: float,
    clip_start: int = 0,
    clip_end: Optional[int] = None,
) -> SwingEvents:
    """관절 좌표(원본 프레임 좌표, (T, 12, 3))에서 이벤트를 찾는다.

    clip_start / clip_end 는 분석에 쓸 프레임 범위다. 앵글이 바뀌거나 다른 장면이 섞인
    영상에서 쓸 구간만 넘기면 그 안에서만 이벤트를 찾는다.
    """
    arr = np.asarray(pixel_landmarks, dtype=float)
    n_frames = arr.shape[0]
    events = SwingEvents(fps=float(fps), n_frames=n_frames)
    if n_frames < 8:
        events.warnings.append("프레임이 너무 적어 이벤트를 찾을 수 없습니다.")
        return events

    end = n_frames - 1 if clip_end is None else min(clip_end, n_frames - 1)
    start = max(0, clip_start)

    scale = _body_scale(arr)
    hand_x, hand_y = _track(arr, (LEAD_WRIST, REAR_WRIST), scale)
    speed = np.hypot(np.diff(hand_x), np.diff(hand_y))  # speed[i] = i -> i+1 이동량
    if not np.isfinite(speed).any() or speed.max() <= 0:
        events.warnings.append("손 좌표가 없어 이벤트를 찾을 수 없습니다.")
        return events

    # --- 임팩트: 손이 가장 빠른 프레임 ---
    lo = max(start, EDGE_MARGIN)
    hi = min(end, len(speed) - 1)
    if hi <= lo:
        events.warnings.append("임팩트를 찾을 구간이 없습니다.")
        return events
    impact = int(np.argmax(speed[lo:hi])) + lo + 1
    events.impact = impact
    peak_speed = float(speed[impact - 1])
    if impact <= lo + 1 or impact >= end - 1:
        events.warnings.append("임팩트가 구간 끝에 잡혔습니다. 스윙 전체가 담기지 않았을 수 있습니다.")

    # --- 스윙 방향: 임팩트 전후에 손이 크게 움직인 방향을 그 스윙의 투수 쪽으로 본다 ---
    window = slice(max(start, impact - 3), min(end + 1, impact + 3))
    swing_dir = np.sign(hand_x[window][-1] - hand_x[window][0]) if window.stop > window.start else 1.0
    swing_dir = swing_dir or 1.0

    # --- 스윙 시작: 임팩트 직전에 손이 느렸던 마지막 프레임 ---
    before = speed[start:impact]
    slow = np.nonzero(before < peak_speed * SWING_START_RATIO)[0]
    events.swing_start = int(slow[-1]) + start + 1 if len(slow) else None
    if events.swing_start is None:
        events.warnings.append("스윙 시작을 찾지 못했습니다. 영상이 이미 스윙 중에 시작한 것 같습니다.")

    # --- 앞발 들기 / 착지: 앞 발목의 수직 움직임 (픽셀 좌표는 아래로 갈수록 값이 커진다) ---
    _, ankle_y = _track(arr, (LEAD_ANKLE,), scale)
    ankle_v = np.diff(ankle_y)[start:impact]  # +면 내려가는 중, -면 올라가는 중
    if len(ankle_v):
        rising = np.nonzero(ankle_v < -FOOT_LIFT_SPEED)[0]
        events.foot_lift = int(rising[0]) + start if len(rising) else None
        falling = np.nonzero(ankle_v > FOOT_PLANT_SPEED)[0]
        events.foot_plant = int(falling[-1]) + start + 1 if len(falling) else None
    if events.foot_plant is None:
        events.warnings.append("앞발 착지를 찾지 못했습니다. 스트라이드가 영상에 담기지 않았을 수 있습니다.")

    # --- 로딩 시작: 발을 들기 전(없으면 스윙 시작 전), 손이 투수 반대쪽으로 움직이기 시작 ---
    limit = events.foot_lift or events.swing_start or impact
    if limit > start + 3:
        back = np.diff(hand_x[start:limit]) * -swing_dir  # 장전 방향을 +로
        moving = np.nonzero(back > peak_speed * LOAD_SPEED_RATIO)[0]
        events.load_start = int(moving[0]) + start if len(moving) else None
    if events.load_start is None:
        events.warnings.append("로딩 시작을 찾지 못했습니다. 영상이 로딩 도중에 시작한 것 같습니다.")

    # --- 팔로우 종료: 임팩트 이후 손 속도가 다시 떨어지는 프레임 ---
    after = speed[impact:hi]
    if len(after):
        slow_after = np.nonzero(after < peak_speed * FOLLOW_END_RATIO)[0]
        events.follow_end = int(slow_after[0]) + impact + 1 if len(slow_after) else end
    else:
        events.follow_end = end
        events.warnings.append("임팩트 이후 프레임이 없습니다.")

    _check_order(events)
    return events


def _check_order(events: SwingEvents) -> None:
    """이벤트 순서가 맞는지 확인하고, 어긋나면 경고를 남긴다."""
    order = [
        ("load_start", events.load_start),
        ("foot_lift", events.foot_lift),
        ("foot_plant", events.foot_plant),
        ("swing_start", events.swing_start),
        ("impact", events.impact),
        ("follow_end", events.follow_end),
    ]
    found = [(name, value) for name, value in order if value is not None]
    for (prev_name, prev), (name, value) in zip(found, found[1:]):
        if value < prev:
            events.warnings.append(f"이벤트 순서가 어긋납니다: {prev_name}({prev}) > {name}({value})")
