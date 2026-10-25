"""이전 분석 대비 비교 API. 테스트용 SQLite만 사용한다.

핵심: 비교 데이터는 DB(Swing.result)에서 읽으므로 서버 재시작과 무관하게 조회된다.
"""

from datetime import datetime, timezone
import uuid

from api.database import SessionLocal, Swing, User


def _part(key: str, name: str, score, *, available=True, reliability="high") -> dict:
    return {"key": key, "name": name, "available": available, "score": score, "reliability": reliability}


def _result(overall_score, parts: list[dict]) -> dict:
    return {"overall": {"score": overall_score, "group_scores": parts}}


def _phase(key: str, name: str, score, *, available=True, reliability="high") -> dict:
    return {"key": key, "name": name, "available": available, "reliability": reliability, "score": score}


def _joint(key: str, name: str, body_part: str, diff, *, available=True, reliability="high") -> dict:
    return {
        "key": key, "name": name, "body_part": body_part,
        "available": available, "reliability": reliability, "impact": {"diff": diff},
    }


def _rich_result(overall_score, parts, phases=None, joints=None) -> dict:
    r = _result(overall_score, parts)
    if phases is not None:
        r["phases"] = {"phases": phases}
    if joints is not None:
        r["joints"] = joints
    return r


def _swing(owner: str, when: datetime, *, status="done", result=None) -> Swing:
    return Swing(
        analysis_id=uuid.uuid4().hex,
        user_id=owner,
        worker_id="cmp-test",
        created_at=when,
        recorded_at=when,
        status=status,
        result=result,
    )


def _seed(swings: list[Swing], *, user_ids: list[str]) -> None:
    with SessionLocal.begin() as db:
        for uid in user_ids:
            db.add(User(user_id=uid, email=f"{uid}@example.com", nickname=uid, password_hash="x"))
        db.flush()
        db.add_all(swings)


def test_comparison_uses_most_recent_previous_done(mock_client):
    owner = f"cmp-{uuid.uuid4().hex}"
    older = _swing(owner, datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                   result=_result(72.0, [_part("lead_arm", "왼쪽 팔", 60.0)]))
    middle = _swing(owner, datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
                    result=_result(70.0, [_part("lead_arm", "왼쪽 팔", 55.0)]))
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8)]))
    _seed([older, middle, current], user_ids=[owner])

    res = mock_client.get(f"/api/users/{owner}/analyses/{current.analysis_id}/comparison")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_previous"] is True
    # 가장 최근 이전 것(10/1, 70.0)을 쓴다 — 더 오래된 9/20(72.0)이 아니다.
    assert body["previous_analysis_id"] == middle.analysis_id
    assert body["overall_previous_score"] == 70.0
    assert body["overall_delta"] == 7.3
    part = next(p for p in body["parts"] if p["key"] == "lead_arm")
    assert part["previous_score"] == 55.0
    assert part["delta"] == 8.8


def test_comparison_first_swing_has_no_previous(mock_client):
    owner = f"cmp-{uuid.uuid4().hex}"
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8)]))
    _seed([current], user_ids=[owner])

    body = mock_client.get(f"/api/users/{owner}/analyses/{current.analysis_id}/comparison").json()
    assert body["has_previous"] is False
    assert body["previous_analysis_id"] is None
    assert body["parts"] == []


