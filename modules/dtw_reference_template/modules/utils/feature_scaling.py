"""Feature scaling helpers for final 80x64 DTW templates."""

from __future__ import annotations

from typing import Any, Dict, Sequence

import numpy as np


EXPECTED_SEQUENCE_LEN = 80
EXPECTED_FEATURE_DIM = 64
EXPECTED_SEQUENCE_SHAPE = (EXPECTED_SEQUENCE_LEN, EXPECTED_FEATURE_DIM)


def validate_feature_sequence(sequence: np.ndarray, name: str = "feature sequence") -> np.ndarray:
    """Return ``sequence`` as float after enforcing exact ``(80, 64)`` shape."""

    arr = np.asarray(sequence, dtype=float)
    if arr.shape != EXPECTED_SEQUENCE_SHAPE:
        raise ValueError(f"{name} must have shape {EXPECTED_SEQUENCE_SHAPE}, got {arr.shape}")
    return arr


def validate_feature_dataset(sequences: Sequence[np.ndarray], name: str = "feature dataset") -> np.ndarray:
    """Return ``sequences`` as float after enforcing exact ``(N, 80, 64)`` shape."""

    arr = np.asarray(sequences, dtype=float)
    if arr.ndim != 3 or arr.shape[1:] != EXPECTED_SEQUENCE_SHAPE:
        raise ValueError(f"{name} must have shape (N, 80, 64), got {arr.shape}")
    if arr.shape[0] < 1:
        raise ValueError(f"{name} must contain at least one sequence")
    return arr


def validate_feature_vector(values: Sequence[float], name: str) -> np.ndarray:
    """Return a validated 64-element vector."""

    arr = np.asarray(values, dtype=float)
    if arr.shape != (EXPECTED_FEATURE_DIM,):
        raise ValueError(f"{name} must have length {EXPECTED_FEATURE_DIM}, got shape {arr.shape}")
    return arr


def validate_feature_names(feature_names: Sequence[str], name: str = "feature_names") -> list[str]:
    names = [str(value) for value in feature_names]
    if len(names) != EXPECTED_FEATURE_DIM:
        raise ValueError(f"{name} must contain {EXPECTED_FEATURE_DIM} entries, got {len(names)}")
    return names


def validate_scaler(scaler: Dict[str, Any]) -> Dict[str, Any]:
    """Validate scaler vectors stored in ``reference_templates.npz``."""

    for key in ("median", "mean", "std"):
        if key not in scaler:
            raise ValueError(f"scaler is missing required vector: {key}")
        scaler[key] = validate_feature_vector(scaler[key], f"scaler[{key!r}]")
    return scaler


def fit_feature_scaler(
    sequences: Sequence[np.ndarray],
    feature_names: Sequence[str] | None = None,
    feature_weights: Sequence[float] | None = None,
) -> Dict[str, Any]:
    """Fit median-impute then mean/std scaling from selected reference features."""

    arr = validate_feature_dataset(sequences, name="reference sequences")
    finite = np.asarray(arr, dtype=float).copy()
    finite[~np.isfinite(finite)] = np.nan
    flat = finite.reshape(-1, finite.shape[-1])

    median = np.nanmedian(flat, axis=0)
    median = np.nan_to_num(median, nan=0.0, posinf=0.0, neginf=0.0)
    filled = np.where(np.isfinite(flat), flat, median)
    mean = np.mean(filled, axis=0)
    std = np.std(filled, axis=0)
    std = np.where(std < 1e-8, 1.0, std)

    scaler: Dict[str, Any] = {
        "median": median,
        "mean": mean,
        "std": std,
        "n_sequences": int(arr.shape[0]),
    }
    if feature_names is not None:
        scaler["feature_names"] = validate_feature_names(feature_names)
    if feature_weights is not None:
        scaler["feature_weights"] = validate_feature_vector(feature_weights, "feature_weights")
    return validate_scaler(scaler)


def transform_feature_sequence(sequence: np.ndarray, scaler: Dict[str, Any]) -> np.ndarray:
    """Apply a fitted scaler to one sequence or a batch of sequences."""

    scaler = validate_scaler(dict(scaler))
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
    filled = np.where(np.isfinite(arr), arr, median)
    scaled = (filled - mean) / std
    return np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)
