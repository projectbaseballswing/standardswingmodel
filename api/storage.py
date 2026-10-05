"""Supabase Storage REST API. 파일은 private bucket에, 경로만 DB에 저장한다."""

from pathlib import Path
from urllib.parse import quote

import httpx

from api.settings import settings


class StorageError(Exception):
    """응답 본문/인증 헤더 등 secret을 외부로 노출하지 않는 오류."""


class StorageObjectNotFound(StorageError):
    pass


class SupabaseStorage:
    def __init__(self, url: str, key: str, bucket: str, expires_in: int = 900):
        if not url or not key or not bucket:
            raise StorageError("Supabase URL, service role key, bucket을 .env에 설정하세요.")
        if not url.startswith("https://"):
            raise StorageError("SUPABASE_URL은 https:// 프로젝트 URL이어야 합니다.")
        if not 1 <= expires_in <= 604800:
            raise StorageError("signed URL 유효기간은 1~604800초여야 합니다.")
        self.base_url = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.expires_in = expires_in
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "apikey": key},
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    def _request(self, method: str, path: str, *, missing_is_not_found=False, **kwargs):
        try:
            response = self.client.request(method, self.base_url + path, **kwargs)
            if response.is_error and missing_is_not_found:
                try:
                    error = response.json()
                except ValueError:
                    error = {}
                if not isinstance(error, dict):
                    error = {}
                code = error.get("code") or error.get("error")
                if (code in ("NoSuchKey", "not_found") or error.get("message") == "Object not found"
                        or (response.status_code == 404 and code != "NoSuchBucket")):
                    raise StorageObjectNotFound("저장된 영상 파일을 찾을 수 없습니다.")
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            raise StorageError("영상 저장소 요청에 실패했습니다. 서버의 Storage 설정과 연결을 확인하세요.") from None

    def upload(self, path: str, local_path: str, content_type: str):
        endpoint = f"/object/{quote(self.bucket, safe='')}/{quote(path, safe='/')}"
        with open(local_path, "rb") as stream:
            self._request("POST", endpoint, content=stream, headers={
                "Content-Type": content_type,
                "Content-Length": str(Path(local_path).stat().st_size),
                "x-upsert": "false",
            })

    def signed_url(self, bucket: str, path: str) -> str:
        endpoint = f"/object/sign/{quote(bucket, safe='')}/{quote(path, safe='/')}"
        response = self._request("POST", endpoint, missing_is_not_found=True, json={"expiresIn": self.expires_in})
        try:
            signed = response.json()["signedURL"]
            if not isinstance(signed, str) or not signed.startswith("/object/sign/"):
                raise ValueError("Unexpected signed URL")
            return self.base_url + signed
        except (ValueError, KeyError, TypeError):
            raise StorageError("영상 URL 발급 응답을 확인할 수 없습니다.") from None

    def close(self):
        self.client.close()


def create_storage():
    return SupabaseStorage(
        settings.supabase_url, settings.supabase_service_role_key,
        settings.storage_bucket, settings.signed_url_seconds,
    )
