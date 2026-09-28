"""이벤트 라벨링 웹 도구.

영상 프레임과 스켈레톤, 신호 그래프를 보면서 스윙 이벤트 프레임을 지정해 CSV 로 저장한다.
검출기(feedback/events.py)의 결과가 초기값으로 채워지므로, 틀린 것만 고치면 된다.

실행:
    .venv/bin/python scripts/label_server.py
    → http://127.0.0.1:8100

저장 위치: data/labels.csv (한 줄 = 한 스윙)
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.events import _body_scale, _interpolate_nan, _smooth, detect_events  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKELETON_DIR = PROJECT_ROOT / "data" / "skeletons"
VIDEO_DIR = PROJECT_ROOT / "data" / "videos"
LABEL_PATH = PROJECT_ROOT / "data" / "labels.csv"
PRIORITY_PATH = PROJECT_ROOT / "data" / "label_priority.txt"  # 먼저 라벨링할 영상 순서
PAGE = PROJECT_ROOT / "web" / "labeler.html"

EVENT_KEYS = ["load_start", "foot_lift", "foot_plant", "swing_start", "impact", "follow_end"]
# 사용할 구간. 앵글이 바뀌거나 다른 장면이 섞인 부분을 잘라내기 위해 쓴다.
RANGE_KEYS = ["clip_start", "clip_end"]
ALL_KEYS = [*EVENT_KEYS, *RANGE_KEYS]
CSV_FIELDS = ["video_id", "labeler", "labeled_at", *ALL_KEYS, "note"]

app = FastAPI(title="스윙 이벤트 라벨링")
_frame_cache: Dict[str, List[bytes]] = {}


def _video_path(video_id: str) -> Optional[Path]:
    for suffix in (".mp4", ".mov", ".MOV", ".avi", ".mkv"):
        candidate = VIDEO_DIR / f"{video_id}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _load_frames(video_id: str, flip: bool) -> List[bytes]:
    """영상 전체를 한 번만 디코딩해서 JPEG 로 들고 있는다 (좌타는 좌우반전)."""
    if video_id in _frame_cache:
        return _frame_cache[video_id]
    path = _video_path(video_id)
    if path is None:
        raise HTTPException(404, f"영상을 찾을 수 없습니다: {video_id}")

    cap = cv2.VideoCapture(str(path))
    frames: List[bytes] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if flip:
            frame = cv2.flip(frame, 1)
        scale = 640 / max(frame.shape[1], 1)
        if scale < 1:
            frame = cv2.resize(frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            frames.append(buf.tobytes())
    cap.release()

    if len(_frame_cache) > 3:  # 메모리 보호: 최근 3개 영상만 유지
        _frame_cache.pop(next(iter(_frame_cache)))
    _frame_cache[video_id] = frames
    return frames


def _read_labels() -> Dict[str, dict]:
    if not LABEL_PATH.exists():
        return {}
    with LABEL_PATH.open(encoding="utf-8-sig") as f:
        return {row["video_id"]: row for row in csv.DictReader(f)}


class LabelIn(BaseModel):
    video_id: str
    labeler: str = ""
    note: str = ""
    events: Dict[str, Optional[int]]


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.get("/api/videos")
def list_videos():
    labeled = _read_labels()
    all_ids = sorted(path.stem for path in SKELETON_DIR.glob("*.npz"))

    # 우선순위 목록이 있으면 그 순서대로 앞에 놓는다 (표본이 골고루 섞이도록 뽑은 목록)
    priority: List[str] = []
    if PRIORITY_PATH.exists():
        wanted = [line.strip() for line in PRIORITY_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        available = set(all_ids)
        priority = [video_id for video_id in wanted if video_id in available]

    ordered = priority + [video_id for video_id in all_ids if video_id not in set(priority)]
    items = [
        {"video_id": video_id, "labeled": video_id in labeled, "priority": video_id in set(priority)}
        for video_id in ordered
    ]
    return {
        "total": len(items),
        "labeled": sum(1 for i in items if i["labeled"]),
        "priority_total": len(priority),
        "priority_labeled": sum(1 for i in items if i["priority"] and i["labeled"]),
        "videos": items,
    }


@app.get("/api/videos/{video_id}")
def video_detail(video_id: str):
    path = SKELETON_DIR / f"{video_id}.npz"
    if not path.exists():
        raise HTTPException(404, "스켈레톤 파일이 없습니다.")
    data = np.load(path, allow_pickle=True)
    meta = json.loads(str(data["meta_json"]))
    pixel = data["landmarks_pixel"].astype(float)
    saved_row = _read_labels().get(video_id)
    clip_start = int(saved_row["clip_start"]) if saved_row and saved_row.get("clip_start") else 0
    clip_end = int(saved_row["clip_end"]) if saved_row and saved_row.get("clip_end") else None
    events = detect_events(pixel, meta["fps"], clip_start=clip_start, clip_end=clip_end)

    # 라벨링 판단을 돕는 신호들. 검출기와 같은 좌표(픽셀/어깨너비)를 쓴다.
    scale = _body_scale(pixel)
    hand = (pixel[:, 4, :2] + pixel[:, 5, :2]) / 2 / scale
    hand_x = _smooth(_interpolate_nan(hand[:, 0]))
    hand_y = _smooth(_interpolate_nan(hand[:, 1]))
    speed = np.concatenate([[0.0], np.hypot(np.diff(hand_x), np.diff(hand_y))])
    signals = {
        "hand_speed": np.nan_to_num(speed).round(3).tolist(),
        "hand_x": np.nan_to_num(hand_x).round(3).tolist(),
        # 픽셀 좌표는 아래로 갈수록 값이 커지므로, 발을 들면 그래프가 올라가도록 부호를 뒤집는다
        "lead_ankle_y": np.nan_to_num(-_smooth(_interpolate_nan(pixel[:, 10, 1])) / scale).round(3).tolist(),
        "rear_ankle_y": np.nan_to_num(-_smooth(_interpolate_nan(pixel[:, 11, 1])) / scale).round(3).tolist(),
    }
    # 스윙 후보 위치(손 속도 봉우리). 스윙이 여러 번 담겼는지 눈으로 보기 위한 표시다.
    smooth = np.convolve(np.nan_to_num(speed), np.ones(3) / 3, mode="same")
    threshold = smooth.max() * 0.5
    gap = max(3, int(0.4 * meta["fps"]))
    peaks: List[int] = []
    for i in range(1, len(smooth) - 1):
        if smooth[i] >= threshold and smooth[i] >= smooth[i - 1] and smooth[i] >= smooth[i + 1]:
            if not peaks or i - peaks[-1] >= gap:
                peaks.append(i)
            elif smooth[i] > smooth[peaks[-1]]:
                peaks[-1] = i

    saved = saved_row
    saved_events = (
        {key: (int(saved[key]) if saved.get(key) not in (None, "") else None) for key in ALL_KEYS}
        if saved else None
    )
    return {
        "video_id": video_id,
        "fps": meta["fps"],
        "n_frames": int(pixel.shape[0]),
        "handedness": meta.get("handedness", "right"),
        "detected": events.as_dict(),
        "warnings": events.warnings,
        "saved": saved_events,
        "peaks": peaks,
        "saved_note": saved.get("note", "") if saved else "",
        "signals": signals,
    }


@app.get("/api/videos/{video_id}/frames/{index}")
def frame(video_id: str, index: int):
    path = SKELETON_DIR / f"{video_id}.npz"
    if not path.exists():
        raise HTTPException(404, "스켈레톤 파일이 없습니다.")
    meta = json.loads(str(np.load(path, allow_pickle=True)["meta_json"]))
    frames = _load_frames(video_id, flip=meta.get("handedness") == "left")
    if not frames:
        raise HTTPException(404, "영상 프레임을 읽지 못했습니다.")
    index = max(0, min(index, len(frames) - 1))
    return Response(frames[index], media_type="image/jpeg")


@app.post("/api/labels")
def save_label(item: LabelIn):
    rows = _read_labels()
    rows[item.video_id] = {
        "video_id": item.video_id,
        "labeler": item.labeler,
        "labeled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **{key: ("" if item.events.get(key) is None else item.events[key]) for key in ALL_KEYS},
        "note": item.note,
    }
    LABEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LABEL_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows.values())
    return {"saved": True, "labeled_count": len(rows)}


@app.get("/api/labels/download")
def download_labels():
    if not LABEL_PATH.exists():
        raise HTTPException(404, "저장된 라벨이 없습니다.")
    return FileResponse(LABEL_PATH, filename="labels.csv")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8100)
