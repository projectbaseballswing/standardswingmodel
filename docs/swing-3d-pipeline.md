# 사용자 스윙 World 좌표와 표시 처리

기존 영상 디코딩·YOLO ROI·MediaPipe IMAGE 전처리·모델 0.2 점수 계산은 유지한다. 별도 MediaPipe 추론 대신 **같은 `detect_for_video` 결과**의 `pose_world_landmarks`를 관찰한다. 표시용 좌표와 오류는 `SkeletonResult.pose3d_capture` / `pose3d_error`에 분리하며 점수 입력에 넣지 않는다.

## 처리 경계

1. `modules/utils/video_roi_left.py`: 기존 디코딩에서 `CAP_PROP_POS_MSEC`를 별도로 수집한다. 기존 프레임·FPS 반환은 유지한다. MediaPipe 입력 시간은 기존 `frame_index / fps`를 유지하여 추론 조건을 바꾸지 않는다.
2. `modules/extract_pose_with_roi.py`: 기존 호출을 관찰해 몸 12관절과 heel/toe 4관절을 기록한다. 관찰 실패는 표시만 실패시키며 IMAGE 추출 결과를 바꾸지 않는다.
3. `feedback/pose3d.py`: 프레임 수·실제 PTS를 검증하고 원본 world와 표시 좌표를 분리한다. 누락·비유한 좌표는 JSON `null`이다. IMAGE의 visibility/필터 마스크는 품질 신호이며 World 정확도가 아니다.
4. 좌타 입력을 기존 추출 전에 반전했다면 anatomical L/R 교환과 X 반사를 한 번 적용해 원본 영상 방향으로 복원한다. 골반 중심 이동, Y/Z 부호 변환으로 `source_view_hip_centered_xright_yup_zcamera` 계약을 만든다. 골반 기준점이 없으면 복원된 좌표를 임의로 만들지 않으며, 원시 관측은 `raw_estimation`에 남는다.
5. `feedback/pose3d_policy.py`: 검증된 P2로 원시 관측의 연결·경고 마스크를 결정한다. S2를 적용한 뒤 마스크를 다시 계산하지 않는다.
6. `feedback/pose3d_display/preprocess.py`: 실제 PTS, P2, 신체 크기에 기반한 S2를 **한 번** 적용하고 S0 및 S2를 함께 묶는다. 이미 처리된 입력은 거부한다. 과거 실험 폴더나 파일명에 의존하지 않는다.
7. Flutter는 저장된 S2에 O1 몸통·F1 발·H4 머리 표시를 적용한다. H4는 실제 시선/얼굴 추적이 아닌 보수적인 측면 머리 표시다. 추가 얼굴 관절은 현재 추출하지 않으며 `head_landmarks_present=false`로 명시한다. Flutter에서 S2·좌우 복원을 반복하지 않는다.

## 계약과 공개 인터페이스

`build_pose3d(skeleton, *, analysis_id, user_id, source_sha256)`는 현재 업로드에 결합된 strict JSON clip을 반환한다. `Pose3DError(code, message)`는 기존 점수와 분리해서 처리한다. 과거 분석에 World가 없으면 표시 불가 상태이며 샘플을 대체하지 않는다.

기존 검증된 소비자와 호환하도록 API `EXP008-pose3d-v1`, 내부 표시 `EXP007-final-display-v1`, O1 바인딩 `EXP007-O1-binding-v1`을 유지한다. 이는 스키마 버전명이며 실험 DB/버킷 또는 샘플 영상 선택을 의미하지 않는다.

