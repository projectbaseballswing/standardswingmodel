"""생성된 DTW reference template의 품질을 평가하는 모듈입니다.

각 sequence가 자기 label template에 얼마나 가까운지, 다른 label template과는
얼마나 떨어져 있는지를 계산합니다. in-sample 평가와 leave-one-out 평가를
지원합니다.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from modules.utils.dtw_utils import dtw_distance
from modules.utils.feature_scaling import validate_feature_dataset, validate_feature_sequence, validate_feature_vector
from modules.utils.reference_template_builder import build_dtw_aligned_mean_template, choose_medoid


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
    return value


def evaluate_reference_templates(
    sequences: Sequence[np.ndarray],
    video_ids: Sequence[str],
    labels: Sequence[str],
    label_names: Sequence[str],
    label_templates: Sequence[np.ndarray],
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
    eval_mode: str = "insample",
    quality_scores: Optional[Sequence[float]] = None,
    quality_weighting: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """생성된 player template들을 이용해 nearest-template 평가를 수행합니다.

    `insample`은 template 생성에 사용된 sequence를 그대로 평가합니다. `loo`는 query
    sequence를 자기 label template에서 제외하고 다시 평가하므로 더 엄격하지만 시간이
    오래 걸릴 수 있습니다.
    """

    if len(sequences) != len(video_ids) or len(sequences) != len(labels):
        raise ValueError("sequences, video_ids, and labels must have the same length")
    if len(label_names) != len(label_templates):
        raise ValueError("label_names and label_templates must have the same length")
    if eval_mode not in {"insample", "loo"}:
        raise ValueError("eval_mode must be 'insample' or 'loo'")
    if quality_scores is not None and len(quality_scores) != len(sequences):
        raise ValueError("quality_scores must have the same length as sequences")
    sequences = validate_feature_dataset(sequences, name="evaluation sequences")
    if feature_weights is not None:
        validate_feature_vector(feature_weights, "feature_weights")

    label_template_map = {
        str(label_name): validate_feature_sequence(template, name=f"label template {label_name}")
        for label_name, template in zip(label_names, label_templates)
    }
    labels_as_str = [str(label) for label in labels]
    rows: List[Dict[str, Any]] = []
    own_distances: List[float] = []
    other_distances: List[float] = []

    def loo_own_template(query_index: int, label_name: str) -> Optional[np.ndarray]:
        indices = [idx for idx, value in enumerate(labels_as_str) if value == label_name and idx != query_index]
        if not indices:
            return None
        source_sequences = [sequences[idx] for idx in indices]
        source_video_ids = [video_ids[idx] for idx in indices]
        source_quality = (
            [float(quality_scores[idx]) for idx in indices]
            if quality_scores is not None and quality_weighting
            else None
        )
        medoid_index, _, _ = choose_medoid(
            source_sequences,
            source_video_ids,
            feature_weights=feature_weights,
            sakoe_chiba_ratio=sakoe_chiba_ratio,
        )
        mean_template, _, _, _ = build_dtw_aligned_mean_template(
            source_sequences,
            np.asarray(source_sequences[medoid_index], dtype=float),
            feature_weights=feature_weights,
            sakoe_chiba_ratio=sakoe_chiba_ratio,
            sample_weights=source_quality,
        )
        return mean_template

    if eval_mode == "loo" and len(sequences) > 50:
        print("[warning] LOO evaluation may be slow because it rebuilds one own-label template per sequence.")

    for query_index, (sequence, video_id, true_label) in enumerate(zip(sequences, video_ids, labels)):
        distances: Dict[str, float] = {}
        skipped_own = False
        for label_name in label_names:
            label_name = str(label_name)
            template = label_template_map[label_name]
            if eval_mode == "loo" and label_name == str(true_label):
                own_template = loo_own_template(query_index, label_name)
                if own_template is None:
                    distances[label_name] = float("nan")
                    skipped_own = True
                    continue
                template = own_template
            distance, _ = dtw_distance(
                sequence,
                template,
                feature_weights=feature_weights,
                sakoe_chiba_ratio=sakoe_chiba_ratio,
            )
            distances[label_name] = distance

        finite = {label: value for label, value in distances.items() if np.isfinite(value)}
        predicted_label = min(finite, key=finite.get) if finite else ""
        own_distance = distances.get(str(true_label), float("nan"))
        other_values = [value for label, value in distances.items() if label != str(true_label) and np.isfinite(value)]
        mean_other = float(np.mean(other_values)) if other_values else float("nan")
        own_distances.append(own_distance)
        other_distances.extend(other_values)

        row = {
            "video_id": video_id,
            "true_label": true_label,
            "predicted_label": predicted_label,
            "is_correct": predicted_label == true_label,
            "own_template_distance": own_distance,
            "mean_other_template_distance": mean_other,
            "own_other_distance_ratio": own_distance / mean_other if mean_other and np.isfinite(mean_other) else float("nan"),
            "eval_mode": eval_mode,
            "evaluation_type": "leave_one_out" if eval_mode == "loo" else "in_sample",
            "loo_own_template_skipped": skipped_own,
        }
        for label_name, distance in distances.items():
            row[f"distance_to_{label_name}"] = distance
        rows.append(row)

    detail_df = pd.DataFrame(rows)
    accuracy = float(detail_df["is_correct"].mean()) if len(detail_df) else float("nan")
    label_accuracy = detail_df.groupby("true_label")["is_correct"].mean().to_dict() if len(detail_df) else {}
    mean_own = float(np.nanmean(own_distances)) if own_distances else float("nan")
    std_own = float(np.nanstd(own_distances)) if own_distances else float("nan")
    mean_other = float(np.nanmean(other_distances)) if other_distances else float("nan")

    summary = {
        "template_classification_accuracy": accuracy,
        "label_wise_accuracy": {str(k): float(v) for k, v in label_accuracy.items()},
        "mean_own_template_distance": mean_own,
        "std_own_template_distance": std_own,
        "mean_other_template_distance": mean_other,
        "own_other_distance_ratio": mean_own / mean_other if mean_other and np.isfinite(mean_other) else float("nan"),
        "n_sequences": int(len(sequences)),
        "n_label_templates": int(len(label_names)),
        "eval_mode": eval_mode,
        "evaluation_type": "leave_one_out" if eval_mode == "loo" else "in_sample",
        "quality_weighting_used_for_loo_player_templates": bool(eval_mode == "loo" and quality_scores is not None and quality_weighting),
        "eval_note": (
            "Leave-one-out: query sequence is excluded from its own-label template."
            if eval_mode == "loo"
            else "In-sample: each sequence is evaluated against templates built from the full selected reference set."
        ),
    }
    return detail_df, summary


def save_template_quality_outputs(detail_df: pd.DataFrame, summary: Dict[str, Any], out_dir: str | Path) -> None:
    """template 평가 상세 결과와 summary JSON을 저장합니다."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    detail_df.to_csv(
        out_path / "template_classification_eval.csv",
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
    )
    with (out_path / "template_comparison_summary.json").open("w", encoding="utf-8") as f:
        json.dump(_to_jsonable(summary), f, ensure_ascii=False, indent=2)
