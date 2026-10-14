"""월별 스윙 기록 목록 API. 테스트용 SQLite만 사용한다."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from api.database import SessionLocal, Swing, User


def _add_user_and_swings(*, other_user=False):
    owner = f"list-{uuid.uuid4().hex}"
    foreign = f"list-{uuid.uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(User(user_id=owner, email=f"{owner}@example.com", nickname=owner,
                    password_hash="not-used-in-list-test"))
        if other_user:
            db.add(User(user_id=foreign, email=f"{foreign}@example.com", nickname=foreign,
                        password_hash="not-used-in-list-test"))
        db.flush()
        swings = [
            Swing(analysis_id=uuid.uuid4().hex, user_id=owner, worker_id="list-test",
                  created_at=datetime(2026, 9, 30, 15, 32, tzinfo=timezone.utc),
                  recorded_at=datetime(2026, 9, 30, 15, 30, tzinfo=timezone.utc),
                  status="done", result={"overall": {"score": 77.3}},
                  video_storage_path="swings/example/original.mp4", storage_bucket="swing-videos"),
            Swing(analysis_id=uuid.uuid4().hex, user_id=owner, worker_id="list-test",
                  created_at=datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc),
                  recorded_at=datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc),
                  status="queued", result=None),
            Swing(analysis_id=uuid.uuid4().hex, user_id=owner, worker_id="list-test",
                  created_at=datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc),
                  status="failed", result={"overall": {"score": 99.0}}),
            Swing(analysis_id=uuid.uuid4().hex, user_id=owner, worker_id="list-test",
                  created_at=datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
                  recorded_at=datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc),
                  status="done", result={"overall": {"score": 72}}),
        ]
        if other_user:
            swings.append(Swing(analysis_id=uuid.uuid4().hex, user_id=foreign, worker_id="list-test",
                                created_at=datetime(2026, 10, 10, 10, tzinfo=timezone.utc),
                                recorded_at=datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                                status="done", result={"overall": {"score": 33}}))
        db.add_all(swings)
    return owner, foreign, swings


def test_list_user_swings_filters_month_sorts_and_omits_private_metadata(mock_client):
    owner, foreign, swings = _add_user_and_swings(other_user=True)
    response = mock_client.get(f"/api/users/{owner}/swings", params={"year": 2026, "month": 10})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == owner
    assert body["year_month"] == "2026-10"
    assert body["count"] == 3  # 9/30 15:30 UTC = 10/1 00:30 KST
    assert [item["analysis_id"] for item in body["items"]] == [
        swings[2].analysis_id, swings[1].analysis_id, swings[0].analysis_id,
    ]
    assert [item["score"] for item in body["items"]] == [None, None, 77.3]
    assert body["items"][0]["recorded_at"].startswith("2026-10-20T13:00:00")
    assert all(item["thumbnail_url"] is None for item in body["items"])
    assert all("video_storage_path" not in item and "result" not in item for item in body["items"])
    assert swings[4].analysis_id not in [item["analysis_id"] for item in body["items"]]

    september = mock_client.get(f"/api/users/{owner}/swings?year=2026&month=9").json()
    assert september["count"] == 1
    assert september["items"][0]["analysis_id"] == swings[3].analysis_id


def test_list_all_records_and_empty_month_and_unknown_user(mock_client):
    owner, _, swings = _add_user_and_swings(other_user=True)
    result = mock_client.get(f"/api/users/{owner}/swings").json()
    assert result["count"] == 4 and result["year_month"] is None
    assert [item["analysis_id"] for item in result["items"]] == [
        swings[2].analysis_id, swings[1].analysis_id, swings[0].analysis_id, swings[3].analysis_id,
    ]
    empty = mock_client.get(f"/api/users/{owner}/swings", params={"year": 2027, "month": 1})
    assert empty.status_code == 200 and empty.json()["items"] == [] and empty.json()["count"] == 0
    unknown = mock_client.get("/api/users/not-a-real-user/swings")
    assert unknown.status_code == 404


def test_list_month_validation_and_offset(mock_client):
    owner, _, swings = _add_user_and_swings()
    for params in ({"year": 2026}, {"month": 10}, {"year": 100, "month": 10}, {"year": 2026, "month": 13},
                   {"year": 2026, "month": 0}, {"year": 2026, "month": 10, "tz_offset_minutes": 2000}):
        response = mock_client.get(f"/api/users/{owner}/swings", params=params)
        assert response.status_code == 422, (params, response.text)
    utc = mock_client.get(f"/api/users/{owner}/swings",
                          params={"year": 2026, "month": 9, "tz_offset_minutes": 0}).json()
    # KST의 10/1 00:30은 UTC의 9/30이므로 UTC 달력에서는 9월에 포함된다.
    assert utc["count"] == 2
    assert swings[0].analysis_id in {item["analysis_id"] for item in utc["items"]}


def _add_empty_user():
    owner = f"list-{uuid.uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(User(user_id=owner, email=f"{owner}@example.com", nickname=owner,
                    password_hash="not-used-in-list-test"))
    return owner


def test_user_without_swings_returns_empty_list(mock_client):
    owner = _add_empty_user()
    response = mock_client.get(f"/api/users/{owner}/swings")
    assert response.status_code == 200
    assert response.json() == {"user_id": owner, "year_month": None, "count": 0, "items": []}


@pytest.mark.parametrize("year,month,next_year,next_month", [
    (2026, 10, 2026, 11), (2026, 12, 2027, 1), (2024, 2, 2024, 3),
])
def test_month_boundaries_include_start_and_exclude_next_month(
    mock_client, year, month, next_year, next_month,
):
    owner = _add_empty_user()
    kst = timezone(timedelta(hours=9))
    start = datetime(year, month, 1, tzinfo=kst).astimezone(timezone.utc)
    end = datetime(next_year, next_month, 1, tzinfo=kst).astimezone(timezone.utc)
    timestamps = [start - timedelta(microseconds=1), start, end - timedelta(microseconds=1), end]
    ids = [uuid.uuid4().hex for _ in timestamps]
    with SessionLocal.begin() as db:
        for analysis_id, timestamp in zip(ids, timestamps):
            db.add(Swing(analysis_id=analysis_id, user_id=owner, worker_id="list-test",
                         recorded_at=timestamp, created_at=timestamp, status="done"))
    response = mock_client.get(f"/api/users/{owner}/swings", params={"year": year, "month": month})
    assert response.status_code == 200
    assert [item["analysis_id"] for item in response.json()["items"]] == [ids[2], ids[1]]
    assert all(datetime.fromisoformat(item["recorded_at"]).utcoffset() == timedelta(0)
               for item in response.json()["items"])


@pytest.mark.parametrize("status,result,expected", [
    ("queued", {"overall": {"score": 99}}, None),
    ("processing", {"overall": {"score": 99}}, None),
    ("failed", {"overall": {"score": 99}}, None),
    ("done", None, None),
    ("done", {}, None),
    ("done", {"overall": None}, None),
    ("done", {"overall": {}}, None),
    ("done", {"overall": {"score": None}}, None),
    ("done", {"overall": {"score": True}}, None),
    ("done", {"overall": {"score": "77.3"}}, None),
    ("done", {"overall": {"score": 0}}, 0.0),
    ("done", {"overall": {"score": 77.3}}, 77.3),
])
def test_score_only_comes_from_completed_numeric_result(mock_client, status, result, expected):
    owner = _add_empty_user()
    with SessionLocal.begin() as db:
        db.add(Swing(analysis_id=uuid.uuid4().hex, user_id=owner, worker_id="list-test",
                     status=status, result=result))
    response = mock_client.get(f"/api/users/{owner}/swings")
    assert response.status_code == 200
    item, = response.json()["items"]
    assert item["status"] == status
    assert item["score"] == expected
    assert item["thumbnail_url"] is None
    assert set(item) == {"analysis_id", "recorded_at", "status", "score", "thumbnail_url"}


def test_swing_listing_is_registered_in_swagger(mock_client):
    assert mock_client.get("/docs").status_code == 200
    response = mock_client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    operation = spec["paths"]["/api/users/{user_id}/swings"]["get"]
    assert operation["tags"] == ["swings"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "user_id", "year", "month", "tz_offset_minutes",
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SwingListResponse",
    }
    assert "인증 수단이 아니다" in operation["description"]
