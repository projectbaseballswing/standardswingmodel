# 기준 동작 API (`/reference-motion`)

프로 대표 스켈레톤과, 같은 좌표·같은 시점으로 맞춘 사용자 스켈레톤을 내려준다.
사용자 자세와 프로 자세를 겹쳐 그리는 데 쓰는 데이터다. **점수에는 쓰이지 않는다.**

기존 3D 표시(`/pose-3d`, `EXP008-pose3d-v1`)와는 별개의 API다. `/pose-3d` 의 규격과 동작은 바뀌지 않았다.

## 요청

```
GET /api/analyses/{analysis_id}/reference-motion
```

인증과 소유자 확인은 다른 `/api/analyses/{id}/...` 와 같다.

| 상태 | 뜻 |
|---|---|
| 200 | 정상 |
| 404 | 분석이 없거나, 이 기능 이전에 분석한 스윙이라 사용자 스켈레톤이 저장돼 있지 않음 (새 영상 분석 필요) |
| 409 | 아직 분석 중 |
| 422 | 분석 실패 |
| 503 | 서버에 기준 동작 파일(`data/reference_motion.npz`)이 없음 |

목업 모드(`SWING_MOCK=1`)에서도 샘플 데이터로 응답한다. 응답 크기는 약 50KB 이다.

## 응답 구조

```jsonc
{
  "analysis_id": "...",
  "version": "reference-motion-v1",
  "method": "bone_direction_mode",
  "reference_model_version": "0.2.2-draft",
  "handedness": "right",                // left 면 좌표가 좌우반전(우타 기준)되어 있음. 아래 '좌타' 참고
  "coordinate_convention": { ... },     // 아래 '좌표계'와 같은 내용
  "joint_names": ["lead_shoulder", "rear_shoulder", ...],   // 12개, 아래 표
  "draw_edges": [[0, 1], [6, 7], ...],  // 그릴 선 (joint_names 번호 쌍)
  "bones": [{"name": "pelvis", "length": 0.41}, ...],       // 표준 체형 뼈 길이
  "fps": 30.0,
  "frame_count": 130,
  "events": {"foot_lift": 17, "foot_plant": 80, "swing_start": 92, "impact": 100, "follow_end": 115, ...},
  "phases": [
    {
      "key": "stride", "name": "스트라이드",
      "start_event": "foot_lift", "end_event": "foot_plant",
      "progress": [0.0, 0.0526, ..., 1.0],          // 20개 시점
      "reference": {
        "joints": [[[x, y, z] x 12] x 20],           // 프로 대표 자세
        "root":   [[x, y, z] x 20],                  // 프로 골반 이동
        "spread_deg": [[뼈 11개] x 20],              // 프로들 사이 뼈 방향 퍼짐(도)
        "swings_used": 599
      },
      "user": {                                      // 사용자 영상에 이 구간이 없으면 null
        "start_frame": 17, "end_frame": 80,
        "frames": [17.0, 20.32, ...],                // 20개, 분석 영상 프레임 번호 (소수 = 두 프레임 사이)
        "timestamps_s": [0.5667, ...],               // frames / fps
        "joints": [[[x, y, z] x 12] x 20],           // 사용자 실제 자세
        "root": [[x, y, z] x 20]                     // 임팩트를 못 찾으면 null
      },
      "improved": {                                  // VAE 개선 자세. user 가 null 이거나 모델이 없으면 null
        "joints": [[[x, y, z] x 12] x 20],           // 사용자 스윙을 프로다운 스윙으로 고친 자세 (사용자 체형)
        "change_deg": [[뼈 11개] x 20],              // 사용자 자세에서 바뀐 각도(도). 뼈 순서는 bones 와 같다
        "applied": [0.0, ..., 1.0]                   // 20개, 0 = 사용자 자세 그대로, 1 = 고친 자세
      }
    },
    ...  // transition, swing, follow
  ],
  "improvement": {                                   // 모델이 없으면 null
    "version": "pose-vae-v1",
    "largest_changes": [                             // 많이 바뀐 (구간, 뼈) 최대 5개. 고칠 곳이 없으면 []
      {"phase": "stride", "phase_name": "스트라이드", "bone": "lead_thigh", "bone_name": "앞다리 허벅지",
       "max_change_deg": 34.5, "at_point": 9}        // at_point = 가장 많이 바뀐 시점 번호
    ]
  }
}
```

