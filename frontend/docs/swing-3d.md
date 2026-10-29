# 사용자 스윙 3D 화면

종합 피드백의 **3D 스윙 보기**는 `/analyses/:id/pose-3d`로 이동한다. `Pose3dApi`는 로그인 서버가 발급한 Bearer 세션으로 해당 분석을 조회하며 소유자, 분석 ID, 프레임 수, 좌우타와 데이터 계약을 검사한다. 이 앱에는 선수 샘플 자산, 샘플 경로 또는 실패 시 샘플로 대체하는 로더를 포함하지 않는다.

## 처리 경계

- 서버: 같은 MediaPipe 추론의 실제 World 좌표 보존 → 원본 방향 복원 → P2 표시 정책 → S2 한 번 적용 → 비공개 저장.
- Flutter: 버전과 처리 이력 검사 → O1 몸통 / F1 독립 발 방향 / H4 보수적 머리 표시 → 실제 timestamp 재생.
- 원본과 표시용 좌표는 별개이며 Flutter에서 S2, 좌우 반전 또는 프레임 보간을 다시 수행하지 않는다. P0와 원본 좌표는 비교 모드로 유지한다.
- H4는 실제 얼굴·시선 추적이 아니다. 단안 관절 추정 오류가 남을 수 있으며 결측을 정상 좌표로 만들지 않는다.

`Swing3dScreen`은 필수 `SwingClipLoader`를 받는다. `UserSwing3dScreen`이 인증된 API 조회, 생성 중 polling, 오류/재시도와 로그아웃 시 화면 제거를 맡는다. 카메라 회전·확대·재생·일시정지·배속·탐색은 공유 렌더러를 사용한다. 배경 진입이나 다른 화면 전환 시 재생을 멈춘다.

색상은 `lib/features/swing_3d/rendering/mannequin_style.dart`에 모았다. 청록 본체, 밝은 머리, 주황 발 방향, 회색 불확실 형상을 원본/P0/개선 모드에 공통 사용한다.

## 실행과 의존성

```powershell
flutter run -d chrome --dart-define=API_BASE_URL=http://127.0.0.1:8000
flutter analyze
flutter test
flutter test --platform chrome test/swing_upload_test.dart
flutter build web --dart-define=API_BASE_URL=https://your-api.example
```

기존 SDK와 의존성이 준비된 환경에서는 위 명령에 `--no-pub`를 추가해 설치 없이 실행할 수 있다. API URL에 인증 정보나 비밀 키를 넣지 않는다. Android 실기기는 PC의 `127.0.0.1`로 접근할 수 없으므로 해당 기기가 접근 가능한 HTTPS 또는 개발 LAN API 주소를 명시한다.

기존 실험에서 검증한 `three_js 0.3.0`과 동일한 잠금 파일의 3D 관련 의존성을 재사용했다. 다른 기존 의존성 버전은 변경하지 않았다. `flutter_angle 0.4.2`의 WebGL 브리지를 `web/gles_bindings.js`에 포함했고 MIT 고지를 `web/FLUTTER_ANGLE_LICENSE.txt`에 보존했다. 새 원격 패키지 다운로드/업그레이드는 수행하지 않았다.

`SWING_3D_DIAGNOSTICS=true`는 로컬 검증 빌드에서만 쓰는 선택 플래그다. 기본값은 false이며 운영 빌드에는 진단 상태를 노출하지 않는다.

## 테스트 데이터와 한계

`test/fixtures/synthetic_left60.json`, `synthetic_right30.json`은 실제 선수 영상에서 가져온 좌표가 아닌 합성 인체 기하다. 100프레임/60FPS 및 27프레임/30FPS를 사용하며 `python -m tests.pose3d_fixture_builder`로 재생성한다. 실제 Python P2/S2 포장 결과를 Dart 계약·재생·방향·결측·소유권·회귀 테스트에서 읽는다. 합성 기하 테스트는 실제 사람의 3D 추정 정확도를 측정하지 않는다.

Android는 연결 기기가 없고 로컬 SDK에 `flutter_angle`이 요구하는 CMake 3.31.4가 없다. SDK를 추가 설치하지 않았으며 Android 빌드·렌더링·터치·성능은 미검증이다. Chrome 결과로 Android 검증을 대체하지 않는다.

2026-10-28 검증에서 Flutter analyze 문제 없음, VM 테스트 228개 통과 및 웹 전용 3개 skip, 실제 Chrome에서 해당 웹 전용 3개 모두 통과를 확인했다. 기존 Blob 수명 테스트의 브라우저 `FileReader` 작업은 widget fake clock 밖의 `tester.runAsync`에서 기다리도록 수정했다. Flutter 3.44.9의 Windows 테스트 하네스는 CanvasKit URL을 Windows 경로로 변환한 뒤 `/` 접두어로 검사하여 설치된 자산에 404를 반환했다. 이 환경에서는 테스트 Chrome에 설치된 SDK의 동일 CanvasKit JS/WASM 바이트만 임시 CDP 경유로 제공했다. SDK나 앱을 패치하지 않았으며 API·좌표·영상·테스트 기대값을 대체하지 않았다. 따라서 Windows에서 위 기본 Chrome 테스트 명령만으로 모두 통과했다고 해석하지 않는다. 실제 앱 Web 빌드와 실제 API Chrome 검증은 이 하네스 우회 없이 수행한다.
