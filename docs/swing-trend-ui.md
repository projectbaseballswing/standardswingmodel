# 스윙 추이 UI

> 이 문서는 최초 구현·격리 검증 기록입니다. GitHub 최종 반영 및 현재 DB 상태는 [최종 검증 보고서](swing-trend-video-delete-release.md)를 참고하세요. 캡처·검증 JSON은 로컬에 보존하며 Git에는 포함하지 않습니다.

로그인 사용자의 기존 스윙 기록 API를 이용해 종합 점수 변화를 표시한다. 달력 하단의 **스윙 추이**를 누르면 열리며, 그래프의 점을 선택한 뒤 **종합 피드백 보기** 또는 아래 기록을 누르면 기존 분석 결과 화면으로 이동한다.

작업 위치는 `swing-trend-ui` worktree, 브랜치는 `feat/swing-trend-ui`다. 시작 기준은 최신 `origin/main`의 `3178845`다. 커밋·Push·PR·병합은 수행하지 않았다. 원본 `standardswingmodel`의 브랜치와 미추적 파일은 보존했다.

## 표시 규칙

- 최근 1주는 오늘 포함 7일, 최근 1개월은 오늘 포함 30일, 전체는 현재까지의 기록이다. 날짜는 기존 달력과 같은 기기 로컬 시간대를 사용하며 화면에도 기준을 안내한다.
- 분석 완료(`done`) 및 유한한 0~100점 기록만 표시한다. 실제 0점은 유효하다. 미래 날짜, 미완료 기록, 없는 점수는 계산에 넣지 않는다.
- 같은 분석 ID의 동일 기록은 한 번만 사용한다. 날짜·상태·점수가 서로 다른 중복 ID는 어느 행이 맞는지 추측하지 않고 제외한다. 같은 시각의 서로 다른 분석은 모두 보존한다.
- X축은 실제 기록 시각, Y축은 0~100점이다. 선은 관측된 두 기록을 연결할 뿐, 빈 날짜의 점수나 가상의 점을 생성하지 않는다.
- 단일 기록은 점 하나와 `비교 전`으로 표시한다. 평균과 첫 기록 대비 변화도 선택한 기간의 유효 기록만 사용한다.
- 최초 조회와 새로고침에서 전체 기록을 가져온다. 기간 변경은 받아온 기록을 필터링하며, 피드백 화면에서 돌아오면 다시 조회한다.
- 로그아웃·사용자 변경 시 이전 기록을 지우고 오래된 응답을 버린다. 로딩, 통신 오류와 재시도, 기록 없음, 유효 점수 없음 상태를 구분한다.

기존 `GET /api/users/{user_id}/swings`에서 year/month를 생략하는 방식이다. 서버·DB·인증·점수 모델·3D 렌더러는 수정하지 않았으며 신규 패키지도 추가하지 않았다. 최신 main에 이미 지정된 의존성만 lockfile을 유지해 복원했다.

## 변경 파일

| 파일 | 내용 |
| --- | --- |
| `frontend/lib/api/swing_api.dart` | 기존 월별 API 호출에 전체 조회 지원 |
| `frontend/lib/data/swing_repository.dart` | 로그인 사용자의 전체 기록 조회, 이전 세션 응답 차단 |
| `frontend/lib/models/swing_trend.dart` | 기간·중복·유효성 검사와 실제 점수 집계 |
| `frontend/lib/widgets/swing_trend_chart.dart` | 실제 시간축 그래프와 점 선택 |
| `frontend/lib/screens/swing_trend_screen.dart` | 추이 화면과 상태 처리 |
| `frontend/lib/screens/swing_list_screen.dart` | 기존 하단 탭 연결 |
| `frontend/lib/router.dart` | `/swings/trend` 경로 추가 |
| `frontend/test/swing_trend_test.dart` | API·세션·집계 테스트 |
| `frontend/test/swing_trend_screen_test.dart` | 이동·필터·오류·작은 화면 테스트 |
| `scripts/verify_swing_trend_browser.py` | 격리된 로컬 FastAPI/SQLite를 사용하는 Chrome 재현 검사 |

