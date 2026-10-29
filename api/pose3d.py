"""Independent display generation, compressed private storage and owner API."""
import gzip
import hashlib
import io
import json
import logging
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import JSONResponse
from api import database
from api.auth import analysis_access
from api.database import Pose3D,Swing
from api.storage import StorageError,StorageObjectNotFound
from feedback.pose3d import Pose3DError
logger=logging.getLogger(__name__)
CONTRACT='EXP008-pose3d-v1'
MAX_RESPONSE_BYTES=32*1024*1024  # Same bound as Flutter Pose3DApi.
MAX_RAW_BYTES=31*1024*1024  # Reserve 1 MiB for the API metadata envelope.
PUBLIC_ERRORS={
    'WORLD_CAPTURE_INIT_FAILED': '3D 좌표 보존을 시작하지 못했습니다.',
    'WORLD_CAPTURE_FAILED': '3D 좌표 보존에 실패했습니다. 점수 결과는 유지됩니다.',
    'WORLD_FRAME_ALIGNMENT': '영상 시간과 3D 관절 프레임 수가 일치하지 않습니다.',
    'INVALID_VIDEO_PTS': '영상의 실제 timestamp를 검증할 수 없어 3D를 생성하지 않았습니다.',
    'INVALID_VIDEO_FPS': '3D를 생성하려면 유효한 영상 FPS가 필요합니다.',
    'WORLD_NOT_AVAILABLE': 'MediaPipe World 관절을 확보하지 못했습니다.',
    'WORLD_NOT_CAPTURED': '이 분석에는 3D World 관절이 저장되지 않았습니다.',
    'AMBIGUOUS_COORDINATES': '좌우 반전 메타데이터를 검증할 수 없습니다.',
    'INVALID_ANALYSIS_BINDING': '3D 데이터의 분석 및 소유자 정보를 검증할 수 없습니다.',
    'POSE3D_TOO_LARGE': '3D 표시 데이터가 앱의 크기 한도를 초과했습니다. 더 짧은 영상으로 분석하세요. 점수 결과는 유지됩니다.',
}
router=APIRouter(prefix='/api',tags=['pose-3d'],dependencies=[Depends(analysis_access)])
def now():return datetime.now(timezone.utc)
def init_pose(job):
    if job.user_id is None:return
    with database.SessionLocal.begin() as db:
        db.add(Pose3D(analysis_id=job.analysis_id,user_id=job.user_id,status='pending',contract_version=CONTRACT,handedness=job.input.get('handedness'),warnings=[]))
def fail_pose(analysis_id,code,message):
    with database.SessionLocal.begin() as db:
        row=db.get(Pose3D,analysis_id)
        if row is not None:
            row.status='failed';row.error={'code':code,'message':message};row.updated_at=now()

def _metadata(row):
    return {'analysis_id':row.analysis_id,'user_id':row.user_id,'status':row.status,
            'contract_version':row.contract_version,'frame_count':row.frame_count,
            'handedness':row.handedness,'warnings':row.warnings,
            'created_at':row.created_at.isoformat(),'updated_at':row.updated_at.isoformat()}
