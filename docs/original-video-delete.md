# 사용자 원본 영상 삭제

> 이 문서는 최초 구현·격리 검증 기록입니다. GitHub 최종 반영 및 현재 DB 상태는 [최종 검증 보고서](swing-trend-video-delete-release.md)를 참고하세요. 캡처·검증 JSON은 로컬에 보존하며 Git에는 포함하지 않습니다.

스윙 목록에서 해당 기록의 **더보기(⋮) → 원본 영상 삭제 → 삭제**를 누른다. 확인창은 원본 영상의 복구 불가와 점수·3D 기록 보존을 안내한다. 취소하면 요청하지 않으며, 요청 중에는 같은 기록의 중복 삭제를 막는다.

삭제 후 썸네일에는 `원본 삭제됨`, 기존 종합 피드백에는 `원본 영상이 삭제되었습니다`를 표시한다. 기록을 눌러 점수·피드백·3D 화면으로 이동하는 기존 흐름은 유지한다. 팝업을 닫을 때 목록을 불필요하게 재조회하지 않으며, 늦은 목록 응답이 확인된 삭제 상태를 덮어쓰지 않도록 처리했다.

작업 공간: `swing-video-delete`, 브랜치: `feat/original-video-delete`, 기준: `origin/main` `3178845`. 원본 저장소와 `swing-trend-ui`는 별도로 보존했다. 커밋·Push·PR·병합은 수행하지 않았다.

## API와 보존 범위

`DELETE /api/analyses/{analysis_id}/video`는 기존 Bearer 인증과 소유권 검사를 사용한다. 요청 본문에 경로나 버킷을 받아 사용하지 않는다. DB의 해당 분석 경로가 기존 업로더 규약인 `swings/{analysis_id}/original.<지원 확장자>` 및 설정된 버킷과 일치해야 삭제한다.

| 상황 | 응답 |
| --- | --- |
| 본인 원본 삭제 완료 | 200, `video_status: deleted`, `already_deleted: false` |
| 이미 삭제 완료 | 200, `already_deleted: true`; Storage 재호출 없음 |
| 비로그인·잘못된 토큰 / 다른 소유자 | 401 / 403 |
| 분석 ID 또는 원본 정보 없음 | 404 |
| 분석 대기·진행, 3D 대기·진행, 경로 검증 불가 | 409 |
| Storage 삭제 실패 | 502; 완료로 표시하지 않음 |
| DB 또는 Storage 설정 문제 | 503; 원인 복구 후 같은 요청 재시도 |

보존하는 항목은 분석 ID·사용자·날짜·분석 상태·입력 메타데이터·점수·관절별/구간별 피드백·LLM 코칭·3D 메타데이터와 3D 객체 전체다. `Swing.result`, `Pose3D` 및 3D Storage 객체는 삭제 코드에서 수정하지 않는다. 성공 시 원본 경로·버킷·크기·MIME 필드만 비우고 삭제 완료 시각을 기록한다.

목록과 분석 응답에 `video_status`를 추가했다. 값은 `available`, `deleting`, `deleted`, `unavailable`이다. 기존 분석 `status` 및 점수는 바뀌지 않으므로 추이 계산에 남는다. 구버전 서버 응답의 상태 필드가 없으면 앱에서는 `unknown`으로 취급하고 삭제 메뉴를 비활성화한다.

## Storage와 DB 실패 복구

1. 행을 잠그고 인증·소유권·분석/3D 상태·경로를 확인한다.
2. `video_delete_requested_at`을 **먼저 DB에 commit**한다. 실패하면 Storage를 삭제하지 않는다.
3. 원본 Storage 객체 하나만 삭제한다. 이미 객체가 없는 경우도 재시도를 완료할 수 있다. 인증·버킷·네트워크 오류를 객체 없음으로 취급하지 않는다.
4. `video_deleted_at`과 비워진 원본 메타데이터를 commit한다. 이 단계가 실패하면 2단계의 요청 시각과 원래 경로가 남는다. 동일 DELETE를 재요청하면 복구한다.

미완료 요청은 `deleting`으로 노출되고 원본 URL 신규 발급은 409로 차단된다. 자동 반복 삭제나 백그라운드 재시도 작업은 추가하지 않았다. 사용자는 더보기의 삭제 재시도로 완료한다. 완료된 원본의 URL 조회는 410이며, 앱은 재생 컨트롤러와 재시도 버튼을 만들지 않는다.

