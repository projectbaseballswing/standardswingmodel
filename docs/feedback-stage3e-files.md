# 3-E 변경 파일 및 향후 PR 포함 후보

총 35개 파일을 PR 대상으로 검수했다. 검수 당시에는 모두 미커밋 상태였으며 staged 파일은 없었다. 기존 실험 결과나 실제 GPT 응답 파일은 포함하지 않는다. 최종 검수에서는 점수 요약/상세 배치와 관련 위젯 테스트만 서비스 코드에 추가 변경했다.

## FastAPI

- [api/analyses.py](../api/analyses.py)
- [api/jobs.py](../api/jobs.py)
- [api/schemas.py](../api/schemas.py)
- [api/swings.py](../api/swings.py)

## 코칭 근거·생성·검토

- [feedback/coaching_compact.py](../feedback/coaching_compact.py)
- [feedback/coaching_evidence.py](../feedback/coaching_evidence.py)
- [feedback/coaching_policy.py](../feedback/coaching_policy.py)
- [feedback/coaching_review.py](../feedback/coaching_review.py)
- [feedback/llm_coach.py](../feedback/llm_coach.py)

## Flutter 코드·테스트·재생 도구

- [frontend/lib/data/feedback_guidance.dart](../frontend/lib/data/feedback_guidance.dart)
- [frontend/lib/data/feedback_repository.dart](../frontend/lib/data/feedback_repository.dart)
- [frontend/lib/models/feedback.dart](../frontend/lib/models/feedback.dart)
- [frontend/lib/screens/joint_analysis_screen.dart](../frontend/lib/screens/joint_analysis_screen.dart)
- [frontend/lib/screens/overall_feedback_screen.dart](../frontend/lib/screens/overall_feedback_screen.dart)
- [frontend/lib/screens/phase_feedback_screen.dart](../frontend/lib/screens/phase_feedback_screen.dart)
- [frontend/lib/widgets/feedback_metrics.dart](../frontend/lib/widgets/feedback_metrics.dart)
- [frontend/test/feedback_guidance_test.dart](../frontend/test/feedback_guidance_test.dart)
- [frontend/test/feedback_repository_test.dart](../frontend/test/feedback_repository_test.dart)
- [frontend/test/model_v2_feedback_test.dart](../frontend/test/model_v2_feedback_test.dart)
- [frontend/test/phase_feedback_screen_test.dart](../frontend/test/phase_feedback_screen_test.dart)
- [frontend/tool/replay_feedback_test.dart](../frontend/tool/replay_feedback_test.dart)

## 백엔드 테스트

- [tests/test_coaching_compact.py](../tests/test_coaching_compact.py)
- [tests/test_coaching_policy.py](../tests/test_coaching_policy.py)
- [tests/test_coaching_review.py](../tests/test_coaching_review.py)
- [tests/test_comparison.py](../tests/test_comparison.py)

## 로컬 검증 도구

- [scripts/coaching_stage3e/README.md](../scripts/coaching_stage3e/README.md)
- [scripts/coaching_stage3e/dev_fixtures.py](../scripts/coaching_stage3e/dev_fixtures.py)
- [scripts/coaching_stage3e/replay_report.py](../scripts/coaching_stage3e/replay_report.py)
- [scripts/coaching_stage3e/serve_report.py](../scripts/coaching_stage3e/serve_report.py)
- [scripts/coaching_stage3e/verify_app.py](../scripts/coaching_stage3e/verify_app.py)

## 문서

- [docs/PR-feedback-coaching-draft.md](../docs/PR-feedback-coaching-draft.md)
- [docs/coaching-review-lifecycle.md](../docs/coaching-review-lifecycle.md)
- [docs/feedback-coaching-final-review.md](../docs/feedback-coaching-final-review.md)
- [docs/feedback-coaching-stage3e.md](../docs/feedback-coaching-stage3e.md)
- [docs/feedback-stage3e-files.md](../docs/feedback-stage3e-files.md)

## 필수 코드와 선택 도구

API 4개, 코칭 모듈 5개, Flutter 코드 7개와 관련 테스트 8개가 기능 통합의 핵심이다. 위 문서 5개는 검토·배포·PR 설명용이다.

`scripts/coaching_stage3e/` 5개와 `frontend/tool/replay_feedback_test.dart`는 연구 재현용 선택 도구이다. 외부 3-A/B/D 결과나 로컬 Python·Chrome 환경을 요구하므로 새 clone의 필수 실행 경로가 아니다. PR에 함께 포함한다면 [입력 전제](../scripts/coaching_stage3e/README.md)를 유지한다. 실제 실험 응답/자료를 같이 커밋하지 않는다.

## 제외할 자료

`.local/`, `.env`, 가상환경, 빌드/브라우저 캐시, SQLite/Storage 테스트 파일, 인증 정보, 원본 영상/NPZ 및 기존 실험의 실제 A/B 결과 파일은 커밋하지 않는다.
