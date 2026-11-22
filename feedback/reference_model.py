"""이벤트 기반 기준 스윙 모델(0.2) 로딩.

scripts/build_reference_model.py 가 만든 npz 를 읽어서 비교에 필요한 값을 제공한다.

담고 있는 것
    구간별 자세 곡선   구간마다 진행률 20등분 × 피처 13개의 평균/편차/표본 수
    구간 길이 분포     구간마다 길이(ms) 평균/편차
    이벤트 시점 분포   임팩트를 0으로 본 각 이벤트 시점(ms) 평균/편차
    속도 지표 분포     스윙 시간, 최대 손 속도, 착지→임팩트 시간
    점수 환산 기준     기준 스윙들이 평균 곡선에서 떨어진 거리, 최대 손 속도의 중앙값/상위 10%
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from feedback.reference import PROJECT_ROOT

DEFAULT_MODEL_PATH = PROJECT_ROOT / "data" / "reference_model.npz"

# 사용자에게 보여줄 구간 이름. 키는 모델 파일과 같다.
PHASE_NAMES: Dict[str, str] = {
    "stride": "스트라이드",
    "transition": "착지 후 준비",
    "swing": "스윙",
    "follow": "팔로우스루",
}

# 구간 경계가 되는 이벤트 (사용자 영상에서도 같은 규칙으로 찾는다)
PHASE_EVENTS: Dict[str, tuple] = {
    "stride": ("foot_lift", "foot_plant"),
    "transition": ("foot_plant", "swing_start"),
    "swing": ("swing_start", "impact"),
    "follow": ("impact", "follow_end"),
}

SPEED_METRICS: Dict[str, tuple] = {
    # 키: (이름, 단위, 값이 클수록 좋은가)
    "swing_time_ms": ("스윙 시간", "ms", False),
    "peak_hand_speed": ("최대 손 속도", "body/s", True),  # body = 몸통 길이
    "plant_to_impact_ms": ("착지→임팩트 시간", "ms", None),
}

TIMING_NAMES: Dict[str, str] = {
    "load_start": "로딩 시작",
    "foot_lift": "앞발 들기",
    "foot_plant": "앞발 착지",
    "swing_start": "스윙 시작",
    "follow_end": "팔로우 종료",
}

# 편차 하한 = 그 피처의 프로 편차 중앙값(모든 구간·지점) × 이 비율.
# 하한은 표본이 적은 지점에서 편차가 우연히 무너져 z 가 폭주하는 것만 막는 안전장치다.
# 프로끼리 편차가 작은 피처는 실제로 일관된 동작이라 엄격하게 봐야 하므로, 정상 범위의 편차는
# 건드리지 않는다. 프로 805개 기준 피처별 최소 편차는 중앙값의 56~93% 라 25% 에는 걸리지 않는다.
# (예전 고정값 0.15 는 단위가 다른 피처에 같은 숫자를 써서, 몸통·다리 길이로 나눈 피처의 편차를 덮어썼다.)
MIN_SPREAD_RATIO = 0.25


def min_spread(stds: List[np.ndarray]) -> np.ndarray:
    """구간별 편차 (points, n_features) 목록 -> 피처별 하한 (n_features,)."""
    stacked = np.concatenate([np.asarray(s, dtype=float) for s in stds], axis=0)
    return MIN_SPREAD_RATIO * np.nanmedian(stacked, axis=0)


@dataclass
class Phase:
    key: str
    name: str
    mean: np.ndarray  # (points, n_features)
    std: np.ndarray
    count: int
    duration_mean: float
    duration_std: float
    duration_median: float  # 템포 판정 기준 (평균보다 이상치에 덜 흔들린다)
    duration_iqr: float  # 사분위 범위. 정규분포라면 표준편차의 약 1.35배


class ReferenceModel:
    def __init__(self, path: Path = DEFAULT_MODEL_PATH):
        self.path = Path(path)
        data = np.load(self.path, allow_pickle=True)
        self.metadata = json.loads(str(data["metadata_json"]))
        self.feature_names: List[str] = [str(name) for name in data["feature_names"]]
        self.points = int(data["phase_points"])

        phase_keys = [str(k) for k in data["phase_keys"] if f"{k}_std" in data.files]
        floor = min_spread([data[f"{k}_std"] for k in phase_keys])
        self.phases: Dict[str, Phase] = {}
        for key in [str(k) for k in data["phase_keys"]]:
            if f"{key}_mean" not in data.files:
                continue
            self.phases[key] = Phase(
                key=key,
                name=PHASE_NAMES.get(key, key),
                mean=np.asarray(data[f"{key}_mean"], dtype=float),
                std=np.maximum(np.asarray(data[f"{key}_std"], dtype=float), floor),
                count=int(data[f"{key}_count"]),
                duration_mean=float(data[f"{key}_duration_mean"]),
                duration_std=float(data[f"{key}_duration_std"]),
                duration_median=float(data.get(f"{key}_duration_median", data[f"{key}_duration_mean"])),
                duration_iqr=float(data.get(f"{key}_duration_iqr", data[f"{key}_duration_std"] * 1.35)),
            )

        self.timings = {
            key: (float(data[f"timing_{key}_mean"]), float(data[f"timing_{key}_std"]), int(data[f"timing_{key}_count"]))
            for key in TIMING_NAMES
            if f"timing_{key}_mean" in data.files
        }
        self.speed = {
            key: (float(data[f"speed_{key}_mean"]), float(data[f"speed_{key}_std"]), int(data[f"speed_{key}_count"]))
            for key in SPEED_METRICS
            if f"speed_{key}_mean" in data.files
        }
        self.typical_distance = float(data["typical_distance"]) if "typical_distance" in data.files else 1.0
        # 속도 점수 기준 (프로 최대 손 속도의 중앙값, 상위 10%). 예전 모델 파일에는 없다.
        self.peak_speed_reference: Optional[Tuple[float, float]] = None
        if "speed_peak_hand_speed_median" in data.files:
            self.peak_speed_reference = (float(data["speed_peak_hand_speed_median"]),
                                         float(data["speed_peak_hand_speed_p90"]))

    @property
    def model_version(self) -> str:
        return str(self.metadata.get("model_version", "0.2"))

    @property
    def swings_used(self) -> int:
        return int(self.metadata.get("swings_used", 0))

    def feature_index(self, name: str) -> int:
        return self.feature_names.index(name)


def load_reference_model(path: Path = DEFAULT_MODEL_PATH) -> Optional[ReferenceModel]:
    """모델 파일이 없으면 None (그때는 기존 0.1 비교를 쓴다)."""
    try:
        return ReferenceModel(path)
    except (FileNotFoundError, KeyError, ValueError):
        return None