## 검증

- `flutter analyze --no-pub`: 오류 없음.
- `flutter test --no-pub`: 255개 통과, 6개 건너뜀, 실패 없음. 새 추이 테스트와 기존 달력·인증·피드백 등의 회귀 테스트를 포함한다.
- 건너뛴 6개는 기존 3D 웹 테스트 3개와 웹 Blob 테스트 3개다. 일반 VM 실행에서 제외되며 이번 변경에서 해당 테스트의 Chrome 실행까지 검증한 것은 아니다.
- `flutter build web --no-pub --no-web-resources-cdn --dart-define=API_BASE_URL=http://127.0.0.1:8897`: 성공.
- 실제 Chrome의 Flutter 웹 화면을 CDP로 조작해 15개 항목을 확인했다. 로그인 → 달력 탭 → 추이, 7/30일·전체 필터, 해당 분석 ID의 피드백 API 조회 및 앱 뒤로가기, 통신 오류·재시도, 빈 기록·점수 없음·단일 점수를 포함한다.
- Chrome은 1280×1100 및 390×844에서 확인했다. 위젯 테스트에서는 320×568, 1280×900 및 글자 배율 1.3도 확인했다. Android 실기기 검증은 수행하지 않았다.
- 테스트 API는 인증 없는 조회에 401, 다른 사용자 기록 조회에 403을 반환했다.

Chrome 검증은 **변경하지 않은 FastAPI + 격리된 SQLite의 합성 테스트 기록**을 사용했다. 실행 앱의 화면과 HTTP 통신은 실제지만, 캡처의 점수·날짜는 사용자 분석 결과가 아니다. Supabase에 쓰거나 원본 영상을 추론하지 않았다. 운영 Supabase 데이터를 이용한 E2E 검증으로 해석하면 안 된다. 실제 앱은 항상 로그인 사용자의 API 응답을 표시하고, 테스트 기록으로 대체하는 fallback은 없다.

## 결과 화면

아래는 로컬 테스트 기록을 표시한 Chrome 캡처다.

- 데스크톱 최근 1개월 (로컬 `docs/screenshots/swing-trend/desktop-month-fixture.png`)
- 모바일 전체 기간 (로컬 `docs/screenshots/swing-trend/mobile-all-fixture.png`)
- 단일 점수 (로컬 `docs/screenshots/swing-trend/mobile-single-fixture.png`)
- 기록 없음 (로컬 `docs/screenshots/swing-trend/mobile-empty-fixture.png`)
- 유효 점수 없음 (로컬 `docs/screenshots/swing-trend/mobile-no-score-fixture.png`)
- 통신 오류 (로컬 `docs/screenshots/swing-trend/mobile-error-fixture.png`)

## 실행 및 재현

기존 FastAPI를 사용할 때는 `frontend`에서 `flutter run -d chrome --dart-define=API_BASE_URL=<실행 중인 API 주소>`로 실행하고 로그인한다. API 주소에는 `/api`를 붙이지 않는다.

독립된 Chrome 검증은 위의 8897번 API 주소로 웹 빌드 후 프로젝트 루트에서 기존 개발 Python으로 `python -B scripts/verify_swing_trend_browser.py`를 실행한다. FastAPI 의존성과 기존 개발 환경의 `httpx`, `psutil`, `websockets`, Chrome이 필요하다. 스크립트는 패키지를 설치하지 않는다.

테스트는 API 8897, Chrome 디버깅 9547 포트를 사용하고, 정적 웹은 빈 포트를 자동 할당한다. 비밀번호는 실행마다 메모리에서 생성하며 보고서에 저장하지 않는다. 실행한 서버와 Chrome만 종료한다. DB·로그·프로필·테스트 결과는 Git 제외 경로 `.local/swing-trend/`에 남고, 캡처만 위 문서 경로에 저장한다.

전체 기록 조회는 기존 API의 비페이지 방식이다. 기록이 매우 많을 때의 네트워크·그래프 성능은 별도 검증이 필요하다. 다른 미구현 기능과 영상 삭제 기능은 이번 범위에 포함하지 않았다.