구간은 항상 4개가 이 순서로 온다: `stride`(앞발 들기 → 착지), `transition`(착지 → 스윙 시작),
`swing`(스윙 시작 → 임팩트), `follow`(임팩트 → 팔로우 끝).

**같은 구간의 같은 번호 시점끼리 대응한다.** 예를 들어 `swing` 의 19번 시점은 기준과 사용자 모두 임팩트 순간이다.
사용자 스윙이 프로보다 느려도 빨라도, 구간 진행률(0~1)로 맞춰 놓았기 때문에 그대로 겹쳐 그리면 된다.

## 좌표계

기준과 사용자가 같은 좌표계를 쓴다.

| | |
|---|---|
| 원점 | 그 시점의 골반 중심 (양쪽 골반 관절의 가운데) |
| 단위 | 몸통 길이 = 1 (어깨 중심 ~ 골반 중심, 화면 x-y 로 잰 길이의 영상 내 중앙값) |
| x | + 투수 쪽 |
| y | + 위 |
| z | + 카메라에서 멀어지는 쪽 (MediaPipe 이미지 z 에 0.30 을 곱해 x, y 와 같은 단위로 맞춘 값) |
| root | 임팩트 순간의 골반 중심을 원점으로 본, 그 시점의 골반 중심 위치. z 는 항상 0 (이미지 z 로는 골반 자체의 깊이 이동을 알 수 없음) |

- `joints` 는 골반 중심이 원점이라 몸이 앞으로 나가는 움직임이 빠져 있다. 이동까지 보여주려면 `joints + root` 를 그린다.
- `root` 는 화면 좌표에서 구한 값이라 카메라가 움직이는 영상에서는 틀어질 수 있다.
- `/pose-3d` 는 MediaPipe 월드 좌표(미터)를 쓰고, 이 API 는 몸통 길이 단위다. 같은 장면에 함께 그리려면
  `/pose-3d` 마네킹의 몸통 길이를 곱해서 크기를 맞춘다.

### 관절 순서 (`joint_names`)

| 번호 | 이름 | 뜻 |
|---|---|---|
| 0 | lead_shoulder | 앞 어깨 (투수 쪽) |
| 1 | rear_shoulder | 뒤 어깨 (포수 쪽) |
| 2 | lead_elbow | 앞 팔꿈치 |
| 3 | rear_elbow | 뒤 팔꿈치 |
| 4 | lead_wrist | 앞 손목 |
| 5 | rear_wrist | 뒤 손목 |
| 6 | lead_hip | 앞 골반 |
| 7 | rear_hip | 뒤 골반 |
| 8 | lead_knee | 앞 무릎 |
| 9 | rear_knee | 뒤 무릎 |
| 10 | lead_ankle | 앞 발목 |
| 11 | rear_ankle | 뒤 발목 |

머리, 손, 발끝은 없다. 우타자는 앞 = 왼쪽, 좌타자는 앞 = 오른쪽이다.

### 좌타

좌타 영상은 분석 전에 좌우반전해서 우타처럼 분석한다. `handedness` 가 `left` 이면 기준과 사용자 좌표 모두 반전된 상태다.
원래 영상 방향으로 그리려면 x 에 -1 을 곱한다. 이름(`lead_*`, `rear_*`)은 그대로 둬도 된다(앞/뒤 기준이라 반전과 무관).

### `/pose-3d` 와 시간 맞추기

`user.frames` 는 분석 영상의 프레임 번호이고, `/pose-3d` 의 `frames[].index` 와 같은 번호다.
소수이면 두 프레임 사이이므로 `/pose-3d` 의 `timestamps_s` 를 그 사이에서 보간하면 실제 영상 시각이 된다.
`user.timestamps_s` 는 `frames / fps` 로 낸 명목 시각이라, 가변 프레임레이트 영상에서는 `/pose-3d` 시각과 약간 다를 수 있다.

