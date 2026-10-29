# 실제 영상 API 검증 도구

`scripts/verify_swing_3d.py`는 실행 중인 API에 새 테스트 계정 두 개를 가입하고 실제 MP4를 업로드한다. 서버를 시작하거나 DB migration·버킷 생성·리소스 삭제를 실행하지 않는다. 운영 환경에서는 **해당 환경에 테스트 계정과 영상을 생성해도 된다는 승인**을 먼저 받아야 한다.

```powershell
python scripts/verify_swing_3d.py `
  --base-url http://127.0.0.1:8000 `
  --case "left=C:\approved-input\left.mp4" `
  --case "right=C:\approved-input\right.mp4" `
  --output .local/validation/live-swing-3d.json `
  --allow-create-test-data
```

외부 API 주소는 HTTPS를 요구한다. `http`는 localhost/loopback에서만 허용하며 URL의 사용자정보·query·fragment를 거부한다. 기존 환경변수·DB·Storage 설정은 서버가 그대로 사용한다. 도구는 DB 비밀키를 읽지 않는다.

기본적으로 각 업로드의 점수 및 3D 완료를 합쳐 300초 기다린다. 필요하면 `--timeout-seconds`를 최대 3600까지 명시한다. 제한 시간이 지나도 서버의 추론을 종료하지 않으며 상태를 실패 영수증에 남긴다. 자동 재업로드·재추론은 하지 않는다. 이미 영수증이 있으면 네트워크 호출 전에 중단한다. 실패 영수증을 삭제해 무심코 재실행하기보다 생성된 리소스와 실패 원인을 확인하고, 의도적인 새 실행에는 다른 출력 경로를 지정한다.

검사 범위는 다음과 같다.

- `mock=false`, 모델 버전 0.2, 실제 업로드에서 점수와 3D 생성
- 실제 MP4 디코딩의 프레임 수·PTS와 3D timestamp 일치; 명목 FPS와 PTS FPS 구분
- 분석 ID·업로드 SHA·좌우타·복원 정보·S2 1회 처리·P2 및 null 마스크 보존
- 미인증/잘못된 토큰 401, 다른 계정의 분석·3D·영상·피드백·기록 접근 403
- 본인의 저장된 3D 재조회, 영상 signed/capability URL 읽기, 기록 조회, 로그아웃 후 토큰 폐기

이 도구는 계정 ID·분석 ID·파일 해시·FPS·검사 결과만 남긴다. 비밀번호·인증 토큰·signed URL·전체 좌표·원본 파일 경로·임의 서버 오류 본문은 저장하지 않는다. 비밀번호와 토큰은 메모리에서만 사용하고 종료 시 자신이 만든 세션의 로그아웃을 시도한다. 계정·분석·영상·3D 객체는 삭제하지 않는다. 완료 후에는 영수증의 계정/분석 ID로 생성된 리소스를 확인할 수 있다.

서버의 Storage 구현을 HTTP만으로 확정하지 않으므로 이 결과만으로 Supabase PostgreSQL/Storage 또는 RLS를 검증했다고 주장하지 않는다. 실제 Supabase 연결·일반 역할 정책 감사는 별도로 수행한다. Flutter 조작·렌더링, Android, 모델 점수의 통합 전후 회귀 비교 및 실제 자세 정확도 역시 별도 검증이다.

`tests/test_verify_swing_3d.py`는 실행 승인·기존 영수증 보호·HTTPS·mock 거부·패킷 검사·오류 비밀값 차단만 합성/가짜 HTTP로 검사하며 실제 영상 E2E 통과가 아니다. 실제 E2E에는 이미 설치된 API HTTP 의존성과 영상 디코딩용 OpenCV가 필요하다.
