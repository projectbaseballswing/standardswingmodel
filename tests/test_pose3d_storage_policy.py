"""Transport-level checks only; not a real Supabase RLS test."""
import httpx
import pytest
from api.storage import SupabaseStorage,StorageError

def storage(handler):
    value=SupabaseStorage('https://example.supabase.co','test-secret','dedicated-private')
    value.client.close()
    value.client=httpx.Client(transport=httpx.MockTransport(handler),headers={'Authorization':'Bearer test-secret','apikey':'test-secret'})
    return value

def test_rejects_public_bucket_and_uses_authenticated_object_route():
    seen=[]
    def handler(request):
        seen.append(request.url.path)
        assert request.headers['Authorization']=='Bearer test-secret'
        if request.url.path.endswith('/bucket/dedicated-private'):
            return httpx.Response(200,json={'id':'dedicated-private','public':False})
        assert '/object/authenticated/dedicated-private/pose3d/' in request.url.path
        return httpx.Response(200,content=b'compressed-bytes')
    s=storage(handler)
    try:
        s.ensure_private()
        assert s.download(s.bucket,'pose3d/a/b/display-v1.json.gz')==b'compressed-bytes'
        with pytest.raises(StorageError):s.download('foreign-bucket','pose3d/a/b')
        with pytest.raises(StorageError):s.download(s.bucket,'pose3d/a/b',max_bytes=1)
    finally:s.close()
    assert not any('/object/public/' in path for path in seen)
    s=storage(lambda request:httpx.Response(200,json={'id':'dedicated-private','public':True}))
    try:
        with pytest.raises(StorageError):s.ensure_private()
    finally:s.close()

def test_download_errors_never_expose_service_key_or_remote_response():
    s=storage(lambda request:httpx.Response(500,text='test-secret internal response'))
    try:
        with pytest.raises(StorageError) as error:s.download(s.bucket,'pose3d/a/b')
        assert 'test-secret' not in str(error.value) and 'internal response' not in str(error.value)
    finally:s.close()
