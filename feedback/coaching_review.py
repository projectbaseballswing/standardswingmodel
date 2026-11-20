"""Private review lifecycle for generated coaching; no I/O or network.

The envelope lives in Swing.result JSON, but only an allowlisted public status
and a hash-bound, explicitly approved candidate may leave the backend. Approval
is a trusted-operator Python function, not a user-facing authorization API.
Hashes detect stale/tampered records; they are not a substitute for DB access
control or a cryptographic reviewer identity.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

PRIVATE_KEY = "_coaching_review"
REPORT_FIELDS = ("model_version", "overall", "joints", "phases", "speed", "phase_frames",
                 "handedness", "reference_id")
STATUSES = {"approved", "review_required", "blocked", "generation_failed"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def report_fingerprint(report: dict) -> str | None:
    """Bind approval to evidence; malformed/nonfinite evidence cannot be approved."""
    if not isinstance(report, dict):
        return None
    try:
        return digest({k: report[k] for k in REPORT_FIELDS if k in report})
    except (TypeError, ValueError):
        return None


def context_for(analysis_id: str, user_id: str | None, *,
                previous_analysis_id: str | None = None, previous: dict | None = None) -> dict:
    result = {"analysis_id": analysis_id, "user_id": user_id}
    if previous_analysis_id is not None:
        result.update(previous_analysis_id=previous_analysis_id,
                      previous_report_sha256=report_fingerprint(previous or {}))
    return result


def _validate(report, candidate, scope, previous=None):
    from feedback.llm_coach import build_llm_input, build_comparison_input
    from feedback.coaching_policy import validate_coaching_output
    payload = (build_comparison_input(report, previous, scope=scope) if previous is not None
               else build_llm_input(report, scope=scope))
    return validate_coaching_output(candidate, payload, scope=scope)


def capture_review(report: dict, sink: dict, *, context: dict, scope="overall",
                   previous: dict | None = None, failure_reason="generation_failed") -> dict:
    """Do not trust a returned Coaching dict or automatic 'approved' flag."""
    sink = sink if isinstance(sink, dict) else {}
    candidate = sink.get("candidate")
    validation = {}
    report_hash = report_fingerprint(report)
    if isinstance(candidate, dict):
        try:
            # A non-JSON candidate must not poison database JSON serialization.
            candidate_hash = digest(candidate)
        except (TypeError, ValueError):
            candidate = None
            candidate_hash = None
            validation = {"status": "blocked", "reason": "non_json_candidate"}
            state = "blocked"
        else:
            try:
                if report_hash is None or (previous is not None and report_fingerprint(previous) is None):
                    raise ValueError("Invalid review evidence")
                validation = _validate(report, candidate, scope, previous)
                state = "blocked" if validation.get("status") == "blocked" else "review_required"
            except Exception:
                # Failed validation withholds coaching, never fails a completed score job.
                validation = {"status": "blocked", "reason": "invalid_candidate_or_evidence"}
                state = "blocked"
    else:
        candidate = None
        state, candidate_hash = "generation_failed", None
        validation = {"status": "generation_failed", "reason": failure_reason}
    return {
        "version": "coaching-review-v1", "status": state, "scope": scope,
        "context": deepcopy(context), "candidate": deepcopy(candidate),
        "candidate_sha256": candidate_hash, "report_sha256": report_hash,
        "validation": validation, "policy_version": validation.get("policy_version"),
        "created_at": datetime.now(timezone.utc).isoformat(), "approval": None,
    }


def approve_review(report: dict, envelope: dict, *, context: dict, reviewer_id: str,
                   note: str, expected_candidate_sha256: str,
                   previous: dict | None = None) -> dict:
    """Trusted operator only: validate a reviewed exact revision, then persist it.

    This function grants no role and is intentionally not exposed as an HTTP
    endpoint. The calling operator must already have authorized DB write access.
    The caller persists the returned envelope in a locked transaction and checks
    that the stored candidate still matches expected_candidate_sha256.
    """
    if not reviewer_id.strip() or not note.strip():
        raise ValueError("Reviewer and review note are required")
    candidate = envelope.get("candidate")
    if envelope.get("status") != "review_required" or not isinstance(candidate, dict):
        raise ValueError("Only a pending candidate can be approved")
    report_hash = report_fingerprint(report)
    if report_hash is None or (previous is not None and report_fingerprint(previous) is None):
        raise ValueError("Invalid review evidence")
    if envelope.get("context") != context or envelope.get("report_sha256") != report_hash:
        raise ValueError("Review context or report changed")
    if digest(candidate) != expected_candidate_sha256 or envelope.get("candidate_sha256") != expected_candidate_sha256:
        raise ValueError("Candidate revision changed")
    scope = envelope.get("scope")
    if scope not in ("overall", "full"):
        raise ValueError("Unknown review scope")
    validation = _validate(report, candidate, scope, previous)
    if validation.get("status") == "blocked":
        raise ValueError("A structurally blocked candidate cannot be approved")
    result = deepcopy(envelope)
    result.update(status="approved", validation=validation, policy_version=validation.get("policy_version"))
    result["approval"] = {
        "reviewer_id": reviewer_id.strip(), "note": note.strip(),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "candidate_sha256": expected_candidate_sha256,
        "report_sha256": result["report_sha256"], "context": deepcopy(context),
        "scope": scope, "policy_version": result["policy_version"],
    }
    return result


def capture_extended_review(report: dict, envelope: dict, sink: dict, *, context: dict) -> dict:
    """Validate the raw extension before merging; changed text always loses approval."""
    from feedback.llm_coach import build_llm_input
    from feedback.coaching_policy import validate_coaching_output

    extension = sink.get("candidate") if isinstance(sink, dict) else None
    original = envelope.get("candidate") if isinstance(envelope, dict) else None
    if not isinstance(extension, dict) or not isinstance(original, dict):
        return {**deepcopy(envelope), "extended_status": "generation_failed"}
    try:
        digest(extension)
        extension_validation = validate_coaching_output(
            extension, build_llm_input(report, scope="full"), scope="full", extended=True,
        )
    except Exception:
        result = deepcopy(envelope)
        result.update(status="blocked", approval=None, extended_status="blocked",
                      validation={"status": "blocked", "reason": "invalid_extended_candidate_or_evidence"})
        return result
    merged = deepcopy(original)
    merged.update(joints=extension.get("joints", []), phases=extension.get("phases", []))
    result = capture_review(report, {"candidate": merged}, context=context, scope="full")
    result.update(extended_candidate=deepcopy(extension), extended_validation=extension_validation,
                  extended_status="done")
    if extension_validation.get("status") == "blocked":
        result.update(status="blocked", extended_status="blocked",
                      validation={"status": "blocked", "reason": "extended_policy_blocked",
                                  "policy_version": extension_validation.get("policy_version")})
    return result


def _status(status: str, reason: str, *, allowed=False) -> dict:
    return {"status": status, "source": "openai" if allowed else "rules",
            "display_allowed": allowed, "reason": reason}


def public_coaching(report: dict, envelope: Any, *, context: dict,
                    previous: dict | None = None, legacy_present=False) -> tuple[dict | None, dict]:
    if not isinstance(envelope, dict):
        return None, _status("review_required" if legacy_present else "generation_failed",
                             "legacy_unreviewed" if legacy_present else "not_generated")
    state = envelope.get("status")
    if not isinstance(state, str) or state not in STATUSES:
        return None, _status("blocked", "invalid_review_state")
    report_hash = report_fingerprint(report)
    if report_hash is None or (previous is not None and report_fingerprint(previous) is None):
        return None, _status("blocked", "invalid_review_evidence")
    if envelope.get("context") != context or envelope.get("report_sha256") != report_hash:
        return None, _status("review_required", "stale_review_context")
    if state == "generation_failed":
        validation = envelope.get("validation")
        reason = validation.get("reason") if isinstance(validation, dict) else None
        # Never expose provider details or infer an actual failure from old metadata.
        if not isinstance(reason, str) or reason not in (
            "generation_disabled", "not_configured", "not_generated", "generation_failed",
        ):
            reason = "not_generated"
        return None, _status(state, reason)
    candidate = envelope.get("candidate")
    if not isinstance(candidate, dict):
        return None, _status("blocked", "missing_candidate")
    try:
        current_hash = digest(candidate)
    except (ValueError, TypeError):
        return None, _status("blocked", "invalid_candidate")
    if current_hash != envelope.get("candidate_sha256"):
        return None, _status("blocked", "candidate_changed")
    if state != "approved":
        return None, _status(state, "policy_blocked" if state == "blocked" else "awaiting_human_review")
    approval = envelope.get("approval")
    expected = {"candidate_sha256": current_hash, "report_sha256": envelope["report_sha256"],
                "context": context, "scope": envelope.get("scope"), "policy_version": envelope.get("policy_version")}
    if (not isinstance(approval, dict) or not approval.get("reviewer_id") or not approval.get("reviewed_at")
            or not approval.get("note") or any(approval.get(k) != v for k, v in expected.items())):
        return None, _status("blocked", "missing_or_stale_approval")
    try:
        check = _validate(report, candidate, envelope["scope"], previous)
    except Exception:
        return None, _status("blocked", "invalid_candidate_or_evidence")
    if check.get("status") == "blocked":
        return None, _status("blocked", "policy_blocked")
    if check.get("policy_version") != envelope.get("policy_version"):
        return None, _status("review_required", "policy_version_changed")
    return deepcopy(candidate), _status("approved", "human_review_completed", allowed=True)


def public_result(report: Any, *, context: dict) -> Any:
    if not isinstance(report, dict):
        return report
    public = deepcopy(report)
    envelope = public.pop(PRIVATE_KEY, None)
    # Comparison candidates have their own authenticated endpoint/context.
    public.pop("comparison", None)
    candidate, metadata = public_coaching(report, envelope, context=context,
                                         legacy_present=isinstance(report.get("coaching"), dict))
    public["coaching"] = candidate
    public["coaching_review"] = metadata
    return public
