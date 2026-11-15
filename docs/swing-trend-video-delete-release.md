# 스윙 추이·원본 영상 삭제 GitHub 최종 검증

2026-11-15 기준 최종 반영 기록이다. 스윙 추이와 원본 삭제를 통합하고 최신 main의 점수·피드백·3D 변경을 유지한다. [최초 통합 기록](swing-trend-video-delete-integration.md)의 56개 파일에 실제 Supabase 실행 도구와 문서 2개가 추가되어 검토 시작 시 58개였다. 캡처 20개와 검증 JSON 1개는 로컬에 보존하고 커밋에서 제외한다. 소스·자동 테스트·실행 문서만 선별한다.

## 사용자 동작

- 목록 하단 **스윙 추이**에서 최근 7일·30일·전체의 실제 종합 점수를 확인한다. 완료 상태이고 유효 점수가 있는 기록만 사용하며, 그래프/목록에서 기존 피드백으로 이동한다.
- 목록 기록의 더보기 → **원본 영상 삭제** → 확인으로 해당 원본만 삭제한다. 분석 ID·일시·점수·피드백·코칭·3D와 추이 기록을 보존한다.
- `DELETE /api/analyses/{analysis_id}/video`: 인증 401, 타인 403, 없는 ID 404, 분석/3D 생성 중 409. Storage 실패 502와 DB 최종 저장 실패 503은 같은 요청으로 재시도할 수 있다. 삭제 완료 후 원본 조회는 410이다.

## 배포 조건

migration 연결은 `0001 → 0002 → 0003 → 0004`다. `0004`는 `swings`에 nullable timestamp 두 개만 추가한다. **0003 DB에는 새 백엔드를 먼저 배포하면 안 된다.** ORM의 기존 스윙 조회에도 새 열이 포함되므로 조회가 실패할 수 있다. 격리 DB에서 해당 실패와 upgrade 후 조회 복구를 재현하는 회귀 검사를 추가했다.

현재 개발 환경의 기존 Supabase 연결은 이전 승인으로 이미 `0004`이며, 이번 작업에서는 읽기 전용으로 확인했다. PR 초안의 “운영 migration 미적용” 문구를 이 DB에 그대로 적용하지 않는다. 다른 환경은 대상 연결별 확인이 필요하다. 이번 작업은 원격 migration·데이터 갱신·Storage 삭제를 수행하지 않는다.

배포 순서: 대상 revision/열과 백업 확인 → 미적용 DB라면 별도 승인 후 0004 → 백엔드 → Flutter. 롤백은 먼저 이전 코드로 복귀하고 nullable 열과 삭제 이력은 유지한다. downgrade는 별도 검토하며 삭제된 영상은 복원되지 않는다. 저장소의 Actions는 테스트용이며 원격 DB 증명을 제공하거나 migration을 실행하지 않는다.

## 검증 결과

