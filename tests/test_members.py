import uuid

import pytest
from sqlalchemy import select

from api.database import SessionLocal, User
from api.security import verify_password


def member():
    unique = uuid.uuid4().hex
    return {"id": unique, "email": f"{unique}@example.com", "nickname": unique, "password": "member-password"}


def test_member_contract_and_persistence(mock_client):
    body = member()
    result = mock_client.post("/api/register", json=body)
    assert result.status_code == 200
    assert result.json() == {"id-uniqueness": 1, "nickname-uniqueness": 1, "registered": True}
    with SessionLocal() as db:
        row = db.get(User, body["id"])
        assert row is not None and row.created_at is not None
        assert row.password_hash != body["password"]
        assert verify_password(body["password"], row.password_hash)
    result = mock_client.post("/api/login", json={"id": body["id"], "password": body["password"]})
    assert result.status_code == 200
    assert result.json() == {"success": True, "user": body["id"]}
    result = mock_client.post("/api/me", json={"user": body["id"]})
    assert result.json() == {"id": body["id"], "email": body["email"]}
    assert mock_client.get("/api/check-email", params={"email": body["email"]}).json() == {"email-uniqueness": 0}


@pytest.mark.parametrize("include_email", [False, True])
def test_registration_rejects_legacy_email_key(mock_client, include_email):
    body = member()
    body["e-mail"] = body["email"]
    if not include_email:
        del body["email"]
    assert mock_client.post("/api/register", json=body).status_code == 422
    with SessionLocal() as db:
        assert db.get(User, body["id"]) is None


@pytest.mark.parametrize("email_key", ["email", "e-mail"])
def test_login_rejects_email_fields(mock_client, email_key):
    body = member()
    assert mock_client.post("/api/register", json=body).json()["registered"] is True
    request = {email_key: body["email"], "password": body["password"]}
    assert mock_client.post("/api/login", json=request).status_code == 422
    assert mock_client.post("/api/login", json={**request, "id": body["id"]}).status_code == 422


@pytest.mark.parametrize("duplicate", ["id", "email", "nickname"])
def test_duplicate_member_returns_existing_schema(mock_client, duplicate):
    first, second = member(), member()
    assert mock_client.post("/api/register", json=first).json()["registered"] is True
    second[duplicate] = first[duplicate]
    result = mock_client.post("/api/register", json=second)
    assert result.status_code == 200
    assert result.json() == {"id-uniqueness": int(duplicate != "id"),
                             "nickname-uniqueness": int(duplicate != "nickname"), "registered": False}
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == second["email"])) is None or duplicate == "email"


def test_login_errors_and_openapi(mock_client):
    body = member()
    mock_client.post("/api/register", json=body)
    for request in ({"id": body["id"], "password": "wrong"},
                    {"id": "absent-user", "password": "wrong"},
                    {"id": body["id"], "password": "x" * 73},
                    {"id": "' OR 1=1 --", "password": body["password"]}):
        assert mock_client.post("/api/login", json=request).status_code == 401
    for request in ({"password": "wrong"}, {"id": body["id"]},
                    {"id": None, "password": body["password"]}):
        assert mock_client.post("/api/login", json=request).status_code == 422
    assert mock_client.post("/api/me", json={"user": "absent-user"}).status_code == 404
    schemas = mock_client.get("/openapi.json").json()["components"]["schemas"]
    for name, fields in (("RegisterRequest", {"id", "password", "email", "nickname"}),
                         ("LoginRequest", {"id", "password"})):
        assert set(schemas[name]["properties"]) == fields
        assert set(schemas[name]["required"]) == fields
        assert schemas[name]["additionalProperties"] is False


@pytest.mark.parametrize("password", ["", "x" * 73, "가" * 25])
def test_invalid_bcrypt_length_is_client_error(mock_client, password):
    body = {**member(), "password": password}
    response = mock_client.post("/api/register", json=body)
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.get(User, body["id"]) is None


def test_concurrent_registration_preserves_duplicate_response(mock_client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import api.register

    body = member()
    barrier = threading.Barrier(2)
    original = api.register.hash_password
    def simultaneous_hash(password):
        result = original(password)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(api.register, "hash_password", simultaneous_hash)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: mock_client.post("/api/register", json=body), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert sorted(response.json()["registered"] for response in responses) == [False, True]
