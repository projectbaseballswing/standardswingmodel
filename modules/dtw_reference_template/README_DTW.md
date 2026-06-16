# DTW Reference Template Module

This folder contains the final-submission DTW reference template module.

It builds player-balanced DTW reference templates from saved pose-only feature
datasets and aligns individual feature files to a saved reference template.
The module uses generated feature artifacts only. It does not run video
processing, pose extraction, or template extraction from raw videos.

The LSTM model is handled by the teammate's module. That module consumes the
aligned feature files produced here.

## Final Feature Format

The final individual feature matrix is:

```text
(80, 64)
```

The final dataset shape is:

```text
(N, 80, 64)
```

Feature groups:

| Range | Meaning |
|---|---|
| 0:48 | landmark x, y, z, visibility |
| 48:57 | relative position features |
| 57:64 | angle / rotation features |

All public scripts validate this shape strictly. If input features, reference
templates, scaler vectors, feature names, or feature weights do not match the
64D final format, the scripts raise `ValueError`.

## Generated Artifacts

Individual `.npy` feature files are generated artifacts and are not committed.
Reference template outputs are generated into:

```text
reference_templates_900_loo_mincount8
```

Main template outputs:

```text
reference_templates.npz
template_scaler.json
template_summary.csv
template_quality_report.md
template_classification_eval.csv
template_comparison_summary.json
selected_reference_videos.csv
```

The default reference template key is:

```text
global_mean_template
```

## Create Or Validate The Final Dataset

Use `prepare_64d_feature_dataset.py` only when an existing dataset has three
extra trailing source-only columns that must be removed for the final format.
The script updates compatible metadata and `feature_names`, then validates the
result as `(N, 80, 64)`.

```powershell
python prepare_64d_feature_dataset.py `
  --input-npz "C:\path\to\pose_only_dtw_features_source.npz" `
  --output-npz "C:\path\to\pose_only_dtw_features_64d.npz" `
  --overwrite

python prepare_64d_feature_dataset.py `
  --input-npz "C:\path\to\pose_only_dtw_features_source.npz" `
  --validate-only
```

## Build Reference Templates

Final defaults:

```text
out dir: reference_templates_900_loo_mincount8
eval mode: loo
min label count: 8
sakoe_chiba_ratio: 0.15
```

Run from this folder:

```powershell
python dtw_reference_template_builder.py `
  --features-npz "C:\path\to\pose_only_dtw_features_64d.npz" `
  --per-video-csv "C:\path\to\per_video_summary.csv" `
  --out-dir "reference_templates_900_loo_mincount8" `
  --min-label-count 8 `
  --eval-mode loo `
  --sakoe-chiba-ratio 0.15
```

Optional filters:

| Option | Purpose |
|---|---|
| `--metadata-csv` | optional video selection metadata |
| `--view-group` | keep one metadata view group |
| `--use-template-only` | keep rows marked for template use |
| `--max-nan-ratio` | maximum allowed per-video NaN ratio |
| `--no-quality-weighting` | disable quality weighting inside player template construction |

## Compare One User Feature

```powershell
python compare_user_swing.py `
  --user-feature-npy "C:\path\to\user_feature.npy" `
  --reference-templates "reference_templates_900_loo_mincount8\reference_templates.npz" `
  --template-scaler "reference_templates_900_loo_mincount8\template_scaler.json" `
  --out-json "C:\path\to\comparison_result.json"
```

## Align Individual Features

`align_individual_features_to_template.py` aligns existing final-format `.npy`
files to the saved DTW template timeline. It loads the saved scaler, transforms
each input feature, aligns it to `global_mean_template`, saves aligned `.npy`
files, and writes a CSV summary.

```powershell
python align_individual_features_to_template.py `
  --input-dir "C:\path\to\individual_features_64d" `
  --reference-templates "reference_templates_900_loo_mincount8\reference_templates.npz" `
  --template-scaler "reference_templates_900_loo_mincount8\template_scaler.json" `
  --out-dir "C:\path\to\aligned_individual_features" `
  --summary-csv "C:\path\to\aligned_individual_features_summary.csv" `
  --sakoe-chiba-ratio 0.15
```

For one file:

```powershell
python align_individual_features_to_template.py `
  --input-npy "C:\path\to\one_feature.npy" `
  --reference-templates "reference_templates_900_loo_mincount8\reference_templates.npz" `
  --template-scaler "reference_templates_900_loo_mincount8\template_scaler.json" `
  --out-dir "C:\path\to\aligned_individual_features" `
  --summary-csv "C:\path\to\aligned_one_summary.csv"
```
