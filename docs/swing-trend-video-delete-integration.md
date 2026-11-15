# 스윙 추이 + 원본 영상 삭제 통합 검증

> 이 문서는 최초 구현·격리 검증 기록입니다. GitHub 최종 반영 및 현재 DB 상태는 [최종 검증 보고서](swing-trend-video-delete-release.md)를 참고하세요. 캡처·검증 JSON은 로컬에 보존하며 Git에는 포함하지 않습니다.

## 통합 범위

`origin/main`의 `3178845`에서 별도 worktree `swing-trend-video-delete`, 브랜치 `feat/swing-trend-video-delete`를 만들었다. 두 기능의 tracked diff를 확인해 순서대로 적용하고 신규 소스·테스트·문서만 선별했다. 커밋, Push, PR, main 병합은 하지 않았다.

공통 수정 파일은 `frontend/lib/screens/swing_list_screen.dart` 하나였다. 추이 작업의 하단 탭 연결과 삭제 작업의 메뉴·확인창·상태 갱신은 서로 다른 부분이라 텍스트 충돌 없이 통합됐다. 팝업을 닫을 때 불필요한 목록 재조회가 일어나지 않는 기존 삭제 작업의 보호 처리도 유지했다.

추이는 기존 전체 기록 조회 API를 사용한다. 삭제 API는 원본 Storage 객체와 원본 메타데이터만 변경한다. 두 기능을 위해 새 통계 API나 DB 테이블을 만들지 않았다. 로그인·점수 계산·피드백·3D 렌더링 소스는 이번 통합에서 추가로 변경하지 않았다.

## 앱 사용 및 테스트 환경

현재 프론트엔드는 **http://127.0.0.1:8717/**, FastAPI는 **http://127.0.0.1:8899/**에서 실행 중이다. 새로 검증을 시작하면 웹 포트가 달라지며 `.local/integration/dev-state.json`에 기록된다. 최종 Chrome 결과는 `docs/validation/trend-video-integration.json`에 있다. 이 앱은 **격리 SQLite + LocalPrivateStorage + 합성 테스트 기록**을 사용한다. 운영 Supabase 및 기존 사용자 계정과 연결되지 않는다.

검증 계정은 `integration-review`이다. 임의 생성한 비밀번호는 Windows DPAPI로 암호화하여 Git 제외 폴더 `.local/integration/`에만 저장한다. 비밀번호·토큰을 로그나 문서에 쓰지 않는다. 검증 Chrome 창에서 이미 로그인한 상태로 확인하거나 아래 명령으로 같은 창에서 정상 로그인 API를 통해 다시 로그인한다.

```powershell
cd C:\Users\DO\project\team\swing-trend-video-delete
& ..\standardswingmodel\.venv\Scripts\python.exe -X utf8 -B scripts\verify_trend_video_integration.py --open
```

앱을 새로 열면 기존 서비스와 동일하게 재로그인이 필요하다. 토큰 영구 저장이나 인증 우회를 추가하지 않았다. 일반 Chrome에서 주소만 열 경우 이 격리 계정의 세션이 자동 공유되지 않는다.

종료 명령은 이 스크립트가 시작한 프로세스의 PID와 생성 시각을 확인하고 해당 API·웹 서버·검증 Chrome만 종료한다. DB·테스트 파일은 보존한다.

```powershell
& ..\standardswingmodel\.venv\Scripts\python.exe -X utf8 -B scripts\verify_trend_video_integration.py --stop
```

처음부터 다시 검증하려면 기존 검증 프로세스를 종료한 뒤 새 격리 DB로 실행한다. 기존 검증 DB는 덮어쓰지 않는다.

```powershell
cd frontend
& C:\Users\DO\flutter\bin\flutter.bat build web --no-pub --no-web-resources-cdn --no-wasm-dry-run --dart-define=API_BASE_URL=http://127.0.0.1:8899
cd ..
& ..\standardswingmodel\.venv\Scripts\python.exe -X utf8 -B scripts\verify_trend_video_integration.py --keep
```

새 패키지나 SDK를 설치·업그레이드하지 않았다. 기존 lockfile과 로컬 캐시를 사용했다.

## 삭제 정책 및 데이터 보존

- 경로: `DELETE /api/analyses/{analysis_id}/video`. 클라이언트가 Storage 경로나 버킷을 지정할 수 없다.
- Bearer 인증 401, 다른 사용자 403, 없는 분석 404, 분석/3D 생성 진행 중 409를 검사한다.
- Storage 삭제 실패는 502이며 완료로 처리하지 않는다. DB에 삭제 요청을 먼저 남기므로 같은 DELETE로 복구할 수 있다. DB commit 실패는 503이고 재시도 가능하다.
- 삭제 완료 후 원본 조회는 410이다. 종합 피드백에는 삭제 안내를 보여주고 영상 URL을 다시 요청하지 않는다. 로컬에서 이전에 발급한 URL도 사용할 수 없다.
- 분석 ID·일시·상태·종합 점수·관절/구간별 피드백·코칭·3D 메타데이터와 객체는 유지한다. 재삭제는 200으로 처리하고 파일을 다시 삭제하지 않는다.
- 실제 Supabase 객체 삭제는 수행하지 않았다. 기존 Supabase 어댑터의 단일 객체 REST 요청과 오류 분류는 MockTransport로 검사했다. 이미 다운로드한 영상이나 원격 CDN 캐시의 회수까지 보장하는 검증은 아니다.

