# 코칭 검토·승인·공개 흐름 — 3-E

이 문서는 `swing-feedback-stage3e`의 구현과 운영 적용 전 필요한 작업을 구분한다. 추가 OpenAI 호출이나 운영 DB 변경을 위한 실행 지시가 아니다. 3-B/3-D의 실제 GPT A/B 응답은 승인하지 않았으며, 승인 표시 검증에는 명확히 표시한 합성 문구만 사용했다.

## 구현된 저장 구조

기존 `Swing.result` JSON에 `_coaching_review`를 추가한다. 새 테이블·열·migration은 없다. 기존 `Coaching` JSON 구조와 점수·분석 피처·3D 데이터는 유지한다.

| 위치 | 내용 | 일반 사용자 API 공개 |
|---|---|---|
| `result._coaching_review.candidate` | 실제 생성 후보 | 승인 및 재검사 통과 전 비공개 |
| `validation`, `extended_validation` | 구조·정책 검사 결과 | 비공개 |
| `extended_candidate` | 확장 응답의 원본 JSON | 비공개 |
| `candidate_sha256`, `report_sha256`, `context`, `scope`, `policy_version` | 검토한 버전과 대상 식별 | 비공개 |
| `approval` | 검토자, 검토 시각·메모, 승인 대상 해시·문맥 | 비공개 |
| 공개 응답의 `coaching` | 검증을 통과한 승인 후보 또는 `null` | 공개 |
| 공개 응답의 `coaching_review` | 상태·현재 표시 출처·표시 허용 여부·이유 코드 | 공개 |

비교 코칭은 기존 `result.comparison` 아래에 `previous_analysis_id`와 별도의 `_coaching_review`를 저장할 수 있다. 분석 상세 응답에서는 이 비교 캐시를 제거하고, 인증된 비교 API에서 해당 이전 분석과의 관계를 다시 검사한다.

공개 추가 필드는 `AnalysisReport.coaching_review` 및 `ComparisonResponse.coaching_review`다.

```json
{
  "coaching": null,
  "coaching_review": {
    "status": "review_required",
    "source": "rules",
    "display_allowed": false,
    "reason": "awaiting_human_review"
  }
}
```

여기서 `source`는 현재 화면에 표시할 코칭의 출처다. 생성 후보가 GPT여도 공개가 보류되면 `rules`이며, 승인된 GPT 문구를 공개할 때만 `openai`다. `rules`가 특정 고정 문구를 서버에서 새로 생성했다는 뜻은 아니다. Flutter가 분석 결과를 바탕으로 기존 규칙 기반 안내를 구성한다.

`_coaching_review`의 비공개성은 API 직렬화 경계에서 보장한다. JSON 필드명 자체가 DB 접근 제어는 아니다. 운영 적용 전 Supabase의 직접 테이블 접근·RLS·DB 역할을 확인하여 일반 사용자가 `result` 원문을 읽거나 쓰지 못하는지 검증해야 한다. 이 단계에서는 원격 정책을 변경하거나 검증 완료로 간주하지 않았다.

## 상태와 표시 정책

| 상태 | 의미 | 사용자 표시 |
|---|---|---|
| `approved` | 권한 있는 검토자가 해당 버전을 검토했고 현재 해시·문맥·정책 검사도 통과 | 승인 GPT 문구 |
| `review_required` | 생성은 되었으나 사람 검토 전, 기존 출처 미확인 문구, 승인 대상 변경 | 규칙 기반 안내 |
| `blocked` | 구조·정책 위반, 후보 변조, 승인 정보 이상, 검증 불가 | 규칙 기반 안내 |
| `generation_failed` | 생성 실패, 설정 없음, 생성 결과 없음 | 규칙 기반 안내 |

`approved`는 실제 스윙 진단 정확도를 입증했다는 의미가 아니다. 해당 문구를 해당 근거로 서비스에 표시하는 것을 사람이 승인했다는 뜻이다. 자동 의미 검사는 완전하지 않으며 정상 JSON만으로 승인하지 않는다.

`capture_review()`는 후보를 현재 검증기에 다시 통과시킨 후 대기 또는 차단 상태로 저장한다. 생성 함수가 돌려준 승인 표시를 신뢰하지 않는다. `capture_extended_review()`는 확장 응답을 병합하기 전에 검사한다. 잘못된 추가 필드를 버려서 정상 후보처럼 만들지 않는다. 새 관절·구간 문구가 병합되면 기존 승인을 제거하고 전체 후보를 다시 검토 대상으로 만든다. 확장 생성이 실패하여 문구가 바뀌지 않으면 원래 후보와 기존 검토 상태를 유지하며 별도로 확장 실패를 기록한다.

## 읽기 API와 기존 기록

