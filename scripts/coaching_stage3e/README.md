# 3-E 격리 앱 검증

최신 Flutter 빌드와 실제 FastAPI 서버를 함께 실행합니다. DB는 이 작업 공간의 `.local/feedback-stage3e/app/` 아래 SQLite이고 Storage도 같은 경로 아래 로컬 비공개 파일입니다. 원격 Supabase와 OpenAI 키는 사용하지 않습니다.

실행 Python은 기존 `swing-llm/.venv`를 사용합니다. 이 환경에 없는 프로세스 소유권 확인 도구 `psutil`만 동일 Python 3.11 기반의 기존 `standardswingmodel/.venv` 설치본에서 읽어 사용합니다. 패키지 설치나 기존 환경 변경은 수행하지 않습니다.

## 로컬 연구 환경 전제

이 폴더는 서비스 실행에 필요한 모듈이 아니라 기존 연구 자료를 재사용하는 선택적 검증 도구입니다. 새로운 Git clone만으로 아래 실험 재현 명령을 즉시 실행할 수 있는 것은 아닙니다.

- `dev_fixtures.py`/`verify_app.py`: 같은 부모 폴더의 3-B `current-run/coaching.json`, 3-D `b-run/coaching.json`이 필요합니다. 실제 A/B는 읽어서 비공개 검토 상태로만 사용하며 승인하지 않습니다.
- `replay_report.py`: 3-A의 `inputs.json`, 3-B/3-D의 저장된 응답·입력·실행 근거가 필요합니다. 부모 경로와 출력 폴더는 `--workspace-parent`, `--output`으로 지정할 수 있습니다.
- 브라우저 도구는 Windows의 Chrome, DPAPI, 기존 환경의 `psutil`, `httpx`, `websockets`를 사용합니다. 새 환경의 의존성 설치를 자동 수행하지 않습니다.
- API와 일반 pytest/Flutter 테스트에는 이 외부 실험 자료가 필요하지 않습니다. 원본 응답, 로그인 정보, DB, Storage, 브라우저 프로필은 `.local`에 유지하고 PR에 첨부하지 않습니다.

PowerShell에서 작업 공간 루트로 이동한 뒤 실행합니다.

```powershell
cd C:\Users\DO\project\team\swing-feedback-stage3e
# frontend에서 API_BASE_URL=http://127.0.0.1:8906으로 web 빌드한 뒤:
& ..\swing-llm\.venv\Scripts\python.exe -X utf8 -B scripts\coaching_stage3e\verify_app.py --keep
```

- 앱: http://127.0.0.1:8990/
- API: http://127.0.0.1:8906/api/health
- 테스트 계정 식별자: `stage3e-review`
- 임의 생성 비밀번호는 현재 Windows 계정 전용 DPAPI 파일로만 보관합니다. 터미널에 비밀번호를 출력하지 않습니다.

안전한 재로그인과 종료:

```powershell
& ..\swing-llm\.venv\Scripts\python.exe -X utf8 -B scripts\coaching_stage3e\verify_app.py --open
& ..\swing-llm\.venv\Scripts\python.exe -X utf8 -B scripts\coaching_stage3e\verify_app.py --stop
```

`--stop`은 이 도구가 생성한 PID와 생성 시각이 일치하는 서버·Chrome 프로세스만 종료합니다. DB와 결과 파일은 보존합니다. 이미 사용 중인 포트를 발견하면 다른 서버에 연결하거나 종료하지 않고 중단합니다.

검토 화면의 네 기록:

| 분석 ID | 상태 | 의미 |
|---|---|---|
| `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` | 승인됨 | 직접 작성한 합성 예시로 승인 표시 분기만 검증. 실제 GPT 평가/승인이 아님 |
| `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` | 검토 필요 | 보존된 3-D 실제 B 응답을 비공개 보관. 사용자 화면에는 규칙 기반 안내 |
| `cccccccccccccccccccccccccccccccc` | 차단 | 보존된 3-B 실제 A 응답을 비공개 보관. 사용자 화면에는 규칙 기반 안내 |
| `dddddddddddddddddddddddddddddddd` | 생성 실패 | GPT 호출 없이 실패 상태를 구성. 사용자 화면에는 규칙 기반 안내 |

실제 A/B의 기존 파일은 읽기만 합니다. 점수는 `analysis_sample.json`의 고정 예시이며 실제 사용자 이력이 아닙니다. 3D는 기존 합성 관절 fixture이고 영상 파일은 Storage 검증용 컨테이너입니다. 실제 영상 재생·업로드·추론·3D 정확도·원격 Storage 삭제는 이 도구로 검증하지 않습니다.

자동 확인은 로그인, 비로그인/타인 차단, 승인 전 원문 비노출, 점수 근거 펼치기, 관절·구간 화면, 스윙 추이, 취소·파일 잠금에 의한 삭제 실패·재시도, 삭제 후 점수/피드백/3D 보존을 포함합니다. 결과는 `.local/feedback-stage3e/app/browser-validation.json`, 화면 캡처는 같은 경로의 `screenshots/`에 저장합니다.