def test_comparison_ignores_non_done_and_other_users(mock_client):
    owner = f"cmp-{uuid.uuid4().hex}"
    other = f"cmp-{uuid.uuid4().hex}"
    # 더 최근이지만 다른 유저 / 실패 / 진행중이라 '직전'으로 안 잡혀야 한다.
    other_recent = _swing(other, datetime(2026, 10, 9, 9, tzinfo=timezone.utc),
                          result=_result(99.0, [_part("lead_arm", "왼쪽 팔", 99.0)]))
    failed = _swing(owner, datetime(2026, 10, 8, 9, tzinfo=timezone.utc),
                    status="failed", result=None)
    queued = _swing(owner, datetime(2026, 10, 7, 9, tzinfo=timezone.utc),
                    status="queued", result=None)
    real_prev = _swing(owner, datetime(2026, 9, 1, 9, tzinfo=timezone.utc),
                       result=_result(65.0, [_part("lead_arm", "왼쪽 팔", 50.0)]))
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8)]))
    _seed([other_recent, failed, queued, real_prev, current], user_ids=[owner, other])

    body = mock_client.get(f"/api/users/{owner}/analyses/{current.analysis_id}/comparison").json()
    assert body["has_previous"] is True
    assert body["previous_analysis_id"] == real_prev.analysis_id  # 9/1, done, 같은 유저
    assert body["overall_previous_score"] == 65.0


def test_comparison_missing_part_in_previous_gives_null(mock_client):
    owner = f"cmp-{uuid.uuid4().hex}"
    prev = _swing(owner, datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                  result=_result(70.0, [_part("lead_arm", "왼쪽 팔", 60.0)]))
    # 현재엔 torso가 추가됨 → 이전엔 없으니 previous_score/delta는 null.
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8),
                                           _part("torso", "몸통", 73.0)]))
    _seed([prev, current], user_ids=[owner])

    body = mock_client.get(f"/api/users/{owner}/analyses/{current.analysis_id}/comparison").json()
    torso = next(p for p in body["parts"] if p["key"] == "torso")
    assert torso["previous_score"] is None
    assert torso["delta"] is None


def test_comparison_endpoint_returns_and_caches_coaching(mock_client, monkeypatch):
    import api.swings as swings

    calls = {"n": 0}
    fake = {
        "overall_summary": "지난 스윙보다 전체적으로 좋아졌어요.",
        "overall_coach": "뒷다리 무릎에 집중해 보세요.",
        "parts": [
            {"key": "lead_arm", "summary": "앞팔이 개선됐어요.",
             "keep_points": ["팔꿈치 각도 유지"], "improve_points": []},
        ],
    }

    def fake_gen(current, previous, **kwargs):
        calls["n"] += 1
        return fake

    # 네트워크 대신 가짜 생성기 + 키가 있는 것처럼 (Settings는 frozen이라 통째 교체).
    from dataclasses import replace

    monkeypatch.setattr(swings, "settings", replace(swings.settings, gemini_api_key="test-key"))
    monkeypatch.setattr(swings, "generate_comparison_coaching", fake_gen)

    owner = f"cmp-{uuid.uuid4().hex}"
    prev = _swing(owner, datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                  result=_result(70.0, [_part("lead_arm", "왼쪽 팔", 60.0)]))
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8)]))
    _seed([prev, current], user_ids=[owner])
    url = f"/api/users/{owner}/analyses/{current.analysis_id}/comparison"

    body1 = mock_client.get(url).json()
    assert body1["coaching"]["overall_summary"] == fake["overall_summary"]
    assert body1["coaching"]["parts"][0]["key"] == "lead_arm"
    assert calls["n"] == 1

    # 두 번째 호출 → 캐시 사용, 생성 함수 재호출 안 함.
    body2 = mock_client.get(url).json()
    assert body2["coaching"]["overall_coach"] == fake["overall_coach"]
    assert calls["n"] == 1


