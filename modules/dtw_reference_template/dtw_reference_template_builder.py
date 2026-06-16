"""DTW 기반 기준 스윙 템플릿을 생성하는 CLI입니다.

입력은 이미 생성된 pose-only feature dataset입니다. 이 스크립트는
영상을 다시 읽거나 pose landmark를 추출하지 않고, `(N, 80, 64)` feature
sequence를 이용해 선수별 DTW template과 player-balanced global template을
생성합니다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np

from modules.utils.feature_scaling import save_scaler
from modules.utils.reference_template_builder import (
    EXPECTED_FEATURE_DIM,
    EXPECTED_SEQUENCE_LEN,
    FEATURE_GROUPS,
    build_global_template_from_player_templates,
    build_label_templates,
    build_template_summary_rows,
    create_default_feature_weights,
    filter_reference_dataset,
    fit_and_transform_references,
    load_feature_dataset,
    save_reference_templates,
    save_selected_reference_videos,
    save_template_summary,
    write_quality_report,
)
from modules.utils.template_quality_evaluator import (
    evaluate_reference_templates,
    save_template_quality_outputs,
)


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if np.isfinite(out) else None


# 전체 실행 흐름: 데이터 로드 → 필터링 → scaling → template 생성 → 평가/저장
def run(args: argparse.Namespace) -> None:
    # 1) 입력 feature와 summary CSV를 로드하고, template 생성 대상 영상을 선별합니다.
    """전체 template 생성 파이프라인을 실행합니다.

    흐름: feature dataset 로드 → reference 후보 필터링 → scaler fit → 선수별
    template 생성 → global player-balanced template 생성 → 평가 및 저장.
    """
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 이미 생성된 pose-only feature dataset을 읽습니다.
    dataset = load_feature_dataset(
        args.features_npz,
        args.per_video_csv,
        feature_key=args.feature_key,
        metadata_csv=args.metadata_csv,
    )
    metadata_loaded = bool(dataset.metadata_loaded)
    if args.use_template_only and not metadata_loaded:
        print("[warning] --use-template-only was passed but metadata CSV was not loaded. Ignoring it.")
    if args.view_group and not metadata_loaded:
        print("[warning] --view-group was passed but metadata CSV was not loaded. Ignoring it.")

    use_template_only = bool(metadata_loaded and args.use_template_only)
    view_group = args.view_group if metadata_loaded else None
    # 2) status, label count, nan_ratio, metadata 조건으로 reference 후보를 선별합니다.
    selected = filter_reference_dataset(
        dataset,
        min_label_count=args.min_label_count,
        max_nan_ratio=args.max_nan_ratio,
        use_template_only=use_template_only,
        view_group=view_group,
    )
    save_selected_reference_videos(out_dir / "selected_reference_videos.csv", selected)

    # 3) DTW local distance에서 사용할 feature group 가중치를 설정합니다.
    feature_weights = create_default_feature_weights(selected.features.shape[-1])
    scaler, scaled_features = fit_and_transform_references(selected, feature_weights=feature_weights)
    distance_matrix_policy = "not_provided_recomputed_from_selected_sequences"

    # 4) raw video 전체를 바로 평균내지 않고, 먼저 선수별 player template을 만듭니다.
    # 2) 선수별 player template을 먼저 생성합니다.
    player_templates = build_label_templates(
        scaled_features,
        selected.video_ids,
        selected.labels,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=args.sakoe_chiba_ratio,
        quality_scores=selected.quality_score,
        quality_weighting=args.quality_weighting,
    )
    # 5) global template은 선수별 template들을 동일 가중치로 평균내는 player-balanced 방식입니다.
    # 3) 선수별 template들을 동일 가중치로 묶어 global reference template을 만듭니다.
    global_template = build_global_template_from_player_templates(
        player_templates,
        feature_weights=feature_weights,
        sakoe_chiba_ratio=args.sakoe_chiba_ratio,
    )

    # 6) 생성된 template이 sequence를 얼마나 잘 대표하는지 평가합니다.
    # 4) 생성된 template의 품질을 in-sample 또는 LOO 방식으로 평가합니다.
    detail_df, quality_summary = evaluate_reference_templates(
        scaled_features,
        selected.video_ids,
        selected.labels,
        [template.label for template in player_templates],
        [template.mean_template for template in player_templates],
        feature_weights=feature_weights,
        sakoe_chiba_ratio=args.sakoe_chiba_ratio,
        eval_mode=args.eval_mode,
        quality_scores=selected.quality_score,
        quality_weighting=args.quality_weighting,
    )

    args_summary: Dict[str, Any] = {
        "features_npz": str(args.features_npz),
        "per_video_csv": str(args.per_video_csv),
        "metadata_csv": str(args.metadata_csv) if args.metadata_csv else None,
        "metadata_csv_loaded": metadata_loaded,
        "distance_matrix_policy": distance_matrix_policy,
        "feature_key": args.feature_key,
        "loaded_feature_key": selected.feature_key,
        "eval_mode": args.eval_mode,
        "out_dir": str(out_dir),
        "min_label_count": args.min_label_count,
        "max_nan_ratio": args.max_nan_ratio,
        "use_template_only": use_template_only,
        "view_group": view_group,
        "quality_weighting": args.quality_weighting,
        "sakoe_chiba_ratio": args.sakoe_chiba_ratio,
    }
    metadata = {
        "builder": "dtw_reference_template_builder",
        "template_space": "scaled_pose_only_features",
        "template_build_method": "player_balanced_dtw_aligned_arithmetic_mean",
        "global_template_source": "player_level_templates",
        "default_template": "global_mean_template",
        "raw_videos_averaged_directly_for_global": False,
        "quality_weighting_scope": "inside_player_template_construction_only" if args.quality_weighting else "disabled",
        "feature_shape": [EXPECTED_SEQUENCE_LEN, EXPECTED_FEATURE_DIM],
        "feature_groups": {name: [start, end] for name, (start, end) in FEATURE_GROUPS.items()},
        "feature_weight_config": {
            "landmark_xyz_visibility": 0.7,
            "visibility_columns": 0.2,
            "relative_positions": 1.0,
            "angle_rotation": 1.2,
        },
        "quality_summary": quality_summary,
        "player_template_quality_metadata": [
            {
                "label": template.label,
                "medoid_video_id": template.medoid_video_id,
                "source_video_ids": template.source_ids,
                "quality_scores": template.quality_scores,
                "quality_weighted": template.quality_weighted,
            }
            for template in player_templates
        ],
        "global_source_player_labels": global_template.source_ids,
        "args": args_summary,
    }

    save_reference_templates(
        out_dir / "reference_templates.npz",
        global_template=global_template,
        label_templates=player_templates,
        feature_weights=feature_weights,
        metadata=metadata,
    )
    save_template_summary(out_dir / "template_summary.csv", build_template_summary_rows(global_template, player_templates))
    scaler["feature_weight_config"] = metadata["feature_weight_config"]
    scaler["feature_weights"] = feature_weights
    scaler["feature_names"] = selected.feature_names
    save_scaler(scaler, out_dir / "template_scaler.json")
    save_template_quality_outputs(detail_df, quality_summary, out_dir)
    write_quality_report(
        out_dir / "template_quality_report.md",
        dataset=selected,
        global_template=global_template,
        label_templates=player_templates,
        quality_summary=quality_summary,
        feature_weights=feature_weights,
        args_summary=args_summary,
    )

    label_counts = {label: selected.labels.count(label) for label in sorted(set(selected.labels))}
    print("\n[완료] Player-balanced DTW reference template 생성")
    print(f"- selected videos: {len(selected.video_ids)}")
    print(f"- player/label counts: {json.dumps(label_counts, ensure_ascii=False)}")
    print(f"- eval mode: {args.eval_mode}")
    print(f"- global medoid player/template: {global_template.medoid_video_id}")
    print(f"- template classification accuracy: {quality_summary['template_classification_accuracy']:.4f}")
    ratio = _finite_float(quality_summary.get("own_other_distance_ratio"))
    print(f"- own/other distance ratio: {ratio:.6f}" if ratio is not None else "- own/other distance ratio: n/a")
    print(f"- output: {out_dir}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build player-balanced pose-only DTW reference templates.")
    parser.add_argument("--features-npz", required=True)
    parser.add_argument("--per-video-csv", required=True)
    parser.add_argument("--metadata-csv", default=None)
    parser.add_argument("--out-dir", default="reference_templates_900_loo_mincount8")
    parser.add_argument("--feature-key", default=None)
    parser.add_argument("--min-label-count", type=int, default=8)
    parser.add_argument("--max-nan-ratio", type=float, default=0.20)
    parser.add_argument("--view-group", default=None)
    parser.add_argument("--use-template-only", action="store_true")
    parser.set_defaults(quality_weighting=True)
    parser.add_argument("--quality-weighting", dest="quality_weighting", action="store_true")
    parser.add_argument("--no-quality-weighting", dest="quality_weighting", action="store_false")
    parser.add_argument("--eval-mode", choices=["insample", "loo"], default="loo")
    parser.add_argument("--sakoe-chiba-ratio", type=float, default=0.15)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.min_label_count < 1:
        raise ValueError("--min-label-count must be >= 1")
    if not (0.0 <= args.max_nan_ratio <= 1.0):
        raise ValueError("--max-nan-ratio must be between 0 and 1")
    if args.sakoe_chiba_ratio < 0:
        raise ValueError("--sakoe-chiba-ratio must be >= 0")
    run(args)


if __name__ == "__main__":
    main()
