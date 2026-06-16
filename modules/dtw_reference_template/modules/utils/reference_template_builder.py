"""player-balanced DTW reference template 생성 모듈입니다.

팀 feature pipeline이 만든 pose-only feature sequence를 입력으로 받아
선수별 DTW-aligned mean template을 만들고, 선수별 template들을 동일
가중치로 평균해 global reference template을 생성합니다.
"""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from modules.utils.dtw_utils import dtw_distance, pairwise_dtw_matrix
from modules.utils.feature_scaling import (
    EXPECTED_FEATURE_DIM,
    EXPECTED_SEQUENCE_LEN,
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
    "angle_rotation": (57, 64),
}

PHASES: Dict[str, Tuple[int, int]] = {
    "address": (0, 15),
    "loading": (15, 35),
    "stride": (35, 50),
    "pre_impact": (50, 60),
    "impact": (60, 64),
    "follow_through": (64, 80),
}


@dataclass
class FeatureDataset:
    features: np.ndarray
    video_ids: List[str]
    labels: List[str]
    status: List[str]
    nan_ratio: np.ndarray
    feature_names: List[str]
    source_rows: pd.DataFrame
    feature_key: str
    view_group: List[str]
    use_for_template: List[Any]
    reason: List[str]
    quality_score: np.ndarray
    metadata_loaded: bool = False
    selection_report: Optional[pd.DataFrame] = None


@dataclass
class TemplateResult:
    label: str
    template_type: str
    mean_template: np.ndarray
    std_template: np.ndarray
    count_template: np.ndarray
    medoid_sequence: np.ndarray
    medoid_video_id: str
    medoid_local_index: int
    source_indices: List[int]
    source_ids: List[str]
    quality_scores: List[float]
    quality_weighted: bool
    mean_to_medoid_distance: float


def normalize_label(label: Any) -> str:
    """한글 label을 NFC로 정규화해 조합형/완성형 차이를 줄입니다."""
    return unicodedata.normalize("NFC", str(label)).strip()


def create_default_feature_weights(n_features: int = EXPECTED_FEATURE_DIM) -> np.ndarray:
    """DTW distance에 사용할 기본 feature group weight를 생성합니다.

    visibility feature는 신뢰도 정보 성격이므로 좌표/각도 feature보다 낮은 weight를
    부여합니다.
    """
    if n_features != EXPECTED_FEATURE_DIM:
        raise ValueError(f"default weights expect {EXPECTED_FEATURE_DIM} features, got {n_features}")
    weights = np.ones(n_features, dtype=float)
    weights[0:48] = 0.7
    weights[3:48:4] = 0.2
    weights[48:57] = 1.0
    weights[57:64] = 1.2
    return weights