def test_comparison_includes_phase_and_joint_deltas(mock_client):
    owner = f"cmp-{uuid.uuid4().hex}"
    prev = _swing(owner, datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                  result=_rich_result(70.0, [_part("lead_arm", "왼쪽 팔", 60.0)],
                                      phases=[_phase("stride", "스트라이드", 65.0)],
                                      joints=[_joint("lead_elbow_angle", "앞팔 팔꿈치 각도", "lead_arm", 12.0)]))
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_rich_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8)],
                                         phases=[_phase("stride", "스트라이드", 73.0)],
                                         joints=[_joint("lead_elbow_angle", "앞팔 팔꿈치 각도", "lead_arm", 5.0)]))
    _seed([prev, current], user_ids=[owner])

    body = mock_client.get(f"/api/users/{owner}/analyses/{current.analysis_id}/comparison").json()

    # 구간: 65 → 73, delta +8
    ph = next(p for p in body["phases"] if p["key"] == "stride")
    assert ph["previous_score"] == 65.0
    assert ph["current_score"] == 73.0
    assert ph["delta"] == 8.0

    # 관절: 기준과의 차이 12 → 5 → gap_narrowed = 12 − 5 = 7 (프로에 더 가까워짐)
    jt = next(j for j in body["joints"] if j["key"] == "lead_elbow_angle")
    assert jt["previous_diff"] == 12.0
    assert jt["current_diff"] == 5.0
    assert jt["gap_narrowed"] == 7.0
    assert jt["body_part"] == "lead_arm"


def test_comparison_missing_previous_phase_joint_gives_null(mock_client):
    owner = f"cmp-{uuid.uuid4().hex}"
    # 이전엔 구간/관절이 없음 → previous null, delta/gap null.
    prev = _swing(owner, datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                  result=_result(70.0, [_part("lead_arm", "왼쪽 팔", 60.0)]))
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_rich_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8)],
                                         phases=[_phase("stride", "스트라이드", 73.0)],
                                         joints=[_joint("lead_elbow_angle", "앞팔 팔꿈치 각도", "lead_arm", 5.0)]))
    _seed([prev, current], user_ids=[owner])

    body = mock_client.get(f"/api/users/{owner}/analyses/{current.analysis_id}/comparison").json()
    assert body["phases"][0]["previous_score"] is None
    assert body["phases"][0]["delta"] is None
    assert body["joints"][0]["previous_diff"] is None
    assert body["joints"][0]["gap_narrowed"] is None


def test_comparison_no_phases_joints_returns_empty_lists(mock_client):
    # 리포트에 phases/joints가 없으면 빈 리스트(기존 동작 유지).
    owner = f"cmp-{uuid.uuid4().hex}"
    prev = _swing(owner, datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                  result=_result(70.0, [_part("lead_arm", "왼쪽 팔", 60.0)]))
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8)]))
    _seed([prev, current], user_ids=[owner])

    body = mock_client.get(f"/api/users/{owner}/analyses/{current.analysis_id}/comparison").json()
    assert body["phases"] == []
    assert body["joints"] == []


def test_comparison_no_key_returns_null_coaching(mock_client):
    # 기본 테스트 환경은 키가 비어 있다 → coaching None (규칙 기반 폴백).
    owner = f"cmp-{uuid.uuid4().hex}"
    prev = _swing(owner, datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                  result=_result(70.0, [_part("lead_arm", "왼쪽 팔", 60.0)]))
    current = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                     result=_result(77.3, [_part("lead_arm", "왼쪽 팔", 63.8)]))
    _seed([prev, current], user_ids=[owner])

    body = mock_client.get(f"/api/users/{owner}/analyses/{current.analysis_id}/comparison").json()
    assert body["has_previous"] is True
    assert body["coaching"] is None


def test_comparison_404_and_409(mock_client):
    owner = f"cmp-{uuid.uuid4().hex}"
    processing = _swing(owner, datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                        status="processing", result=None)
    _seed([processing], user_ids=[owner])

    # 없는 유저
    assert mock_client.get(f"/api/users/nobody/analyses/{processing.analysis_id}/comparison").status_code == 404
    # 없는 분석
    assert mock_client.get(f"/api/users/{owner}/analyses/deadbeef/comparison").status_code == 404
    # 아직 완료 안 됨
    assert mock_client.get(f"/api/users/{owner}/analyses/{processing.analysis_id}/comparison").status_code == 409
