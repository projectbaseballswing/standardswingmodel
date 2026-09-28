"""reference_templates.npz 로딩과 템플릿 관련 계산."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np

from feedback.features import FEATURE_GROUPS, IMPACT_FRAME, joint_xyz_indices

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DTW_MODULE_DIR = PROJECT_ROOT / "modules" / "dtw_reference_template"
DEFAULT_TEMPLATE_PATH = DTW_MODULE_DIR / "reference_templates.npz"

# 템플릿 std 가 0에 가까운 프레임에서 z-score 가 폭주하지 않도록 하는 하한 (scaled 단위)
MIN_SPREAD = 0.2


def _load_module_from_file(name: str, path: Path):
    # DTW 모듈은 자기 폴더 기준으로 `modules.utils...` 를 import 하는 구조라
    # 프로젝트 루트의 `modules` 와 이름이 겹친다. 파일 경로로 직접 로드한다.
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dtw_utils = _load_module_from_file("swing_dtw_utils", DTW_MODULE_DIR / "modules" / "utils" / "dtw_utils.py")
feature_scaling = _load_module_from_file(
    "swing_feature_scaling", DTW_MODULE_DIR / "modules" / "utils" / "feature_scaling.py"
)


@dataclass
class Template:
    mean: np.ndarray  # (80, 64), scaled
    std: np.ndarray  # (80, 64), scaled
    sample_count: int


@dataclass
class PhaseSpec:
    key: str
    name: str
    start: int  # 템플릿 프레임, 포함
    end: int  # 템플릿 프레임, 미포함


def detect_phases(raw_template: np.ndarray) -> List[PhaseSpec]:
    """템플릿의 손목 속도로 구간 경계를 찾는다.

    - 로딩 시작: 손목이 처음으로 크게 움직이기 시작하는 프레임
    - 스윙 시작: 임팩트 전, 손목 속도가 최대 속도의 절반을 넘기 시작하는 프레임
    - 임팩트: 피처 정렬 기준 프레임(60)
    """
    left_wrist = raw_template[:, list(joint_xyz_indices(4))]
    right_wrist = raw_template[:, list(joint_xyz_indices(5))]
    wrist_center = (left_wrist + right_wrist) / 2
    # speed[i] = i -> i+1 프레임 이동량
    speed = np.linalg.norm(np.diff(wrist_center, axis=0), axis=1)[:IMPACT_FRAME]

    load_start, swing_start = 30, 50
    baseline = float(np.median(speed[:20]))
    moving = np.nonzero(speed > max(baseline * 5, 1e-6))[0]
    if len(moving):
        load_start = int(moving[0])
    slow = np.nonzero(speed < speed.max() * 0.5)[0]
    if len(slow):
        swing_start = int(slow[-1]) + 1
    if not (0 < load_start < swing_start < IMPACT_FRAME):
        load_start, swing_start = 30, 50

    return [
        PhaseSpec("stance", "준비 자세", 0, load_start),
        PhaseSpec("load", "로딩(테이크백·스트라이드)", load_start, swing_start),
        PhaseSpec("swing", "스윙", swing_start, IMPACT_FRAME),
        PhaseSpec("follow_through", "팔로우스루", IMPACT_FRAME, raw_template.shape[0]),
    ]


def _weighted_rms(values: np.ndarray, weights: np.ndarray) -> float:
    return float(np.sqrt(np.sum(weights * values**2) / np.sum(weights)))


class ReferenceStore:
    """전체 선수 기준(global) 템플릿, scaler, 피처 가중치, 구간 정의를 한 번 로드해서 들고 있는다."""

    def __init__(self, path: Path = DEFAULT_TEMPLATE_PATH):
        data = np.load(path, allow_pickle=True)
        metadata = json.loads(str(data["metadata_json"])) if "metadata_json" in data.files else {}

        self.path = Path(path)
        self.scaler = feature_scaling.validate_scaler(
            {"median": data["scaler_median"], "mean": data["scaler_mean"], "std": data["scaler_std"]}
        )
        self.feature_weights = np.asarray(data["feature_weights"], dtype=float)
        self.sakoe_chiba_ratio = float(metadata.get("sakoe_chiba_ratio", 0.15) or 0.15)

        self.template = Template(
            mean=np.asarray(data["global_mean_template"], dtype=float),
            std=np.asarray(data["global_std_template"], dtype=float),
            sample_count=int(len(data["selected_video_ids"])),
        )

        self.phases = detect_phases(self.to_raw(self.template.mean))

        # 점수 환산 기준: 프로 선수 스윙 1개가 전체 기준과 보통 떨어져 있는 거리.
        # 선수 간 차이(global std)와 같은 선수 내 차이(선수별 std 평균)를 합쳐서 추정한다.
        between = self.template.std
        within = np.mean(np.asarray(data["label_std_templates"], dtype=float), axis=0)
        spread_sq = (between**2 + within**2).mean(axis=0)  # (64,)
        self.typical_distance = _weighted_rms(np.sqrt(spread_sq), self.feature_weights)
        self.typical_group_distance = {
            group: _weighted_rms(np.sqrt(spread_sq[idx]), self.feature_weights[idx])
            for group, idx in FEATURE_GROUPS.items()
        }

    def scale(self, raw: np.ndarray) -> np.ndarray:
        return feature_scaling.transform_feature_sequence(raw, self.scaler)

    def to_raw(self, scaled: np.ndarray) -> np.ndarray:
        return scaled * self.scaler["std"] + self.scaler["mean"]

    def std_to_raw(self, scaled_std: np.ndarray) -> np.ndarray:
        return scaled_std * self.scaler["std"]
