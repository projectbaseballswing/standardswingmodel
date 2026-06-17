"""Build a self-contained DTW reference template from individual .npy files."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

try:
    import numpy as np

    from modules.utils.dtw_utils import EXPECTED_SEQUENCE_SHAPE
    from modules.utils.reference_template_builder import (
        FEATURE_GROUPS,
        build_global_template_from_label_templates,
        build_label_templates,
        collect_npy_feature_files,
        create_default_feature_names,
        create_default_feature_weights,
        fit_and_scale_records,
        load_npy_feature_records,
        save_reference_templates,
        select_records_for_template,
    )

    _RUNTIME_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    np = None
    EXPECTED_SEQUENCE_SHAPE = (80, 64)
    _RUNTIME_IMPORT_ERROR = exc


def _require_runtime_dependencies() -> None:
    if _RUNTIME_IMPORT_ERROR is not None:
        raise ModuleNotFoundError(
            f"DTW template building requires runtime dependency: {_RUNTIME_IMPORT_ERROR.name}"
        ) from _RUNTIME_IMPORT_ERROR


def _label_counts(labels: List[str]) -> Dict[str, int]:
    return dict(sorted(Counter(labels).items()))


def _metadata(args: argparse.Namespace, selection_rows: List[Dict[str, Any]], selected_labels: List[str]) -> Dict[str, Any]:
    return {
        "input_source": "individual .npy feature files",
        "feature_shape": list(EXPECTED_SEQUENCE_SHAPE),
        "template_role": "DTW timeline reference for aligning player features before LSTM",
        "template_build_method": "player-balanced DTW-aligned mean template",
        "template_space": "scaled",
        "min_label_count": int(args.min_label_count),
        "max_nan_ratio": float(args.max_nan_ratio),
        "sakoe_chiba_ratio": float(args.sakoe_chiba_ratio),
        "feature_groups": {name: [start, end] for name, (start, end) in FEATURE_GROUPS.items()},
        "feature_weight_config": {
            "landmark_xyz_visibility": 0.7,
            "visibility_columns": 0.2,
            "relative_positions": 1.0,
            "angles_deg": 1.2,
        },
        "selection": {
            "input_file_count": len(selection_rows),
            "selected_file_count": len(selected_labels),
            "selected_label_counts": _label_counts(selected_labels),
            "rows": selection_rows,
        },
    }


def _print_skips(selection_rows: List[Dict[str, Any]]) -> None:
    skipped = [row for row in selection_rows if not row["selected"]]
    for row in skipped[:20]:
        print(f"[skip] {row['path']} - {row['note']}")
    if len(skipped) > 20:
        print(f"[skip] ... {len(skipped) - 20} more skipped files are recorded in metadata_json")


def run(args: argparse.Namespace) -> Path:
    _require_runtime_dependencies()
    if args.min_label_count < 1:
        raise ValueError("--min-label-count must be >= 1")
    if not (0.0 <= args.max_nan_ratio <= 1.0):
        raise ValueError("--max-nan-ratio must be between 0 and 1")
    if args.sakoe_chiba_ratio < 0:
        raise ValueError("--sakoe-chiba-ratio must be >= 0")
    if args.max_files < 0:
        raise ValueError("--max-files must be >= 0")

    out_template = Path(args.out_template)
    if out_template.exists() and not args.overwrite:
        raise FileExistsError(f"output template already exists: {out_template}. Pass --overwrite to replace it.")

    paths = collect_npy_feature_files(args.feature_dir, recursive=args.recursive, max_files=args.max_files)
    records = load_npy_feature_records(paths)
    selected_records, selection_rows = select_records_for_template(
        records,
        min_label_count=args.min_label_count,
        max_nan_ratio=args.max_nan_ratio,
    )

    feature_names = create_default_feature_names()
    feature_weights = create_default_feature_weights()
    scaler, scaled_features = fit_and_scale_records(selected_records, feature_names, feature_weights)
    selected_video_ids = [record.video_id for record in selected_records]
    selected_labels = [record.label for record in selected_records]

    label_templates = build_label_templates(
        scaled_features,
        selected_video_ids,
        selected_labels,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=args.sakoe_chiba_ratio,
    )
    global_template = build_global_template_from_label_templates(
        label_templates,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=args.sakoe_chiba_ratio,
    )

    metadata = _metadata(args, selection_rows, selected_labels)
    save_reference_templates(
        out_template,
        global_template=global_template,
        label_templates=label_templates,
        feature_names=feature_names,
        feature_weights=feature_weights,
        scaler=scaler,
        selected_records=selected_records,
        metadata=metadata,
    )

    _print_skips(selection_rows)
    print("[complete] built DTW reference template")
    print(f"- input files: {len(records)}")
    print(f"- selected files: {len(selected_records)}")
    print(f"- selected labels: {json.dumps(_label_counts(selected_labels), ensure_ascii=False)}")
    print(f"- output template: {out_template}")
    return out_template


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build reference_templates.npz directly from individual 80x64 .npy feature files."
    )
    parser.add_argument("--feature-dir", required=True)
    parser.add_argument("--out-template", default=".\\reference_templates.npz")
    parser.add_argument("--min-label-count", type=int, default=8)
    parser.add_argument("--max-nan-ratio", type=float, default=0.15)
    parser.add_argument("--sakoe-chiba-ratio", type=float, default=0.15)
    parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    run(build_arg_parser().parse_args())


if __name__ == "__main__":
    main()
