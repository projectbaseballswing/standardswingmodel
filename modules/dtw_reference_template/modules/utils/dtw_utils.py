"""Small DTW helpers for final 80x64 feature sequences."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np


AlignmentPath = List[Tuple[int, int]]
EXPECTED_SEQUENCE_LEN = 80
EXPECTED_FEATURE_DIM = 64
EXPECTED_SEQUENCE_SHAPE = (EXPECTED_SEQUENCE_LEN, EXPECTED_FEATURE_DIM)
ALIGNED_SUFFIXES = ("_DTW_aligned.npy", "_DTW_aligned_scaled.npy")


def _as_finite_array(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def _validate_sequence(sequence: np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(sequence, dtype=float)
    if arr.shape != EXPECTED_SEQUENCE_SHAPE:
        raise ValueError(f"{name} must have shape {EXPECTED_SEQUENCE_SHAPE}, got {arr.shape}")
    return arr


def _safe_weights(feature_weights: Optional[Sequence[float]], n_features: int) -> np.ndarray:
    if n_features != EXPECTED_FEATURE_DIM:
        raise ValueError(f"feature dimension must be {EXPECTED_FEATURE_DIM}, got {n_features}")
    if feature_weights is None:
        return np.ones(n_features, dtype=float)
    weights = _as_finite_array(np.asarray(feature_weights, dtype=float))
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
    """Return weighted RMSE between two 64D frames."""

    x_arr = _as_finite_array(np.asarray(x, dtype=float))
    y_arr = _as_finite_array(np.asarray(y, dtype=float))
    if x_arr.shape != y_arr.shape:
        raise ValueError(f"frame shapes must match, got {x_arr.shape} and {y_arr.shape}")
    if x_arr.shape != (EXPECTED_FEATURE_DIM,):
        raise ValueError(f"frames must have length {EXPECTED_FEATURE_DIM}, got {x_arr.shape}")

    weights = _safe_weights(feature_weights, x_arr.shape[0])
    diff = x_arr - y_arr
    return float(np.sqrt(np.sum(weights * diff * diff) / float(np.sum(weights))))


def _band_radius(n_frames: int, m_frames: int, sakoe_chiba_ratio: Optional[float]) -> int:
    if sakoe_chiba_ratio is None:
        return max(n_frames, m_frames)
    if sakoe_chiba_ratio < 0:
        raise ValueError("sakoe_chiba_ratio must be >= 0")
    return max(abs(n_frames - m_frames), int(np.ceil(max(n_frames, m_frames) * sakoe_chiba_ratio)))


def dtw_distance(
    x_sequence: np.ndarray,
    y_sequence: np.ndarray,
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
) -> Tuple[float, AlignmentPath]:
    """Return normalized DTW distance and path for two final 80x64 sequences.

    Path entries are ``(x_frame_index, y_frame_index)``.
    """

    x_seq = _as_finite_array(_validate_sequence(x_sequence, "x_sequence"))
    y_seq = _as_finite_array(_validate_sequence(y_sequence, "y_sequence"))
    n_frames, m_frames = x_seq.shape[0], y_seq.shape[0]
    weights = _safe_weights(feature_weights, x_seq.shape[1])
    radius = _band_radius(n_frames, m_frames, sakoe_chiba_ratio)

    costs = np.full((n_frames + 1, m_frames + 1), np.inf, dtype=float)
    steps = np.zeros((n_frames + 1, m_frames + 1), dtype=np.uint8)
    costs[0, 0] = 0.0

    for i in range(1, n_frames + 1):
        j_start = max(1, i - radius)
        j_end = min(m_frames, i + radius)
        for j in range(j_start, j_end + 1):
            local_cost = weighted_frame_distance(x_seq[i - 1], y_seq[j - 1], weights)
            candidates = (
                costs[i - 1, j - 1],
                costs[i - 1, j],
                costs[i, j - 1],
            )
            step = int(np.argmin(candidates))
            costs[i, j] = local_cost + candidates[step]
            steps[i, j] = step

    if not np.isfinite(costs[n_frames, m_frames]):
        raise ValueError("DTW path not found. Increase sakoe_chiba_ratio.")

    path: AlignmentPath = []
    i, j = n_frames, m_frames
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
        step = int(steps[i, j])
        if step == 0:
            i -= 1
            j -= 1
        elif step == 1:
            i -= 1
        else:
            j -= 1

    path.reverse()
    return float(costs[n_frames, m_frames] / max(len(path), 1)), path


def pairwise_dtw_matrix(
    sequences: Sequence[np.ndarray],
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
) -> np.ndarray:
    """Return a symmetric pairwise DTW distance matrix."""

    seqs = [_validate_sequence(np.asarray(seq, dtype=float), f"sequences[{idx}]") for idx, seq in enumerate(sequences)]
    n_sequences = len(seqs)
    matrix = np.zeros((n_sequences, n_sequences), dtype=float)
    for i in range(n_sequences):
        for j in range(i + 1, n_sequences):
            distance, _ = dtw_distance(
                seqs[i],
                seqs[j],
                feature_weights=feature_weights,
                sakoe_chiba_ratio=sakoe_chiba_ratio,
            )
            matrix[i, j] = distance
            matrix[j, i] = distance
    return matrix


def align_sequence_to_template_timeline(
    source_sequence: np.ndarray,
    template_length: int,
    alignment_path: AlignmentPath,
) -> Tuple[np.ndarray, np.ndarray]:
    """Average source frames into template-frame buckets using a DTW path."""

    source = _validate_sequence(source_sequence, "source_sequence")
    if template_length != EXPECTED_SEQUENCE_LEN:
        raise ValueError(f"template_length must be {EXPECTED_SEQUENCE_LEN}, got {template_length}")

    buckets: List[List[np.ndarray]] = [[] for _ in range(template_length)]
    for source_frame, template_frame in alignment_path:
        if not (0 <= source_frame < source.shape[0]):
            raise ValueError(f"source frame index out of range: {source_frame}")
        if not (0 <= template_frame < template_length):
            raise ValueError(f"template frame index out of range: {template_frame}")
        buckets[template_frame].append(source[source_frame])

    aligned = np.zeros((template_length, source.shape[1]), dtype=float)
    counts = np.zeros(template_length, dtype=int)
    for frame_idx, bucket in enumerate(buckets):
        if not bucket:
            raise ValueError(f"DTW path did not cover template frame {frame_idx}")
        stacked = np.asarray(bucket, dtype=float)
        counts[frame_idx] = stacked.shape[0]
        valid = np.isfinite(stacked)
        values = np.where(valid, stacked, 0.0)
        denom = np.sum(valid, axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            aligned[frame_idx] = np.sum(values, axis=0) / denom
        aligned[frame_idx, denom == 0] = np.nan

    return aligned, counts
