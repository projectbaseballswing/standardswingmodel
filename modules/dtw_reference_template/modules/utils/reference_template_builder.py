"""Build player-balanced DTW reference templates from individual .npy files."""

from __future__ import annotations

import json
import math
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from modules.utils.dtw_utils import (
    EXPECTED_FEATURE_DIM,
    EXPECTED_SEQUENCE_LEN,
    EXPECTED_SEQUENCE_SHAPE,
    align_sequence_to_template_timeline,
    dtw_distance,
    pairwise_dtw_matrix,
)
from modules.utils.feature_scaling import (
    fit_feature_scaler,
    transform_feature_sequence,
    validate_feature_dataset,
    validate_feature_names,
    validate_feature_sequence,
    validate_feature_vector,
)


FEATURE_GROUPS: Dict[str, Tuple[int, int]] = {
    "landmark_xyz_visibility": (0, 48),
    "relative_positions": (48, 57),
    "angles_deg": (57, 64),
}

ALIGNED_SUFFIXES = ("_DTW_aligned.npy", "_DTW_aligned_scaled.npy")


@dataclass
class FeatureRecord:
    path: Path
    video_id: str
    label: str
    feature: np.ndarray | None
    status: str
    nan_ratio: float
    note: str = ""


@dataclass
class TemplateResult:
    label: str
    mean_template: np.ndarray
    std_template: np.ndarray
    count_template: np.ndarray
    medoid_sequence: np.ndarray
    medoid_video_id: str
    source_video_ids: List[str]
    sample_count: int
    mean_to_medoid_distance: float


def normalize_text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value)).strip()


def infer_label_from_stem(stem: str) -> str:
    """Infer player label from a filename stem such as ``Kt_6_PlayerName``."""

    normalized = normalize_text(stem)
    parts = [part for part in normalized.split("_") if part]
    if len(parts) >= 3:
        return normalize_text("_".join(parts[2:]))
    if parts:
        return normalize_text(parts[-1])
    return ""


def create_default_feature_names() -> List[str]:
    names: List[str] = []
    for landmark_idx in range(12):
        names.extend(
            [
                f"landmark_{landmark_idx:02d}_x",
                f"landmark_{landmark_idx:02d}_y",
                f"landmark_{landmark_idx:02d}_z",
                f"landmark_{landmark_idx:02d}_visibility",
            ]
        )
    names.extend(f"relative_position_{idx:02d}" for idx in range(9))
    names.extend(f"angle_deg_{idx:02d}" for idx in range(7))
    return validate_feature_names(names)


def create_default_feature_weights() -> np.ndarray:
    """Create the final feature weights used for DTW local distance."""

    weights = np.ones(EXPECTED_FEATURE_DIM, dtype=float)
    weights[0:48] = 0.7
    weights[3:48:4] = 0.2
    weights[48:57] = 1.0
    weights[57:64] = 1.2
    return validate_feature_vector(weights, "feature_weights")


def collect_npy_feature_files(feature_dir: str | Path, recursive: bool, max_files: int = 0) -> List[Path]:
    base_dir = Path(feature_dir)
    if not base_dir.exists():
        raise FileNotFoundError(f"feature dir not found: {base_dir}")
    if not base_dir.is_dir():
        raise NotADirectoryError(f"feature dir is not a directory: {base_dir}")

    pattern = "**/*.npy" if recursive else "*.npy"
    paths = sorted(path for path in base_dir.glob(pattern) if path.is_file())
    paths = [path for path in paths if not path.name.endswith(ALIGNED_SUFFIXES)]
    if max_files < 0:
        raise ValueError("max_files must be >= 0")
    if max_files > 0:
        paths = paths[:max_files]
    if not paths:
        raise ValueError(f"no input .npy files found in {base_dir}")
    return paths


