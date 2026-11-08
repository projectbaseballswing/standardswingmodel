"""LSTM 이벤트 판별: 관절 좌표 시퀀스에서 프레임마다 이벤트 확률을 내고, 순서를 지키는 프레임을 고른다.

학습은 scripts/train_event_lstm.py (PyTorch) 에서 하고, 여기서는 저장된 가중치로 NumPy 만 써서 계산한다.
API 서버에는 PyTorch 가 없다. 모델 파일이 없으면 load_event_model() 이 None 을 돌려주고,
detect_events 는 지금처럼 규칙 감지기만 쓴다.

예전(0.1) LSTM 오토인코더와 용도가 다르다. docs/lstm-event-model.md 참고.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from feedback.events import (
    LEAD_ANKLE,
    LEAD_HIP,
    LEAD_SHOULDER,
    LEAD_WRIST,
    REAR_HIP,
    REAR_SHOULDER,
    REAR_WRIST,
    _interpolate_nan,
    find_zoom_frame,
)

EVENT_KEYS: List[str] = ["foot_lift", "foot_plant", "swing_start", "impact", "follow_end"]
MODEL_FPS = 30.0
DEPTH_SCALE = 0.30  # feedback/swing_features.DEPTH_SCALE 와 같은 값 (순환 import 를 피해 따로 둔다)
DEFAULT_EVENT_MODEL_PATH = Path(__file__).resolve().parent / "event_lstm.npz"


# ----------------------------------------------------------------------
# 입력 피처
# ----------------------------------------------------------------------
def _resample(values: np.ndarray, fps: float) -> np.ndarray:
    """(T, ...) 를 MODEL_FPS 시간축으로 선형 보간한다. fps 가 거의 같으면 그대로 둔다."""
    if abs(fps - MODEL_FPS) / MODEL_FPS < 0.1 or len(values) < 2:
        return values
    n_out = max(2, int(round((len(values) - 1) * MODEL_FPS / fps)) + 1)
    source = np.arange(len(values)) / fps
    target = np.arange(n_out) / MODEL_FPS
    flat = values.reshape(len(values), -1)
    out = np.stack([np.interp(target, source, flat[:, c]) for c in range(flat.shape[1])], axis=1)
    return out.reshape((n_out,) + values.shape[1:])


def to_model_frame(frame: float, fps: float) -> float:
    return frame if abs(fps - MODEL_FPS) / MODEL_FPS < 0.1 else frame * MODEL_FPS / fps


def from_model_frame(frame: float, fps: float) -> int:
    return int(round(frame if abs(fps - MODEL_FPS) / MODEL_FPS < 0.1 else frame * fps / MODEL_FPS))


def sequence_features(pixel_landmarks: np.ndarray, fps: float) -> np.ndarray:
    """(T, 12, 3) 픽셀 좌표 -> (T', F) 입력 피처. T' 는 MODEL_FPS 기준 프레임 수.

    골반 중심을 원점, 몸통 길이를 1 로 맞춘 관절 위치(36), 그 프레임 간 변화(36),
    골반 중심의 이동(2), 손과 앞 발목의 속력(2). 화면이 중간에 확대되면 몸통 길이를 앞뒤로 따로 잰다.
    """
    arr = np.asarray(pixel_landmarks, dtype=float) * np.array([1.0, 1.0, DEPTH_SCALE])
    T = len(arr)
    filled = np.stack([np.stack([_interpolate_nan(arr[:, j, c]) for c in range(3)], axis=1)
                       for j in range(arr.shape[1])], axis=1)
    filled = np.nan_to_num(filled)

    hip = (filled[:, LEAD_HIP] + filled[:, REAR_HIP]) / 2
    shoulder = (filled[:, LEAD_SHOULDER] + filled[:, REAR_SHOULDER]) / 2
    torso = np.linalg.norm((shoulder - hip)[:, :2], axis=1)

    def median(values: np.ndarray) -> float:
        value = float(np.median(values[values > 0])) if (values > 0).any() else 1.0
        return value if value > 1e-6 else 1.0

    scale = np.full(T, median(torso))
    zoom = find_zoom_frame(np.asarray(pixel_landmarks, dtype=float))
    if zoom is not None:
        scale[:zoom], scale[zoom:] = median(torso[:zoom]), median(torso[zoom:])

    local = (filled - hip[:, None]) / scale[:, None, None]
    local[..., 1] *= -1  # 위가 +
    hip_track = hip[:, :2] / scale[:, None]
    hip_track[:, 1] *= -1

    local = _resample(local, fps)
    hip_track = _resample(hip_track, fps)

    position = local.reshape(len(local), -1)
    velocity = np.vstack([np.zeros((1, position.shape[1])), np.diff(position, axis=0)])
    hip_move = np.vstack([np.zeros((1, 2)), np.diff(hip_track, axis=0)])
    hand = (local[:, LEAD_WRIST] + local[:, REAR_WRIST]) / 2 + np.hstack([hip_track, np.zeros((len(local), 1))])
    ankle = local[:, LEAD_ANKLE] + np.hstack([hip_track, np.zeros((len(local), 1))])
    hand_speed = np.r_[0.0, np.linalg.norm(np.diff(hand[:, :2], axis=0), axis=1)]
    ankle_speed = np.r_[0.0, np.linalg.norm(np.diff(ankle[:, :2], axis=0), axis=1)]
    return np.hstack([position, velocity, hip_move, hand_speed[:, None], ankle_speed[:, None]]).astype(np.float32)


# ----------------------------------------------------------------------
# 순서를 지키는 이벤트 선택
# ----------------------------------------------------------------------
def decode_events(prob: np.ndarray, start: int = 0, end: Optional[int] = None,
                  present_threshold: float = 0.2, optional: Sequence[str] = ("foot_lift", "foot_plant")) -> Dict[str, Optional[int]]:
    """(T, 5) 확률 -> 이벤트 프레임. foot_lift < foot_plant <= swing_start < impact < follow_end 를 지킨다.

    앞부분이 잘린 영상은 앞발 들기/착지가 없을 수 있다. optional 이벤트는 구간 안 최대 확률이
    present_threshold 보다 낮으면 '없음' 으로 보고 순서 계산에서 뺀다.
    log 확률 합이 가장 큰 조합을 동적 계획법으로 찾는다.
    """
    T = len(prob)
    end = T - 1 if end is None else min(end, T - 1)
    window = slice(start, end + 1)
    logp = np.log(np.clip(prob[window], 1e-6, 1.0))
    n = logp.shape[0]
    keys = [k for i, k in enumerate(EVENT_KEYS)
            if k not in optional or prob[window, i].max(initial=0.0) >= present_threshold]
    if n == 0:
        return {k: None for k in EVENT_KEYS}
    cols = [EVENT_KEYS.index(k) for k in keys]
    # 착지와 스윙 시작은 같은 프레임일 수 있다 (라벨에 있음). 나머지는 앞 이벤트보다 뒤여야 한다.
    gap = {("foot_plant", "swing_start"): 0}

    score = logp[:, cols[0]].copy()
    back: List[np.ndarray] = []
    for prev_key, key, col in zip(keys, keys[1:], cols[1:]):
        g = gap.get((prev_key, key), 1)
        # best[t] = 앞 이벤트를 t-g 이하에 둘 때의 최고 점수
        running = np.maximum.accumulate(score)
        arg = np.zeros(n, dtype=int)
        best_idx = 0
        for t in range(n):
            if score[t] >= score[best_idx]:
                best_idx = t
            arg[t] = best_idx
        new = np.full(n, -np.inf)
        prev_arg = np.zeros(n, dtype=int)
        if n > g:
            new[g:] = running[: n - g] + logp[g:, col]
            prev_arg[g:] = arg[: n - g]
        back.append(prev_arg)
        score = new

    frames = [int(np.argmax(score))]
    for prev_arg in reversed(back):
        frames.append(int(prev_arg[frames[-1]]))
    frames.reverse()
    out = {k: None for k in EVENT_KEYS}
    if np.isfinite(score.max()):
        for key, frame in zip(keys, frames):
            out[key] = frame + start
    return out


# ----------------------------------------------------------------------
# NumPy LSTM
# ----------------------------------------------------------------------
def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def _lstm_direction(x: np.ndarray, w_ih: np.ndarray, w_hh: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """PyTorch nn.LSTM 한 방향과 같은 계산. 게이트 순서 i, f, g, o."""
    hidden = w_hh.shape[1]
    gates_x = x @ w_ih.T + bias
    h = np.zeros(hidden, dtype=np.float64)
    c = np.zeros(hidden, dtype=np.float64)
    out = np.empty((len(x), hidden))
    for t in range(len(x)):
        gates = gates_x[t] + w_hh @ h
        i, f, g, o = np.split(gates, 4)
        c = _sigmoid(f) * c + _sigmoid(i) * np.tanh(g)
        h = _sigmoid(o) * np.tanh(c)
        out[t] = h
    return out


@dataclass
class EventModel:
    weights: Dict[str, np.ndarray]
    mean: np.ndarray
    std: np.ndarray
    num_layers: int
    use_events: List[str]  # 검증 데이터에서 규칙 감지기보다 나았던 이벤트만 LSTM 값을 쓴다
    present_threshold: float

    def probabilities(self, pixel_landmarks: np.ndarray, fps: float) -> np.ndarray:
        """(T', 5) 프레임별 이벤트 확률 (MODEL_FPS 시간축)."""
        x = (sequence_features(pixel_landmarks, fps) - self.mean) / self.std
        x = x.astype(np.float64)
        for layer in range(self.num_layers):
            w = self.weights
            fwd = _lstm_direction(x, w[f"weight_ih_l{layer}"], w[f"weight_hh_l{layer}"],
                                  w[f"bias_ih_l{layer}"] + w[f"bias_hh_l{layer}"])
            bwd = _lstm_direction(x[::-1], w[f"weight_ih_l{layer}_reverse"], w[f"weight_hh_l{layer}_reverse"],
                                  w[f"bias_ih_l{layer}_reverse"] + w[f"bias_hh_l{layer}_reverse"])[::-1]
            x = np.hstack([fwd, bwd])
        return _sigmoid(x @ self.weights["head_weight"].T + self.weights["head_bias"])

    def predict(self, pixel_landmarks: np.ndarray, fps: float, clip_start: int = 0,
                clip_end: Optional[int] = None) -> Dict[str, Optional[int]]:
        """원본 프레임 번호로 된 이벤트."""
        prob = self.probabilities(pixel_landmarks, fps)
        start = int(np.floor(to_model_frame(clip_start, fps)))
        end = None if clip_end is None else int(np.ceil(to_model_frame(clip_end, fps)))
        picked = decode_events(prob, start, end, self.present_threshold)
        n = len(pixel_landmarks)
        return {k: (None if v is None else min(n - 1, from_model_frame(v, fps))) for k, v in picked.items()}


_CACHE: Dict[str, Optional[EventModel]] = {}


def load_event_model(path: str = str(DEFAULT_EVENT_MODEL_PATH)) -> Optional[EventModel]:
    """저장된 가중치. 파일이 없으면 None (규칙 감지기만 쓴다)."""
    if path in _CACHE:
        return _CACHE[path]
    file = Path(path)
    model = None
    if file.exists():
        data = np.load(file, allow_pickle=False)
        weights = {k[2:]: data[k].astype(np.float64) for k in data.files if k.startswith("w_")}
        model = EventModel(
            weights=weights,
            mean=data["feature_mean"],
            std=data["feature_std"],
            num_layers=int(data["num_layers"]),
            use_events=[str(k) for k in data["use_events"]],
            present_threshold=float(data["present_threshold"]),
        )
    _CACHE[path] = model
    return model
