"""Align final individual feature files to a saved DTW reference template.

This script only reads existing ``.npy`` feature files and saved DTW template
artifacts. It does not process videos, run pose extraction, or build templates.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np

from modules.utils.dtw_utils import AlignmentPath, dtw_distance
from modules.utils.feature_scaling import (
    EXPECTED_SEQUENCE_SHAPE,
    load_scaler,
    transform_feature_sequence,
    validate_feature_sequence,
    validate_feature_vector,
)
from modules.utils.swing_comparator import load_reference_templates


def _collect_input_files(args: argparse.Namespace) -> List[Path]:
    if args.input_npy:
        paths = [Path(path) for path in args.input_npy]
    else:
        base_dir = Path(args.input_dir)
        pattern = "**/*.npy" if args.recursive else args.glob
        paths = sorted(base_dir.glob(pattern))
    paths = [path for path in paths if path.suffix.lower() == ".npy"]
    if not paths:
        raise ValueError("no .npy input files found")
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"input .npy files not found: {missing}")
    return paths


def _output_path(input_path: Path, out_dir: Path, input_dir: str | None) -> Path:
    if input_dir:
        try:
            relative = input_path.relative_to(Path(input_dir))
        except ValueError:
            relative = Path(input_path.name)
        return out_dir / relative.with_name(f"{relative.stem}_aligned.npy")
    return out_dir / f"{input_path.stem}_aligned.npy"


def _align_to_template_timeline(
    source_sequence: np.ndarray,
    template_sequence: np.ndarray,
    alignment_path: AlignmentPath,
) -> np.ndarray:
    buckets: List[List[np.ndarray]] = [[] for _ in range(template_sequence.shape[0])]
    for source_frame, template_frame in alignment_path:
        buckets[template_frame].append(source_sequence[source_frame])

    aligned = np.zeros_like(template_sequence, dtype=float)
    for frame_idx, bucket in enumerate(buckets):
        if not bucket:
            raise ValueError(f"DTW path did not cover template frame {frame_idx}")
        aligned[frame_idx] = np.mean(np.asarray(bucket, dtype=float), axis=0)
    return validate_feature_sequence(aligned, name="aligned feature")


def align_one_file(
    input_path: Path,
    output_path: Path,
    template_sequence: np.ndarray,
    scaler: Dict[str, Any],
    feature_weights: Sequence[float] | None,
    sakoe_chiba_ratio: float,
) -> Dict[str, Any]:
    feature = validate_feature_sequence(np.load(input_path, allow_pickle=True), name=f"input feature {input_path}")
    scaled_feature = transform_feature_sequence(feature, scaler)
    distance, path = dtw_distance(
        scaled_feature,
        template_sequence,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=sakoe_chiba_ratio,
    )
    aligned = _align_to_template_timeline(scaled_feature, template_sequence, path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, aligned)
    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "input_shape": str(tuple(feature.shape)),
        "output_shape": str(tuple(aligned.shape)),
        "distance_to_template": float(distance),
        "alignment_path_length": len(path),
    }


def write_summary(rows: Iterable[Dict[str, Any]], path: Path) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "input_path",
        "output_path",
        "input_shape",
        "output_shape",
        "distance_to_template",
        "alignment_path_length",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> List[Dict[str, Any]]:
    templates = load_reference_templates(args.reference_templates)
    if args.template_key not in templates:
        raise ValueError(f"template key {args.template_key!r} not found in {args.reference_templates}")
    template_sequence = validate_feature_sequence(templates[args.template_key], name=args.template_key)

    scaler = load_scaler(args.template_scaler)
    feature_weights = templates.get("feature_weights")
    if feature_weights is not None:
        feature_weights = validate_feature_vector(feature_weights, "feature_weights")

    input_paths = _collect_input_files(args)
    out_dir = Path(args.out_dir)
    rows = [
        align_one_file(
            input_path=input_path,
            output_path=_output_path(input_path, out_dir, args.input_dir),
            template_sequence=template_sequence,
            scaler=scaler,
            feature_weights=feature_weights,
            sakoe_chiba_ratio=args.sakoe_chiba_ratio,
        )
        for input_path in input_paths
    ]
    write_summary(rows, Path(args.summary_csv))

    print("[complete] aligned individual features")
    print(f"- template: {args.template_key}")
    print(f"- expected shape: {EXPECTED_SEQUENCE_SHAPE}")
    print(f"- input files: {len(rows)}")
    print(f"- output dir: {out_dir}")
    print(f"- summary csv: {args.summary_csv}")
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Align final 80x64 .npy feature files to a saved DTW template.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-npy", action="append", default=None)
    source.add_argument("--input-dir", default=None)
    parser.add_argument("--glob", default="*.npy")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument(
        "--reference-templates",
        default="reference_templates_900_loo_mincount8/reference_templates.npz",
    )
    parser.add_argument(
        "--template-scaler",
        default="reference_templates_900_loo_mincount8/template_scaler.json",
    )
    parser.add_argument("--template-key", default="global_mean_template")
    parser.add_argument("--out-dir", default="aligned_individual_features")
    parser.add_argument("--summary-csv", default="aligned_individual_features_summary.csv")
    parser.add_argument("--sakoe-chiba-ratio", type=float, default=0.15)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.sakoe_chiba_ratio < 0:
        raise ValueError("--sakoe-chiba-ratio must be >= 0")
    run(args)


if __name__ == "__main__":
    main()