## 자동 검증

| 항목 | 결과 |
| --- | --- |
| Flutter analyze | 최종 통과, 지적 사항 없음 |
| Flutter 전체 VM 테스트 | 275 통과, 기존 6 제외 |
| Chrome 업로드 테스트 | 27 통과, 제외 없음; VM의 웹 전용 3개 포함 |
| FastAPI 전체 테스트 | 171 통과, 7 제외 |
| Web build | 성공, 로컬 API 8899 지정 |
| Chrome 실제 앱 조작 | 28개 확인 통과, 런타임 예외 0건 |

새 통합 위젯 테스트는 목록 → 추이 → 원본 삭제 → 추이 재진입 → 피드백 진입 순서에서 동일한 분석 ID, 날짜, 82.4점이 유지되는지 검사한다. 기존 두 기능의 개별 테스트도 함께 실행했다.

실제 Chrome에서는 최근 1주 3건, 최근 1개월 4건, 전체 5건이 삭제 전후와 재로그인 후 모두 유지됐다. 로컬 파일을 Windows 핸들로 잠갔을 때 DELETE 502와 파일 보존을 확인하고, 잠금을 해제한 뒤 같은 UI로 재시도하여 200 및 실제 파일 삭제를 확인했다. 삭제 이후에도 피드백과 100프레임 합성 마네킹을 표시하고 재생·일시정지·다음 프레임·확대 버튼을 조작했다. 모든 분석 필드와 3D payload는 삭제 전후 동일하며, 다른 사용자의 파일도 해시가 같았다.

검증 도구를 준비할 때 합성 fixture의 최상위 ID만 바꾼 결과 3D 계약 검사가 내부 `clip_id` 불일치를 거부했다. fixture의 내부 binding을 같은 테스트 분석 ID에 연결하여 해결했다. 실제 앱의 ID 검사를 완화하거나 샘플 fallback을 추가하지 않았다.

Chrome 자동 테스트의 첫 실행은 CanvasKit 로딩 404로 시작하지 못했다. 설치된 Flutter 테스트 서버의 Windows 경로 처리(`flutter_web_platform.dart`, `_localCanvasKitHandler`)에서 `/canvaskit/` 요청을 처리하지 못했다. 검증 브라우저의 CDP Fetch에서 **이미 빌드된 동일 CanvasKit JS/WASM 파일 두 개만** 제공하고 테스트 iframe을 다시 로드하니 27개가 실행되어 통과했다. 모델/API 응답을 가로채지 않았고 SDK·테스트·앱 소스도 변경하지 않았다. 일반 Web 빌드와 앱 검증 서버는 CanvasKit을 정상 제공하므로 이 우회가 필요하지 않았다.

### 기존 Flutter 제외 항목

다음 세 테스트는 main에서 S2 단일 표시로 전환하면서 모드 토글을 보류하여 `skip: true`로 남아 있다. 이번 기능 통합에서 토글을 복구하거나 테스트를 삭제하지 않았다.

1. `improved default, P0/raw comparison keep frame camera and mounted scene`
2. `playback speed uses actual timestamps and mode switch does not reset time`
3. `P0 all suppression remains explicit and raw switch restores observations`

다음 세 개는 VM에서 `skip: !kIsWeb`이며, 이번 Chrome 실행에서 모두 통과했다.

1. `web Blob failure offers an explicit stored-video fallback`
2. `web Blob is released when review is cancelled`
3. `result error still releases its Blob on exit`

### 기존 백엔드 제외 항목

`tests/test_compare_v2.py`의 다음 다섯 테스트는 이 worktree에 `data/skeletons` 실험 데이터가 없어서 제외됐다. 실제 모델 회귀 점수 검증을 통과한 것으로 간주하지 않는다.

1. `test_report_matches_api_schema`
2. `test_reference_swing_scores_reasonably`
3. `test_speed_metrics_are_filled`
4. `test_phase_durations_are_compared_in_time`
5. `test_missing_phase_is_marked_unavailable`

`test_real_supabase_end_to_end`는 원격 리소스 변경 금지 조건에 따라 opt-in을 켜지 않았다. `test_local_delete_rejects_wrong_bucket_directory_escape_and_links`는 Windows에서 테스트용 symlink 생성 권한이 없어 제외됐다. 다른 경로 검증 테스트는 실행됐다. 기존 Starlette/httpx deprecation 경고 1건은 남아 있으며 의존성을 바꾸지 않았다.

## Migration 0004

revision 연결은 `0001 → 0002 → 0003 → 0004`이며 `0004.down_revision = 0003`이다. `swings`에 nullable timestamp `video_delete_requested_at`, `video_deleted_at`만 추가한다.

