"""스윙 피드백 라우터.

앱 조립은 api/main.py 에서 합니다. 여기서는 /api 아래에 붙는 라우터와,
서버 시작 시 템플릿·작업 큐를 준비하는 lifespan 만 제공합니다.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from api import schemas
from api.jobs import Job, JobManager
from api.settings import settings
from feedback.compare import MODEL_VERSION
from feedback.features import to_template_features
from feedback.pipeline import SwingPipeline
from feedback.reference import ReferenceStore

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "analysis_sample.json"

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}

router = APIRouter(prefix="/api")


def _mock_report() -> dict:
    """목업 모드에서 돌려주는 고정 응답. 실제 분석 결과를 저장해 둔 것이다."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """기준 템플릿과 작업 큐를 서버 시작 시 한 번 준비한다."""
    if settings.mock:
        # 목업 모드에서는 무거운 모델과 템플릿을 불러오지 않는다
        app.state.store = None
        app.state.jobs = None
        app.state.mock_jobs = {}
        yield
        return

    store = ReferenceStore(settings.template_path)
    app.state.store = store
    app.state.jobs = JobManager(
        store,
        pipeline_factory=lambda: SwingPipeline(
            settings.yolo_weights, settings.pose_model, target_fps=settings.reference_fps
        ),
        reference_fps=settings.reference_fps,
        max_jobs=settings.max_jobs,
    )
    yield
    app.state.jobs.shutdown()


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def _store(request: Request) -> ReferenceStore:
    return request.app.state.store


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
    )


def _finished_result(request: Request, analysis_id: str) -> dict:
    if settings.mock:
        if analysis_id not in request.app.state.mock_jobs:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "분석 결과를 찾을 수 없습니다.")
        return _mock_report()
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
):
    """영상을 업로드하면 분석 작업을 등록합니다. 결과는 GET /api/analyses/{analysis_id} 로 조회합니다."""
    suffix = Path(video.filename or "").suffix.lower()
    if settings.mock:
        if suffix not in VIDEO_SUFFIXES:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"지원하지 않는 영상 형식입니다: {suffix}")
        analysis_id = uuid.uuid4().hex
        request.app.state.mock_jobs[analysis_id] = {
            "filename": video.filename, "handedness": handedness, "created_at": datetime.now(timezone.utc),
        }
        return schemas.AnalysisCreated(analysis_id=analysis_id, status="queued")

    if suffix not in VIDEO_SUFFIXES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"지원하지 않는 영상 형식입니다: {suffix}")

    fd, video_path = tempfile.mkstemp(suffix=suffix, prefix="swing_")
    with os.fdopen(fd, "wb") as out:
        await run_in_threadpool(shutil.copyfileobj, video.file, out)
    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if size_mb > settings.max_upload_mb:
        os.remove(video_path)
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"영상은 {settings.max_upload_mb}MB 이하여야 합니다.")

    job = _jobs(request).submit_video(
        video_path,
        is_left=(handedness == "left"),
        input_info={"type": "video", "filename": video.filename, "handedness": handedness},
    )
    return schemas.AnalysisCreated(analysis_id=job.analysis_id, status=job.status)


@router.post("/analyses/features", response_model=schemas.Analysis, tags=["analyses"])
async def create_analysis_from_features(
    request: Request,
    features: UploadFile = File(..., description="(80, 64) 또는 (80, 67) 스윙 피처 .npy"),
    fps: float = Form(30.0, gt=0, description="피처를 만든 영상의 fps"),
):
    """이미 추출한 피처(.npy)로 바로 비교합니다. 영상 처리 없이 비교 로직만 확인할 때 씁니다."""
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
    if settings.mock:
        info = request.app.state.mock_jobs.get(analysis_id)
        if info is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "분석 결과를 찾을 수 없습니다.")
        report = _mock_report()
        if not include_series:
            for joint in report["joints"]:
                joint["series"] = None
        return schemas.Analysis(
            analysis_id=analysis_id, status="done", stage=None,
            created_at=info["created_at"], finished_at=info["created_at"],
            input={"type": "video", "filename": info["filename"], "handedness": info["handedness"], "mock": True},
            error=None, result=report,
        )
    job = _jobs(request).get(analysis_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "분석 결과를 찾을 수 없습니다.")
    analysis = _to_analysis(job)
    if analysis.result is not None and not include_series:
        for joint in analysis.result.joints:
            joint.series = None
    return analysis


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