기준 main은 `1b0ec66`(PR #75)이다. 25개 후속 커밋을 병합했으며 공통 수정 5파일은 자동 병합됐다. 충돌 표식은 없고, `frontend/lib/features/swing_3d`, `feedback`, `modules`, 인증·로그인·작업 큐는 최신 main과 동일하다.

| 검사 | 결과 |
| --- | --- |
| Flutter analyze | 통과 |
| Flutter 전체 VM 테스트 | 276 통과, 기존 6 제외 |
| FastAPI 전체 테스트 | 187 통과, 14 제외 |
| Web build | 통과 |
| 실제 Chrome 통합 조작 | 28항목 통과, 런타임 예외 0 |
| Migration | 격리 SQLite fresh/기존 데이터 보존/0003↔0004, PostgreSQL offline SQL 통과 |
| 미적용 DB | 0003에서 새 ORM 조회 실패, 0004 적용 뒤 조회 복구 확인 |

Chrome에서 정상 로그인 → 추이 기간 필터 → 삭제 취소 → 실제 임시 파일 잠금에 따른 502 → 잠금 해제 후 재삭제 200 → 추이·피드백·3D 유지 → 재로그인 후 유지까지 확인했다. API·UI는 실제 실행하되 점수와 3D는 명시한 합성 fixture이며 운영 데이터나 실제 AI 재추론을 사용하지 않았다. 원본은 Storage 검사용 MP4 컨테이너여서 영상 디코딩 품질 검증은 아니다. 기존 서버/DB는 건드리지 않고 해당 검사 프로세스만 종료했다.

Windows에서 저장·재시작 검사 subprocess 로그의 문자 디코딩 경고가 발생했다. `PYTHONUTF8=1`로 해당 검사만 다시 실행해 통과했고 디코딩 경고는 없어졌다. 기존 Starlette/httpx deprecation 경고는 남아 있으며 의존성을 변경하지 않았다.

GitHub CI 결과는 PR의 Checks에서 확인한다. 실제 Supabase 객체 삭제, Android 실기기, PostgreSQL 동시 삭제 잠금은 미검증이다.

### 제외된 검사

- Flutter VM: 기존 `swing_3d_screen_test.dart`의 P0/raw 모드 전환 관련 3개는 main의 표시 정책 변경으로 계속 skip이다. `swing_upload_test.dart`의 웹 Blob 실패 대체·취소 해제·결과 오류 시 해제 3개는 VM 제외이며 GitHub Linux Chrome job에서 따로 실행한다.
- `test_compare_v2.py` 10개: 이 checkout에 `data/skeletons` 원본 실험 데이터가 없어 제외. schema, reference score, speed, phase duration, missing phase, whole-video missing joint, depth normal/abnormal, direction wording, rotation cap 검사다.
- `test_event_lstm.py` 2개: 실제 스켈레톤 데이터가 없어 실제 스윙 이벤트 순서와 LSTM anchor 비교를 제외.
- `test_real_supabase_end_to_end`: 원격 변경을 수행하지 않기 위해 opt-in 비활성.
- `test_local_delete_rejects_wrong_bucket_directory_escape_and_links`: Windows symlink 생성 권한이 없어 제외. Linux CI에서 재검증한다.

### 기존 작업 보존과 공개 범위

두 원본 feature worktree와 `standardswingmodel`의 HEAD·변경 상태·수정/미추적 파일 SHA-256을 전후 비교한다. Git fetch로 공통 원격 추적 ref만 최신화하며 원본 파일은 변경하지 않는다. 테스트 캡처 20개와 JSON 1개는 untracked 상태로 남기고 삭제하지 않는다. `.env`, 키·토큰·비밀번호, 개인 영상·NPZ, 로컬 DB·캐시·실행 로그는 커밋에 포함하지 않는다.

## PR에 포함하는 38개 파일

- `api/analyses.py`
- `api/database.py`
- `api/main.py`
- `api/schemas.py`
- `api/storage.py`
- `api/swings.py`
- `api/video_deletion.py`
- `docs/original-video-delete.md`
- `docs/supabase-live-connection.md`
- `docs/swing-trend-ui.md`
- `docs/swing-trend-video-delete-integration.md`
- `docs/swing-trend-video-delete-release.md`
- `frontend/lib/api/analysis_api.dart`
- `frontend/lib/api/original_video_api.dart`
- `frontend/lib/api/swing_api.dart`
- `frontend/lib/data/feedback_repository.dart`
- `frontend/lib/data/swing_repository.dart`
- `frontend/lib/models/feedback.dart`
- `frontend/lib/models/swing.dart`
- `frontend/lib/models/swing_trend.dart`
- `frontend/lib/router.dart`
- `frontend/lib/screens/overall_feedback_screen.dart`
- `frontend/lib/screens/swing_list_screen.dart`
- `frontend/lib/screens/swing_trend_screen.dart`
- `frontend/lib/widgets/swing_trend_chart.dart`
- `frontend/lib/widgets/swing_video.dart`
- `frontend/test/original_video_delete_test.dart`
- `frontend/test/swing_trend_screen_test.dart`
- `frontend/test/swing_trend_test.dart`
- `frontend/test/swing_trend_video_delete_test.dart`
- `migrations/versions/0004_original_video_delete.py`
- `scripts/run_supabase_review.py`
- `scripts/verify_original_video_delete_browser.py`
- `scripts/verify_swing_trend_browser.py`
- `scripts/verify_trend_video_integration.py`
- `tests/test_migrations.py`
- `tests/test_swing_listing.py`
- `tests/test_video_deletion.py`
