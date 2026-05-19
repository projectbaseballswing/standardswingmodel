"""DTW 비교 전에 feature scale을 맞추는 유틸입니다.

좌표, 각도, 속도 feature는 값의 범위가 다르기 때문에 그대로 DTW에
넣으면 특정 feature가 distance를 과도하게 지배할 수 있습니다. 이 모듈은
reference set 기준 median imputation과 mean/std scaling을 담당합니다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np


def _finite_array(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float).copy()
    arr[~np.isfinite(arr)] = np.nan
    return arr


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def fit_feature_scaler(
    sequences: Sequence[np.ndarray],
    feature_names: Optional[Sequence[str]] = None,
    feature_weights: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """선택된 reference sequence만 사용해 scaler를 학습합니다.

    사용자 입력이나 평가 대상이 scaler 학습에 섞이지 않도록 reference set 기준으로
    median, mean, std를 계산합니다.
    """

    if len(sequences) == 0:
        raise ValueError("at least one reference sequence is required to fit scaler")
    arr = _finite_array(np.asarray(sequences, dtype=float))
    if arr.ndim != 3:
        raise ValueError(f"sequences must have shape (N, T, F), got {arr.shape}")

    flat = arr.reshape(-1, arr.shape[-1])
    median = np.nanmedian(flat, axis=0)
    median = np.nan_to_num(median, nan=0.0, posinf=0.0, neginf=0.0)
    filled = np.where(np.isfinite(flat), flat, median)
    mean = np.mean(filled, axis=0)
    std = np.std(filled, axis=0)
    std = np.where(std < 1e-8, 1.0, std)

    scaler: Dict[str, Any] = {
        "version": 1,
        "method": "median_impute_then_standardize",
        "n_features": int(arr.shape[-1]),
        "median": median,
        "mean": mean,
        "std": std,
        "n_sequences": int(arr.shape[0]),
        "n_frames_per_sequence": int(arr.shape[1]),
    }
    if feature_names is not None:
        scaler["feature_names"] = [str(x) for x in feature_names]
    if feature_weights is not None:
        scaler["feature_weights"] = np.asarray(feature_weights, dtype=float)
    return scaler


def transform_feature_sequence(sequence: np.ndarray, scaler: Dict[str, Any]) -> np.ndarray:
    """학습된 scaler를 하나의 sequence 또는 batch에 적용합니다."""

    arr = np.asarray(sequence, dtype=float).copy()
    if arr.ndim not in (2, 3):
        raise ValueError(f"sequence must have shape (T, F) or (N, T, F), got {arr.shape}")
    n_features = int(scaler["n_features"])
    if arr.shape[-1] != n_features:
        raise ValueError(f"expected {n_features} features, got {arr.shape[-1]}")

    median = np.asarray(scaler["median"], dtype=float)
    mean = np.asarray(scaler["mean"], dtype=float)
    std = np.asarray(scaler["std"], dtype=float)
    arr[~np.isfinite(arr)] = np.nan
    arr = np.where(np.isfinite(arr), arr, median)
    scaled = (arr - mean) / std
    return np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)


def inverse_transform_feature_sequence(sequence: np.ndarray, scaler: Dict[str, Any]) -> np.ndarray:
    """mean/std scaling을 되돌립니다. 원래 NaN 위치까지 복원하지는 않습니다."""

    arr = np.asarray(sequence, dtype=float)
    mean = np.asarray(scaler["mean"], dtype=float)
    std = np.asarray(scaler["std"], dtype=float)
    return arr * std + mean


def save_scaler(scaler: Dict[str, Any], path: str | Path) -> None:
    """scaler 정보를 JSON으로 저장합니다."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(_jsonable(scaler), f, ensure_ascii=False, indent=2)


def load_scaler(path: str | Path) -> Dict[str, Any]:
    """JSON으로 저장된 scaler를 다시 읽어 numpy 배열 형태로 복원합니다."""
    in_path = Path(path)
    if not in_path.exists():
        raise FileNotFoundError(f"scaler json not found: {in_path}")
    with in_path.open("r", encoding="utf-8") as f:
        scaler = json.load(f)
    for key in ("median", "mean", "std", "feature_weights"):
        if key in scaler and scaler[key] is not None:
            scaler[key] = np.asarray(scaler[key], dtype=float)
    return scaler
