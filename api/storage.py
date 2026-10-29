"""Supabase Storage REST API. 파일은 private bucket에, 경로만 DB에 저장한다."""

from pathlib import Path
from urllib.parse import quote
import hashlib
import hmac
import secrets
import time
import tempfile

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

    def ensure_private(self):
        response=self._request('GET',f"/bucket/{quote(self.bucket,safe='')}")
        try:
            info=response.json()
            if info.get('id')!=self.bucket or info.get('public') is not False:
                raise ValueError('Private bucket required')
        except (ValueError,AttributeError):
            raise StorageError('선택한 Storage bucket은 비공개여야 합니다.') from None

    def download(self,bucket,path,max_bytes=32*1024*1024):
        if bucket!=self.bucket:raise StorageError('Unexpected storage bucket')
        endpoint=f"/object/authenticated/{quote(bucket,safe='')}/{quote(path,safe='/')}"
        # Stream bounded compressed payload; never proxy arbitrary client URLs.
        try:
            with self.client.stream('GET',self.base_url+endpoint) as response:
                if response.status_code==404:raise StorageObjectNotFound('저장된 파일을 찾을 수 없습니다.')
                response.raise_for_status();chunks=[];size=0
                for part in response.iter_bytes():
                    size+=len(part)
                    if size>max_bytes:raise StorageError('저장된 파일 크기가 허용 범위를 벗어났습니다.')
                    chunks.append(part)
                return b''.join(chunks)
        except httpx.HTTPError:
            raise StorageError('저장소에서 파일을 읽을 수 없습니다.') from None

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


class LocalPrivateStorage:
    """Explicit isolated development backend; no public static directory.

    It is persistent disk storage, not a fixture. Real bearer ownership remains
    mandatory. Supabase deployment must use the default supabase backend.
    """
    bucket='local-private'
    expires_in=60
    _signing_key=secrets.token_bytes(32)
    def __init__(self,root):
        self.root=Path(root).resolve()
        project = Path(__file__).resolve().parents[1]
        temporary = Path(tempfile.gettempdir()).resolve()
        if (not root or self.root in (project, temporary)
                or not any(self.root.is_relative_to(base) for base in (project, temporary))):
            raise StorageError('Local storage must be a private subdirectory of the project or OS temporary directory')
        self.root.mkdir(parents=True,exist_ok=True)
    def _path(self,path):
        target=(self.root/path).resolve()
        if not target.is_relative_to(self.root) or target==self.root:
            raise StorageError('Invalid storage path')
        return target
    def upload(self,path,local_path,content_type):
        target=self._path(path);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as out,open(local_path,'rb') as stream:
            while chunk:=stream.read(1024*1024):out.write(chunk)
    def download(self,bucket,path,max_bytes=32*1024*1024):
        if bucket!=self.bucket:raise StorageError('Unexpected storage bucket')
        target=self._path(path)
        if not target.is_file():raise StorageObjectNotFound('저장된 파일을 찾을 수 없습니다.')
        if target.stat().st_size>max_bytes:raise StorageError('File too large')
        return target.read_bytes()
    def signed_url(self,bucket,path):
        # Local API serves videos through authenticated, bounded capability URLs.
        if bucket!=self.bucket or not self._path(path).is_file():raise StorageObjectNotFound('저장된 파일을 찾을 수 없습니다.')
        expiry=int(time.time())+self.expires_in
        digest=hmac.new(self._signing_key,f'{path}:{expiry}'.encode(),hashlib.sha256).hexdigest()
        return f'/api/local-video?path={quote(path,safe="")}&expires={expiry}&signature={digest}'
    def capability_path(self,path,expires,signature):
        expected=hmac.new(self._signing_key,f'{path}:{expires}'.encode(),hashlib.sha256).hexdigest()
        if expires<int(time.time()) or expires>int(time.time())+self.expires_in or not hmac.compare_digest(expected,signature):
            raise StorageError('Expired or invalid video capability')
        if not path.startswith('swings/') or '/original' not in path:raise StorageError('Only videos use capability URLs')
        return self._path(path)
    def close(self):pass

def create_storage():
    if settings.storage_backend=='local':
        return LocalPrivateStorage(settings.local_storage_root)
    if settings.storage_backend!='supabase':raise StorageError('Unknown storage backend')
    storage=SupabaseStorage(
        settings.supabase_url, settings.supabase_service_role_key,
        settings.storage_bucket, settings.signed_url_seconds,
    )
    try:storage.ensure_private()
    except Exception:
        storage.close();raise
    return storage
