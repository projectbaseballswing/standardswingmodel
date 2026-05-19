# DTW 기준 스윙 템플릿 모듈 안내

이 폴더는 **pose-only feature sequence**를 입력으로 받아 DTW 기반 기준 스윙 템플릿을 만들고, 사용자 스윙 feature와 비교하기 위한 코드 묶음입니다.

현재 이 모듈은 영상에서 pose landmark를 직접 추출하지 않습니다. 영상 처리, pose 추출, feature 생성은 팀 파이프라인에서 담당하고, DTW 모듈은 이미 만들어진 feature 파일을 입력으로 사용합니다.

---

## 1. 입력 데이터 형식

DTW 모듈의 기본 입력은 아래 두 파일입니다.

```text
pose_only_dtw_features.npz
per_video_summary.csv
```

`pose_only_dtw_features.npz`에는 영상별 pose-only feature sequence가 들어 있어야 합니다.

```text
features 또는 raw_features: shape (N, 80, 67)
video_ids: 영상 ID 목록
labels: 선수 label 목록
feature_names: feature 이름 목록
```

feature shape `(N, 80, 67)`의 의미는 다음과 같습니다.

```text
N개 영상
각 영상은 80 frame
각 frame은 67개 feature
```

현재 feature 구성은 아래와 같습니다.

| 구간 | 의미 |
|---|---|
| 0:48 | 12개 핵심 관절의 x, y, z, visibility |
| 48:57 | 손목/발목/어깨 중심의 상대 위치 |
| 57:64 | 팔꿈치, 무릎, 몸통, 골반/어깨 회전 각도 |
| 64:67 | pose 기반 velocity feature |

현재 YOLO/bat feature는 제외되어 있으며, pose-only feature만 사용합니다.

---

## 2. 이 폴더에서 담당하는 일

이 폴더의 핵심 역할은 두 가지입니다.

```text
1. 여러 프로 선수 feature sequence로 기준 스윙 템플릿 생성
2. 사용자 feature sequence를 기준 템플릿과 DTW로 비교
```

즉, 전체 흐름은 다음과 같습니다.

```text
팀 feature pipeline
→ pose_only_dtw_features.npz
→ DTW reference template builder
→ reference_templates.npz
→ user swing comparator
→ comparison result
```

---

## 3. 핵심 코드 파일

### `modules/utils/dtw_utils.py`

DTW 계산 유틸입니다.

- frame 간 weighted distance 계산
- multivariate DTW distance 계산
- Sakoe-Chiba band 지원
- alignment path 반환
- pairwise DTW matrix 계산

---

### `modules/utils/feature_scaling.py`

DTW 비교 전에 feature scale을 맞추는 모듈입니다.

- NaN/Inf 값을 feature별 median으로 보정
- mean/std standardization 적용
- scaler를 JSON으로 저장/로드

주의할 점은 scaler를 사용자 데이터까지 포함해 fit하지 않는다는 점입니다. 기준 템플릿 생성에 사용한 reference set으로 fit한 scaler를 사용자 feature에도 동일하게 적용합니다.

---

### `modules/utils/reference_template_builder.py`

기준 스윙 템플릿을 만드는 핵심 모듈입니다.

현재 방식은 **player-balanced DTW-aligned reference template**입니다.

```text
1. 선수별 feature sequence 수집
2. 선수 내부에서 DTW medoid 선택
3. medoid timeline에 각 sequence를 DTW 정렬
4. 정렬된 frame bucket에서 arithmetic mean 계산
5. 선수별 player template 생성
6. player template들을 다시 DTW 정렬
7. player template을 동일 가중치로 평균
8. global reference template 생성
```

중요한 점은 global template을 raw video 전체 평균으로 만들지 않는다는 것입니다. 먼저 선수별 template을 만들고, 그 선수별 template들을 평균냅니다. 이렇게 하면 영상 수가 많은 선수가 global template을 과도하게 지배하는 문제를 줄일 수 있습니다.

---

### `modules/utils/template_quality_evaluator.py`

생성된 template의 품질을 평가하는 모듈입니다.

평가 항목은 다음과 같습니다.

- in-sample 평가
- leave-one-out 평가
- 자기 label template과의 거리
- 다른 label template과의 거리
- template classification accuracy
- own/other distance ratio

---

### `modules/utils/swing_comparator.py`

사용자 feature sequence를 reference template과 비교하는 모듈입니다.

반환 결과에는 다음 정보가 포함됩니다.

- global template과의 DTW distance
- 가장 가까운 player template
- similarity score
- phase별 error
- feature group별 error
- comparison confidence
- warning message

---

### `dtw_reference_template_builder.py`

기준 스윙 템플릿 생성용 실행 파일입니다.

입력:

```text
pose_only_dtw_features.npz
per_video_summary.csv
```

출력:

```text
reference_templates.npz
template_summary.csv
template_quality_report.md
template_classification_eval.csv
template_comparison_summary.json
template_scaler.json
selected_reference_videos.csv
```

---

### `compare_user_swing.py`

사용자 feature sequence와 생성된 reference template을 비교하는 실행 파일입니다.

입력은 영상이 아니라 이미 생성된 feature입니다.

```text
user_feature.npy 또는 user_feature.npz
reference_templates.npz
template_scaler.json
```

---


## 4. 기준 템플릿 생성 실행 예시

`team_ready` 폴더에서 실행합니다.

```powershell
cd C:\Users\DO\project\dorami\reference_swing\scripts\team_ready

python dtw_reference_template_builder.py `
  --features-npz "C:\Users\DO\project\dorami\reference_swing\pose_dtw_output_local\pose_only_dtw_features.npz" `
  --per-video-csv "C:\Users\DO\project\dorami\reference_swing\pose_dtw_output_local\per_video_summary.csv" `
  --out-dir "C:\Users\DO\project\dorami\reference_swing\reference_templates_local" `
  --min-label-count 3 `
  --max-nan-ratio 0.15 `
  --eval-mode loo
```

주요 옵션은 다음과 같습니다.

| 옵션 | 의미 |
|---|---|
| `--features-npz` | pose-only feature dataset |
| `--per-video-csv` | 영상별 처리 요약 CSV |
| `--out-dir` | 템플릿 결과 저장 폴더 |
| `--metadata-csv` | 선택 영상/시점 정보가 담긴 metadata CSV |
| `--feature-key` | npz 안에서 사용할 feature key |
| `--min-label-count` | template 생성에 필요한 label별 최소 영상 수 |
| `--max-nan-ratio` | 허용할 최대 NaN 비율 |
| `--eval-mode` | `insample` 또는 `loo` |

---

## 5. 사용자 스윙 비교 실행 예시

```powershell
python compare_user_swing.py `
  --user-feature-npy "C:\path\to\user_feature.npy" `
  --reference-templates "C:\path\to\reference_templates.npz" `
  --template-scaler "C:\path\to\template_scaler.json" `
  --out-json "C:\path\to\comparison_result.json"
```

---

## 6. 현재 한계

- 촬영 시점과 카메라 거리 차이는 feature 비교 결과에 영향을 줄 수 있습니다.
- 따라서 최종 reference template 품질을 높이려면 metadata CSV를 통해 view group, 사용 목적, pose 품질을 관리하는 것이 좋습니다.

---
