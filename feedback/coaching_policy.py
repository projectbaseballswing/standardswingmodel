"""Offline output-policy checks, separate from the public Coaching JSON contract.

Structural violations are deterministic. Natural-language checks are deliberately
review hints, not proofs of semantic correctness. Even a response with no matched
hint requires human review; this module never certifies coaching accuracy and
never edits the response, retries a model, or manufactures replacement coaching.
"""
from __future__ import annotations

import math
import re
from typing import Any


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _texts(value: Any, field: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            if key != "key":
                yield from _texts(item, f"{field}.{key}" if field else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _texts(item, f"{field}[{index}]")
    elif isinstance(value, str):
        yield field, value


def _allowed(payload: dict, section: str) -> set[str]:
    explicit = payload.get("allowed") or {}
    if section in explicit:
        return {k for k in explicit[section] if isinstance(k, str)}
    rows = payload.get(section) or []
    if section == "joints" and not rows:
        rows = [f for p in payload.get("parts", []) for f in p.get("features", [])]
    return {r["key"] for r in rows if isinstance(r, dict) and isinstance(r.get("key"), str)}


def _unknown_fields(raw: Any, parsed: Any, path: str = ""):
    """Pydantic defaults ignore extras, but unknown policy fields must be visible."""
    if hasattr(type(parsed), "model_fields") and isinstance(raw, dict):
        known = type(parsed).model_fields
        for key, value in raw.items():
            field = f"{path}.{key}" if path else key
            if key not in known:
                yield field
            else:
                yield from _unknown_fields(value, getattr(parsed, key), field)
    elif isinstance(parsed, list) and isinstance(raw, list):
        for index, (r, p) in enumerate(zip(raw, parsed)):
            yield from _unknown_fields(r, p, f"{path}[{index}]")


_NOT_MEASURED = re.compile(
    r"측정(?:하지\s*않|되지\s*않|하지\s*못|할\s*수\s*없)|"
    r"확인(?:할\s*수\s*없|하기\s*어렵)|판단(?:할\s*수\s*없|하기\s*어렵)|"
    r"원인(?:은|을)?\s*(?:미확인|알\s*수\s*없)|검증(?:되지\s*않|한\s*것이\s*아니)"
)
_DENIAL = re.compile(r"뜻하지\s*않|의미하지\s*않|(?:을|를|이|가|은|는)?\s*아니(?:에요|예요|다|며|고|라|라고|라는|ㅂ니다|었습니다|므로)|아닙니다")
# Negation applies to a clause, not every sentence containing a disclaimer.
# These boundaries are intentionally conservative heuristics, not a Korean NLP
# parser. Mixed claims still receive mandatory semantic review if unmatched.
_CLAUSE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+|[;,]\s*|(?:하지만|그러나|다만|반면)\s*|(?<=지만)\s*|(?<=않았고)\s+|(?<=않고)\s+")
_UNMEASURED_PATTERNS = {
    "head_or_gaze": re.compile(r"머리|시선|공을\s*보(?:려|는|고)|바라보"),
    "force_or_weight": re.compile(r"근력|지지력|지면\s*반력|체중\s*이동|힘(?:이|을|의|으로)|버티|버텨|바닥을\s*밀"),
    "rotation_order": re.compile(r"골반.{0,20}먼저.{0,35}어깨|어깨.{0,20}먼저.{0,35}골반|회전\s*(?:시작\s*)?순서"),
    "bat_or_ball_path": re.compile(r"배트\s*(?:궤적|속도)|타구\s*속도"),
}
_CAUSAL = re.compile(r"때문|탓|원인은|원인으로|영향으로|로\s*인해|그래서")
_HISTORICAL = re.compile(
    r"(?:지난|이전|직전|전번|전보다).{0,45}(?:개선|좋아|악화|나빠|유지|늘|줄|상승|하락|높아|낮아|가까워)|"
    r"개선됐|개선되었|좋아졌|나아졌|악화됐|악화되었|향상됐|향상되었"
)
_NO_HISTORY_ASSERTION = re.compile(
    r"(?:이전|직전|지난)\s*(?:스윙\s*)?(?:기록|분석)(?:이|은|도)?\s*(?:전혀\s*)?(?:없|존재하지)|첫\s*(?:스윙|분석|기록)"
)
_EXACT_TARGET = re.compile(
    r"(?:기준|목표).{0,12}(?:위치|높이|각도|자세).{0,20}(?:도달|맞추|맞춰|정확|순간)|"
    r"정확히.{0,12}(?:기준|목표).{0,12}(?:위치|높이|각도|자세)"
)


def _negated(clause: str) -> bool:
    return bool(_NOT_MEASURED.search(clause) or _DENIAL.search(clause))


def _unmeasured_claim(pattern: re.Pattern, clause: str) -> bool:
    """Only suppress an identified concept when its own following text denies it.

    A leading disclaimer does not suppress a later concept/claim. For example,
    '시선은 측정하지 않았지만 머리가 흔들려요' is split before this check.
    """
    for mention in pattern.finditer(clause):
        if not _negated(clause[mention.end():]):
            return True
    return False


def _body_value_exposure(text: str, payload: dict) -> bool:
    features = [f for p in payload.get("parts", []) for f in p.get("features", [])]
    features += payload.get("observations", [])
    names = {x.get("name") for x in features if x.get("unit") == "body" and isinstance(x.get("name"), str)}
    if not any(name in text for name in names):
        return False
    # Scores and real durations may legitimately be numeric. Only flag numeric
    # body-coordinate comparisons, not every number appearing in a response.
    return bool(re.search(r"(?:사용자|기준)\s*(?:값|위치|높이)?\s*[:=]?\s*-?\d+(?:\.\d+)?|-\d+\.\d+", text))


def validate_coaching_output(
    response: dict, payload: dict, *, scope: str = "overall", extended: bool = False
) -> dict:
    """Return policy diagnostics beside, never inside, the Coaching response.

    ``blocked`` means a deterministic schema/key/count violation. Otherwise the
    status is always ``review_required``. Free-text hints may have false positives
    and false negatives; explicit uncertainty statements are not diagnoses.
    """
    # Local import avoids a cycle when llm_coach itself calls this validator.
    from pydantic import ValidationError
    from feedback.llm_coach import Coaching, CoachingFull, ExtendedCoaching

    findings: list[dict] = []
    seen = set()

    def add(code: str, severity: str, field: str, reason: str):
        identifier = (code, field)
        if identifier not in seen:
            findings.append({"code": code, "severity": severity, "field": field, "reason": reason})
            seen.add(identifier)

    schema = ExtendedCoaching if extended else CoachingFull if scope == "full" else Coaching
    schema_valid = False
    try:
        parsed = schema.model_validate(response, strict=True)
        schema_valid = True
        for field in _unknown_fields(response, parsed):
            add("unexpected_field", "block", field, "기존 JSON 계약에 없는 필드입니다. 이 값으로 코칭 범위를 확장하지 않습니다.")
    except ValidationError as error:
        # Pydantic error input can contain arbitrary response text; retain only
        # field paths and stable error types, never the raw input/error dump.
        for item in error.errors(include_input=False):
            add("schema_error", "block", ".".join(map(str, item["loc"])), "기존 JSON 스키마 불일치: " + item["type"])

    if schema_valid:
        sections = ("joints", "phases") if extended else (("parts", "joints", "phases") if scope == "full" else ("parts",))
        for section in sections:
            allowed = _allowed(payload, section)
            used = set()
            for index, row in enumerate(response[section]):
                path = f"{section}[{index}]"
                key = row["key"]
                if key not in allowed:
                    add("unknown_key", "block", path + ".key", "허용된 " + section + " 키가 아닙니다: " + key)
                if key in used:
                    add("duplicate_key", "block", path + ".key", "같은 항목을 중복 생성했습니다: " + key)
                used.add(key)
                if section == "parts" and len(row["keep_points"]) + len(row["improve_points"]) > 3:
                    add("part_point_limit", "block", path, "부위별 keep_points와 improve_points 합계가 최대 3개를 초과했습니다.")

    canonical = payload.get("canonical_evidence")
    evidence = canonical if isinstance(canonical, dict) else payload
    comparison = payload.get("comparison") or {}
    comparison_available = comparison.get("available") is True
    excluded_names = {r.get("name") for r in evidence.get("excluded", []) if isinstance(r, dict) and r.get("name")}
    score_basis = evidence.get("score_basis") or {}
    for field, text in _texts(response):
        if not text.strip():
            add("empty_text", "review", field, "빈 코칭 문장입니다. 누락된 설명인지 검토하세요.")
        if _body_value_exposure(text, evidence):
            add("normalized_body_value_exposed", "review", field, "신체 크기로 정규화한 위치 숫자가 사용자 문구에 노출됐습니다. 실제 거리나 정확한 목표 자세로 오해하지 않도록 쉬운 상대 방향으로 설명하고 수치는 상세 근거로 분리하세요.")
        for sentence in _CLAUSE_BREAK.split(text):
            negated = _negated(sentence)
            for concept, pattern in _UNMEASURED_PATTERNS.items():
                if _unmeasured_claim(pattern, sentence):
                    add("unmeasured_" + concept, "review", field, "현재 분석이 직접 측정하지 않는 개념을 언급했습니다. 새 진단·인과관계인지 검토하세요.")
            if _CAUSAL.search(sentence) and not negated:
                add("unsupported_causality", "review", field, "인과관계 표현이 있습니다. 관절 차이만으로 원인을 설명하지 않았는지 검토하세요.")
            if not comparison_available and _HISTORICAL.search(sentence) and not negated:
                add("history_without_comparison", "review", field, "검증된 직전 스윙 비교가 없는데 시간적 개선·악화·유지를 주장하는지 검토하세요.")
            if (not comparison_available and comparison.get("absence_confirmed") is not True
                    and _NO_HISTORY_ASSERTION.search(sentence) and not _DENIAL.search(sentence)):
                add("history_absence_not_confirmed", "review", field, "이전 비교가 제공되지 않은 것과 실제 이전 기록이 없는 것은 다릅니다. 기록 부재가 확인되지 않았다면 이번 분석에 비교 자료가 제공되지 않았다고 설명하세요.")
            if _EXACT_TARGET.search(sentence) and not negated:
                add("average_as_exact_target", "review", field, "구간 평균의 차이를 정확한 한 순간의 목표 위치·자세로 바꾸었는지 검토하세요. 목표 순간이나 자세를 직접 관측한 근거가 필요합니다.")
            if any(name in sentence for name in excluded_names) and not negated:
                add("excluded_item_in_text", "review", field, "제외된 항목 이름이 문장에 있습니다. 보류 안내인지 저신뢰 항목의 교정 지시인지 검토하세요.")
            if re.search(r"(?:리듬|템포).{0,12}유지", sentence) and not negated:
                add("tempo_claim_review", "review", field, "자세 점수를 리듬 유지 권고로 확장했는지 실제 시간 근거와 대조하세요.")
            if re.search(r"(?:내내|전\s*구간|모든\s*(?:구간|순간)).{0,35}(?:안정|자연|유지|기울)", sentence) and not negated:
                add("aggregate_to_all_frames", "review", field, "구간 평균을 전 프레임의 상태로 확대했는지 검토하세요.")
            if re.search(r"(?:몸통|가슴).{0,30}(?:세워|세우|수직)|기울지\s*않", sentence) and not negated:
                add("absolute_posture_target", "review", field, "기준 자세도 같은 방향으로 기울었을 수 있습니다. 상대적 차이를 없애야 할 절대 자세로 바꿨는지 검토하세요.")

        for label, key, weight_key in [("종합|전체", "overall_score", None), ("자세", "posture_score", "posture"), (r"손\s*속도|속도", "speed_score", "speed")]:
            value_pattern = rf"(?:{label})(?:\s*점수)?\s*(?:는|가|:|은)?\s*(-?\d+(?:\.\d+)?)\s*점"
            for match in re.finditer(value_pattern, text):
                expected = score_basis.get(key)
                if not _finite(expected) or abs(float(match.group(1)) - expected) > .051:
                    add("score_value_conflict", "review", field, "명시한 점수가 검증된 저장 점수와 일치하지 않거나 근거가 없습니다. 예시·인용 여부도 검토하세요.")
            if weight_key:
                # Decimal points in a preceding component score are not sentence
                # boundaries ("자세 80.4점의 60%" still needs a ratio check).
                for match in re.finditer(rf"(?:{label})(?:[^.!?\n]|\.(?=\d)){{0,35}}?(\d+(?:\.\d+)?)\s*(?:%|퍼센트)", text):
                    weight = (score_basis.get("weights") or {}).get(weight_key)
                    if not score_basis.get("verified_composition") or not _finite(weight) or abs(float(match.group(1)) - 100 * weight) > .001:
                        add("score_formula_conflict", "review", field, "명시한 합산 비율이 검증된 계산 관계와 다릅니다. 다른 모델의 비율을 소급 적용했는지 검토하세요.")
        if re.search(r"부위.{0,12}(?:평균|감점|기여)|최저.{0,20}(?:감점|낮췄)", text):
            if not _NOT_MEASURED.search(text) and not re.search(r"아니|않|없", text):
                add("score_attribution_review", "review", field, "부위 점수를 종합 점수의 평균·감점 기여도로 해석했는지 검토하세요.")

    if schema_valid and not extended:
        for index, part in enumerate(response["parts"]):
            issue_rows = [e for e in evidence.get("observations", [])
                          if e.get("part") == part["key"] and e.get("level") in ("caution", "warning")]
            text = " ".join([part["summary"], *part["keep_points"], *part["improve_points"]])
            phase_names = {str(e.get("phase_name") or e.get("phase") or "") for e in issue_rows}
            # Omitting an adverse phase can be a deliberate single-focus summary;
            # this is a review hint, never a definite omission/accuracy failure.
            if (issue_rows and not part["improve_points"] and re.search(r"비슷|가까|좋|양호|안정|자연", text)
                    and not any(name and name in text for name in phase_names)):
                add("part_adverse_phase_omitted", "review", f"parts[{index}]", "이 부위의 다른 구간에 확인할 차이가 있지만 좋은 구간만 설명합니다. 한 가지 우선순위에 집중한 의도인지, 부위 전체가 양호하다고 오해하게 하는 누락인지 검토하세요.")

    add("semantic_verification_required", "review", "*", "키·개수·JSON 검사는 의미적 정확도를 보장하지 않습니다. 근거 연결, 한국어 해석, 교정·훈련의 적절성은 사람이 검토해야 합니다.")
    blocked = sum(f["severity"] == "block" for f in findings)
    return {
        "policy_version": "coaching-policy-3e-v1",
        "status": "blocked" if blocked else "review_required",
        "schema_valid": schema_valid,
        "blocking_count": blocked,
        "review_count": sum(f["severity"] == "review" for f in findings),
        "findings": findings,
        "auto_publish_allowed": False,
        "semantic_accuracy_verified": False,
        "response_modified": False,
        "limitations": "의미 검사는 휴리스틱이며 오탐·미탐이 가능합니다. 검출이 없다는 이유로 정확성을 승인하지 않습니다.",
    }
