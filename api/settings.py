"""환경변수로 바꿀 수 있는 API 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from feedback.pipeline import DEFAULT_POSE_MODEL, DEFAULT_YOLO_WEIGHTS
from feedback.reference import DEFAULT_TEMPLATE_PATH


@dataclass(frozen=True)
class Settings:
    template_path: Path = Path(os.getenv("SWING_TEMPLATE_PATH", DEFAULT_TEMPLATE_PATH))
    yolo_weights: Path = Path(os.getenv("SWING_YOLO_WEIGHTS", DEFAULT_YOLO_WEIGHTS))
    pose_model: Path = Path(os.getenv("SWING_POSE_MODEL", DEFAULT_POSE_MODEL))
    # 기준 템플릿을 만든 영상의 fps. 사용자 영상은 이 fps 로 변환해서 비교한다.
    reference_fps: float = float(os.getenv("SWING_REFERENCE_FPS", "30"))
    max_upload_mb: int = int(os.getenv("SWING_MAX_UPLOAD_MB", "200"))
    max_jobs: int = int(os.getenv("SWING_MAX_JOBS", "200"))
    # SWING_MOCK=1 이면 모델을 불러오지 않고 고정된 샘플 응답을 돌려준다 (프론트/백엔드 개발용)
    mock: bool = os.getenv("SWING_MOCK", "") == "1"


settings = Settings()
