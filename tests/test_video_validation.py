import pytest
from sqlalchemy import func, select

from api.database import SessionLocal, Swing
from api.storage import StorageError, StorageObjectNotFound
from tests.test_persistence import upload
from tests.video_fixture import VIDEO_BYTES


@pytest.mark.parametrize("filename,mime,payload", [
    ("../swing.mp4", "video/mp4", VIDEO_BYTES),
    ("..\\swing.mp4", "video/mp4", VIDEO_BYTES),
    ("swing.mp4", "image/png", VIDEO_BYTES),
    ("swing.mp4", "video/mp4", b"this is text"),
    ("swing.avi", "video/x-msvideo", VIDEO_BYTES),
    ("swing.mkv", "video/x-matroska", VIDEO_BYTES),
])
def test_obviously_invalid_video_is_rejected(mock_client, fake_storage, filename, mime, payload):
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Swing))
    response = mock_client.post("/api/analyses", data={"handedness": "right"},
                                files={"video": (filename, payload, mime)})
    assert response.status_code == 415
    assert not fake_storage.objects
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Swing)) == before


@pytest.mark.parametrize("mime,stored", [("video/mp4", "video/mp4"),
                                        ("application/mp4", "application/mp4"),
                                        ("application/octet-stream", "video/mp4")])
def test_mime_and_extension_preserved(mock_client, mime, stored):
    response = mock_client.post("/api/analyses", data={"handedness": "left"},
                                files={"video": ("Swing.MP4", VIDEO_BYTES, mime)})
    assert response.status_code == 202
    with SessionLocal() as db:
        row = db.get(Swing, response.json()["analysis_id"])
        assert row.user_id is None
        assert row.content_type == stored
        assert row.video_storage_path.endswith("/original.mp4")


@pytest.mark.parametrize("error,expected", [(StorageObjectNotFound("missing"), 404), (StorageError("outage"), 502)])
def test_video_endpoint_storage_errors(mock_client, fake_storage, monkeypatch, error, expected):
    analysis_id = upload(mock_client).json()["analysis_id"]
    def fail(*args):
        raise error
    monkeypatch.setattr(fake_storage, "signed_url", fail)
    assert mock_client.get(f"/api/analyses/{analysis_id}/video").status_code == expected