## 기준 스켈레톤은 어떻게 만들었나

특정 선수의 영상이 아니라 프로 스윙 800개로 새로 조립한 자세다. AI 학습 없이 계산만으로 만든다.

1. 프로 스윙마다 위 좌표계로 맞추고, 이벤트로 나눈 구간을 20개 시점으로 맞춘다 (점수 기준 모델과 같은 스윙, 같은 이벤트).
2. 뼈 11개(`bones`)마다 방향만 모아, 시점별로 프로들이 가장 많이 몰린 방향을 고른다.
3. 뼈 길이는 프로 전체의 중앙값(표준 체형)으로 고정하고, 골반 중심부터 뼈를 이어 붙인다.

그래서 기준 스켈레톤의 뼈 길이는 모든 시점에서 `bones[].length` 와 같다.
사용자 스켈레톤은 실제 좌표 그대로라 뼈 길이가 사용자 체형을 따르고, 프레임마다 조금씩 흔들린다.

좌표를 그대로 평균 내는 방식은 선수마다 다른 방향이 섞여 팔다리가 짧아진다 (프로 데이터에서 뼈가 최대 11~62% 짧아짐).
뼈 방향을 고르는 방식은 뼈 길이가 그대로이면서, 점수 기준과의 차이도 프로 한 명이 보통 벗어나는 정도(0.9)보다 작다 (구간별 0.17~0.34, 기준 편차 단위).

`spread_deg` 는 그 시점에 프로들끼리 뼈 방향이 얼마나 다른지다. 큰 곳(예: 스트라이드 중 앞다리)은 프로마다 스타일이 달라서,
기준 자세와 다르다고 틀린 동작은 아니다. 화면에서 기준 자세를 흐리게 그리거나 범위로 보여줄 때 쓸 수 있다.

## 개선 자세 (`improved`)

사용자 스윙을 VAE 로 '프로다운' 스윙으로 옮긴 자세다. 기준 스켈레톤(`reference`)은 모두에게 같은 프로 대표 자세지만,
개선 자세는 사용자마다 다르다. 사용자 체형과 프로에게도 흔한 스타일은 그대로 두고, 프로들이 하지 않는 움직임이 있는
순간만 고친다. 점수에는 쓰지 않는다. 만드는 법과 검증은 docs/pose-vae.md.

- 좌표, 관절 순서, 시점은 `user` 와 같다. `user.joints` 와 `improved.joints` 를 같은 시점끼리 겹쳐 그리면
  "내 스윙 vs 고친 내 스윙" 이 된다. 뼈 길이는 사용자 뼈 길이(중앙값)라 체형이 같다.
- `applied` 가 0 인 시점은 사용자 자세와 거의 같다 (뼈 길이만 중앙값으로 맞춘 차이). 1 에 가까운 시점이 고친 순간이다.
  화면에서 강조하거나 그 순간만 개선 자세를 보여줄 때 쓴다.
- `change_deg` 는 뼈마다 바뀐 각도라, 어느 부위가 바뀌었는지 색으로 표시할 때 쓸 수 있다.
- `improvement.largest_changes` 는 문구용 요약이다. 예: "스트라이드에서 앞다리 허벅지가 가장 많이 달라요".
- 프로 영상으로만 학습했고, 뒷팔꿈치 높이 같은 일부 실수는 잘 고치지 못한다 (docs/pose-vae.md).

## 다시 만들기

```
python scripts/build_reference_model.py      # 점수 기준 (라벨이 늘었을 때)
python scripts/build_reference_motion.py     # 기준 동작 -> data/reference_motion.npz
python scripts/train_pose_vae.py --final      # 개선 자세 모델 -> feedback/pose_vae.npz (약 20분)
```

같은 스윙 선택 규칙을 쓰므로 기준 모델을 다시 만들면 기준 동작도 다시 만든다.