격리 SQLite에서 fresh upgrade, 모델과 migration 일치, 기존 사용자 보존, 기존 분석을 넣은 `0003 → 0004 → 0003` upgrade/downgrade 후 점수·원본 경로 보존을 확인했다. 브라우저 DB도 0004를 적용했다. PostgreSQL DDL은 연결 없는 offline SQL 생성만 검증했다.

향후 운영 반영 전에는 대상 revision 확인, DB 백업과 복원 절차 확인, 운영 migration 승인이 별도로 필요하다. DB 0004를 먼저 적용한 후 해당 백엔드를 배포해야 한다. 롤백 시에는 원본 삭제 기능을 먼저 중지하고 미완료 삭제를 확인하며, 삭제 이력을 보존한 뒤 코드 롤백을 검토한다. **0003 downgrade는 삭제 이력을 없애며 이미 삭제한 Storage 바이트를 복원하지 않는다.** 운영 DB migration이나 롤백은 실행하지 않았다.

## 화면 및 확인 범위

- 삭제 전 추이 (로컬 `docs/screenshots/trend-video-integration/01-before-delete-trend.png`)
- 확인창 (로컬 `docs/screenshots/trend-video-integration/02-confirmation.png`)
- 실제 로컬 Storage 실패 (로컬 `docs/screenshots/trend-video-integration/03-storage-failure.png`)
- 삭제 후 목록 (로컬 `docs/screenshots/trend-video-integration/04-deleted-calendar.png`)
- 삭제 후 동일 점수 추이 (로컬 `docs/screenshots/trend-video-integration/05-after-delete-trend.png`)
- 보존된 피드백과 원본 삭제 안내 (로컬 `docs/screenshots/trend-video-integration/06-feedback-preserved.png`)
- 삭제 후 3D (로컬 `docs/screenshots/trend-video-integration/07-3d-after-delete.png`)
- 3D 재생 (로컬 `docs/screenshots/trend-video-integration/08-3d-playing.png`)
- 재로그인 후 추이 (로컬 `docs/screenshots/trend-video-integration/09-after-relogin-trend.png`)

검증용 3D는 기존 테스트 fixture의 합성 100프레임 좌표를 별도 분석 ID에 올바르게 연결해 저장했다. 실제 추론을 실행하지 않았다. 테스트의 원본 파일은 Storage 검사용 합성 MP4 컨테이너이며 실제 스윙 영상 디코딩/재생 검증 자료는 아니다. 실제 AI 품질, 원격 Supabase 삭제, PostgreSQL 동시 요청 잠금, Android 실기기는 이번 통합에서 검증하지 않았다.

## 변경 파일 및 보호 확인

전체 **56개 파일(기존 추적 파일 수정 18개, 신규 38개)** 목록과 테스트 요약은 통합 검증 JSON (로컬 `docs/validation/trend-video-integration.json`)의 `changed_files`에 포함한다.

| 구분 | 파일 |
| --- | --- |
| 백엔드 | `api/analyses.py`, `database.py`, `main.py`, `schemas.py`, `storage.py`, `swings.py`, `video_deletion.py` |
| DB | `migrations/versions/0004_original_video_delete.py` |
| Flutter API | `frontend/lib/api/analysis_api.dart`, `swing_api.dart`, `original_video_api.dart` |
| Flutter 데이터·모델 | `frontend/lib/data/feedback_repository.dart`, `swing_repository.dart`, `frontend/lib/models/feedback.dart`, `swing.dart`, `swing_trend.dart` |
| Flutter 화면 | `frontend/lib/router.dart`, `frontend/lib/screens/overall_feedback_screen.dart`, `swing_list_screen.dart`, `swing_trend_screen.dart` |
| Flutter 위젯 | `frontend/lib/widgets/swing_video.dart`, `swing_trend_chart.dart` |
| Flutter 테스트 | `frontend/test/original_video_delete_test.dart`, `swing_trend_test.dart`, `swing_trend_screen_test.dart`, `swing_trend_video_delete_test.dart` |
| 백엔드 테스트 | `tests/test_migrations.py`, `test_swing_listing.py`, `test_video_deletion.py` |
| Chrome 도구 | `scripts/verify_original_video_delete_browser.py`, `verify_swing_trend_browser.py`, `verify_trend_video_integration.py` |
| 문서·검증 자료 | 두 기능 문서, 이 통합 보고서, 검증 JSON, 기능별/통합 화면 캡처 20개 |

추가 통합 산출물은 이 문서, Chrome 검증 스크립트, 통합 위젯 테스트, 화면 캡처와 검증 JSON이다. 기존 두 기능의 문서·스크립트는 각각의 기존 검증 결과를 설명하며, 이번 결과는 이 문서가 기준이다.

원본 `standardswingmodel`의 미추적 2파일, `swing-trend-ui`의 수정/신규 17파일, `swing-video-delete`의 수정/신규 27파일은 작업 전후 SHA-256과 Git 상태·HEAD를 비교했다. 원본 작업 공간은 변경하지 않았다. 통합 worktree의 변경은 모두 미커밋 상태로 남긴다.
