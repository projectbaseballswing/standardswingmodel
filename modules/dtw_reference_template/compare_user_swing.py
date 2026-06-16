"""사용자 스윙 feature를 reference template과 비교하는 CLI입니다.

이 파일은 영상을 직접 처리하지 않습니다. 팀 feature pipeline 또는 별도
전처리 코드가 만든 `(80, 64)` feature sequence를 입력으로 받아,
`reference_templates.npz`와 `template_scaler.json`을 이용해 비교 결과를
JSON으로 저장합니다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from modules.utils.feature_scaling import EXPECTED_SEQUENCE_SHAPE, load_scaler, validate_feature_sequence
from modules.utils.swing_comparator import compare_user_to_templates, load_reference_templates


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
        return float(value)
    return value


def _load_feature_from_npz(path: str | Path, feature_key: Optional[str] = None) -> np.ndarray:
    """NPZ 파일에서 사용자 feature sequence 하나를 읽습니다.

    NPZ 안에 여러 sequence가 들어 있으면 어떤 사용자 입력인지 알 수 없으므로
    batch 크기가 1인 경우만 허용합니다.
    """
    data = np.load(path, allow_pickle=True)
    if feature_key:
        if feature_key not in data.files:
            raise ValueError(f"feature key {feature_key!r} not found. Available keys: {list(data.files)}")
        arr = data[feature_key]
    else:
        arr = None
        for key in ("user_feature", "features", "raw_features", "scaled_features", "sequences", "X"):
            if key in data.files:
                arr = data[key]
                break
        if arr is None:
            raise ValueError(f"no supported feature key found. Available keys: {list(data.files)}")
    arr = np.asarray(arr, dtype=float)
    if arr.ndim == 3:
        if arr.shape[0] != 1:
            raise ValueError(f"user feature npz contains {arr.shape[0]} sequences; provide one sequence")
        arr = arr[0]
    return arr


def load_user_feature(args: argparse.Namespace) -> np.ndarray:
    """CLI 인자에서 사용자 feature 입력을 읽어 `(80, 64)` 배열로 반환합니다."""
    if args.user_feature_npy:
        feature = np.asarray(np.load(args.user_feature_npy, allow_pickle=True), dtype=float)
        return validate_feature_sequence(feature, name="user feature")
    if args.user_feature_npz:
        feature = _load_feature_from_npz(args.user_feature_npz, feature_key=args.feature_key)
        return validate_feature_sequence(feature, name="user feature")
    raise ValueError("provide --user-feature-npy or --user-feature-npz")


def run(args: argparse.Namespace) -> Dict[str, Any]:
    # 사용자 feature를 불러온 뒤, 저장된 reference template/scaler와 비교합니다.
    """reference template과 사용자 feature를 비교하고 결과 JSON을 저장합니다."""
    user_feature = load_user_feature(args)
    templates = load_reference_templates(args.reference_templates)
    scaler = load_scaler(args.template_scaler)
    feature_weights = templates.get("feature_weights")
    result = compare_user_to_templates(
        user_feature,
        templates,
        scaler,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=args.sakoe_chiba_ratio,
    )

    summary = {
        "best_template": result["best_label_template"]["label"] if result.get("best_label_template") else None,
        "global_distance": result.get("distance_to_global"),
        "best_label_distance": result.get("distance_to_best_label"),
        "similarity_score_0_100": result.get("similarity_score_0_100"),
        "comparison_confidence": result.get("comparison_confidence"),
        "phase_error": result.get("phase_error"),
        "feature_group_error": result.get("feature_group_error"),
        "warnings": result.get("warnings", []),
        "full_result": result,
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(_json_safe(summary), f, ensure_ascii=False, indent=2)

    print("[완료] User swing comparison")
    print(f"- best template: {summary['best_template']}")
    print(f"- global distance: {summary['global_distance']}")
    print(f"- best label distance: {summary['best_label_distance']}")
    print(f"- similarity score: {summary['similarity_score_0_100']}")
    print(f"- output: {out_path}")
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Compare one user pose-only feature sequence with shape {EXPECTED_SEQUENCE_SHAPE} to reference templates."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--user-feature-npy", default=None)
    source.add_argument("--user-feature-npz", default=None)
    parser.add_argument("--reference-templates", required=True)
    parser.add_argument("--template-scaler", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--feature-key", default=None)
    parser.add_argument("--sakoe-chiba-ratio", type=float, default=0.15)
    return parser


# 사용자 feature와 저장된 reference template을 비교하는 CLI 진입점
def main() -> None:
    run(build_arg_parser().parse_args())


if __name__ == "__main__":
    main()