- 분석 상세·하위 조회는 `public_result()`를 통해 비공개 영역을 제거한다. `/coaching`도 같은 공개 검사를 거치며 표시할 승인 문구가 없으면 404를 반환한다.
- 이전 분석 비교 GET은 읽기 전용이다. GPT를 호출하지 않고 비교 캐시를 갱신하지 않는다. 숫자·관절·구간의 기존 비교 결과는 유지한다.
- 승인 정보 없이 기존 `coaching`만 저장된 기록은 `legacy_unreviewed`로 보류한다. GET에서 DB 원문을 삭제하거나 재작성하지 않는다. 저장된 기존 기록을 사람이 승인한 것으로 간주하지 않는다.
- 잘못된 비공개 검토 JSON이나 NaN 후보가 있어도 유효한 기존 분석 조회를 실패시키지 않고 코칭을 차단한다. 손상된 분석 점수·피처 자체를 임의로 수정하거나 복구하는 기능은 아니다.
- 승인 공개 여부와 별개로 기존 Bearer 인증 및 분석 소유권 검사를 유지한다. 비로그인 401·다른 사용자 403 검증을 수행했다.

## 해시·문맥·정책 검사

승인은 후보 JSON의 SHA-256, 분석 근거 해시, `analysis_id`, `user_id`, `scope`, 정책 버전에 연결한다. 분석 근거 해시는 `model_version`, `overall`, `joints`, `phases`, `speed`, `phase_frames`, `handedness`, `reference_id`를 포함한다. 썸네일·3D 진행 정보·검토 메모 변경 때문에 점수 근거가 바뀐 것으로 처리하지 않는다.

비교 코칭은 이전 분석 ID와 이전 분석 근거 해시도 포함한다. 동일한 ID의 이전 기록이라도 실제 근거가 바뀌면 승인 문구를 반환하지 않는다. 후보 변경, 사용자·분석 대상 변경, scope 변경, 승인 정보 불일치도 표시를 막는다. 승인 후에도 현재 출력 정책을 다시 검사하며 정책 버전이 바뀌면 재검토한다.

해시는 서명이나 검토자 인증 수단이 아니다. DB에 쓸 권한이 있는 공격자가 후보와 승인 정보를 함께 바꾸는 것을 해시만으로 막을 수 없다. 또한 의미 있는 검증 규칙 변경 시 정책 버전을 갱신해야 한다. 해시 일치가 측정값의 물리적 진실이나 문장의 모든 의미를 검증하지 않는다.

## 운영 승인 도구에 필요한 조건

현재 `approve_review()`는 순수 Python 함수이며 인증 API가 아니다. 사용자용 승인 엔드포인트는 없고, 로그인 사용자라는 이유만으로 코칭을 승인할 수 없다. 실제 운영 도구에는 다음을 추가해야 한다.

1. 검토자 인증과 별도 검토 권한 검사. `reviewer_id`는 인증된 운영자 정보에서 얻으며 요청자가 임의 지정하지 못하게 한다.
2. 원본 후보·측정 근거·자동 검사 결과·이전 비교 관계를 함께 보여주는 제한된 검토 화면.
3. 검토 화면에서 본 정확한 후보·보고서·전체 검토 버전을 저장 시 다시 확인하는 비교 후 갱신(CAS) 처리.
4. 행 잠금과 짧은 트랜잭션. 대기 중 GPT 호출이나 사람이 읽는 시간을 DB 잠금 안에 포함하지 않는다.
5. 승인·보류·차단·철회 이벤트의 별도 감사 기록과 접근 제한. 현재 JSON의 승인 메모는 승인 스냅샷이며 변경 불가능한 감사 로그를 대체하지 않는다.
6. 승인 후 실제 사용자 API 직렬화 결과 확인, 검토 권한 없는 요청의 거부, 동시 수정·재시작·정책 변경 테스트.

`blocked` 후보를 승인 함수로 직접 승인할 수 없다. 원인 수정으로 새 후보가 만들어진 경우 다시 검증하고 해당 새 버전을 검토해야 한다. DB JSON의 상태 문자열만 수동으로 `approved`로 바꾸는 절차는 허용하지 않는다.

### 트랜잭션 예시 — 설계용, 실행하지 않음

다음은 이미 검토한 단일 분석 후보를 저장하는 운영 도구의 예시다. 인증·감사 함수는 아직 구현된 API가 아니며 아래 코드를 실제 서비스 작업으로 실행하지 않았다.

```python
# Authenticated operator tool only. Not a user-facing approval endpoint.
principal = require_authenticated_coaching_reviewer()
# expected_* are immutable snapshots captured when this operator reviewed it.
with SessionLocal.begin() as db:
    row = db.execute(
        select(Swing)
        .where(Swing.analysis_id == reviewed_analysis_id)
        .with_for_update()
    ).scalar_one()
    require_operator_access(principal, row)
    latest = deepcopy(row.result)
    pending = latest[PRIVATE_KEY]
    if digest(pending) != expected_review_revision:
        raise ReviewConflict("Candidate or review state changed; review again")
    if report_fingerprint(latest) != expected_report_sha256:
        raise ReviewConflict("Analysis evidence changed; review again")
    if pending["policy_version"] != expected_policy_version:
        raise ReviewConflict("Policy changed; review again")
    # Also require expected_policy_version to equal the currently deployed policy.
    approved = approve_review(
        latest,
        pending,
        context=context_for(row.analysis_id, row.user_id),
        reviewer_id=principal.id,
        note=review_note,
        expected_candidate_sha256=expected_candidate_sha256,
    )
    latest[PRIVATE_KEY] = approved
    latest["coaching"] = None  # Public text comes only through the approval gate.
    row.result = latest       # Preserve unrelated current JSON fields.
    append_review_audit_in_same_transaction(
        db, principal, row.analysis_id, pending, approved
    )
# Read the normal authenticated API and confirm its public result after commit.
```

