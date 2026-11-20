# 자연어 피드백 및 저신뢰 UI 반영

## 범위와 선행 PR

PR #85가 병합된 `3899665`에서 시작한다. 선행 PR의 GPT 근거 압축·출력 검증·승인 전 차단·규칙 기반 폴백은 다시 구현하지 않는다. 기존 최종 검증 worktree의 변경을 비교해 아래의 표시 변경 구간만 적용했다. 원래 worktree와 실험 자료는 보존한다.

1. **문장:** 기준·구간·관절이 드러나는 한국어 템플릿, 반복 축약, 상세 측정 설명. 저장된 리포트와 과거 GPT 응답을 고치거나 과거 응답을 정적 코칭으로 사용하지 않는다.
2. **저신뢰 UI:** 종합·관절 화면에 공통 상태 분류를 사용한다. `low`는 '측정 확인 필요'이며 개선·악화 판정과 교정 우선순위에서 제외한다. 이전·현재 점수는 참고용으로 남기고 증감 화살표와 빨간 악화 강조를 표시하지 않는다.
3. **영향도:** PR #86·#87의 실제 값과 계산은 유지한다. 저신뢰 부위도 수치 계산에는 포함되지만 회색 막대로 표시한다. 비중을 종합점수 감점량이나 실제 자세 오류의 원인으로 바꾸지 않는다.

## 측정 의미

- 골반선 기울기: 원본 화면에서 양쪽 골반을 연결한 선의 기울기. 실제 3D 회전이나 수평 교정 목표가 아니다.
- 골반 기준 앞발 위치: 골반에 대한 화면상 상대 위치. 스탠스 폭이나 스트라이드 이동 거리로 해석하지 않는다.
- 팔꿈치: 각도 증가/감소를 펴짐/굽힘으로 구분한다.
- 손 높이: 어깨 기준 상대 높이로 설명한다.
- 구간 평균은 특정 순간에 맞출 목표 자세가 아니다. 원본에서 차이를 확인하도록 안내하며 임의의 교정량을 만들지 않는다.

## 검증

- 새 worktree에서 `flutter analyze --no-pub`: 통과.
- 전체 Flutter 테스트: **323개 통과, 6개 제외**. 3개는 서비스에서 보류된 P0/원본 모드 전환에 의존하는 기존 테스트다. 나머지 3개는 Chrome 전용 Blob 테스트로 CI에서 별도 실행한다.
- 같은 6개 저장 리포트를 실제 Flutter mapper로 다시 재생: 점수 스냅샷 동일, 원본 입력 불변, 미승인 GPT 표시 없음. 재생 테스트 1개 추가 통과.
- API·모델·점수·GPT 정책 코드 변경 없음. 로그인·업로드·스윙 추이·원본 삭제·3D 관련 코드는 선행 main과 동일하며 전체 테스트의 해당 회귀 검증을 유지한다.
- PR CI는 백엔드 전체 테스트, Flutter 전체 테스트, Chrome 웹 전용 테스트, 서비스 Web build를 실행한다. 최종 HEAD의 결과는 PR Checks에서 확인한다. 이전 커밋의 CI를 새 커밋의 결과로 간주하지 않는다.

로컬 Chrome 확인은 격리된 fixture 앱에서 실제 서비스 피드백 위젯을 사용한다. 실제 Supabase 사용자 E2E나 새 영상의 실제 추론 검증과 구분한다. 검증 로그·화면 캡처·6개 입력 리포트는 `.local/`에만 저장한다.

## 포함 파일

문장 및 UI:

- `frontend/lib/data/feedback_language.dart`
- `frontend/lib/data/feedback_guidance.dart`
- `frontend/lib/data/feedback_repository.dart`
- `frontend/lib/models/feedback.dart`
- `frontend/lib/screens/overall_feedback_screen.dart`
- `frontend/lib/screens/joint_analysis_screen.dart`
- `frontend/lib/screens/phase_feedback_screen.dart`

테스트 및 오프라인 검토 도구:

- `frontend/test/feedback_guidance_test.dart`
- `frontend/test/feedback_language_test.dart`
- `frontend/test/feedback_repository_test.dart`
- `frontend/test/model_v2_feedback_test.dart`
- `frontend/test/phase_feedback_screen_test.dart`
- `frontend/test/score_contribution_integration_test.dart`
- `frontend/tool/feedback_language_app.dart`
- `frontend/tool/replay_feedback_test.dart`
- `scripts/feedback_language_review.py`
- `scripts/verify_feedback_language_browser.py`
- `docs/feedback-language-release.md`

원래 47개 변경 파일 중 선행 PR의 백엔드·GPT 코드와 과거 보고서, 중복 E2E 도구 변경은 새 PR에 넣지 않았다. 두 PR이 같은 Flutter 파일을 수정하더라도 이 PR의 기준점은 이미 병합된 #85이므로 남은 변경 구간만 포함한다.

## 배포 및 남은 검증

- `OPENAI_COACHING_ENABLED=0`이 기본값이다. 키가 존재해도 새 유료 생성은 기본적으로 실행하지 않는다. 활성화에는 별도 운영 승인이 필요하다.
- 실제 GPT B는 `review_required` 상태다. 이 PR은 승인·공개 상태를 바꾸지 않는다. 합성 승인 테스트는 운영 승인이 아니다.
- 운영 DB migration, Supabase 변경, 실제 OpenAI 호출은 없다.
- Android 실기기와 실제 운동자의 문장 이해도, 실제 3D 자세 정확도는 이번 검증 대상이 아니다.
- 롤백은 이 표시 변경 PR을 되돌리는 별도 검토 PR로 수행할 수 있다. 점수·원본 데이터·스키마 변경이 없어 데이터 롤백은 필요 없다.