def persist_pose(job,skeleton,storage_factory):
    """Called only after score result is saved; errors never change that result."""
    storage=None;temporary=None
    try:
        with database.SessionLocal.begin() as db:
            row=db.get(Pose3D,job.analysis_id)
            if row is None:return
            row.status='processing';row.updated_at=now()
        if skeleton is None:
            fail_pose(job.analysis_id,'WORLD_CAPTURE_UNAVAILABLE','이 분석에서 World 좌표를 생성하지 못했습니다.');return
        from feedback.pose3d import build_pose3d
        clip=build_pose3d(skeleton,analysis_id=job.analysis_id,user_id=job.user_id,source_sha256=job.input['source_sha256'])
        if clip.get('data_kind')!='analysis' or clip.get('analysis_id')!=job.analysis_id or clip.get('id')!=job.analysis_id:
            raise ValueError('Pose identity mismatch')
        raw=json.dumps(clip,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
        if len(raw)>MAX_RAW_BYTES:raise Pose3DError('POSE3D_TOO_LARGE', '')
        # Check duplicated warnings/identity metadata too. A small clip must
        # not become an oversized response after the API envelope is added.
        envelope={**_metadata(row),'status':'ready','frame_count':clip['frame_count'],
                  'warnings':clip.get('warnings',[]),'clip':None}
        if len(JSONResponse(envelope).body)>MAX_RESPONSE_BYTES-MAX_RAW_BYTES-1024:
            raise Pose3DError('POSE3D_TOO_LARGE', '')
        compressed=gzip.compress(raw,compresslevel=6,mtime=0)
        # Never use a caller-supplied object path, original file name or access token.
        owner=hashlib.sha256(job.user_id.encode()).hexdigest()[:24]
        path=f'pose3d/{owner}/{job.analysis_id}/display-v1.json.gz'
        fd,temporary=tempfile.mkstemp(suffix='.json.gz',prefix='swing_pose_')
        import os
        with os.fdopen(fd,'wb') as out:out.write(compressed)
        storage=storage_factory();storage.upload(path,temporary,'application/gzip')
        with database.SessionLocal.begin() as db:
            row=db.get(Pose3D,job.analysis_id)
            row.storage_path=path;row.storage_bucket=storage.bucket
            row.payload_sha256=hashlib.sha256(raw).hexdigest()
            row.raw_size_bytes=len(raw);row.compressed_size_bytes=len(compressed)
            row.frame_count=clip['frame_count'];row.timestamps_s=clip['timestamps_s']
            row.coordinate_convention=clip['coordinate_convention'];row.warnings=clip.get('warnings',[])
            row.status='ready';row.error=None;row.updated_at=now()
    except Pose3DError as exc:
        # Pipeline diagnostics can include library-provided messages. Publish
        # only known codes with fixed text; never relay arbitrary exceptions.
        code=exc.code if isinstance(exc.code,str) and exc.code in PUBLIC_ERRORS else 'POSE3D_FAILED'
        message=PUBLIC_ERRORS.get(code,'3D 표시 데이터를 생성하거나 저장하지 못했습니다. 점수 결과는 유지됩니다.')
        fail_pose(job.analysis_id,code,message)
    except Exception as exc:
        logger.warning('3D display failed for %s: %s',job.analysis_id,type(exc).__name__)
        fail_pose(job.analysis_id,'POSE3D_FAILED','3D 표시 데이터를 생성하거나 저장하지 못했습니다. 점수 결과는 유지됩니다.')
    finally:
        if storage is not None:storage.close()
        if temporary is not None:Path(temporary).unlink(missing_ok=True)

@router.get('/analyses/{analysis_id}/pose-3d')
def get_pose3d(request:Request,analysis_id:str):
    from api.analyses import _storage
    with database.SessionLocal() as db:
        row=db.get(Pose3D,analysis_id)
        if row is None:
            raise HTTPException(404,'이 분석에는 저장된 3D 데이터가 없습니다. 새 영상 분석이 필요합니다.')
        # Defense in depth against accidental orphan/misowned metadata.
        if row.user_id!=request.state.user_id:raise HTTPException(403,'3D 데이터 소유자가 일치하지 않습니다.')
        payload=_metadata(row)
        if row.status in ['pending','processing']:
            return JSONResponse(payload,status_code=202,headers={'Retry-After':'2','Cache-Control':'no-store'})
        if row.status=='failed':
            return JSONResponse({**payload,'error':row.error},status_code=422,headers={'Cache-Control':'no-store'})
        try:
            compressed=_storage(request).download(row.storage_bucket,row.storage_path,max_bytes=32*1024*1024)
            if len(compressed) != row.compressed_size_bytes:
                raise ValueError('Compressed pose size mismatch')
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:raw=f.read(MAX_RAW_BYTES+1)
            if len(raw)>MAX_RAW_BYTES or len(raw)!=row.raw_size_bytes or hashlib.sha256(raw).hexdigest()!=row.payload_sha256:
                raise ValueError('Pose content integrity failure')
            clip=json.loads(raw)
            if clip.get('data_kind')!='analysis' or clip.get('analysis_id')!=analysis_id or clip.get('id')!=analysis_id:
                raise ValueError('Pose identity mismatch')
        except StorageObjectNotFound:
            raise HTTPException(404,'저장된 3D 파일을 찾을 수 없습니다.') from None
        except (StorageError,ValueError,OSError,EOFError,TypeError,AttributeError):
            raise HTTPException(502,'3D 데이터 저장소 또는 파일 무결성을 확인할 수 없습니다.') from None
        response=JSONResponse({**payload,'clip':clip},headers={'Cache-Control':'private, no-store'})
        if len(response.body)>MAX_RESPONSE_BYTES:
            raise HTTPException(502,'3D 응답이 앱의 크기 한도를 초과했습니다.')
        return response
