"""Offline replay of existing 3-A reports and saved 3-B/3-D responses.

No credentials, model inference, DB, or OpenAI imports/calls. Experiment files
stay local; the script and summary documentation are suitable for a later PR.
"""
from __future__ import annotations

import argparse
import ast
import base64
import csv
import hashlib
import html
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from feedback.llm_coach import build_llm_input, SYSTEM_INSTRUCTION
from feedback.coaching_compact import compact_coaching_input, expand_coaching_input
from feedback.coaching_policy import validate_coaching_output


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def serialized(value, *, compact=False):
    options = {"separators": (",", ":")} if compact else {}
    return json.dumps(value, ensure_ascii=False, allow_nan=False, **options)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", "-C", str(cwd), *args])


def public_schema_ast(source):
    names = {"PartCoaching", "CoachFeedback", "Coaching", "JointCoaching",
             "PhaseCoaching", "CoachingFull", "ExtendedCoaching"}
    return {n.name: ast.dump(n, include_attributes=False)
            for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name in names}


def table(headers, rows):
    return "<table><thead><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>" for row in rows) + "</tbody></table>"


def disclosure(title, value):
    return f"<details><summary>{html.escape(title)}</summary><pre>{html.escape(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-parent", type=Path, default=ROOT.parent)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/feedback-stage3e")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parent = args.workspace_parent
    stage_a = parent / "swing-feedback-stage3a/.local/feedback-stage3a"
    run_a = parent / "swing-feedback-stage3b/.local/feedback-stage3b/current-run"
    run_b = parent / "swing-feedback-stage3d/.local/feedback-stage3d/b-run"
    reports = read(stage_a / "inputs.json")
    cases = []
    input_artifacts = {}
    for case in reports:
        report = case["body"]["result"]
        before = serialized(report)
        full_evidence = build_llm_input(report, scope="full")
        evidence = build_llm_input(report, scope="overall")
        compact = compact_coaching_input(evidence)
        full_compact = compact_coaching_input(full_evidence)
        restored = expand_coaching_input(compact)
        unchanged = before == serialized(report)
        exact = restored == evidence and expand_coaching_input(full_compact) == full_evidence
        assert unchanged and exact, case["id"]
        assert all(x["reliability"] in ("high", "medium") and x["phase_reliability"] in ("high", "medium") for x in evidence["observations"])
        joints = [j for p in evidence["parts"] for j in p["features"]]
        row = {"case": case["id"], "score": report["overall"].get("score"),
               "canonical_bytes": len(serialized(evidence).encode()),
               "compact_bytes": len(serialized(compact, compact=True).encode()),
               "observations": len(evidence["observations"]), "joints": len(joints),
               "rom": sum(j["range_of_motion"] is not None for j in joints),
               "excluded": len(evidence["excluded"]),
               "score_basis": evidence["score_basis"]["explanation_status"],
               "input_unchanged": unchanged, "roundtrip_exact": exact,
               "report_sha256": sha(before.encode())}
        row["byte_reduction_pct"] = round(100 * (1 - row["compact_bytes"] / row["canonical_bytes"]), 2)
        cases.append(row)
        input_artifacts[case["id"]] = {"canonical": evidence, "compact": compact}
    fixture = read(ROOT / "api/fixtures/analysis_sample.json")
    candidate_input = input_artifacts["sample"]["canonical"]
    assert candidate_input == build_llm_input(fixture)
    old_input = read(run_b / "candidate-input.json")
    old_prompt = (run_b / "system-prompt.txt").read_text(encoding="utf-8")
    old_wire = serialized(old_input)
    new_wire = serialized(input_artifacts["sample"]["compact"], compact=True)
    canonical_wire = serialized(candidate_input)
    compression = {
        "stage3d_actual_prompt_tokens": read(run_b / "evidence.json")["usage"]["prompt_tokens"],
        "stage3e_actual_prompt_tokens": None,
        "token_count_note": "추가 호출 없음. 토크나이저 미설치로 새 토큰 수/요금 절감률은 측정하지 않음. UTF-8 바이트 및 문자 수만 비교.",
        "stage3d_payload_bytes": len(old_wire.encode()),
        "stage3e_expanded_payload_bytes": len(canonical_wire.encode()),
        "stage3e_compact_payload_bytes": len(new_wire.encode()),
        "stage3d_payload_characters": len(old_wire), "stage3e_compact_characters": len(new_wire),
        "stage3d_system_prompt_bytes": len(old_prompt.encode()), "stage3e_system_prompt_bytes": len(SYSTEM_INSTRUCTION.encode()),
        "payload_reduction_vs_stage3d_pct": round(100 * (1 - len(new_wire.encode()) / len(old_wire.encode())), 2),
        "system_plus_payload_reduction_pct": round(100 * (1 - len((SYSTEM_INSTRUCTION + new_wire).encode()) / len((old_prompt + old_wire).encode())), 2),
        "same_evidence_roundtrip": True,
        "restored_observation_ids": sorted({o["evidence_id"] for o in candidate_input["observations"]} - {o["evidence_id"] for o in old_input["observations"]}),
        "rom_before": sum(j.get("range_of_motion") is not None for p in old_input["parts"] for j in p["features"]),
        "rom_after": cases[0]["rom"],
        "required_fields_preserved": ["score_basis", "priority_candidates", "strengths", "observations", "tempo_evidence", "excluded", "allowed", "not_measured", "comparison", "rotation_issues", "parts"],
        "serialization_note": "3-D의 실제 json.dumps 기본 구분자와 3-E 전송용 공백 제거 구분자로 측정. 시스템+입력 비교는 JSON schema/API wrapper를 포함하지 않음.",
    }
    audits = {}
    responses = {}
    for label, path in (("A", run_a), ("B", run_b)):
        response = read(path / "coaching.json")
        responses[label] = response
        audits[label] = validate_coaching_output(response, candidate_input, scope="overall")
        assert audits[label]["auto_publish_allowed"] is False
    protected = ["feedback/compare_v2.py", "feedback/swing_features.py", "api/fixtures/analysis_sample.json",
                 "api/auth.py", "api/storage.py", "api/pose3d.py", "frontend/lib/router.dart", "frontend/lib/screens/swing_trend_screen.dart"]
    invariance = {}
    for path in protected:
        if not (ROOT / path).exists():
            continue
        head = git("show", f"HEAD:{path}").replace(b"\r\n", b"\n")
        local = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        invariance[path] = head == local
    assert all(invariance.values())
    old_schemas = public_schema_ast(git("show", "HEAD:feedback/llm_coach.py").decode("utf-8"))
    new_schemas = public_schema_ast((ROOT / "feedback/llm_coach.py").read_text(encoding="utf-8-sig"))
    assert old_schemas == new_schemas and old_schemas
    preservation = {}
    snapshot = out / "preservation-before.json"
    if snapshot.exists():
        for key, before in read(snapshot).items():
            repo = parent / f"swing-feedback-stage{key}"
            changed = [f for f, digest in before["files"].items() if not (repo / f).exists() or sha((repo / f).read_bytes()) != digest]
            preservation[key] = {"files_checked": len(before["files"]), "files_changed": changed,
                                 "head_unchanged": git("rev-parse", "HEAD", cwd=repo).decode().strip() == before["head"],
                                 "status_unchanged": git("status", "--short", cwd=repo).decode("utf-8") == before["status"]}
            assert not changed and preservation[key]["head_unchanged"] and preservation[key]["status_unchanged"], key
    results = {"openai_requests_this_stage": 0, "cases": cases, "compression": compression,
               "audits": audits, "source_invariance": invariance, "public_coaching_schemas_unchanged": sorted(old_schemas), "preservation": preservation}
    (out / "replay-validation.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "input-comparison.json").write_text(json.dumps(input_artifacts, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "compression.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(cases[0])); writer.writeheader(); writer.writerows(cases)
    body = "<h1>3-E · 근거 보존과 표시 승인 검증</h1><p class='notice'>이번 단계 OpenAI 호출 0회 · 운영 DB/Storage 접근 없음 · A/B는 저장된 실제 GPT 응답. 새 압축 프롬프트의 생성 품질은 아직 미검증입니다.</p>"
    body += "<h2>6개 기존 리포트 재생</h2>" + table(["리포트", "점수", "근거 수", "ROM", "입력 bytes", "압축 bytes", "절감", "근거 복원"], [[x[k] for k in ("case", "score", "observations", "rom", "canonical_bytes", "compact_bytes", "byte_reduction_pct", "roundtrip_exact")] for x in cases])
    body += "<p>순위는 신뢰 가능한 구간의 표준화 차이 |z|를 사용한 ‘우선 확인 후보’입니다. 점수 기여도 또는 교정 효과의 순위가 아닙니다. 6개 저장 리포트의 숫자·피처가 바뀌지 않았으며 원본 추론은 다시 실행하지 않았습니다.</p>"
    body += "<h2>입력 압축</h2>" + disclosure("크기와 보존 결과", compression)
    body += "<p>중복 관절/구간을 한 번 저장하고 참조합니다. 각 구간의 사용자/기준값, 신뢰도, 제외 이유, 좋은 구간, ROM, 비교 가능 여부는 복원 후 원본 구조와 동일합니다. 실제 GPT가 참조표를 잘 읽는지는 후속 승인된 생성 평가가 필요합니다.</p>"
    body += "<h2>기존 실제 응답 재검사</h2><p>검토 항목 수는 검사 범위와 임계값의 영향도 받습니다. A/B 정확도 점수 또는 사용자의 평가가 아닙니다.</p><div class='columns'>"
    for label in ("A", "B"):
        audit = audits[label]
        body += f"<section><h3>{label} · 기존 실제 GPT</h3><p>{audit['status']} · 차단 {audit['blocking_count']} / 검토 {audit['review_count']}</p>"
        body += disclosure("원문 (수정하지 않음)", responses[label]) + disclosure("3-E 재검사", audit) + "</section>"
    body += "</div><h2>3-D 문제의 처리 범위</h2>" + table(["문제", "3-E 변경", "남은 확인"], [
        ["구간 평균을 순간 목표로 지시", "프롬프트 제한 + average_as_exact_target 검토", "문맥상 실제 과잉 지시인지 사람 검토"],
        ["이전 기록 없음 단정", "비교자료 미제공과 기록 부재 분리", "과거 조회 범위와 실제 입력 확인"],
        ["정규화 수치 노출", "일반 문구에서 제외하고 상세 측정 화면으로 분리", "새 GPT 문장의 이해도"],
        ["좋은 부위 점수로 문제 구간 누락", "구간별 근거 유지 + 누락 검토 + UI first-check", "강점·문제점의 균형"],
        ["diff/z 부호", "구간 평균차와 시점별 표준화 차이는 별개로 취급", "원본 관절 추정 정확도 별도"],
        ["ROM 누락", "user/reference/diff 계약으로 보존", "ROM만으로 진단하지 않음"],
        ["부정문 오탐", "개념·절별 부정문 검사", "한국어 복합 문맥 오탐·미탐 가능"],
    ])
    replay_path = out / "flutter-replay.json"
    if replay_path.exists():
        body += "<h2>현재 Flutter 규칙 기반 문구 (실제 입력 재생)</h2>" + disclosure("6개 리포트 UI 모델", read(replay_path))
    body += "<h2>서비스 표시 흐름</h2><p>생성 → 비공개 후보/검사 저장 → 사람 검토 → 정확한 후보·리포트·컨텍스트·정책 버전 승인 → 표시. 차단·미승인·실패·기존 무검토 응답은 coaching=null과 공개 상태만 반환하며 규칙 안내를 표시합니다. 비교 GET은 새 GPT를 호출하지 않습니다.</p>"
    body += "<p>승인은 인증된 운영자 도구/권한과 트랜잭션 저장을 붙이기 전에는 서비스에서 실행하지 않습니다. 이 단계에는 관리 API를 공개하지 않았습니다. 앱 검증의 approved 사례는 합성 테스트 문구이며 실제 B를 승인한 것이 아닙니다.</p>"
    browser_file = out / "app/browser-validation.json"
    if browser_file.exists():
        browser = read(browser_file)
        checks = browser.get("checks", [])
        body += f"<h2>실제 Chrome 격리 앱 검증</h2><p>{html.escape(browser.get('status', 'unknown'))} · {sum(c.get('passed') is True for c in checks)}/{len(checks)} 항목. 실제 FastAPI + SQLite + 임시 LocalPrivateStorage. 합성 리포트/3D를 사용하며 운영 데이터나 새 GPT 생성은 사용하지 않았습니다.</p>"
        body += "<p><a href='http://127.0.0.1:8990/'>격리 앱 열기</a> · 로그인, 승인/폴백, 구간/관절, 추이, 삭제 실패/재시도, 삭제 후 피드백·3D 유지와 재로그인을 확인합니다.</p>" + disclosure("Chrome 확인 항목", checks)
        body += "<div class='columns'>"
        for name, label in [("04-approved-synthetic-coaching.png", "승인 표시 분기 · 합성 문구"), ("15-pending-review-card.png", "실제 B 미승인 · 규칙 안내")]:
            shot = out / "app/screenshots" / name
            if shot.exists():
                data = base64.b64encode(shot.read_bytes()).decode("ascii")
                body += f"<section><h3>{label}</h3><img alt='{label}' style='max-width:100%;max-height:800px' src='data:image/png;base64,{data}'></section>"
        body += "</div>"
    body += disclosure("코드·기존 작업 보존", {"source": invariance, "worktrees": preservation, "schemas": sorted(old_schemas)})
    body += "<h2>다음 승인 전 확인</h2><ul><li>압축 입력으로 실제 생성 및 독립 코치/사용자 평가</li><li>관리자 인증·승인 이력·행 잠금/버전 검사를 갖춘 검토 운영 절차</li><li>운영 환경 이식은 별도 승인 후. Android 실기기와 실제 모델 업로드는 이번 검증 범위 밖</li></ul>"
    page = "<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>StandardSwing 3-E</title><style>body{font:16px/1.7 system-ui,sans-serif;margin:0 auto;padding:28px;max-width:1200px;color:#18333b;background:#f4f8fa}h1,h2,h3{line-height:1.4}section,details{background:white;border:1px solid #cfdee2;border-radius:10px;padding:16px;margin:12px 0}summary{cursor:pointer;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}table{display:block;overflow:auto;border-collapse:collapse;background:white;width:100%}td,th{padding:10px;border:1px solid #dce4e8;text-align:left;vertical-align:top}.notice{background:#dcf2ee;padding:16px;border-radius:8px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:750px){.columns{display:block}body{padding:16px}}</style><body>" + body + "</body></html>"
    (out / "index.html").write_text(page, encoding="utf-8")
    print(json.dumps({"cases": len(cases), "roundtrip": all(x["roundtrip_exact"] for x in cases), "compression": compression, "audits": {k: {f: v[f] for f in ("status", "blocking_count", "review_count")} for k, v in audits.items()}, "preserved_worktrees": list(preservation)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