def _safe_key(value: str) -> str:
    safe = re.sub(r"[^\w媛-??+", "_", normalize_label(value), flags=re.UNICODE)
    return re.sub(r"_+", "_", safe).strip("_") or "unknown"


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _to_jsonable(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def _load_npz_array(data: np.lib.npyio.NpzFile, names: Sequence[str]) -> Optional[np.ndarray]:
    for name in names:
        if name in data.files:
            return data[name]
    return None


def _select_feature_array(data: np.lib.npyio.NpzFile, feature_key: Optional[str]) -> Tuple[np.ndarray, str]:
    if feature_key:
        if feature_key not in data.files:
            raise ValueError(f"feature key {feature_key!r} not found. Available keys: {list(data.files)}")
        return data[feature_key], feature_key
    for key in ("raw_features", "features", "scaled_features", "sequences", "X"):
        if key in data.files:
            return data[key], key
    raise ValueError(f"npz does not contain a supported feature array key. Available keys: {list(data.files)}")


def _first_row(indexed_df: Optional[pd.DataFrame], video_id: str) -> Optional[pd.Series]:
    if indexed_df is None or video_id not in indexed_df.index:
        return None
    row = indexed_df.loc[video_id]
    return row.iloc[0] if isinstance(row, pd.DataFrame) else row


def _non_empty(value: Any) -> bool:
    return value is not None and not pd.isna(value) and str(value).strip() != ""


def _field_from(row: Optional[pd.Series], name: str, default: Any = "") -> Any:
    if row is not None and name in row.index and _non_empty(row.get(name)):
        return row.get(name)
    return default


def _float_or_nan(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        return float("nan")
    return out if math.isfinite(out) else float("nan")


def compute_quality_score(nan_ratio: Any) -> float:
    ratio = _float_or_nan(nan_ratio)
    if not math.isfinite(ratio):
        return 0.5
    return float(max(0.0, min(1.0, 1.0 - ratio)))


def parse_template_flag(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def load_feature_dataset(
    features_npz: str | Path,
    per_video_csv: str | Path,
    feature_key: Optional[str] = None,
    metadata_csv: Optional[str | Path] = None,
) -> FeatureDataset:
    """feature dataset과 선택적 metadata를 읽습니다.

    label 우선순위는 `metadata CSV > per_video_summary.csv > NPZ labels`입니다.
    metadata가 없으면 기존 per_video_summary 기준으로만 동작합니다.
    """

    npz_path = Path(features_npz)
    csv_path = Path(per_video_csv)
    if not npz_path.exists():
        raise FileNotFoundError(f"features npz not found: {npz_path}")
    if not csv_path.exists():
        raise FileNotFoundError(f"per-video csv not found: {csv_path}")

    data = np.load(npz_path, allow_pickle=True)
    features, loaded_key = _select_feature_array(data, feature_key)
    features = validate_feature_dataset(features, name="feature dataset")

    video_arr = _load_npz_array(data, ["video_ids", "video_id", "ids"])
    label_arr = _load_npz_array(data, ["labels", "label"])
    if video_arr is None:
        raise ValueError(f"{npz_path} must contain video_ids")
    video_ids = [str(x) for x in video_arr.tolist()]
    if len(video_ids) != features.shape[0]:
        raise ValueError("features and video_ids length mismatch")
    npz_labels = label_arr.tolist() if label_arr is not None else None

    per_video = pd.read_csv(csv_path)
    if "video_id" not in per_video.columns:
        raise ValueError("per_video_summary.csv must contain video_id")
    per_video["video_id"] = per_video["video_id"].astype(str)
    per_index = per_video.set_index("video_id", drop=False)

    meta_index: Optional[pd.DataFrame] = None
    metadata_loaded = False
    if metadata_csv:
        metadata_path = Path(metadata_csv)
        if not metadata_path.exists():
            print(f"[warning] metadata csv not found: {metadata_path}. Continuing without metadata.")
        else:
            meta_df = pd.read_csv(metadata_path)
            if "video_id" not in meta_df.columns:
                raise ValueError("metadata CSV must contain video_id")
            meta_df["video_id"] = meta_df["video_id"].astype(str)
            meta_index = meta_df.set_index("video_id", drop=False)
            metadata_loaded = True

    feature_names_arr = _load_npz_array(data, ["feature_names"])
    feature_names = (
        [str(x) for x in feature_names_arr.tolist()]
        if feature_names_arr is not None
        else [f"feature_{i:02d}" for i in range(EXPECTED_FEATURE_DIM)]
    )
    feature_names = validate_feature_names(feature_names)

    labels: List[str] = []
    status: List[str] = []
    nan_ratio: List[float] = []
    view_group: List[str] = []
    use_for_template: List[Any] = []
    reason: List[str] = []
    quality_score: List[float] = []
    rows: List[Dict[str, Any]] = []

    for idx, video_id in enumerate(video_ids):
        row = _first_row(per_index, video_id)
        if row is None:
            raise ValueError(f"video_id {video_id!r} from npz is missing in per_video_summary.csv")
        meta_row = _first_row(meta_index, video_id)

        label_value = _field_from(meta_row, "label", None)
        if not _non_empty(label_value):
            label_value = _field_from(row, "label", None)
        if not _non_empty(label_value) and npz_labels is not None:
            label_value = npz_labels[idx]
        if not _non_empty(label_value):
            raise ValueError(f"label is missing for video_id {video_id!r}")

        status_value = str(_field_from(row, "status", "")).strip()
        nan_value = _float_or_nan(_field_from(row, "nan_ratio", np.nan))
        view_value = str(_field_from(meta_row, "view_group", "")).strip()
        use_value = _field_from(meta_row, "use_for_template", "")
        reason_value = str(_field_from(meta_row, "reason", "")).strip()
        quality = compute_quality_score(nan_value)

        labels.append(normalize_label(label_value))
        status.append(status_value)
        nan_ratio.append(nan_value)
        view_group.append(view_value)
        use_for_template.append(use_value)
        reason.append(reason_value)
        quality_score.append(quality)
        rows.append(
            {
                "index": idx,
                "video_id": video_id,
                "label": labels[-1],
                "status": status_value,
                "view_group": view_value,
                "use_for_template": use_value,
                "reason": reason_value,
                "nan_ratio": nan_value,
                "quality_score": quality,
            }
        )

    return FeatureDataset(
        features=features,
        video_ids=video_ids,
        labels=labels,
        status=status,
        nan_ratio=np.asarray(nan_ratio, dtype=float),
        feature_names=feature_names,
        source_rows=pd.DataFrame(rows),
        feature_key=loaded_key,
        view_group=view_group,
        use_for_template=use_for_template,
        reason=reason,
        quality_score=np.asarray(quality_score, dtype=float),
        metadata_loaded=metadata_loaded,
    )


def filter_reference_dataset(
    dataset: FeatureDataset,
    min_label_count: int,
    max_nan_ratio: float,
    use_template_only: bool = False,
    view_group: Optional[str] = None,
) -> FeatureDataset:
    if min_label_count < 1:
        raise ValueError("min_label_count must be >= 1")
    if not (0.0 <= max_nan_ratio <= 1.0):
        raise ValueError("max_nan_ratio must be between 0 and 1")

    requested_view = str(view_group).strip() if view_group is not None else ""
    candidate = np.ones(len(dataset.video_ids), dtype=bool)
    reasons: List[List[str]] = [[] for _ in dataset.video_ids]

    for idx, status_value in enumerate(dataset.status):
        if str(status_value).strip().lower() != "ok":
            candidate[idx] = False
            reasons[idx].append("status_not_ok")
    for idx, ratio in enumerate(dataset.nan_ratio):
        if not np.isfinite(ratio):
            candidate[idx] = False
            reasons[idx].append("nan_ratio_missing")
        elif ratio > max_nan_ratio:
            candidate[idx] = False
            reasons[idx].append("nan_ratio_gt_max")
    if use_template_only:
        for idx, flag in enumerate(dataset.use_for_template):
            if not parse_template_flag(flag):
                candidate[idx] = False
                reasons[idx].append("use_for_template_false")
    if requested_view:
        for idx, value in enumerate(dataset.view_group):
            if str(value).strip() != requested_view:
                candidate[idx] = False
                reasons[idx].append("view_group_mismatch")

    label_counts: Dict[str, int] = {}
    for label, keep in zip(dataset.labels, candidate):
        if keep:
            label_counts[label] = label_counts.get(label, 0) + 1

    selected_mask = np.zeros(len(dataset.video_ids), dtype=bool)
    for idx, (label, keep) in enumerate(zip(dataset.labels, candidate)):
        if keep and label_counts.get(label, 0) >= min_label_count:
            selected_mask[idx] = True
        elif keep:
            reasons[idx].append("label_count_lt_min_label_count")

    selected_indices = [idx for idx, selected in enumerate(selected_mask) if selected]
    if not selected_indices:
        raise ValueError("no reference sequences remain after filtering")

    selection_report = dataset.source_rows.copy()
    selection_report["selected"] = selected_mask
    selection_report["exclusion_reason"] = [
        "" if selected else ";".join(reason_list or ["not_selected"])
        for selected, reason_list in zip(selected_mask, reasons)
    ]
    selection_report = selection_report[
        ["video_id", "label", "view_group", "use_for_template", "nan_ratio", "quality_score", "selected", "exclusion_reason"]
    ]

    rows = dataset.source_rows.iloc[selected_indices].copy().reset_index(drop=True)
    rows["original_index"] = selected_indices
    return FeatureDataset(
        features=dataset.features[selected_indices],
        video_ids=[dataset.video_ids[i] for i in selected_indices],
        labels=[dataset.labels[i] for i in selected_indices],
        status=[dataset.status[i] for i in selected_indices],
        nan_ratio=dataset.nan_ratio[selected_indices],
        feature_names=dataset.feature_names,
        source_rows=rows,
        feature_key=dataset.feature_key,
        view_group=[dataset.view_group[i] for i in selected_indices],
        use_for_template=[dataset.use_for_template[i] for i in selected_indices],
        reason=[dataset.reason[i] for i in selected_indices],
        quality_score=dataset.quality_score[selected_indices],
        metadata_loaded=dataset.metadata_loaded,
        selection_report=selection_report,
    )


def save_selected_reference_videos(path: str | Path, dataset: FeatureDataset) -> None:
    """reference 후보로 선택/제외된 영상 목록을 CSV로 저장합니다."""
    if dataset.selection_report is None:
        raise ValueError("dataset does not contain a selection report")
    # reference_templates.npz는 이후 사용자 비교 단계에서 직접 로드되는 기준 모델입니다.
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.selection_report.to_csv(out_path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def choose_medoid(
    sequences: Sequence[np.ndarray],
    video_ids: Sequence[str],
    feature_weights: Optional[Sequence[float]],
    sakoe_chiba_ratio: float,
) -> Tuple[int, str, np.ndarray]:
    if len(sequences) == 0:
        raise ValueError("cannot choose medoid from an empty sequence list")
    if len(sequences) != len(video_ids):
        raise ValueError("sequences and video_ids length mismatch")
    for idx, sequence in enumerate(sequences):
        validate_feature_sequence(sequence, name=f"sequence[{idx}]")
    if feature_weights is not None:
        validate_feature_vector(feature_weights, "feature_weights")
    if len(sequences) == 1:
        return 0, str(video_ids[0]), np.zeros((1, 1), dtype=float)
    # medoid는 새로 만든 평균값이 아니라, 다른 sequence들과 평균 DTW 거리가 가장 작은 실제 sequence입니다.
    matrix = pairwise_dtw_matrix(sequences, feature_weights=feature_weights, sakoe_chiba_ratio=sakoe_chiba_ratio)
    medoid_idx = int(np.argmin(np.mean(matrix, axis=1)))
    return medoid_idx, str(video_ids[medoid_idx]), matrix


def _safe_sample_weights(sample_weights: Optional[Sequence[float]], n_sequences: int) -> Optional[np.ndarray]:
    if sample_weights is None:
        return None
    weights = np.asarray(sample_weights, dtype=float)
    if weights.shape != (n_sequences,):
        raise ValueError(f"sample_weights must have shape ({n_sequences},), got {weights.shape}")
    weights = np.where(np.isfinite(weights), weights, 0.0)
    weights = np.maximum(weights, 0.0)
    return weights if float(np.sum(weights)) > 0.0 else np.ones(n_sequences, dtype=float)


def _weighted_nan_mean_std(stacked: np.ndarray, sample_weights: Optional[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    if sample_weights is None:
        return np.nanmean(stacked, axis=0), np.nanstd(stacked, axis=0)
    valid = np.isfinite(stacked)
    values = np.where(valid, stacked, 0.0)
    weights = sample_weights[:, None] * valid
    denom = np.sum(weights, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.sum(values * weights, axis=0) / denom
        var = np.sum(weights * np.square(values - mean), axis=0) / denom
    return np.where(denom > 0.0, mean, np.nan), np.sqrt(np.where(denom > 0.0, var, np.nan))


def build_dtw_aligned_mean_template(
    sequences: Sequence[np.ndarray],
    medoid_sequence: np.ndarray,
    feature_weights: Optional[Sequence[float]],
    sakoe_chiba_ratio: float,
    sample_weights: Optional[Sequence[float]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """medoid timeline에 DTW 정렬한 뒤 arithmetic mean template을 만듭니다.

    단순히 같은 frame index끼리 평균내지 않고, DTW path로 대응된 frame들을
    bucket에 모은 뒤 평균냅니다.
    """

    if len(sequences) == 0:
        raise ValueError("at least one sequence is required to build a template")
    medoid = validate_feature_sequence(medoid_sequence, name="medoid_sequence")
    for idx, sequence in enumerate(sequences):
        validate_feature_sequence(sequence, name=f"sequence[{idx}]")
    if feature_weights is not None:
        validate_feature_vector(feature_weights, "feature_weights")
    weights = _safe_sample_weights(sample_weights, len(sequences))
    frame_buckets: List[List[np.ndarray]] = [[] for _ in range(medoid.shape[0])]
    weight_buckets: List[List[float]] = [[] for _ in range(medoid.shape[0])]
    distances: List[float] = []

    for seq_idx, sequence in enumerate(sequences):
        seq = np.asarray(sequence, dtype=float)
        distance, path = dtw_distance(seq, medoid, feature_weights=feature_weights, sakoe_chiba_ratio=sakoe_chiba_ratio)
        distances.append(distance)
        sample_weight = 1.0 if weights is None else float(weights[seq_idx])
        for source_frame, medoid_frame in path:
            frame_buckets[medoid_frame].append(seq[source_frame])
            weight_buckets[medoid_frame].append(sample_weight)

    mean_template = np.zeros_like(medoid, dtype=float)
    std_template = np.zeros_like(medoid, dtype=float)
    count_template = np.zeros(medoid.shape[0], dtype=int)
    for frame_idx, bucket in enumerate(frame_buckets):
        if not bucket:
            mean_template[frame_idx] = medoid[frame_idx]
            count_template[frame_idx] = 1
            continue
        stacked = np.asarray(bucket, dtype=float)
        bucket_weights = None if weights is None else np.asarray(weight_buckets[frame_idx], dtype=float)
        mean_template[frame_idx], std_template[frame_idx] = _weighted_nan_mean_std(stacked, bucket_weights)
        count_template[frame_idx] = stacked.shape[0]

    return (
        np.nan_to_num(mean_template, nan=0.0, posinf=0.0, neginf=0.0),
        np.nan_to_num(std_template, nan=0.0, posinf=0.0, neginf=0.0),
        count_template,
        float(np.mean(distances)),
    )


def _make_template(
    label: str,
    template_type: str,
    sequences: Sequence[np.ndarray],
    video_ids: Sequence[str],
    source_indices: Sequence[int],
    feature_weights: Optional[Sequence[float]],
    sakoe_chiba_ratio: float,
    sample_weights: Optional[Sequence[float]] = None,
    quality_scores: Optional[Sequence[float]] = None,
    quality_weighted: bool = False,
) -> TemplateResult:
    medoid_idx, medoid_video_id, _ = choose_medoid(sequences, video_ids, feature_weights, sakoe_chiba_ratio)
    medoid_sequence = np.asarray(sequences[medoid_idx], dtype=float)
    mean_template, std_template, count_template, mean_distance = build_dtw_aligned_mean_template(
        sequences,
        medoid_sequence,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=sakoe_chiba_ratio,
        sample_weights=sample_weights,
    )
    return TemplateResult(
        label=label,
        template_type=template_type,
        mean_template=mean_template,
        std_template=std_template,
        count_template=count_template,
        medoid_sequence=medoid_sequence,
        medoid_video_id=medoid_video_id,
        medoid_local_index=medoid_idx,
        source_indices=list(source_indices),
        source_ids=[str(x) for x in video_ids],
        quality_scores=[float(x) for x in (quality_scores or [])],
        quality_weighted=quality_weighted,
        mean_to_medoid_distance=mean_distance,
    )


# label/player별 template을 생성합니다. 각 label 내부에서 medoid를 선택하고 DTW 정렬 후 평균냅니다.
def build_label_templates(
    sequences: Sequence[np.ndarray],
    video_ids: Sequence[str],
    labels: Sequence[str],
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
    quality_scores: Optional[Sequence[float]] = None,
    quality_weighting: bool = True,
) -> List[TemplateResult]:
    # 선수/label별로 player-level template을 만듭니다.
    templates: List[TemplateResult] = []
    for label in sorted(set(labels)):
        indices = [idx for idx, value in enumerate(labels) if value == label]
        label_quality = [float(quality_scores[i]) for i in indices] if quality_scores is not None else []
        templates.append(
            _make_template(
                label=label,
                template_type="player",
                sequences=[sequences[i] for i in indices],
                video_ids=[video_ids[i] for i in indices],
                source_indices=indices,
                feature_weights=feature_weights,
                sakoe_chiba_ratio=sakoe_chiba_ratio,
                sample_weights=label_quality if quality_weighting and label_quality else None,
                quality_scores=label_quality,
                quality_weighted=quality_weighting and bool(label_quality),
            )
        )
    return templates


# player template들을 이용해 global template을 생성합니다. raw 영상 전체를 직접 평균내지 않습니다.
def build_global_template_from_player_templates(
    player_templates: Sequence[TemplateResult],
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
) -> TemplateResult:
    # global template은 raw video 전체가 아니라 player template들을 입력으로 합니다.
    if not player_templates:
        raise ValueError("at least one player template is required")
    return _make_template(
        label="GLOBAL",
        template_type="global_player_balanced",
        sequences=[template.mean_template for template in player_templates],
        video_ids=[template.label for template in player_templates],
        source_indices=list(range(len(player_templates))),
        feature_weights=feature_weights,
        sakoe_chiba_ratio=sakoe_chiba_ratio,
        quality_scores=[1.0 for _ in player_templates],
        quality_weighted=False,
    )


def fit_and_transform_references(dataset: FeatureDataset, feature_weights: Optional[Sequence[float]] = None) -> Tuple[Dict[str, Any], np.ndarray]:
    """선택된 reference dataset으로 scaler를 fit하고 feature를 transform합니다."""
    scaler = fit_feature_scaler(dataset.features, feature_names=dataset.feature_names, feature_weights=feature_weights)
    return scaler, transform_feature_sequence(dataset.features, scaler)


def _player_quality_metadata(label_templates: Sequence[TemplateResult]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for template in label_templates:
        quality = np.asarray(template.quality_scores, dtype=float)
        rows.append(
            {
                "label": template.label,
                "source_video_ids": template.source_ids,
                "source_indices": template.source_indices,
                "sample_count": len(template.source_indices),
                "quality_scores": template.quality_scores,
                "mean_quality_score": float(np.mean(quality)) if quality.size else None,
                "quality_weighted": template.quality_weighted,
                "medoid_video_id": template.medoid_video_id,
            }
        )
    return rows


def save_reference_templates(
    path: str | Path,
    global_template: TemplateResult,
    label_templates: Sequence[TemplateResult],
    feature_weights: Sequence[float],
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    validate_feature_vector(feature_weights, "feature_weights")
    validate_feature_sequence(global_template.mean_template, name="global_mean_template")
    validate_feature_sequence(global_template.std_template, name="global_std_template")
    validate_feature_sequence(global_template.medoid_sequence, name="global_medoid_sequence")
    if global_template.count_template.shape != (EXPECTED_SEQUENCE_LEN,):
        raise ValueError(f"global_count_template must have shape ({EXPECTED_SEQUENCE_LEN},), got {global_template.count_template.shape}")
    for idx, template in enumerate(label_templates):
        validate_feature_sequence(template.mean_template, name=f"label_mean_templates[{idx}]")
        validate_feature_sequence(template.std_template, name=f"label_std_templates[{idx}]")
        validate_feature_sequence(template.medoid_sequence, name=f"label_medoid_sequences[{idx}]")
        if template.count_template.shape != (EXPECTED_SEQUENCE_LEN,):
            raise ValueError(
                f"label_count_templates[{idx}] must have shape ({EXPECTED_SEQUENCE_LEN},), got {template.count_template.shape}"
            )

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    labels = [template.label for template in label_templates]
    payload = {
        "global_mean_template": global_template.mean_template,
        "global_std_template": global_template.std_template,
        "global_count_template": global_template.count_template,
        "global_medoid_sequence": global_template.medoid_sequence,
        "global_medoid_video_id": np.asarray(global_template.medoid_video_id),
        "global_source_player_labels": np.asarray(global_template.source_ids, dtype=object),
        "label_names": np.asarray(labels, dtype=object),
        "label_mean_templates": np.asarray([t.mean_template for t in label_templates], dtype=float),
        "label_std_templates": np.asarray([t.std_template for t in label_templates], dtype=float),
        "label_count_templates": np.asarray([t.count_template for t in label_templates], dtype=int),
        "label_medoid_video_ids": np.asarray([t.medoid_video_id for t in label_templates], dtype=object),
        "label_sample_counts": np.asarray([len(t.source_indices) for t in label_templates], dtype=int),
        "player_names": np.asarray(labels, dtype=object),
        "player_mean_templates": np.asarray([t.mean_template for t in label_templates], dtype=float),
        "player_std_templates": np.asarray([t.std_template for t in label_templates], dtype=float),
        "player_count_templates": np.asarray([t.count_template for t in label_templates], dtype=int),
        "player_quality_metadata_json": json.dumps(_to_jsonable(_player_quality_metadata(label_templates)), ensure_ascii=False),
        "feature_weights": np.asarray(feature_weights, dtype=float),
        "metadata_json": json.dumps(_to_jsonable(metadata or {}), ensure_ascii=False),
    }
    np.savez_compressed(out_path, **payload)


def build_template_summary_rows(
    global_template: TemplateResult,
    label_templates: Sequence[TemplateResult],
) -> List[Dict[str, Any]]:
    # report/CSV에서 사람이 확인할 수 있는 template 요약 정보를 만듭니다.
    rows = []
    for template in [global_template] + list(label_templates):
        rows.append(
            {
                "template_type": template.template_type,
                "label": template.label,
                "sample_count": len(template.source_indices),
                "medoid_video_id": template.medoid_video_id,
                "mean_to_medoid_distance": template.mean_to_medoid_distance,
                "source_ids": "|".join(template.source_ids),
                "quality_weighted": template.quality_weighted,
                "mean_quality_score": float(np.mean(template.quality_scores)) if template.quality_scores else "",
                "mean_template_shape": str(tuple(template.mean_template.shape)),
            }
        )
    return rows


def save_template_summary(path: str | Path, rows: Sequence[Dict[str, Any]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def write_quality_report(
    path: str | Path,
    dataset: FeatureDataset,
    global_template: TemplateResult,
    label_templates: Sequence[TemplateResult],
    quality_summary: Dict[str, Any],
    feature_weights: Sequence[float],
    args_summary: Optional[Dict[str, Any]] = None,
) -> None:
    """결과를 읽을 수 있는 한국어 template 품질 보고서를 작성합니다."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    label_counts = {label: dataset.labels.count(label) for label in sorted(set(dataset.labels))}
    quality_weighting = bool(args_summary.get("quality_weighting", True)) if args_summary else True
    player_lines = []
    for template in label_templates:
        if template.quality_scores:
            player_lines.append(
                f"- {template.label}: medoid={template.medoid_video_id}, "
                f"videos={len(template.source_indices)}, "
                f"mean_quality={np.mean(template.quality_scores):.4f}"
            )
        else:
            player_lines.append(
                f"- {template.label}: medoid={template.medoid_video_id}, "
                f"videos={len(template.source_indices)}"
            )

    text = [
        "# DTW Reference Template Quality Report",
        "",
        "## 템플릿 성격",
        "- 이 모델은 player-balanced DTW-aligned reference template입니다.",
        "- 단일한 universal ideal swing이 아니라, 선별된 프로 선수 pose-only feature로 만든 기준 스윙 템플릿입니다.",
        "- 최종 DTW feature는 80 frame, 64 feature format만 사용합니다.",
        "",
        "## 데이터 선택",
        f"- 선택된 영상 수: {len(dataset.video_ids)}",
        f"- 선수/label별 영상 수: {json.dumps(label_counts, ensure_ascii=False)}",
        f"- metadata CSV 사용 여부: {dataset.metadata_loaded}",
        f"- view_group filter: {args_summary.get('view_group') if args_summary else None}",
        f"- use_template_only filter: {args_summary.get('use_template_only') if args_summary else None}",
        "",
        "## Player-level template",
        "- 먼저 선수/label별 player-level template을 만듭니다.",
        "- 각 선수 내부에서 DTW medoid를 선택합니다.",
        "- 모든 시퀀스를 medoid timeline에 DTW 정렬합니다.",
        "- 정렬된 frame bucket에서 arithmetic mean을 main template으로 사용합니다.",
        "- median은 기본값이 아닙니다.",
        f"- quality weighting은 player-level template 생성 내부에서만 적용됩니다: {'enabled' if quality_weighting else 'disabled'}.",
        *player_lines,
        "",
        "## Global template",
        "- Global template은 raw video 전체를 직접 평균내지 않습니다.",
        "- Player-level template들을 입력으로 사용합니다.",
        "- Player template 사이에서 global medoid를 선택합니다.",
        "- 각 player template을 global medoid timeline에 DTW 정렬한 뒤 평균냅니다.",
        "- 각 player template은 global reference에 동일한 weight로 기여합니다.",
        f"- Global medoid player/template: {global_template.medoid_video_id}",
        "",
        "## Evaluation",
        f"- eval mode: {quality_summary.get('eval_mode')}",
        f"- evaluation type: {quality_summary.get('evaluation_type')}",
        f"- note: {quality_summary.get('eval_note')}",
        f"- classification accuracy: {quality_summary.get('template_classification_accuracy')}",
        f"- mean own-template distance: {quality_summary.get('mean_own_template_distance')}",
        f"- mean other-template distance: {quality_summary.get('mean_other_template_distance')}",
        f"- own/other distance ratio: {quality_summary.get('own_other_distance_ratio')}",
        "",
        "## Builder details",
        f"- feature_key: {args_summary.get('feature_key') if args_summary else None}",
        f"- loaded_feature_key: {args_summary.get('loaded_feature_key') if args_summary else None}",
        f"- eval_mode: {args_summary.get('eval_mode') if args_summary else None}",
        f"- distance_csv policy: {args_summary.get('distance_matrix_policy') if args_summary else None}",
        f"- quality_weighting: {quality_weighting}",
        "",
        "## Feature weights",
        json.dumps({"feature_weights": list(map(float, feature_weights))}, ensure_ascii=False),
    ]
    if args_summary:
        text.extend(["", "## Builder arguments", json.dumps(args_summary, ensure_ascii=False, indent=2)])
    out_path.write_text("\n".join(text) + "\n", encoding="utf-8")
