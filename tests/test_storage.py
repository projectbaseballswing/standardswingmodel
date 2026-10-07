from pathlib import Path

import httpx
import pytest

from api.storage import StorageError, StorageObjectNotFound, SupabaseStorage


def storage_with_transport(handler):
    # Synthetic unit-test inputs; MockTransport never makes network requests.
    storage = SupabaseStorage("https://storage.invalid", "unit-test-only", "test-videos", 60)
    headers = storage.client.headers
    storage.client.close()
    storage.client = httpx.Client(transport=httpx.MockTransport(handler), headers=headers)
    return storage


def test_storage_rest_upload_and_fresh_signing(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["apikey"] == "unit-test-only"
        assert request.headers["authorization"] == "Bearer unit-test-only"
        if "/object/sign/" in request.url.path:
            assert request.read() == b'{"expiresIn":60}'
            return httpx.Response(200, json={"signedURL": "/object/sign/test-videos/video.mp4?token=test"})
        assert request.headers["content-type"] == "video/mp4"
        assert request.headers["x-upsert"] == "false"
        assert request.headers["content-length"] == "5"
        assert request.read() == b"video"
        return httpx.Response(200, json={"Key": "test-videos/video.mp4"})

    storage = storage_with_transport(handler)
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    try:
        storage.upload("video.mp4", str(source), "video/mp4")
        url = storage.signed_url("test-videos", "video.mp4")
        assert url == "https://storage.invalid/storage/v1/object/sign/test-videos/video.mp4?token=test"
        assert len(requests) == 2
    finally:
        storage.close()


@pytest.mark.parametrize("status_code", [400, 401, 403, 500])
def test_storage_errors_do_not_expose_remote_response(status_code):
    storage = storage_with_transport(lambda request: httpx.Response(status_code, text="private upstream detail"))
    try:
        with pytest.raises(StorageError) as error:
            storage.signed_url("test-videos", "video.mp4")
        assert "private upstream detail" not in str(error.value)
        assert "unit-test-only" not in str(error.value)
    finally:
        storage.close()


def test_invalid_signed_url_response_is_rejected():
    storage = storage_with_transport(lambda request: httpx.Response(200, json={"signedURL": "https://other.invalid"}))
    try:
        with pytest.raises(StorageError):
            storage.signed_url("test-videos", "video.mp4")
    finally:
        storage.close()


@pytest.mark.parametrize("status_code,body", [(404, {"code": "NoSuchKey"}),
                                             (400, {"message": "Object not found"})])
def test_missing_object_has_distinct_error(status_code, body):
    storage = storage_with_transport(lambda request: httpx.Response(status_code, json=body))
    try:
        with pytest.raises(StorageObjectNotFound):
            storage.signed_url("test-videos", "missing.mp4")
    finally:
        storage.close()
