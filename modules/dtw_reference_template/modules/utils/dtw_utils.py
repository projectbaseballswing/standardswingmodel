"""pose-only feature sequence 비교를 위한 DTW 유틸입니다.

두 스윙 sequence의 진행 속도 차이를 보정하기 위해 DTW distance와
alignment path를 계산합니다. 
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np


AlignmentPath = List[Tuple[int, int]]


def _safe_array(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def _safe_weights(feature_weights: Optional[Sequence[float]], n_features: int) -> np.ndarray:
    if feature_weights is None:
        return np.ones(n_features, dtype=float)
    weights = _safe_array(np.asarray(feature_weights, dtype=float))
    if weights.shape != (n_features,):
        raise ValueError(f"feature_weights must have shape ({n_features},), got {weights.shape}")
    weights = np.maximum(weights, 0.0)
    if float(np.sum(weights)) <= 0.0:
        raise ValueError("feature_weights must contain at least one positive value")
    return weights


def weighted_frame_distance(
    x: Sequence[float],
    y: Sequence[float],
    feature_weights: Optional[Sequence[float]] = None,
) -> float:
    """두 frame feature vector 사이의 가중 RMSE 거리를 계산합니다.

    NaN/Inf는 0으로 안전하게 치환하고, feature weight를 적용해 local DTW cost로
    사용합니다.
    """

    x_arr = _safe_array(np.asarray(x, dtype=float))
    y_arr = _safe_array(np.asarray(y, dtype=float))
    if x_arr.shape != y_arr.shape:
        raise ValueError(f"frame shapes must match, got {x_arr.shape} and {y_arr.shape}")
    if x_arr.ndim != 1:
        raise ValueError(f"frames must be 1D arrays, got shape {x_arr.shape}")

    weights = _safe_weights(feature_weights, x_arr.shape[0])
    diff = x_arr - y_arr
    return float(np.sqrt(np.sum(weights * diff * diff) / float(np.sum(weights))))


def _band_radius(n: int, m: int, sakoe_chiba_ratio: Optional[float]) -> int:
    if sakoe_chiba_ratio is None:
        return max(n, m)
    if sakoe_chiba_ratio < 0:
        raise ValueError("sakoe_chiba_ratio must be >= 0")
    return max(abs(n - m), int(np.ceil(max(n, m) * sakoe_chiba_ratio)))


def dtw_distance(
    X: np.ndarray,
    Y: np.ndarray,
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
) -> Tuple[float, AlignmentPath]:
    """두 feature sequence의 DTW 거리와 alignment path를 반환합니다.

    반환 path는 `(X의 frame index, Y의 frame index)` 쌍입니다. 거리값은 누적
    cost를 path 길이로 나눈 normalized distance입니다.
    """

    x_seq = _safe_array(np.asarray(X, dtype=float))
    y_seq = _safe_array(np.asarray(Y, dtype=float))
    if x_seq.ndim != 2 or y_seq.ndim != 2:
        raise ValueError(f"sequences must be 2D arrays, got {x_seq.shape} and {y_seq.shape}")
    if x_seq.shape[1] != y_seq.shape[1]:
        raise ValueError(f"feature dimensions must match, got {x_seq.shape[1]} and {y_seq.shape[1]}")
    if x_seq.shape[0] == 0 or y_seq.shape[0] == 0:
        raise ValueError("sequences must contain at least one frame")

    n, m = x_seq.shape[0], y_seq.shape[0]
    weights = _safe_weights(feature_weights, x_seq.shape[1])
    radius = _band_radius(n, m, sakoe_chiba_ratio)

    costs = np.full((n + 1, m + 1), np.inf, dtype=float)
    steps = np.zeros((n + 1, m + 1), dtype=np.uint8)
    costs[0, 0] = 0.0

    for i in range(1, n + 1):
        j_start = max(1, i - radius)
        j_end = min(m, i + radius)
        for j in range(j_start, j_end + 1):
            local = weighted_frame_distance(x_seq[i - 1], y_seq[j - 1], weights)
            candidates = (costs[i - 1, j], costs[i, j - 1], costs[i - 1, j - 1])
            step = int(np.argmin(candidates))
            costs[i, j] = local + candidates[step]
            steps[i, j] = step

    if not np.isfinite(costs[n, m]):
        raise ValueError("DTW path not found. Increase sakoe_chiba_ratio for these sequence lengths.")

    path: AlignmentPath = []
    i, j = n, m
    while i > 0 or j > 0:
        if i == 0:
            j -= 1
            path.append((0, j))
            continue
        if j == 0:
            i -= 1
            path.append((i, 0))
            continue
        path.append((i - 1, j - 1))
        step = steps[i, j]
        if step == 0:
            i -= 1
        elif step == 1:
            j -= 1
        else:
            i -= 1
            j -= 1

    path.reverse()
    return float(costs[n, m] / max(len(path), 1)), path


def pairwise_dtw_matrix(
    sequences: Sequence[np.ndarray],
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
) -> np.ndarray:
    """여러 sequence 사이의 pairwise DTW distance matrix를 계산합니다."""

    seqs = [np.asarray(seq, dtype=float) for seq in sequences]
    n = len(seqs)
    matrix = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            distance, _ = dtw_distance(
                seqs[i],
                seqs[j],
                feature_weights=feature_weights,
                sakoe_chiba_ratio=sakoe_chiba_ratio,
            )
            matrix[i, j] = distance
            matrix[j, i] = distance
    return matrix
