"""분석 작업 저장소와 워커.

영상 분석은 오래 걸리므로 요청을 받으면 작업만 등록하고, 워커 스레드 1개가 순서대로 처리한다.
YOLO 추적(model.track(persist=True))은 모델 객체에 추적 상태를 저장하므로 동시에 여러 영상을
돌리면 안 된다. 그래서 워커는 1개로 고정한다.

작업 결과는 메모리에만 저장된다. 서버를 재시작하면 사라진다.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from feedback.compare import SwingComparison
from feedback.pipeline import PipelineError, SwingPipeline
from feedback.reference import ReferenceStore

logger = logging.getLogger(__name__)


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


class JobManager:
    def __init__(
        self,
        store: ReferenceStore,
        pipeline_factory: Callable[[], SwingPipeline],
        reference_fps: float,
        max_jobs: int = 200,
    ):
        self.store = store
        self.reference_fps = reference_fps
        self.max_jobs = max_jobs
        self._pipeline_factory = pipeline_factory
        self._pipeline: Optional[SwingPipeline] = None
        self._jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swing-worker")

    @property
    def pipeline_loaded(self) -> bool:
        return self._pipeline is not None

    def get(self, analysis_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(analysis_id)

    def _add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.analysis_id] = job
            # 오래된 완료 작업부터 정리
            while len(self._jobs) > self.max_jobs:
                oldest_id, oldest = next(iter(self._jobs.items()))
                if oldest.status in ("queued", "processing"):
                    break
                del self._jobs[oldest_id]

    def compare_features(self, features, fps: float, input_info: Dict[str, Any]) -> Job:
        """이미 추출된 피처(.npy)로 바로 비교한다. 빠르므로 동기로 처리한다."""
        job = Job(analysis_id=uuid.uuid4().hex, input=input_info, status="processing", stage="comparing")
        self._add(job)
        try:
            comparison = SwingComparison(
                self.store,
                features,
                user_fps=fps,
                reference_fps=self.reference_fps,
                quality={"feature_fps": fps},
            )
            job.result = comparison.report(include_series=True)
            job.status = "done"
        except Exception as exc:
            job.status, job.error = "failed", {"code": "INTERNAL_ERROR", "message": str(exc)}
            raise
        finally:
            job.stage, job.finished_at = None, _now()
        return job

    def submit_video(self, video_path: str, is_left: bool, input_info: Dict[str, Any]) -> Job:
        job = Job(analysis_id=uuid.uuid4().hex, input=input_info)
        self._add(job)
        self._executor.submit(self._run_video, job, video_path, is_left)
        return job

    def _run_video(self, job: Job, video_path: str, is_left: bool) -> None:
        job.status = "processing"

        def on_stage(name: str) -> None:
            job.stage = name

        try:
            if self._pipeline is None:
                on_stage("loading_models")
                self._pipeline = self._pipeline_factory()
            result = self._pipeline.run(video_path, is_left=is_left, on_stage=on_stage)
            on_stage("comparing")
            comparison = SwingComparison(
                self.store,
                result.features,
                user_fps=result.fps,
                reference_fps=self.reference_fps,
                quality=result.quality,
            )
            job.result = comparison.report(include_series=True)
            job.status = "done"
        except PipelineError as exc:
            job.status, job.error = "failed", {"code": exc.code, "message": exc.message}
        except Exception as exc:  # 파이프라인 내부 예외도 작업 실패로 기록
            logger.exception("analysis %s failed", job.analysis_id)
            job.status, job.error = "failed", {"code": "INTERNAL_ERROR", "message": str(exc)}
        finally:
            job.stage = None
            job.finished_at = _now()
            try:
                os.remove(video_path)
            except OSError:
                pass

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
