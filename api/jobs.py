"""분석 작업 저장소와 워커.

영상 분석은 오래 걸리므로 요청을 받으면 작업만 등록하고, 워커 스레드 1개가 순서대로 처리한다.
YOLO 추적(model.track(persist=True))은 모델 객체에 추적 상태를 저장하므로 동시에 여러 영상을
돌리면 안 된다. 그래서 워커는 1개로 고정한다.

작업 상태와 결과는 SQLAlchemy로 저장하고 요청/워커마다 별도 세션을 사용한다.
"""

from __future__ import annotations

import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import select, update

from api import database
from api.database import Swing
from feedback.compare import SwingComparison
from feedback.compare_v2 import SwingComparisonV2
from feedback.pipeline import PipelineError, SwingPipeline
from feedback.reference import ReferenceStore
from feedback.reference_model import load_reference_model

logger = logging.getLogger(__name__)


def _skeleton_quality(skeleton) -> Dict[str, Any]:
    """신뢰도 판정에 쓰는 품질 정보."""
    import numpy as np

    from feedback.features import JOINT_NAMES

    visibility = np.asarray(skeleton.visibility, dtype=float)
    return {
        "source_fps": round(float(skeleton.fps), 2),
        "n_frames": int(skeleton.landmarks.shape[0]),
        "max_missing_gap": int(skeleton.max_missing_gap),
        "nan_ratio": round(float(np.mean(~np.isfinite(skeleton.landmarks))), 4),
        "joint_visibility": {
            name: round(float(value), 3)
            for name, value in zip(JOINT_NAMES, np.nanmean(visibility, axis=0))
        },
        "warnings": [],
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    analysis_id: str
    input: Dict[str, Any]
    status: str = "queued"
    stage: Optional[str] = None
    created_at: datetime = field(default_factory=_now)
    finished_at: Optional[datetime] = None
    error: Optional[Dict[str, str]] = None
    result: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    recorded_at: Optional[datetime] = None
    video_storage_path: Optional[str] = None
    storage_bucket: Optional[str] = None
    video_size_bytes: Optional[int] = None
    content_type: Optional[str] = None
    worker_id: str = ""


class JobManager:
    def __init__(
        self,
        store: ReferenceStore,
        pipeline_factory: Callable[[], SwingPipeline],
        reference_fps: float,
        worker_id: str,
    ):
        self.store = store
        self.reference_fps = reference_fps
        self.worker_id = worker_id
        self._pipeline_factory = pipeline_factory
        self._pipeline: Optional[SwingPipeline] = None
        # 이벤트 기반 기준 모델(0.2). 파일이 없으면 기존 0.1 비교를 쓴다.
        self.model_v2 = load_reference_model()
        if self.model_v2 is not None:
            logger.info("기준 모델 %s 사용 (스윙 %d개)", self.model_v2.model_version, self.model_v2.swings_used)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swing-worker")

    @property
    def pipeline_loaded(self) -> bool:
        return self._pipeline is not None

    def get(self, analysis_id: str) -> Optional[Job]:
        with database.SessionLocal() as db:
            row = db.get(Swing, analysis_id)
            if row is None:
                return None
            values = {name: getattr(row, name) for name in Job.__dataclass_fields__}
            # SQLite 테스트도 PostgreSQL과 같은 UTC 응답을 사용한다.
            for name in ("created_at", "finished_at", "recorded_at"):
                if values[name] is not None and values[name].tzinfo is None:
                    values[name] = values[name].replace(tzinfo=timezone.utc)
            return Job(**values)

    def _add(self, job: Job) -> None:
        job.worker_id = self.worker_id
        with database.SessionLocal.begin() as db:
            db.add(Swing(**asdict(job)))

    def _save(self, job: Job) -> None:
        with database.SessionLocal.begin() as db:
            db.execute(update(Swing).where(Swing.analysis_id == job.analysis_id).values(**asdict(job)))

    def recover_interrupted(self) -> None:
        """단일 프로세스 실행 전제. 다른 팀원의 진행 중 작업은 건드리지 않는다."""
        with database.SessionLocal.begin() as db:
            # 회원 테이블도 시작 시 검사한다. create_all로 migration을 우회하지 않는다.
            db.execute(select(database.User.user_id).limit(1))
            db.execute(update(Swing).where(
                Swing.worker_id == self.worker_id,
                Swing.status.in_(("queued", "processing")),
            ).values(status="failed", stage=None, finished_at=_now(), error={
                "code": "SERVER_RESTARTED",
                "message": "서버가 중단되어 분석을 완료하지 못했습니다. 영상을 다시 업로드하세요.",
            }))

    def create_video_job(self, input_info: dict, **metadata) -> Job:
        job = Job(analysis_id=uuid.uuid4().hex, input=input_info, stage="uploading", **metadata)
        suffix = input_info["suffix"]
        job.video_storage_path = f"swings/{job.analysis_id}/original{suffix}"
        self._add(job)
        return job

    def fail(self, job: Job, code: str, message: str) -> None:
        job.status, job.stage, job.finished_at = "failed", None, _now()
        job.error, job.result = {"code": code, "message": message}, None
        self._save(job)

    def complete_mock(self, job: Job, report: dict) -> Job:
        job.status, job.stage, job.finished_at = "done", None, _now()
        job.result = report
        self._save(job)
        return job

    def compare_features(self, features, fps: float, input_info: Dict[str, Any], mock_report=None) -> Job:
        """이미 추출된 피처(.npy)로 바로 비교한다. 빠르므로 동기로 처리한다."""
        job = Job(analysis_id=uuid.uuid4().hex, input=input_info, status="processing", stage="comparing")
        self._add(job)
        try:
            if mock_report is not None:
                job.input = {**job.input, "mock": True}
                job.result = mock_report
            else:
                comparison = SwingComparison(
                    self.store,
                    features,
                    user_fps=fps,
                    reference_fps=self.reference_fps,
                    quality={"feature_fps": fps},
                )
                job.result = comparison.report(include_series=True)
            job.status = "done"
        except Exception:
            job.status, job.error = "failed", {"code": "INTERNAL_ERROR", "message": "피처 비교 중 서버 오류가 발생했습니다."}
            raise
        finally:
            job.stage, job.finished_at = None, _now()
            self._save(job)
        return job

    def submit_video(self, job: Job, video_path: str, is_left: bool) -> Job:
        job.stage = None
        self._save(job)
        self._executor.submit(self._run_video, job, video_path, is_left)
        return job

    def _run_video(self, job: Job, video_path: str, is_left: bool) -> None:
        job.status = "processing"

        def on_stage(name: str) -> None:
            job.stage = name
            self._save(job)

        try:
            self._save(job)
            if self._pipeline is None:
                on_stage("loading_models")
                self._pipeline = self._pipeline_factory()
            # 0.2 는 자르기 전 스켈레톤이 필요하다. 그 기능이 없는 파이프라인이면 0.1 로 돈다.
            use_v2 = self.model_v2 is not None and hasattr(self._pipeline, "extract_skeleton")
            if use_v2:
                # 0.2: 이벤트 기반. 80프레임으로 자르기 전 스켈레톤을 그대로 쓴다.
                skeleton = self._pipeline.extract_skeleton(video_path, is_left=is_left, on_stage=on_stage)
                on_stage("comparing")
                job.result = SwingComparisonV2(
                    self.model_v2,
                    skeleton.landmarks_pixel,
                    skeleton.fps,
                    quality=_skeleton_quality(skeleton),
                    handedness="left" if is_left else "right",
                ).report(include_series=True)
            else:
                # 0.1: 임팩트 기준 80프레임 + DTW (기준 모델 파일이 없을 때)
                result = self._pipeline.run(video_path, is_left=is_left, on_stage=on_stage)
                on_stage("comparing")
                job.result = SwingComparison(
                    self.store,
                    result.features,
                    user_fps=result.fps,
                    reference_fps=self.reference_fps,
                    quality=result.quality,
                ).report(include_series=True)
            job.status = "done"
        except PipelineError as exc:
            job.status, job.error = "failed", {"code": exc.code, "message": exc.message}
        except Exception:  # 파이프라인 내부 예외도 작업 실패로 기록
            logger.exception("analysis %s failed", job.analysis_id)
            job.status, job.error = "failed", {"code": "INTERNAL_ERROR", "message": "분석 중 서버 오류가 발생했습니다."}
        finally:
            job.stage = None
            job.finished_at = _now()
            try:
                self._save(job)
            except Exception:
                logger.exception("analysis %s state could not be saved; recover on restart", job.analysis_id)
            finally:
                try:
                    os.remove(video_path)
                except OSError:
                    pass

    def shutdown(self) -> None:
        # 정상 종료 때는 접수한 작업을 끝내고 임시 파일까지 정리한다.
        self._executor.shutdown(wait=True)