Supabase 어댑터는 [공식 단일 객체 삭제 REST API](https://github.com/supabase/storage/blob/master/src/http/routes/object/deleteObject.ts)를 사용한다. 버킷 전체 삭제나 Storage 메타데이터 SQL 삭제를 하지 않는다. [Supabase 삭제 안내](https://supabase.com/docs/guides/storage/management/delete-objects)도 참고했다. LocalPrivateStorage는 루트 내부의 파일 하나만 지우고 경로 탈출·다른 버킷·디렉터리·심볼릭 링크 및 Windows reparse 경로를 거부한다.

이미 클라이언트에 다운로드된 영상 바이트까지 회수할 수는 없다. Supabase가 기존 signed URL/CDN 캐시를 얼마나 빨리 무효화하는지는 원격 검증을 수행하지 않았다. 서버는 삭제 완료 후 새 URL을 발급하지 않는다. LocalPrivateStorage의 이전 capability는 삭제 요청 이후에도 DB 상태를 검사해 접근을 막는다.

## Migration 및 배포 순서

`migrations/versions/0004_original_video_delete.py`는 `swings`에 nullable timestamp 열 두 개만 추가한다. 기존 행의 값은 NULL이고, 점수·원본 경로·3D 행·사용자·Storage 정책에는 변화가 없다. **운영 DB migration은 실행하지 않았다.**

배포 시에는 다음을 별도 승인·검토 후 수행한다.

1. 대상 DB의 현재 revision과 `swings` 백업/복원 가능 여부를 확인한다. 운영 연결 문자열과 키는 로그에 남기지 않는다.
2. 해당 환경에서 `alembic upgrade head`로 0004를 적용한 뒤 새 백엔드, Flutter 순서로 배포한다. migration 없이 새 ORM을 먼저 배포하면 기존 조회도 실패할 수 있다.
3. 격리된 비공개 버킷의 테스트 객체로 Supabase 실제 삭제·소유권·실패 재시도를 검증한다. 운영 사용자 파일은 검증 대상으로 사용하지 않는다.
4. 코드 롤백 시에는 우선 추가 열과 삭제 이력을 남긴다. 미완료 삭제를 해결한 뒤 필요할 때만 0003 downgrade를 검토한다. DB downgrade나 코드 롤백으로 삭제된 영상 바이트가 복원되지는 않는다.

SQLite의 upgrade/check, 기존 분석을 넣은 0003→0004→0003 보존 검사와 PostgreSQL용 SQL 생성 검사를 제공한다. 실제 PostgreSQL 다중 서버 환경의 동시성·잠금 검증은 별도로 필요하다.

## 검증 결과

- Flutter analyze: 오류 없음. 전체 테스트 250개 통과, 기존 웹 전용 6개 제외. 웹 빌드 성공.
- 백엔드 전체 테스트: 171개 통과, 7개 제외. 제외 항목은 이 worktree에 없는 모델/스켈레톤 실험 데이터, 명시적으로 실행하지 않은 원격 Supabase 검사, Windows 권한으로 만들 수 없는 심볼릭 링크 검사다.
- 실제 LocalPrivateStorage 파일 삭제, 다른 파일 보존, 인증 401·권한 403·없는 분석 404·진행 중 409, 반복 삭제, 삭제 후 GET 410, Storage/DB 실패와 재시도, 점수·코칭·3D payload·전체/월별 목록 보존을 확인했다.
- 0003 기존 분석 데이터에 대한 migration upgrade/downgrade 보존 검사, 전체 모델과 migration 일치 검사, PostgreSQL용 SQL 생성 검사를 통과했다. PostgreSQL 서버에는 접속하지 않았다.
- Flutter 위젯 검사는 삭제·취소·중복 요청·오류·계정 변경·삭제된 피드백에서 URL 요청 생략·팝업 복귀 재조회 방지·320px 화면을 포함한다.
- Supabase 어댑터는 공식 REST 경로와 오류 분류를 MockTransport로 검사했다. **원격 Supabase 객체 삭제는 실행하지 않았다.** Android 실기기 검증도 수행하지 않았다.

Chrome 최종 검사 **20개 항목 통과**, JavaScript 런타임 오류 없음. 실제 FastAPI와 migration을 적용한 격리 SQLite, LocalPrivateStorage를 연결해 390×844 화면을 조작했다. 새 테스트 파일에 Windows 파일 잠금을 걸어 실제 502 실패를 만든 뒤, 잠금을 해제하고 UI에서 재요청해 파일 삭제와 DB 완료 상태를 확인했다. 401/403, 취소, 점수·피드백·3D payload 보존, 과거 로컬 URL 차단, 재삭제 성공도 확인했다. 검사 후 자체 생성한 서버와 Chrome이 모두 종료된 것을 확인했다.

아래 화면은 합성 테스트 기록을 표시한 실제 Chrome 캡처다.

- 삭제 전 목록 (로컬 `docs/screenshots/original-video-delete/01-list-before-fixture.png`)
- 삭제 확인창 (로컬 `docs/screenshots/original-video-delete/02-delete-confirmation-fixture.png`)
- 삭제 실패 안내 (로컬 `docs/screenshots/original-video-delete/03-delete-error-fixture.png`)
- 삭제 후 목록 (로컬 `docs/screenshots/original-video-delete/04-list-deleted-fixture.png`)
- 삭제 후 종합 피드백과 3D 진입 버튼 (로컬 `docs/screenshots/original-video-delete/05-feedback-deleted-fixture.png`)

보호 대상인 원본 저장소의 미추적 파일 2개와 스윙 추이 작업의 수정·신규 파일 17개는 작업 전후 SHA-256이 일치한다. 두 작업 공간의 Git status와 HEAD도 동일하다. 패키지 정의와 lockfile, 점수 모델 소스는 변경하지 않았다.

Chrome 검증 스크립트는 `scripts/verify_original_video_delete_browser.py`다. API 8898, Chrome 디버깅 9548, 자동 할당한 웹 포트를 사용한다. 기존 개발 Python의 의존성만 사용하며 패키지를 설치하지 않는다. 먼저 다음과 같이 빌드한 뒤 프로젝트 루트에서 스크립트를 실행한다.

```powershell
cd frontend
flutter build web --no-pub --no-web-resources-cdn --dart-define=API_BASE_URL=http://127.0.0.1:8898
cd ..
python -B scripts/verify_original_video_delete_browser.py
```

테스트 계정 비밀번호는 메모리에서 생성한다. 격리 DB·개별 서버 로그·브라우저 프로필은 Git 제외 경로 `.local/video-delete/`에 남는다. 테스트 원본은 합성 MP4 컨테이너이고 3D는 보존 검사용 합성 payload다. 실제 AI 추론·원본 디코딩·새 3D 애니메이션 정확도를 검증한 자료가 아니다.

## 변경 파일

| 위치 | 역할 |
| --- | --- |
| `api/video_deletion.py` | 삭제 정책, 상태, 재시도 가능한 절차 |
| `api/database.py`, `migrations/versions/0004_original_video_delete.py` | 삭제 요청·완료 시각 |
| `api/storage.py` | Supabase/Local 단일 객체 삭제 |
| `api/analyses.py`, `api/schemas.py` | DELETE, 삭제된 영상 GET 차단, 상태 응답 |
| `api/main.py`, `api/swings.py` | 이전 로컬 URL 차단, 목록 상태 |
| `frontend/lib/api/original_video_api.dart` | 분석 ID 기반 삭제 클라이언트 |
| `frontend/lib/api/analysis_api.dart`, `frontend/lib/widgets/swing_video.dart` | 410 안내와 재생 재시도 중단; 동일 loopback API의 로컬 capability 지원 |
| `frontend/lib/models/swing.dart`, `frontend/lib/screens/swing_list_screen.dart` | 더보기·확인·로딩·오류·목록 상태 |
| `frontend/lib/models/feedback.dart`, `frontend/lib/data/feedback_repository.dart`, `frontend/lib/screens/overall_feedback_screen.dart` | 피드백 유지 및 원본 삭제 안내 |
| `tests/test_video_deletion.py`, `tests/test_migrations.py`, `tests/test_swing_listing.py` | 삭제·보존·복구·변경된 응답 계약 검사 |
| `frontend/test/original_video_delete_test.dart` | UI/API 회귀 검사 |
| `scripts/verify_original_video_delete_browser.py` | 실제 Chrome·로컬 HTTP·임시 파일 삭제 검사 |

## 스윙 추이 작업과의 후속 통합

공통 수정 파일은 `frontend/lib/screens/swing_list_screen.dart`다. 추이 작업은 하단 탭 연결, 이번 작업은 원본 삭제 메뉴와 상태 처리다. 이번에는 `swing_api.dart`, `swing_repository.dart`, `router.dart`를 수정하지 않아 충돌 범위를 줄였다. 현재 추이 브랜치의 추적 파일 변경을 이 worktree에 적용하는 `git apply --check`는 통과했다. 실제 적용이나 병합은 하지 않았다.

추후 승인 후 두 작업을 각각 검토·커밋하고, 최신 main에서 별도 통합 브랜치를 만들어 합친다. 추이의 신규 미추적 화면·모델·테스트도 반드시 포함해야 한다. 팀의 새로운 migration 번호나 목록 변경이 생겼는지 다시 확인하고, 통합 후 삭제된 원본의 점수가 그래프에 계속 표시되는지 함께 검증한다.