PostgreSQL에서 동작하는 행 잠금·잠금 대기 제한·실패 처리는 운영 도구에 별도 구현해야 한다. SQLite의 격리 테스트가 실제 PostgreSQL 동시성을 증명하지는 않는다. 잠금 없이 구현한다면 이전 버전과 일치하는 경우에만 갱신하고 영향받은 행이 정확히 1개인지 확인하는 원자적 CAS가 필요하다.

비교 코칭 승인 시에는 현재·이전 행을 일정한 ID 순서로 잠그고, 여전히 같은 사용자의 올바른 직전 분석인지 다시 확인한다. 두 근거 해시와 검토 당시의 비교 쌍을 확인한 후 `previous` 및 비교용 `context_for()`를 전달한다. 기록 순서나 이전 결과가 바뀌면 재검토하며, 오래된 전체 JSON을 다시 쓰지 않는다.

## 적용 순서와 롤백

1. 운영 적용 전 배포 기준점을 기록하고 기존 결과의 백업·접근 제어·복구 책임자를 확인한다. 이번 개발 검증에서는 원격 데이터에 접근하거나 변경하지 않았다.
2. 격리 환경에서 신규 백엔드의 비공개 필터와 신규 Flutter의 승인 게이트를 함께 검증한다. 규칙 기반 안내를 기본으로 두고 승인 없는 GPT 문구가 노출되지 않는지 확인한다.
3. 읽기 경로 보호를 먼저 배포한 뒤 생성 후보 저장을 활성화한다. 신규 Flutter는 승인 메타데이터 없는 GPT를 사용하지 않으며, 신규 백엔드는 구버전 Flutter에도 미승인 문구를 보내지 않는다. 동작이 다른 구버전 서버가 트래픽을 받는 혼합 배포를 피한다.
4. 기존 미검토 코칭이 보류되는 변화와 규칙 기반 안내가 유지되는 것을 확인한다. 레거시 결과를 일괄 승인하지 않는다.
5. 권한·감사·동시성 처리가 갖춰진 운영 검토 도구를 별도로 검증한 후 소수 후보부터 사람 검토를 진행한다. 3-B/3-D의 실제 A/B 응답은 이 절차가 완료되지 않았다.

**구버전 백엔드로 단순 롤백하면 기존 `coaching`이나 비교 캐시의 미승인 문구가 다시 노출되고, 비교 GET에서 GPT 생성이 재개될 수 있다.** 키 설정을 끄는 것만으로 저장된 문구 노출을 막을 수 있다고 가정하면 안 된다.

문제가 생기면 우선 승인 공개 게이트를 유지하면서 규칙 기반 안내를 제공하는 호환 빌드로 전환한다. 게이트를 유지할 수 없는 구버전으로 되돌려야 한다면 코칭 응답 경로를 제한한 유지보수 상태에서 노출 여부를 먼저 검증한다. 원본 점수·분석 결과·승인 기록을 지워서 롤백하지 않는다. 새 JSON 필드는 DB migration이 없어도 구버전의 읽기·쓰기 방식과 함께 검증해야 한다. 운영 변경은 별도 배포 승인과 검증 절차가 필요하다.

## 확인한 범위와 남은 한계

`tests/test_coaching_review.py`와 `tests/test_comparison.py`의 집중 검사 39개가 통과했다. 승인 없는 기존 문구·손상된 검토 JSON·NaN 후보 차단, 승인 대상 변경, 확장 후보 변경 시 재검토, 인증·소유권, DB 재조회, 비교 쌍 변경, 다른 JSON 필드 보존을 포함한다. 삭제 회귀 포함 선행 검사에서는 59개 통과·1개 제외였으며 제외 사유는 Windows의 테스트 심볼릭 링크 생성 불가다. 최종 전체 테스트 결과는 통합 검증 보고서를 따른다.

현재 구현은 미승인 GPT 공개를 차단하는 개발 단계 보호와 검토용 데이터 보관을 제공한다. 운영 검토자 역할, 감사 저장 도구, PostgreSQL 동시 승인 검증, 직접 DB 접근 정책, 실제 사용자의 문장 품질 승인은 아직 별도 작업이다. 합성 승인 문구의 화면 표시가 실제 GPT 응답의 사람 검토 완료를 뜻하지 않는다.
