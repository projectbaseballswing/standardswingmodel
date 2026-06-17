# DTW Reference Template Module

이 폴더는 이미 생성된 개별 `.npy` 스윙 feature 파일에서 시작합니다. 영상을 읽지 않고, YOLO/MediaPipe/OpenCV 비디오 처리를 실행하지 않습니다.

입력 feature의 shape은 반드시 `(80, 64)`입니다. shape이 다르면 템플릿 생성 또는 정렬 대상에서 제외됩니다.

## 역할

`build_template_from_npy_features.py`는 개별 `.npy` feature 파일을 모아 `reference_templates.npz`를 생성합니다.

`reference_templates.npz`는 self-contained artifact입니다. 내부에는 global template, 선수별 template, scaler median/mean/std, feature weights, feature names, metadata가 함께 저장됩니다.

`align_individual_features_to_template.py`는 개별 `.npy` feature를 저장된 DTW reference template timeline에 정렬합니다.

정렬된 feature는 팀원의 LSTM 모듈 입력으로 전달됩니다.

## GitHub artifact 기준

최종 template artifact로는 `reference_templates.npz`만 커밋합니다.

원본 개별 `.npy` feature 파일과 DTW 정렬 결과 `.npy` 파일은 생성 산출물이므로 커밋하지 않습니다.

`__pycache__/`와 `*.pyc` 파일도 커밋하지 않습니다.

## 주요 파일

```text
README_DTW.md
build_template_from_npy_features.py
align_individual_features_to_template.py
modules/utils/dtw_utils.py
modules/utils/feature_scaling.py
modules/utils/reference_template_builder.py
```

## Template 생성

```powershell
python build_template_from_npy_features.py `
  --feature-dir "C:\Users\DO\project\dorami\reference_swing\feature" `
  --out-template ".\reference_templates.npz" `
  --min-label-count 8 `
  --sakoe-chiba-ratio 0.15 `
  --overwrite
```

생성되는 기본 artifact:

```text
reference_templates.npz
```

## 개별 feature 정렬

```powershell
python align_individual_features_to_template.py `
  --feature-dir "C:\Users\DO\project\dorami\reference_swing\feature" `
  --reference-template ".\reference_templates.npz" `
  --template-name global_mean_template `
  --out-dir ".\aligned_individual_features_900_loo_mincount8" `
  --out-summary ".\aligned_individual_features_900_loo_mincount8\alignment_summary.csv" `
  --save-space raw
```

기본 raw 출력 파일명은 다음 형식입니다.

```text
*_DTW_aligned.npy
```

`--save-space scaled` 또는 `--save-space both`를 사용하면 scaled 정렬 결과도 저장할 수 있습니다.

```text
*_DTW_aligned_scaled.npy
```
