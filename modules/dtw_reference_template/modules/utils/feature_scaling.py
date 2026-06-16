"""DTW 비교 전에 final feature scale을 맞추는 유틸입니다.

최종 DTW feature format은 한 sequence가 정확히 ``(80, 64)``이고, dataset은
정확히 ``(N, 80, 64)``입니다. 이 모듈은 reference set 기준 median
imputation과 mean/std scaling을 담당하며, scaler vector도 모두 64차원으로
검증합니다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np


EXPECTED_SEQUENCE_LEN = 80
EXPECTED_FEATURE_DIM = 64
EXPECTED_SEQUENCE_SHAPE = (EXPECTED_SEQUENCE_LEN, EXPECTED_FEATURE_DIM)


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


def validate_feature_sequence(sequence: np.ndarray, name: str = "feature sequence") -> np.ndarray:
    """Return ``sequence`` as float after enforcing the final ``(80, 64)`` shape."""

    arr = np.asarray(sequence, dtype=float)
    if arr.shape != EXPECTED_SEQUENCE_SHAPE:
        raise ValueError(f"{name} must have shape {EXPECTED_SEQUENCE_SHAPE}, got {arr.shape}")
    return arr


def validate_feature_dataset(sequences: Sequence[np.ndarray], name: str = "feature dataset") -> np.ndarray:
    """Return ``sequences`` as float after enforcing final ``(N, 80, 64)`` shape."""

    arr = np.asarray(sequences, dtype=float)
    if arr.ndim != 3 or arr.shape[1:] != EXPECTED_SEQUENCE_SHAPE:
        raise ValueError(f"{name} must have shape (N, 80, 64), got {arr.shape}")
    if arr.shape[0] < 1:
        raise ValueError(f"{name} must contain at least one sequence")
    return arr


def validate_feature_vector(values: Sequence[float], name: str) -> np.ndarray:
    """Return a 64-element vector as float."""

    arr = np.asarray(values, dtype=float)
    if arr.shape != (EXPECTED_FEATURE_DIM,):
        raise ValueError(f"{name} must have length {EXPECTED_FEATURE_DIM}, got shape {arr.shape}")
    return arr


def validate_feature_names(feature_names: Sequence[str], name: str = "feature_names") -> list[str]:
    names = [str(x) for x in feature_names]
    if len(names) != EXPECTED_FEATURE_DIM:
        raise ValueError(f"{name} must contain {EXPECTED_FEATURE_DIM} entries, got {len(names)}")
    return names


def validate_scaler(scaler: Dict[str, Any]) -> Dict[str, Any]:
    """Validate that a saved scaler matches the final 64D feature format."""

    n_features = int(scaler.get("n_features", -1))
    if n_features != EXPECTED_FEATURE_DIM:
        raise ValueError(f"scaler n_features must be {EXPECTED_FEATURE_DIM}, got {n_features}")
    n_frames = scaler.get("n_frames_per_sequence")
    if n_frames is not None and int(n_frames) != EXPECTED_SEQUENCE_LEN:
        raise ValueError(f"scaler n_frames_per_sequence must be {EXPECTED_SEQUENCE_LEN}, got {n_frames}")
    for key in ("median", "mean", "std"):
        if key not in scaler:
            raise ValueError(f"scaler is missing required vector: {key}")
        scaler[key] = validate_feature_vector(scaler[key], f"scaler[{key!r}]")
    if "feature_weights" in scaler and scaler["feature_weights"] is not None:
        scaler["feature_weights"] = validate_feature_vector(scaler["feature_weights"], "scaler['feature_weights']")
    if "feature_names" in scaler and scaler["feature_names"] is not None:
        scaler["feature_names"] = validate_feature_names(scaler["feature_names"], "scaler['feature_names']")
    return scaler


def fit_feature_scaler(
    sequences: Sequence[np.ndarray],
    feature_names: Optional[Sequence[str]] = None,
    feature_weights: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """선택된 reference sequence만 사용해 scaler를 학습합니다.

    사용자 입력이나 평가 대상이 scaler 학습에 섞이지 않도록 reference set 기준으로
    median, mean, std를 계산합니다.
    """

    arr = _finite_array(validate_feature_dataset(sequences, name="reference sequences"))

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
        scaler["feature_names"] = validate_feature_names(feature_names)
    if feature_weights is not None:
        scaler["feature_weights"] = validate_feature_vector(feature_weights, "feature_weights")
    return validate_scaler(scaler)


def transform_feature_sequence(sequence: np.ndarray, scaler: Dict[str, Any]) -> np.ndarray:
    """학습된 scaler를 하나의 sequence 또는 batch에 적용합니다."""

    scaler = validate_scaler(scaler)
    arr = np.asarray(sequence, dtype=float).copy()
    if arr.ndim == 2:
        validate_feature_sequence(arr)
    elif arr.ndim == 3:
        validate_feature_dataset(arr)
    else:
        raise ValueError(f"sequence must have shape (80, 64) or (N, 80, 64), got {arr.shape}")

    median = np.asarray(scaler["median"], dtype=float)
    mean = np.asarray(scaler["mean"], dtype=float)
    std = np.asarray(scaler["std"], dtype=float)
    arr[~np.isfinite(arr)] = np.nan
    arr = np.where(np.isfinite(arr), arr, median)
    scaled = (arr - mean) / std
    return np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)


def inverse_transform_feature_sequence(sequence: np.ndarray, scaler: Dict[str, Any]) -> np.ndarray:
    """mean/std scaling을 되돌립니다. 원래 NaN 위치까지 복원하지는 않습니다."""

    scaler = validate_scaler(scaler)
    arr = np.asarray(sequence, dtype=float)
    if arr.ndim == 2:
        validate_feature_sequence(arr, name="scaled feature sequence")
    elif arr.ndim == 3:
        validate_feature_dataset(arr, name="scaled feature dataset")
    else:
        raise ValueError(f"sequence must have shape (80, 64) or (N, 80, 64), got {arr.shape}")
    mean = np.asarray(scaler["mean"], dtype=float)
    std = np.asarray(scaler["std"], dtype=float)
    return arr * std + mean


def save_scaler(scaler: Dict[str, Any], path: str | Path) -> None:
    """scaler 정보를 JSON으로 저장합니다."""
    validate_scaler(scaler)
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
    return validate_scaler(scaler)