def load_npy_feature_records(paths: Sequence[Path]) -> List[FeatureRecord]:
    records: List[FeatureRecord] = []
    for path in paths:
        video_id = normalize_text(path.stem)
        label = infer_label_from_stem(path.stem)
        if not label:
            records.append(
                FeatureRecord(
                    path=path,
                    video_id=video_id,
                    label="",
                    feature=None,
                    status="label_missing",
                    nan_ratio=float("nan"),
                    note="could not infer player label from file name",
                )
            )
            continue

        try:
            feature = np.asarray(np.load(path, allow_pickle=False), dtype=float)
        except Exception as exc:
            records.append(
                FeatureRecord(
                    path=path,
                    video_id=video_id,
                    label=label,
                    feature=None,
                    status="load_error",
                    nan_ratio=float("nan"),
                    note=str(exc),
                )
            )
            continue

        if feature.shape != EXPECTED_SEQUENCE_SHAPE:
            records.append(
                FeatureRecord(
                    path=path,
                    video_id=video_id,
                    label=label,
                    feature=None,
                    status="invalid_shape",
                    nan_ratio=float("nan"),
                    note=f"expected shape {EXPECTED_SEQUENCE_SHAPE}, got {feature.shape}",
                )
            )
            continue

        nan_ratio = float(np.mean(~np.isfinite(feature)))
        records.append(
            FeatureRecord(
                path=path,
                video_id=video_id,
                label=label,
                feature=feature,
                status="ok",
                nan_ratio=nan_ratio,
                note="",
            )
        )
    return records


def _record_note(record: FeatureRecord, label_counts: Counter[str], max_nan_ratio: float, min_label_count: int) -> str:
    if record.status != "ok":
        return record.note
    if not math.isfinite(record.nan_ratio) or record.nan_ratio > max_nan_ratio:
        return f"nan_ratio {record.nan_ratio:.6f} exceeds max_nan_ratio {max_nan_ratio:.6f}"
    if label_counts.get(record.label, 0) < min_label_count:
        return f"label count {label_counts.get(record.label, 0)} is below min_label_count {min_label_count}"
    return ""


def select_records_for_template(
    records: Sequence[FeatureRecord],
    min_label_count: int,
    max_nan_ratio: float,
) -> Tuple[List[FeatureRecord], List[Dict[str, Any]]]:
    if min_label_count < 1:
        raise ValueError("min_label_count must be >= 1")
    if not (0.0 <= max_nan_ratio <= 1.0):
        raise ValueError("max_nan_ratio must be between 0 and 1")

    valid_candidates = [
        record
        for record in records
        if record.status == "ok" and math.isfinite(record.nan_ratio) and record.nan_ratio <= max_nan_ratio
    ]
    label_counts = Counter(record.label for record in valid_candidates)
    selected = [record for record in valid_candidates if label_counts[record.label] >= min_label_count]

    selection_rows = []
    selected_paths = {record.path.resolve() for record in selected}
    for record in records:
        selected_flag = record.path.resolve() in selected_paths
        selection_rows.append(
            {
                "path": str(record.path),
                "video_id": record.video_id,
                "label": record.label,
                "status": record.status,
                "nan_ratio": record.nan_ratio if math.isfinite(record.nan_ratio) else None,
                "selected": selected_flag,
                "note": "" if selected_flag else _record_note(record, label_counts, max_nan_ratio, min_label_count),
            }
        )

    if not selected:
        raise ValueError("no reference sequences remain after filtering")
    return selected, selection_rows


def stack_record_features(records: Sequence[FeatureRecord]) -> np.ndarray:
    features = [record.feature for record in records]
    if any(feature is None for feature in features):
        raise ValueError("selected records must all contain loaded features")
    return validate_feature_dataset(np.stack(features, axis=0), name="selected features")


def fit_and_scale_records(
    records: Sequence[FeatureRecord],
    feature_names: Sequence[str],
    feature_weights: Sequence[float],
) -> Tuple[Dict[str, Any], np.ndarray]:
    features = stack_record_features(records)
    scaler = fit_feature_scaler(features, feature_names=feature_names, feature_weights=feature_weights)
    return scaler, transform_feature_sequence(features, scaler)


