"""Opt-in real Supabase E2E. Creates labelled data and NEVER deletes it.

RUN_SUPABASE_INTEGRATION_TESTS=1 python scripts/verify_supabase.py --video <actual.mp4>
Only IDs, check names and status codes are reported; never credentials or signed URLs.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class VerificationError(Exception):
    """Only fixed, non-secret check descriptions are used in this exception."""


def check(condition, name):
    if not condition:
        raise VerificationError(name)


@contextmanager
def live_server(environment):
    import httpx

    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=150) as client:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                check(process.poll() is None, "server exited during startup")
                try:
                    if client.get("/api/health", timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.2)
            else:
                raise VerificationError("server startup timeout")
            yield client
    finally:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, timeout=15)
            else:
                process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for _ in range(30):
            with socket.socket() as probe:
                probe.settimeout(0.1)
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    break
            time.sleep(0.1)
        else:
            raise VerificationError("verification server did not stop")


def verify(video, report, save):
    import httpx
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    required = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_STORAGE_BUCKET")
    check(all(os.getenv(key) for key in required), "missing Supabase environment")
    check(video.is_file() and video.suffix.lower() == ".mp4", "an actual local MP4 is required")
    os.environ["SWING_MOCK"] = "1"
    os.environ["SWING_WORKER_ID"] = "e2e-" + uuid.uuid4().hex
    from api.database import SessionLocal, Swing, User, engine
    from api.security import verify_password
    from api.schemas import AnalysisReport
    from api.settings import settings
    from api.video_validation import validate_video_header
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    check(engine.dialect.name == "postgresql", "E2E requires PostgreSQL")
    validate_video_header(str(video), ".mp4")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    source_hash = hashlib.sha256(video.read_bytes()).hexdigest()
    report["video_bytes"] = video.stat().st_size
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
        check(current == head, "migration current differs from head")
        report["alembic_current"] = current
        report["alembic_head"] = head
        rls = connection.execute(text("SELECT relname, relrowsecurity FROM pg_class "
                                      "WHERE relnamespace='public'::regnamespace AND relname IN ('users','swings')")).all()
        check(len(rls) == 2 and all(row[1] for row in rls), "RLS is not enabled on both tables")
        report["rls_enabled"] = True
    with httpx.Client(timeout=30) as remote:
        bucket = remote.get(settings.supabase_url.rstrip("/") + "/storage/v1/bucket/" + quote(settings.storage_bucket, safe=""),
                            headers={"apikey": settings.supabase_service_role_key,
                                     "Authorization": "Bearer " + settings.supabase_service_role_key})
        check(bucket.status_code == 200, "bucket inspection failed")
        check(bucket.json().get("public") is False, "bucket must be private")
        report["private_bucket"] = True

    user_id = "e2e_" + datetime.now(timezone.utc).strftime("%Y%m%d") + "_" + uuid.uuid4().hex[:10]
    email = user_id + "@example.com"
    password = secrets.token_urlsafe(24)
    report.update(user_id=user_id, analysis_id=None, worker_id=os.environ["SWING_WORKER_ID"], checks=[])
    save()

    def call(client, method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        report["checks"].append({"method": method, "path": path, "status": response.status_code})
        save()
        check(response.status_code == expected, "unexpected API status")
        return response

    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        for iteration in range(2):
            report["stage"] = "initial_server" if iteration == 0 else "restarted_server"
            save()
            with live_server(environment) as client:
                check(call(client, "GET", "/api/health").json()["mock"] is True, "mock mode not enabled")
                call(client, "GET", "/docs")
                if iteration == 0:
                    registered = call(client, "POST", "/api/register", json={
                        "id": user_id, "password": password, "email": email, "nickname": user_id,
                    })
                    check(registered.json()["registered"] is True, "test member was not registered")
                    with SessionLocal() as db:
                        user = db.get(User, user_id)
                        check(user is not None and user.password_hash != password
                              and verify_password(password, user.password_hash), "password storage check failed")
                    report["password_hash_verified"] = True
                    call(client, "POST", "/api/login", 401, json={"id": user_id, "password": "incorrect"})
                    call(client, "POST", "/api/login", 401, json={"id": uuid.uuid4().hex, "password": "incorrect"})
                check(call(client, "POST", "/api/login", json={"id": user_id, "password": password}).json()["user"] == user_id,
                      "login returned another user")
                check(call(client, "POST", "/api/me", json={"user": user_id}).json()["id"] == user_id, "me mismatch")
                if iteration == 0:
                    with video.open("rb") as stream:
                        uploaded = call(client, "POST", "/api/analyses", 202,
                                        files={"video": ("e2e-sample.mp4", stream, "video/mp4")},
                                        data={"user_id": user_id, "handedness": "right",
                                              "recorded_at": "2026-10-04T11:10:00+09:00"}).json()
                    report["analysis_id"] = uploaded["analysis_id"]
                    report["creation_status"] = uploaded["status"]
                    save()
                analysis_id = report["analysis_id"]
                analysis = call(client, "GET", f"/api/analyses/{analysis_id}?include_series=true").json()
                check(analysis["status"] == "done" and analysis["user_id"] == user_id, "analysis result mismatch")
                report["analysis_status"] = analysis["status"]
                for section in ("overall", "joints", "phases", "speed"):
                    section_result = call(client, "GET", f"/api/analyses/{analysis_id}/{section}").json()
                    if section == "speed":
                        check(section_result["available"] is False, "speed placeholder changed")
                video_result = call(client, "GET", f"/api/analyses/{analysis_id}/video").json()
                signed = video_result["url"]
                check(urlsplit(signed).hostname == urlsplit(settings.supabase_url).hostname, "signed URL origin mismatch")
                with httpx.Client(timeout=60) as remote:
                    downloaded = remote.get(signed)
                check(downloaded.status_code == 200 and hashlib.sha256(downloaded.content).hexdigest() == source_hash,
                      "stored video differs from uploaded bytes")
                with SessionLocal() as db:
                    row = db.get(Swing, analysis_id)
                    check(row is not None and row.user_id == user_id and row.status == "done", "DB swing state mismatch")
                    check(row.recorded_at.utcoffset() is not None, "timestamp is not timezone-aware")
                    check(row.recorded_at.astimezone(timezone.utc).isoformat() == "2026-10-04T02:10:00+00:00", "timestamp changed")
                    check(row.video_size_bytes == report["video_bytes"] and row.content_type == "video/mp4", "video metadata mismatch")
                    check(AnalysisReport.model_validate(row.result).model_dump(mode="json") == analysis["result"],
                          "DB result differs from API")
                    values = {column.name: getattr(row, column.name) for column in Swing.__table__.columns}
                    serialized = json.dumps(values, default=str)
                    check(signed not in serialized and "?token=" not in serialized, "signed URL found in DB")
                    report["storage_path"] = row.video_storage_path
                report["video_download_verified"] = True
                report["signed_url_not_persisted"] = True
                if iteration == 1:
                    report["restart_persistence"] = True
                save()
        report["stage"] = "complete"
        report["passed"] = True
        save()
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=os.getenv("SUPABASE_TEST_VIDEO"))
    parser.add_argument("--report", type=Path, default=ROOT / ".venv" / "supabase-e2e-last.json")
    args = parser.parse_args()
    if os.getenv("RUN_SUPABASE_INTEGRATION_TESTS") != "1":
        print("SKIP: set RUN_SUPABASE_INTEGRATION_TESTS=1 to create real test data")
        return 0
    report = {"passed": False, "stage": "preflight", "test_data_deleted": False}
    def save():
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        check(args.video is not None, "video path required")
        verify(Path(args.video).resolve(), report, save)
    except Exception as exc:
        # Do not print exception messages: libraries may embed URLs or credentials.
        report["error_type"] = type(exc).__name__
        if isinstance(exc, VerificationError):
            report["failed_check"] = str(exc)
        save()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
