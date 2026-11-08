"""LSTM 이벤트 판별 (feedback/event_lstm.py)."""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from feedback.event_lstm import EVENT_KEYS, decode_events, load_event_model
from feedback.events import detect_events

SKELETON_DIR = Path(os.getenv("SWING_TEST_SKELETON_DIR", "data/skeletons"))


def _peaks(length, frames):
    prob = np.full((length, len(EVENT_KEYS)), 0.01)
    for i, frame in enumerate(frames):
        if frame is not None:
            prob[frame, i] = 0.9
    return prob


def test_decode_keeps_event_order_even_when_peaks_are_swapped():
    # 스윙 시작 확률이 임팩트보다 뒤에서 가장 높아도 순서를 지키는 조합을 고른다
    prob = _peaks(40, [5, 12, 30, 20, 35])
    prob[18, 2] = 0.5
    events = decode_events(prob)
    frames = [events[k] for k in EVENT_KEYS]
    assert frames == sorted(frames)
    assert events["impact"] == 20 and events["swing_start"] == 18


def test_decode_marks_cropped_foot_lift_as_missing():
    prob = _peaks(30, [None, 3, 10, 14, 20])
    events = decode_events(prob, present_threshold=0.2)
    assert events["foot_lift"] is None
    assert events["foot_plant"] == 3 and events["impact"] == 14


def test_decode_respects_clip_range():
    prob = _peaks(50, [5, 12, 20, 25, 30])
    events = decode_events(prob, start=10, end=40)
    assert all(v is None or 10 <= v <= 40 for v in events.values())


def test_event_model_keeps_order_on_real_swing():
    model = load_event_model()
    files = sorted(SKELETON_DIR.glob("*.npz")) if SKELETON_DIR.exists() else []
    if model is None or not files:
        pytest.skip("이벤트 모델 또는 스켈레톤 데이터가 없습니다.")
    data = np.load(files[0], allow_pickle=True)
    fps = float(json.loads(str(data["meta_json"]))["fps"])
    pixel = data["landmarks_pixel"].astype(float)

    with_model = detect_events(pixel, fps)
    rules = detect_events(pixel, fps, use_event_model=False)
    order = [getattr(with_model, k) for k in ("foot_lift", "foot_plant", "swing_start", "impact", "follow_end")]
    order = [v for v in order if v is not None]
    assert order == sorted(order)
    assert with_model.impact is not None and rules.impact is not None