def choose_medoid(
    sequences: Sequence[np.ndarray],
    video_ids: Sequence[str],
    feature_weights: Sequence[float] | None,
    sakoe_chiba_ratio: float,
) -> Tuple[int, str, np.ndarray]:
    if len(sequences) == 0:
        raise ValueError("cannot choose medoid from an empty sequence list")
    if len(sequences) != len(video_ids):
        raise ValueError("sequences and video_ids length mismatch")
    for idx, sequence in enumerate(sequences):
        validate_feature_sequence(sequence, name=f"sequences[{idx}]")
    if feature_weights is not None:
        validate_feature_vector(feature_weights, "feature_weights")

    if len(sequences) == 1:
        return 0, str(video_ids[0]), np.zeros((1, 1), dtype=float)
    matrix = pairwise_dtw_matrix(sequences, feature_weights=feature_weights, sakoe_chiba_ratio=sakoe_chiba_ratio)
    medoid_idx = int(np.argmin(np.mean(matrix, axis=1)))
    return medoid_idx, str(video_ids[medoid_idx]), matrix


def build_dtw_aligned_mean_template(
    sequences: Sequence[np.ndarray],
    medoid_sequence: np.ndarray,
    feature_weights: Sequence[float] | None,
    sakoe_chiba_ratio: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Align sequences to the medoid timeline and average them."""

    if len(sequences) == 0:
        raise ValueError("at least one sequence is required")
    medoid = validate_feature_sequence(medoid_sequence, name="medoid_sequence")
    if feature_weights is not None:
        validate_feature_vector(feature_weights, "feature_weights")

    aligned_sequences: List[np.ndarray] = []
    count_template = np.zeros(EXPECTED_SEQUENCE_LEN, dtype=int)
    distances: List[float] = []
    for idx, sequence in enumerate(sequences):
        source = validate_feature_sequence(sequence, name=f"sequences[{idx}]")
        distance, path = dtw_distance(
            source,
            medoid,
            feature_weights=feature_weights,
            sakoe_chiba_ratio=sakoe_chiba_ratio,
        )
        aligned, counts = align_sequence_to_template_timeline(source, medoid.shape[0], path)
        aligned_sequences.append(aligned)
        count_template += counts
        distances.append(distance)

    stacked = np.asarray(aligned_sequences, dtype=float)
    mean_template = np.nanmean(stacked, axis=0)
    std_template = np.nanstd(stacked, axis=0)
    return (
        np.nan_to_num(mean_template, nan=0.0, posinf=0.0, neginf=0.0),
        np.nan_to_num(std_template, nan=0.0, posinf=0.0, neginf=0.0),
        count_template,
        float(np.mean(distances)),
    )


def _make_template(
    label: str,
    sequences: Sequence[np.ndarray],
    video_ids: Sequence[str],
    feature_weights: Sequence[float] | None,
    sakoe_chiba_ratio: float,
) -> TemplateResult:
    medoid_idx, medoid_video_id, _ = choose_medoid(
        sequences,
        video_ids,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=sakoe_chiba_ratio,
    )
    medoid_sequence = validate_feature_sequence(sequences[medoid_idx], name="medoid_sequence")
    mean_template, std_template, count_template, mean_distance = build_dtw_aligned_mean_template(
        sequences,
        medoid_sequence,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=sakoe_chiba_ratio,
    )
    return TemplateResult(
        label=label,
        mean_template=mean_template,
        std_template=std_template,
        count_template=count_template,
        medoid_sequence=medoid_sequence,
        medoid_video_id=medoid_video_id,
        source_video_ids=[str(value) for value in video_ids],
        sample_count=len(sequences),
        mean_to_medoid_distance=mean_distance,
    )


def build_label_templates(
    scaled_features: Sequence[np.ndarray],
    video_ids: Sequence[str],
    labels: Sequence[str],
    feature_weights: Sequence[float] | None,
    sakoe_chiba_ratio: float,
) -> List[TemplateResult]:
    if len(scaled_features) != len(video_ids) or len(scaled_features) != len(labels):
        raise ValueError("features, video_ids, and labels must have the same length")

    grouped: Dict[str, List[int]] = defaultdict(list)
    for idx, label in enumerate(labels):
        grouped[str(label)].append(idx)

    templates: List[TemplateResult] = []
    for label in sorted(grouped):
        indices = grouped[label]
        templates.append(
            _make_template(
                label=label,
                sequences=[scaled_features[idx] for idx in indices],
                video_ids=[video_ids[idx] for idx in indices],
                feature_weights=feature_weights,
                sakoe_chiba_ratio=sakoe_chiba_ratio,
            )
        )
    return templates


def build_global_template_from_label_templates(
    label_templates: Sequence[TemplateResult],
    feature_weights: Sequence[float] | None,
    sakoe_chiba_ratio: float,
) -> TemplateResult:
    if not label_templates:
        raise ValueError("at least one label template is required")
    return _make_template(
        label="GLOBAL",
        sequences=[template.mean_template for template in label_templates],
        video_ids=[template.label for template in label_templates],
        feature_weights=feature_weights,
        sakoe_chiba_ratio=sakoe_chiba_ratio,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
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


def save_reference_templates(
    path: str | Path,
    global_template: TemplateResult,
    label_templates: Sequence[TemplateResult],
    feature_names: Sequence[str],
    feature_weights: Sequence[float],
    scaler: Dict[str, Any],
    selected_records: Sequence[FeatureRecord],
    metadata: Dict[str, Any],
) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    feature_names = validate_feature_names(feature_names)
    feature_weights = validate_feature_vector(feature_weights, "feature_weights")
    validate_feature_sequence(global_template.mean_template, name="global_mean_template")
    validate_feature_sequence(global_template.std_template, name="global_std_template")
    validate_feature_sequence(global_template.medoid_sequence, name="global_medoid_sequence")

    for idx, template in enumerate(label_templates):
        validate_feature_sequence(template.mean_template, name=f"label_mean_templates[{idx}]")
        validate_feature_sequence(template.std_template, name=f"label_std_templates[{idx}]")
        validate_feature_sequence(template.medoid_sequence, name=f"label_medoid_sequences[{idx}]")

    payload = {
        "global_mean_template": global_template.mean_template,
        "global_std_template": global_template.std_template,
        "global_count_template": global_template.count_template,
        "global_medoid_sequence": global_template.medoid_sequence,
        "global_medoid_video_id": np.asarray(global_template.medoid_video_id, dtype=object),
        "label_names": np.asarray([template.label for template in label_templates], dtype=object),
        "label_mean_templates": np.asarray([template.mean_template for template in label_templates], dtype=float),
        "label_std_templates": np.asarray([template.std_template for template in label_templates], dtype=float),
        "label_count_templates": np.asarray([template.count_template for template in label_templates], dtype=int),
        "label_medoid_video_ids": np.asarray([template.medoid_video_id for template in label_templates], dtype=object),
        "label_sample_counts": np.asarray([template.sample_count for template in label_templates], dtype=int),
        "feature_names": np.asarray(feature_names, dtype=object),
        "feature_weights": np.asarray(feature_weights, dtype=float),
        "scaler_median": np.asarray(scaler["median"], dtype=float),
        "scaler_mean": np.asarray(scaler["mean"], dtype=float),
        "scaler_std": np.asarray(scaler["std"], dtype=float),
        "selected_video_ids": np.asarray([record.video_id for record in selected_records], dtype=object),
        "selected_labels": np.asarray([record.label for record in selected_records], dtype=object),
        "metadata_json": json.dumps(_jsonable(metadata), ensure_ascii=False),
    }
    np.savez_compressed(out_path, **payload)
