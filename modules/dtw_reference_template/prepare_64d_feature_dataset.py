"""Prepare a final 64D DTW feature dataset from a legacy NPZ artifact.

This utility only edits saved feature arrays and metadata. It does not process
videos, run pose extraction, or build DTW templates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import numpy as np

from modules.utils.feature_scaling import (
    EXPECTED_FEATURE_DIM,
    EXPECTED_SEQUENCE_LEN,
    validate_feature_dataset,
    validate_feature_names,
)
from modules.utils.reference_template_builder import FEATURE_GROUPS


TRAILING_SOURCE_ONLY_DIM = 3
SOURCE_FEATURE_DIM = EXPECTED_FEATURE_DIM + TRAILING_SOURCE_ONLY_DIM
FEATURE_KEYS = ("raw_features", "features", "scaled_features", "sequences", "X")


def _select_feature_key(data: np.lib.npyio.NpzFile, feature_key: str | None) -> str:
    if feature_key:
        if feature_key not in data.files:
            raise ValueError(f"feature key {feature_key!r} not found. Available keys: {list(data.files)}")
        return feature_key
    for key in FEATURE_KEYS:
        if key in data.files:
            return key
    raise ValueError(f"npz does not contain a supported feature array key. Available keys: {list(data.files)}")


def _is_source_feature_dataset(arr: np.ndarray) -> bool:
    return arr.ndim == 3 and arr.shape[1:] == (EXPECTED_SEQUENCE_LEN, SOURCE_FEATURE_DIM)


def _convert_feature_array(arr: np.ndarray, key: str) -> np.ndarray:
    if not _is_source_feature_dataset(arr):
        raise ValueError(
            f"{key} must have legacy source dataset shape (N, {EXPECTED_SEQUENCE_LEN}, {SOURCE_FEATURE_DIM}), "
            f"got {arr.shape}"
        )
    converted = np.asarray(arr[:, :, :EXPECTED_FEATURE_DIM], dtype=float)
    return validate_feature_dataset(converted, name=key)


def _convert_feature_names(values: np.ndarray) -> np.ndarray:
    names = [str(x) for x in values.tolist()]
    if len(names) == SOURCE_FEATURE_DIM:
        names = names[:EXPECTED_FEATURE_DIM]
    validate_feature_names(names)
    return np.asarray(names, dtype=object)


def _replace_shape_value(value: Any, n_sequences: int | None) -> Any:
    if isinstance(value, list):
        if len(value) == 3 and value[1:] == [EXPECTED_SEQUENCE_LEN, SOURCE_FEATURE_DIM]:
            first = int(value[0]) if n_sequences is None else int(n_sequences)
            return [first, EXPECTED_SEQUENCE_LEN, EXPECTED_FEATURE_DIM]
        if len(value) == 2 and value == [EXPECTED_SEQUENCE_LEN, SOURCE_FEATURE_DIM]:
            return [EXPECTED_SEQUENCE_LEN, EXPECTED_FEATURE_DIM]
        return [_replace_shape_value(item, n_sequences) for item in value]
    if isinstance(value, dict):
        return _update_metadata(value, n_sequences)
    return value


def _update_metadata(metadata: Dict[str, Any], n_sequences: int | None) -> Dict[str, Any]:
    updated = {str(key): _replace_shape_value(value, n_sequences) for key, value in metadata.items()}
    for key in ("n_features", "feature_dim", "num_features"):
        if key not in updated:
            continue
        try:
            value = int(updated[key])
        except (TypeError, ValueError):
            continue
        if value == SOURCE_FEATURE_DIM:
            updated[key] = EXPECTED_FEATURE_DIM
    updated["feature_shape"] = [EXPECTED_SEQUENCE_LEN, EXPECTED_FEATURE_DIM]
    updated["feature_groups"] = {name: [start, end] for name, (start, end) in FEATURE_GROUPS.items()}
    updated["final_feature_format"] = {
        "sequence_shape": [EXPECTED_SEQUENCE_LEN, EXPECTED_FEATURE_DIM],
        "dropped_trailing_columns": TRAILING_SOURCE_ONLY_DIM,
    }
    return updated


def _convert_metadata_json(values: np.ndarray, n_sequences: int | None) -> np.ndarray:
    raw = str(values.item()) if values.shape == () else str(values.tolist())
    metadata = json.loads(raw)
    return np.asarray(json.dumps(_update_metadata(metadata, n_sequences), ensure_ascii=False))


def _convert_payload(data: np.lib.npyio.NpzFile, selected_key: str) -> Tuple[Dict[str, Any], int]:
    selected = np.asarray(data[selected_key])
    if not _is_source_feature_dataset(selected):
        raise ValueError(
            f"selected feature array {selected_key!r} must have legacy source dataset shape "
            f"(N, {EXPECTED_SEQUENCE_LEN}, {SOURCE_FEATURE_DIM}), got {selected.shape}"
        )
    n_sequences = int(selected.shape[0])

    payload: Dict[str, Any] = {}
    converted_feature_keys = []
    for key in data.files:
        arr = data[key]
        if isinstance(arr, np.ndarray) and _is_source_feature_dataset(arr):
            payload[key] = _convert_feature_array(arr, key)
            converted_feature_keys.append(key)
        elif key == "feature_names":
            payload[key] = _convert_feature_names(arr)
        elif key == "metadata_json":
            payload[key] = _convert_metadata_json(arr, n_sequences)
        else:
            payload[key] = arr

    if selected_key not in converted_feature_keys:
        raise ValueError(f"selected feature array {selected_key!r} was not converted")
    validate_feature_dataset(payload[selected_key], name=selected_key)
    return payload, n_sequences


def _write_npz(payload: Dict[str, Any], path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {path}. Pass --overwrite to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **payload)


def run(args: argparse.Namespace) -> None:
    input_path = Path(args.input_npz)
    if not input_path.exists():
        raise FileNotFoundError(f"input npz not found: {input_path}")

    data = np.load(input_path, allow_pickle=True)
    selected_key = _select_feature_key(data, args.feature_key)
    payload, n_sequences = _convert_payload(data, selected_key)

    if args.validate_only:
        print("[complete] dataset conversion validated")
    else:
        if not args.output_npz:
            raise ValueError("--output-npz is required unless --validate-only is passed")
        _write_npz(payload, Path(args.output_npz), overwrite=args.overwrite)
        print("[complete] final 64D dataset saved")
        print(f"- output: {args.output_npz}")
    print(f"- selected feature key: {selected_key}")
    print(f"- sequences: {n_sequences}")
    print(f"- final shape: {tuple(payload[selected_key].shape)}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or validate a final 64D DTW feature dataset NPZ.")
    parser.add_argument("--input-npz", required=True)
    parser.add_argument("--output-npz", default=None)
    parser.add_argument("--feature-key", default=None)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    run(build_arg_parser().parse_args())


if __name__ == "__main__":
    main()
