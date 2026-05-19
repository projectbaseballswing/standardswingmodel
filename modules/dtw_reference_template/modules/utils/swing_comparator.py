"""사용자 스윙 feature와 reference template을 비교하는 모듈입니다.

`reference_templates.npz`와 scaler를 불러온 뒤, 사용자 feature sequence를
global template 및 선수별 template과 DTW로 비교합니다. 결과는 similarity
score, phase별 error, feature group별 error로 정리됩니다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

from modules.utils.dtw_utils import AlignmentPath, dtw_distance
from modules.utils.feature_scaling import transform_feature_sequence
from modules.utils.reference_template_builder import FEATURE_GROUPS, PHASES


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def load_reference_templates(path: str | Path) -> Dict[str, Any]:
    """reference_templates.npz를 읽어 비교에 필요한 배열과 metadata를 반환합니다."""
    in_path = Path(path)
    if not in_path.exists():
        raise FileNotFoundError(f"reference template npz not found: {in_path}")
    data = np.load(in_path, allow_pickle=True)
    templates: Dict[str, Any] = {name: data[name] for name in data.files}
    templates["metadata"] = json.loads(str(templates["metadata_json"].item())) if "metadata_json" in templates else {}
    templates["label_names"] = [str(x) for x in templates.get("label_names", [])]
    return templates


def compute_similarity_score(distance: float, reference_mean: float, reference_std: float) -> float:
    """DTW distance를 0~100 범위의 similarity score로 변환합니다."""
    if not math.isfinite(float(distance)):
        return 0.0
    if not math.isfinite(float(reference_mean)) or reference_mean < 0:
        reference_mean = 0.0
    if not math.isfinite(float(reference_std)) or reference_std <= 1e-8:
        reference_std = max(reference_mean * 0.25, 1.0)
    excess = max(0.0, float(distance) - float(reference_mean))
    return float(max(0.0, min(100.0, 100.0 * math.exp(-excess / float(reference_std)))))


def _calibration(templates: Dict[str, Any]) -> Tuple[float, float]:
    metadata = templates.get("metadata", {})
    quality = metadata.get("quality_summary", {}) if isinstance(metadata, dict) else {}
    mean = float(quality.get("mean_own_template_distance", 0.0) or 0.0)
    std = float(quality.get("std_own_template_distance", max(mean * 0.25, 1.0)) or max(mean * 0.25, 1.0))
    return mean, std


def _rmse_for_pairs(
    user_sequence: np.ndarray,
    template_sequence: np.ndarray,
    alignment_path: AlignmentPath,
    start: int,
    end: int,
    use_template_frame_filter: bool,
) -> float:
    diffs = []
    for user_idx, template_idx in alignment_path:
        frame_idx = template_idx if use_template_frame_filter else user_idx
        if start <= frame_idx < end:
            diffs.append(user_sequence[user_idx] - template_sequence[template_idx])
    if not diffs:
        return float("nan")
    arr = np.asarray(diffs, dtype=float)
    return float(np.sqrt(np.mean(arr * arr)))


# feature group별 error를 계산합니다. 관절/상대위치/각도/속도 그룹별 차이를 확인할 때 사용합니다.
def compute_feature_group_error(
    user_sequence: np.ndarray,
    template_sequence: np.ndarray,
    alignment_path: AlignmentPath,
) -> Dict[str, float]:
    # DTW alignment path를 따라 feature group별 RMSE를 계산합니다.
    # address/loading/impact 등 phase별로 alignment error를 집계합니다.
    errors: Dict[str, float] = {}
    user = np.asarray(user_sequence, dtype=float)
    template = np.asarray(template_sequence, dtype=float)
    for group_name, (start, end) in FEATURE_GROUPS.items():
        diffs = [user[u, start:end] - template[t, start:end] for u, t in alignment_path]
        arr = np.asarray(diffs, dtype=float)
        errors[group_name] = float(np.sqrt(np.mean(arr * arr))) if arr.size else float("nan")
    return errors


# phase별 error를 계산합니다. DTW alignment path 기준으로 frame error를 phase 구간별로 묶습니다.
def compute_phase_error(
    user_sequence: np.ndarray,
    template_sequence: np.ndarray,
    alignment_path: AlignmentPath,
) -> Dict[str, float]:
    user = np.asarray(user_sequence, dtype=float)
    template = np.asarray(template_sequence, dtype=float)
    return {
        phase_name: _rmse_for_pairs(user, template, alignment_path, start, end, use_template_frame_filter=True)
        for phase_name, (start, end) in PHASES.items()
    }


def compare_user_to_global_template(
    user_sequence: np.ndarray,
    templates: Dict[str, Any],
    scaler: Dict[str, Any],
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
) -> Dict[str, Any]:
    # 사용자 feature도 reference template 생성 때 저장한 scaler로 동일하게 변환합니다.
    # 모든 player template과 비교해 가장 가까운 template을 찾습니다.
    user_scaled = transform_feature_sequence(user_sequence, scaler)
    template = np.asarray(templates["global_mean_template"], dtype=float)
    weights = feature_weights if feature_weights is not None else templates.get("feature_weights")
    distance, path = dtw_distance(user_scaled, template, feature_weights=weights, sakoe_chiba_ratio=sakoe_chiba_ratio)
    ref_mean, ref_std = _calibration(templates)
    return {
        "template": "GLOBAL",
        "distance": distance,
        "similarity_score": compute_similarity_score(distance, ref_mean, ref_std),
        "alignment_path": path,
        "feature_group_error": compute_feature_group_error(user_scaled, template, path),
        "phase_error": compute_phase_error(user_scaled, template, path),
    }


def compare_user_to_label_templates(
    user_sequence: np.ndarray,
    templates: Dict[str, Any],
    scaler: Dict[str, Any],
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
) -> Dict[str, Any]:
    user_scaled = transform_feature_sequence(user_sequence, scaler)
    weights = feature_weights if feature_weights is not None else templates.get("feature_weights")
    label_names = templates["label_names"]
    label_templates = np.asarray(templates["label_mean_templates"], dtype=float)
    ref_mean, ref_std = _calibration(templates)

    results = []
    for label, template in zip(label_names, label_templates):
        distance, path = dtw_distance(user_scaled, template, feature_weights=weights, sakoe_chiba_ratio=sakoe_chiba_ratio)
        results.append(
            {
                "label": label,
                "distance": distance,
                "similarity_score": compute_similarity_score(distance, ref_mean, ref_std),
                "alignment_path": path,
                "feature_group_error": compute_feature_group_error(user_scaled, template, path),
                "phase_error": compute_phase_error(user_scaled, template, path),
            }
        )
    best = min(results, key=lambda item: item["distance"]) if results else None
    return {"best_matching_template": best, "label_template_distances": results}


def _comparison_confidence(best: Optional[Dict[str, Any]], label_results: Sequence[Dict[str, Any]]) -> float:
    if best is None or len(label_results) < 2:
        return 0.5 if best is not None else 0.0
    distances = sorted(float(item["distance"]) for item in label_results if np.isfinite(item["distance"]))
    if len(distances) < 2 or distances[1] <= 1e-8:
        return 0.5
    margin = max(0.0, distances[1] - distances[0]) / distances[1]
    return float(max(0.0, min(1.0, margin)))


def compare_user_to_templates(
    user_sequence: np.ndarray,
    templates: Dict[str, Any],
    scaler: Dict[str, Any],
    feature_weights: Optional[Sequence[float]] = None,
    sakoe_chiba_ratio: float = 0.15,
) -> Dict[str, Any]:
    warnings = []
    sequence = np.asarray(user_sequence, dtype=float)
    if sequence.shape != (80, 67):
        warnings.append(f"expected user feature shape (80, 67), got {sequence.shape}")

    global_result = compare_user_to_global_template(sequence, templates, scaler, feature_weights, sakoe_chiba_ratio)
    label_results = compare_user_to_label_templates(sequence, templates, scaler, feature_weights, sakoe_chiba_ratio)
    best = label_results.get("best_matching_template")

    if best is not None:
        distance_to_best = float(best["distance"])
        similarity_score = float(best["similarity_score"])
        feature_group_error = best.get("feature_group_error", {})
        phase_error = best.get("phase_error", {})
    else:
        warnings.append("no label templates were available; using global result only")
        distance_to_best = float("nan")
        similarity_score = float(global_result["similarity_score"])
        feature_group_error = global_result.get("feature_group_error", {})
        phase_error = global_result.get("phase_error", {})

    return _json_safe(
        {
            "global_result": global_result,
            "label_results": label_results,
            "best_label_template": best,
            "distance_to_global": float(global_result["distance"]),
            "distance_to_best_label": distance_to_best,
            "similarity_score_0_100": similarity_score,
            "feature_group_error": feature_group_error,
            "phase_error": phase_error,
            "comparison_confidence": _comparison_confidence(best, label_results.get("label_template_distances", [])),
            "warnings": warnings,
        }
    )