| 필드 | 의미 |
|---|---|
| `id`, `analysis_id`, `data_kind=analysis` | 현재 분석의 식별자; 서버가 검증한 소유권과 함께 조회 |
| `source_provenance.source_video_sha256` | 실제 업로드 영상의 해시 |
| `raw_estimation` | 원본 MediaPipe world, 추가 발 관절, visibility, decoded PTS |
| `frames` | 원본 영상 방향으로 한 번 복원한 body World 및 경고 |
| `orientation_data` | S0 body/feet와 원본 P2 연결 상태 |
| `final_display_data` | S0·S2, 바인딩, 처리 이력·해시, 실제 시간축 |
| `processing.smoothing_passes=1`, `interpolation=false` | 중복 S2·표시 프레임 보간 없음 |
| `quality.measured_accuracy=false` | 유효 좌표율·경고 빈도는 실제 3D 정확도가 아님 |

원본 PTS를 시작 0으로 정규화하고 마지막 샘플 이후의 중앙값 프레임 간격까지 `presentation_end_s`로 표시한다. 프레임을 생성하지 않는다. PTS 비유한·중복·역행 또는 길이 불일치는 3D 실패다. 명목 FPS로 조용히 대체하지 않는다.

3D clip의 비압축 UTF-8 JSON 한도는 31 MiB이며, API 메타데이터에는 1 MiB를 예약한다. 중복 경고가 큰 경우도 저장 전에 envelope 크기를 검사한다. 전체 응답은 Flutter와 같은 32 MiB 한도이며, 초과 시 `POSE3D_TOO_LARGE`로 표시 생성만 실패하고 기존 점수는 유지한다. 이 검사는 원본 영상 업로드 한도와 별개다. 이전 버전에서 생성된 과대 객체를 읽을 때도 응답 한도를 넘겨 반환하지 않는다.

capture가 없는 경우라도 pipeline이 이미 `INVALID_VIDEO_PTS` 또는 `WORLD_FRAME_ALIGNMENT`를 확인했다면 해당 코드와 고정된 안전한 안내를 보존한다. 허용 목록에 없는 코드와 라이브러리 예외 메시지는 일반적인 `POSE3D_FAILED`로 처리하며 응답에 원문을 노출하지 않는다.

S2는 ±67ms 국소 이차 회귀, 이상값 가중, 빠른 동작에서 감소하는 평활화 비중 및 제한된 연결 길이 보정을 사용한다. 최소 5개의 같은 결측 구간 샘플이 필요하다. 결측 구간·큰 시간 간격을 가로질러 연결하지 않으며, null 마스크·원래 P2 연결·timestamp를 보존한다. 전체 영상의 길이 중앙값을 쓰므로 실시간 인과 필터가 아니라 분석 후 처리다. 수학적으로 더 매끄럽다는 사실은 실제 관절 정확도 개선 증거가 아니다.

## 수치 구현과 검증

P2 원본과 S2 numerical core/config는 검증된 EXP-008 바이트를 보존했다. S2 패키지의 CLI·실험 경로·자산 준비 도구는 이식하지 않았다. 런타임 수학 의존성은 기존 NumPy뿐이다. 고정 파일의 줄바꿈은 LF로 유지해야 provenance SHA가 운영체제마다 달라지지 않는다.

`tests/test_pose3d_pipeline.py`는 같은 MediaPipe 호출 수, IMAGE 점수 배열 byte 동일성, 관찰 실패 분리, 원본 decode/PTS 보존, 한 번의 좌타 복원, 결측·마스크·점수 배열 보존을 검사한다. `tests/test_pose3d_smoothing.py`는 실제 PTS와 명목 FPS 분리, 반복 S2 거부, 불규칙 시간의 이차 운동, 빠른 운동 peak, 좌우 반사 불변성과 발 연결 보정을 검사한다. 이들은 합성 단위 검사이며 실제 영상 E2E나 실제 자세 정확도 측정으로 간주하지 않는다.

Flutter fixture 두 개는 `python -m tests.pose3d_fixture_builder`로 생성한다. 모든 좌표가 수학적으로 만든 합성 좌표이며 실제 선수·영상·NPZ가 없다. 좌타 100@60FPS와 우타 27@30FPS로 계약·재생·회귀를 검증한다. 실제 영상의 모델 0.2 전후 비교 및 Chrome 결과는 통합 검증 보고서에 별도로 기록한다.
