"""스윙 피드백 라우터.

앱 조립은 api/main.py 에서 합니다. 여기서는 /api 아래에 붙는 라우터와,
서버 시작 시 템플릿·작업 큐를 준비하는 lifespan 만 제공합니다.
"""

from __future__ import annotations

import io
import os
import tempfile
import logging
from datetime import datetime, timezone
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from api import schemas
from api.jobs import Job, JobManager
from api.database import User, get_db
from api.settings import settings
from api.storage import StorageError, StorageObjectNotFound, create_storage
from api.video_validation import video_type, validate_video_header
from feedback.compare import MODEL_VERSION
from feedback.features import to_template_features
from feedback.pipeline import SwingPipeline
from feedback.reference import ReferenceStore

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "analysis_sample.json"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _mock_report() -> dict:
    """목업 모드에서 돌려주는 고정 응답. 실제 분석 결과를 저장해 둔 것이다."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """기준 템플릿과 작업 큐를 서버 시작 시 한 번 준비한다."""
    store = None if settings.mock else ReferenceStore(settings.template_path)
    app.state.store = store
    app.state.storage = None
    jobs = JobManager(
        store,
        pipeline_factory=lambda: SwingPipeline(
            settings.yolo_weights, settings.pose_model, target_fps=settings.reference_fps
        ),
        reference_fps=settings.reference_fps,
        worker_id=settings.worker_id,
    )
    app.state.jobs = jobs
    try:
        await run_in_threadpool(jobs.recover_interrupted)
        yield
    finally:
        await run_in_threadpool(jobs.shutdown)
        if app.state.storage is not None:
            app.state.storage.close()


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def _store(request: Request) -> ReferenceStore:
    return request.app.state.store


def _storage(request: Request):
    if request.app.state.storage is None:
        try:
            request.app.state.storage = create_storage()
        except StorageError as exc:
            raise HTTPException(503, str(exc)) from None
    return request.app.state.storage


def _to_analysis(job: Job) -> schemas.Analysis:
    return schemas.Analysis(
        analysis_id=job.analysis_id,
        status=job.status,
        stage=job.stage,
        created_at=job.created_at,
        finished_at=job.finished_at,
        input=job.input,
        error=job.error,
        result=job.result,
        user_id=job.user_id,
        recorded_at=job.recorded_at,
    )


def _finished_result(request: Request, analysis_id: str) -> dict:
    job = _jobs(request).get(analysis_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "분석 결과를 찾을 수 없습니다.")
    if job.status == "failed":
        raise HTTPException(422, job.error)
    if job.status != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, f"아직 분석 중입니다 (status={job.status}, stage={job.stage}).")
    return job.result


def _strip_series(joints: list) -> list:
    return [{key: value for key, value in joint.items() if key != "series"} for joint in joints]


# ----------------------------------------------------------------------
# 공통
# ----------------------------------------------------------------------
@router.get("/health", response_model=schemas.Health, tags=["common"])
def health(request: Request):
    if settings.mock:
        return schemas.Health(status="ok", model_version=MODEL_VERSION, mock=True,
                              template_path="(mock)", video_pipeline_loaded=False)
    return schemas.Health(
        status="ok",
        model_version=MODEL_VERSION,
        mock=False,
        template_path=str(_store(request).path),
        video_pipeline_loaded=_jobs(request).pipeline_loaded,
    )


# ----------------------------------------------------------------------
# 분석 요청
# ----------------------------------------------------------------------
@router.post(
    "/analyses",
    response_model=schemas.AnalysisCreated,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["analyses"],
)
async def create_analysis(
    request: Request,
    video: UploadFile = File(..., description="스윙 영상 (mp4, mov 등)"),
    handedness: Literal["right", "left"] = Form(..., description="우타(right) / 좌타(left)"),
    user_id: str | None = Form(None, description="로그인 응답의 user. 생략하면 사용자 미연결"),
    recorded_at: datetime | None = Form(None, description="촬영 시각 ISO 8601, 시간대 포함. 생략하면 업로드 시각"),
    db: Session = Depends(get_db),
):
    """영상을 업로드하면 분석 작업을 등록합니다. 결과는 GET /api/analyses/{analysis_id} 로 조회합니다."""
    suffix, content_type = video_type(video.filename or "", video.content_type)
    if user_id is not None and db.get(User, user_id) is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    if recorded_at is not None and recorded_at.tzinfo is None:
        raise HTTPException(422, "recorded_at에 시간대(Z 또는 +09:00 등)를 포함하세요.")
    storage = _storage(request)
    fd, video_path = tempfile.mkstemp(suffix=suffix, prefix="swing_")
    job, handed_to_worker = None, False
    try:
        size = 0
        with os.fdopen(fd, "wb") as out:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, f"영상은 {settings.max_upload_mb}MB 이하여야 합니다.")
                await run_in_threadpool(out.write, chunk)
        if size == 0:
            raise HTTPException(422, "빈 영상 파일은 업로드할 수 없습니다.")
        await run_in_threadpool(validate_video_header, video_path, suffix)
        info = {"type": "video", "filename": video.filename, "handedness": handedness, "suffix": suffix}
        if settings.mock:
            info["mock"] = True
        job = await run_in_threadpool(
            _jobs(request).create_video_job, info, user_id=user_id,
            recorded_at=(recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc),
            storage_bucket=storage.bucket, video_size_bytes=size, content_type=content_type,
        )
        # 업로드 전에 경로를 DB에 기록한다. 전송 중 연결이 끊겨도 대상 파일을 추적할 수 있다.
        await run_in_threadpool(storage.upload, job.video_storage_path, video_path, job.content_type)
        if settings.mock:
            await run_in_threadpool(_jobs(request).complete_mock, job, _mock_report())
        else:
            await run_in_threadpool(_jobs(request).submit_video, job, video_path, handedness == "left")
            handed_to_worker = True
        return schemas.AnalysisCreated(analysis_id=job.analysis_id, status="queued")
    except StorageError as exc:
        await run_in_threadpool(_jobs(request).fail, job, "STORAGE_UPLOAD_FAILED", str(exc))
        raise HTTPException(502, {"analysis_id": job.analysis_id, "code": "STORAGE_UPLOAD_FAILED",
                                  "message": str(exc)}) from None
    except HTTPException:
        raise
    except Exception:
        if job is not None:
            try:
                await run_in_threadpool(_jobs(request).fail, job, "INTERNAL_ERROR", "업로드 작업을 완료하지 못했습니다.")
            except Exception:
                logger.error("analysis %s state could not be saved; recover on restart", job.analysis_id)
        raise
    finally:
        await video.close()
        if not handed_to_worker:
            Path(video_path).unlink(missing_ok=True)


@router.post(
    "/analyses/features",
    response_model=schemas.Analysis,
    tags=["dev"],
    include_in_schema=False,  # 사용자용 경로가 아니라 개발/테스트 전용
)
async def create_analysis_from_features(
    request: Request,
    features: UploadFile = File(..., description="(80, 64) 또는 (80, 67) 스윙 피처 .npy"),
    fps: float = Form(30.0, gt=0, description="피처를 만든 영상의 fps"),
):
    """[개발 전용] 이미 추출한 피처(.npy)로 바로 비교한다. 사용자는 영상만 올리므로 앱에서는 쓰지 않는다.

    이 경로는 구버전(0.1) 비교를 쓴다. 입력이 이미 80프레임으로 잘린 피처라서
    0.2 에 필요한 프레임별 관절 좌표를 복원할 수 없기 때문이다.
    """
    try:
        array = np.load(io.BytesIO(await features.read()), allow_pickle=False)
        array = to_template_features(array)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    job = await run_in_threadpool(
        _jobs(request).compare_features,
        array,
        fps,
        {"type": "features", "filename": features.filename, "fps": fps},
        _mock_report() if settings.mock else None,
    )
    return _to_analysis(job)


# ----------------------------------------------------------------------
# 결과 조회
# ----------------------------------------------------------------------
@router.get("/analyses/{analysis_id}", response_model=schemas.Analysis, tags=["analyses"])
def get_analysis(
    request: Request,
    analysis_id: str,
    include_series: bool = Query(False, description="관절 각도 80프레임 시계열 포함"),
):
    """작업 상태와 전체 결과(종합 + 관절별 + 구간별 + 속도)."""
    job = _jobs(request).get(analysis_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "분석 결과를 찾을 수 없습니다.")
    analysis = _to_analysis(job)
    if analysis.result is not None and not include_series:
        for joint in analysis.result.joints:
            joint.series = None
    return analysis


@router.get("/analyses/{analysis_id}/video", response_model=schemas.VideoURL, tags=["analyses"])
def get_video(request: Request, analysis_id: str):
    """저장된 원본 영상의 임시 URL. 만료되면 이 API를 다시 호출한다."""
    job = _jobs(request).get(analysis_id)
    if job is None or job.video_storage_path is None:
        raise HTTPException(404, "저장된 영상 정보를 찾을 수 없습니다.")
    if job.stage == "uploading":
        raise HTTPException(409, "영상 업로드 중입니다.")
    storage = _storage(request)
    try:
        url = storage.signed_url(job.storage_bucket, job.video_storage_path)
    except StorageObjectNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except StorageError as exc:
        raise HTTPException(502, str(exc)) from None
    return schemas.VideoURL(analysis_id=analysis_id, url=url, expires_in=storage.expires_in)


@router.get("/analyses/{analysis_id}/overall", response_model=schemas.OverallFeedback, tags=["feedback"])
def get_overall(request: Request, analysis_id: str):
    """종합 피드백: 전체 유사도 점수, 그룹별 점수, 가장 어긋난 구간, 주요 문제점."""
    return _finished_result(request, analysis_id)["overall"]


@router.get("/analyses/{analysis_id}/joints", response_model=schemas.JointsFeedback, tags=["feedback"])
def get_joints(
    request: Request,
    analysis_id: str,
    include_series: bool = Query(False, description="80프레임 시계열 포함"),
):
    """관절별 피드백: 부위별 각도를 구간 평균, 임팩트 순간, 움직임 폭으로 비교."""
    joints = _finished_result(request, analysis_id)["joints"]
    return {"joints": joints if include_series else _strip_series(joints)}


@router.get("/analyses/{analysis_id}/phases", response_model=schemas.PhasesFeedback, tags=["feedback"])
def get_phases(request: Request, analysis_id: str):
    """구간별 피드백: 구간별 길이(템포), 유사도, 크게 다른 관절.

    구간 구성은 모델 버전에 따라 달라지므로 배열 순서대로 그리고, key 로 구분하세요.
    """
    return _finished_result(request, analysis_id)["phases"]


@router.get("/analyses/{analysis_id}/speed", response_model=schemas.SpeedFeedback, tags=["feedback"])
def get_speed(request: Request, analysis_id: str):
    """속도 피드백: 스윙 시간, 최대 손 속도, 회전 속도, 꼬임 순서.

    현재 모델(0.1)에서는 값이 비어 있고 available=false 입니다. 다음 버전에서 채워집니다.
    """
    return _finished_result(request, analysis_id)["speed"]
