"""Align individual 80x64 .npy feature files to a saved DTW template timeline."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Sequence

try:
    import numpy as np

    from modules.utils.dtw_utils import ALIGNED_SUFFIXES, align_sequence_to_template_timeline, dtw_distance
    from modules.utils.feature_scaling import (
        EXPECTED_SEQUENCE_SHAPE,
        transform_feature_sequence,
        validate_feature_sequence,
        validate_feature_vector,
        validate_scaler,
    )

    _RUNTIME_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    np = None
    EXPECTED_SEQUENCE_SHAPE = (80, 64)
    ALIGNED_SUFFIXES = ("_DTW_aligned.npy", "_DTW_aligned_scaled.npy")
    _RUNTIME_IMPORT_ERROR = exc


def _require_runtime_dependencies() -> None:
    if _RUNTIME_IMPORT_ERROR is not None:
        raise ModuleNotFoundError(
            f"DTW feature alignment requires runtime dependency: {_RUNTIME_IMPORT_ERROR.name}"
        ) from _RUNTIME_IMPORT_ERROR


def _scalar_string(value: Any) -> str:
    arr = np.asarray(value)
    return str(arr.item()) if arr.shape == () else str(value)


def _load_metadata(data: Any) -> Dict[str, Any]:
    if "metadata_json" not in data.files:
        return {}
    raw = _scalar_string(data["metadata_json"])
    return json.loads(raw) if raw else {}


def load_reference_template(path: str | Path, template_name: str) -> Dict[str, Any]:
    _require_runtime_dependencies()
    in_path = Path(path)
    if not in_path.exists():
        raise FileNotFoundError(f"reference template not found: {in_path}")
    data = np.load(in_path, allow_pickle=True)

    required = ["scaler_median", "scaler_mean", "scaler_std", "feature_weights", template_name]
    missing = [key for key in required if key not in data.files]
    if missing:
        raise ValueError(f"{in_path} is missing required arrays: {missing}")

    template = validate_feature_sequence(data[template_name], name=template_name)
    scaler = validate_scaler(
        {
            "median": data["scaler_median"],
            "mean": data["scaler_mean"],
            "std": data["scaler_std"],
        }
    )
    feature_weights = validate_feature_vector(data["feature_weights"], "feature_weights")
    metadata = _load_metadata(data)
    return {
        "template": template,
        "scaler": scaler,
        "feature_weights": feature_weights,
        "metadata": metadata,
    }


def collect_input_files(feature_dir: str | Path, recursive: bool, max_files: int) -> List[Path]:
    base_dir = Path(feature_dir)
    if not base_dir.exists():
        raise FileNotFoundError(f"feature dir not found: {base_dir}")
    if not base_dir.is_dir():
        raise NotADirectoryError(f"feature dir is not a directory: {base_dir}")
    if max_files < 0:
        raise ValueError("max_files must be >= 0")

    pattern = "**/*.npy" if recursive else "*.npy"
    paths = sorted(path for path in base_dir.glob(pattern) if path.is_file())
    paths = [path for path in paths if not path.name.endswith(ALIGNED_SUFFIXES)]
    if max_files > 0:
        paths = paths[:max_files]
    if not paths:
        raise ValueError(f"no input .npy files found in {base_dir}")
    return paths


def _relative_output_base(input_path: Path, feature_dir: Path, out_dir: Path) -> Path:
    try:
        relative = input_path.relative_to(feature_dir)
    except ValueError:
        relative = Path(input_path.name)
    return out_dir / relative.with_suffix("")


def output_paths(input_path: Path, feature_dir: Path, out_dir: Path, save_space: str) -> Dict[str, Path | None]:
    base = _relative_output_base(input_path, feature_dir, out_dir)
    raw_path = base.with_name(f"{base.name}_DTW_aligned.npy") if save_space in {"raw", "both"} else None
    scaled_path = (
        base.with_name(f"{base.name}_DTW_aligned_scaled.npy") if save_space in {"scaled", "both"} else None
    )
    return {"raw": raw_path, "scaled": scaled_path}


def _shape_string(value: Any) -> str:
    return str(tuple(value.shape)) if hasattr(value, "shape") else ""


def align_one_file(
    input_path: Path,
    feature_dir: Path,
    out_dir: Path,
    template_sequence: np.ndarray,
    scaler: Dict[str, Any],
    feature_weights: Sequence[float],
    sakoe_chiba_ratio: float,
    save_space: str,
) -> Dict[str, Any]:
    _require_runtime_dependencies()
    row: Dict[str, Any] = {
        "input_path": str(input_path),
        "video_id": input_path.stem,
        "status": "ok",
        "note": "",
        "input_shape": "",
        "nan_ratio": "",
        "distance_to_template": "",
        "alignment_path_length": "",
        "output_raw_path": "",
        "output_scaled_path": "",
    }

    try:
        feature = np.asarray(np.load(input_path, allow_pickle=False), dtype=float)
    except Exception as exc:
        row.update({"status": "skipped", "note": f"load error: {exc}"})
        return row

    row["input_shape"] = _shape_string(feature)
    if feature.shape != EXPECTED_SEQUENCE_SHAPE:
        row.update({"status": "skipped", "note": f"expected shape {EXPECTED_SEQUENCE_SHAPE}, got {feature.shape}"})
        return row

    raw_feature = validate_feature_sequence(feature, name=f"input feature {input_path}")
    row["nan_ratio"] = float(np.mean(~np.isfinite(raw_feature)))
    scaled_feature = transform_feature_sequence(raw_feature, scaler)
    distance, path = dtw_distance(
        scaled_feature,
        template_sequence,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=sakoe_chiba_ratio,
    )
    aligned_raw, _ = align_sequence_to_template_timeline(raw_feature, template_sequence.shape[0], path)
    aligned_scaled, _ = align_sequence_to_template_timeline(scaled_feature, template_sequence.shape[0], path)

    paths = output_paths(input_path, feature_dir, out_dir, save_space)
    if paths["raw"] is not None:
        paths["raw"].parent.mkdir(parents=True, exist_ok=True)
        np.save(paths["raw"], aligned_raw)
        row["output_raw_path"] = str(paths["raw"])
    if paths["scaled"] is not None:
        paths["scaled"].parent.mkdir(parents=True, exist_ok=True)
        np.save(paths["scaled"], aligned_scaled)
        row["output_scaled_path"] = str(paths["scaled"])

    row["distance_to_template"] = float(distance)
    row["alignment_path_length"] = len(path)
    return row


def write_summary(rows: Sequence[Dict[str, Any]], path: str | Path) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "input_path",
        "video_id",
        "status",
        "note",
        "input_shape",
        "nan_ratio",
        "distance_to_template",
        "alignment_path_length",
        "output_raw_path",
        "output_scaled_path",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_out_paths_json(rows: Sequence[Dict[str, Any]], path: str | Path) -> None:
    saved = []
    for row in rows:
        if row.get("status") != "ok":
            continue
        for key in ("output_raw_path", "output_scaled_path"):
            if row.get(key):
                saved.append({"input_path": row["input_path"], "output_path": row[key], "space": key.replace("output_", "").replace("_path", "")})
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)


def run(args: argparse.Namespace) -> List[Dict[str, Any]]:
    _require_runtime_dependencies()
    reference = load_reference_template(args.reference_template, args.template_name)
    metadata = reference["metadata"]
    sakoe_chiba_ratio = float(metadata.get("sakoe_chiba_ratio", 0.15) or 0.15)
    if not math.isfinite(sakoe_chiba_ratio) or sakoe_chiba_ratio < 0:
        sakoe_chiba_ratio = 0.15

    feature_dir = Path(args.feature_dir)
    out_dir = Path(args.out_dir)
    input_paths = collect_input_files(feature_dir, recursive=args.recursive, max_files=args.max_files)
    rows = [
        align_one_file(
            input_path=path,
            feature_dir=feature_dir,
            out_dir=out_dir,
            template_sequence=reference["template"],
            scaler=reference["scaler"],
            feature_weights=reference["feature_weights"],
            sakoe_chiba_ratio=sakoe_chiba_ratio,
            save_space=args.save_space,
        )
        for path in input_paths
    ]

    write_summary(rows, args.out_summary)
    if args.out_paths_json:
        write_out_paths_json(rows, args.out_paths_json)

    ok_count = sum(1 for row in rows if row["status"] == "ok")
    skipped_count = len(rows) - ok_count
    print("[complete] aligned individual features")
    print(f"- template: {args.template_name}")
    print(f"- input files: {len(rows)}")
    print(f"- aligned files: {ok_count}")
    print(f"- skipped files: {skipped_count}")
    print(f"- output dir: {out_dir}")
    print(f"- summary csv: {args.out_summary}")
    if ok_count == 0:
        raise ValueError("no valid input features were aligned")
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Align individual 80x64 .npy features to a saved DTW reference template timeline."
    )
    parser.add_argument("--feature-dir", required=True)
    parser.add_argument("--reference-template", default=".\\reference_templates.npz")
    parser.add_argument("--template-name", default="global_mean_template")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--out-summary", default="alignment_summary.csv")
    parser.add_argument("--save-space", choices=["raw", "scaled", "both"], default="raw")
    parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--out-paths-json", default=None)
    return parser


def main() -> None:
    run(build_arg_parser().parse_args())


if __name__ == "__main__":
    main()
