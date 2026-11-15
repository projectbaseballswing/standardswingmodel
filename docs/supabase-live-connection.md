# 실제 Supabase 연결 확인

이 문서는 실행 방법과 검증 범위를 기록한다. 원격 증명, 계정 비밀번호, 실제 사용자 기록과 캡처는 Git에 포함하지 않는다.

## 확인된 상태

- 이전 사용자 승인으로 기존 Supabase `public`에 migration `0004`를 적용했다. 기존 점수·3D 행과 원본 객체를 삭제하는 migration이 아니다.
- 2026-11-15 읽기 전용 검사에서 revision `0004`, nullable `video_delete_requested_at` / `video_deleted_at` 두 열을 확인했다. 이번 GitHub 반영 작업에서는 migration이나 Storage 삭제를 실행하지 않는다.
- 앞선 Chrome 검사에서 기존 계정의 정상 로그인, 월별/전체 기록 조회, 추이 표시, 피드백과 원본 영상 URL 조회를 확인했다. 실제 Supabase 연결이며 `SWING_MOCK=0`이다.
- 익명 DELETE 401, 다른 사용자 DELETE 403을 확인했다. 본인 원격 객체의 삭제 성공·재시도는 자동 검증하지 않았다. LocalPrivateStorage에서만 실제 삭제·실패·복구를 검증했다.
- 기존 기록의 원본 객체나 3D가 없을 수 있다. 샘플이나 가짜 기록으로 대체하지 않는다.

## 실행 방법

Windows 개발 환경의 기존 Python 의존성과 Chrome을 이용한다. 패키지를 자동 설치하지 않는다. 프로젝트 루트에서 실행한다.

```powershell
# API 주소에 맞춰 별도 Web 빌드. Windows에서는 절대 출력 경로 사용.
cd frontend
flutter build web --no-pub --no-web-resources-cdn --dart-define=API_BASE_URL=http://127.0.0.1:8900 --output=<프로젝트 절대 경로>/.local/supabase-live/web
cd ..
python -B scripts/run_supabase_review.py start --env-file <기존 환경 파일 경로>
python -B scripts/run_supabase_review.py open
python -B scripts/run_supabase_review.py stop
```

앱 `http://127.0.0.1:8718/`, API `http://127.0.0.1:8900/`. 기존 계정으로 직접 로그인한다. 테스트 자동 로그인은 선택적으로 `--credentials <Windows DPAPI JSON 경로> --verify-trend`를 사용하며, 인증 API를 우회하지 않는다. 해당 파일은 Git에 넣지 않는다.

이 도구는 DB revision을 먼저 확인하고 migration·데이터 생성·삭제를 자동 수행하지 않는다. 독립 worker ID를 사용하며 기존 작업을 복구 대상으로 삼지 않는다. `stop`은 도구가 생성한 PID와 생성 시각을 확인해 해당 프로세스만 종료한다. 실행 상태·로그·암호화 증명·캡처는 `.local/supabase-live/`에만 저장한다.

## 배포와 롤백

다른 배포 DB까지 `0004`가 적용됐다고 보장하지 않는다. 배포할 연결의 revision과 두 열을 확인해야 한다. `0003` DB에서 새 ORM으로 스윙을 조회하면 없는 열 때문에 실패하므로 백엔드 배포 전에 승인된 migration이 필요하다. 일반 배포 절차와 미적용 환경의 실패 검증은 [최종 보고서](swing-trend-video-delete-release.md)를 참고한다.

이전에 승인받은 적용에서는 변경 대상 데이터의 Windows DPAPI 암호화 snapshot과 적용 영수증을 로컬에 보존했다. 전체 Storage 백업을 대신하지 않는다. 코드 롤백 시에는 추가 열과 삭제 이력을 남기는 것이 우선이다. `0004 → 0003`은 삭제 이력을 없애며 이미 삭제된 영상 바이트를 복구하지 않는다. 원격 downgrade는 별도 승인과 미완료 삭제 검토 없이 실행하지 않는다.
