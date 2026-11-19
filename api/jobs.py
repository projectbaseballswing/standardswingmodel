"""분석 작업 저장소와 워커.

영상 분석은 오래 걸리므로 요청을 받으면 작업만 등록하고, 워커 스레드 1개가 순서대로 처리한다.
YOLO 추적(model.track(persist=True))은 모델 객체에 추적 상태를 저장하므로 동시에 여러 영상을
돌리면 안 된다. 그래서 워커는 1개로 고정한다.

작업 상태와 결과는 SQLAlchemy로 저장하고 요청/워커마다 별도 세션을 사용한다.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import select, update

from api import database
from api.database import Swing
from feedback.compare import MODEL_VERSION, SwingComparison
from feedback.compare_v2 import SwingComparisonV2
from feedback.llm_coach import generate_coaching, generate_extended_coaching
from feedback.coaching_review import (
    PRIVATE_KEY, capture_review, capture_extended_review, context_for, report_fingerprint,
)
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


def _world_landmarks(skeleton):
    """깊이 점검용 MediaPipe 월드 좌표. 3D 보존에 실패했거나 없으면 None (점검을 건너뛴다)."""
    capture = getattr(skeleton, "pose3d_capture", None)
    return capture.get("world_raw") if isinstance(capture, dict) else None


def _attach_motion(result: Dict[str, Any], skeleton, events) -> None:
    """기준 동작과 겹쳐 그릴 사용자 스켈레톤 (/reference-motion). 점수와 무관해서 실패해도 분석은 그대로."""
    try:
        from feedback.reference_motion import user_motion
        result["motion"] = user_motion(skeleton.landmarks_pixel, skeleton.fps, events.as_dict())
    except Exception:
        logger.warning("reference motion skipped", exc_info=True)
    _attach_shadow_scores(result)


def _attach_shadow_scores(result: Dict[str, Any]) -> None:
    """VAE 거리 점수 후보를 기록만 한다 (API 응답에는 나가지 않음, docs/pose-vae.md '점수 반영').
    기존 점수와 실제 사용자 데이터로 나란히 비교한 뒤 점수 반영을 정한다."""
    phases = (result.get("motion") or {}).get("phases")
    if not phases:
        return
    try:
        from feedback.pose_vae import load_pose_vae, shadow_scores

        model = load_pose_vae()
        if model is not None:
            result["shadow_scores"] = {"pose_vae": shadow_scores(model, phases)}
    except Exception:
        logger.warning("shadow scores skipped", exc_info=True)


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
        openai_api_key: str = "",
        openai_model: str = "",
        coaching_scope: str = "overall",
        pose_storage_factory=None,
    ):
        self.store = store
        self.reference_fps = reference_fps
        self.worker_id = worker_id
        # LLM(OpenAI) 코칭 문장. 키가 비어 있으면 호출하지 않고 프론트 규칙 기반 폴백을 둔다.
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.coaching_scope = coaching_scope
        self._pose_storage_factory = pose_storage_factory
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

    @staticmethod
    def _supports_v2(pipeline) -> bool:
        """0.2 는 80프레임으로 자르기 전 스켈레톤이 필요하다."""
        return hasattr(pipeline, "extract_skeleton")

    @property
    def model_version(self) -> str:
        """실제 분석에 쓰이는 기준 모델 버전. /health 가 이 값을 알린다.

        파이프라인은 첫 요청 때 만들어지므로, 그 전에는 기준 모델 파일 유무만으로 답한다.
        """
        if self.model_v2 is None:
            return MODEL_VERSION
        if self._pipeline is not None and not self._supports_v2(self._pipeline):
            return MODEL_VERSION
        return self.model_v2.model_version

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
            db.execute(select(database.AuthSession.token_hash).limit(1))
            db.execute(update(Swing).where(
                Swing.worker_id == self.worker_id,
                Swing.status.in_(("queued", "processing")),
            ).values(status="failed", stage=None, finished_at=_now(), error={
                "code": "SERVER_RESTARTED",
                "message": "서버가 중단되어 분석을 완료하지 못했습니다. 영상을 다시 업로드하세요.",
            }))
            db.execute(update(database.Pose3D).where(
                database.Pose3D.analysis_id.in_(select(Swing.analysis_id).where(Swing.worker_id == self.worker_id)),
                database.Pose3D.status.in_(("pending", "processing")),
            ).values(status="failed", updated_at=_now(), error={
                "code":"SERVER_RESTARTED", "message":"3D 생성 중 서버가 중단되었습니다. 점수 결과는 별도로 유지됩니다."
            }))

    def create_video_job(self, input_info: dict, **metadata) -> Job:
        job = Job(analysis_id=uuid.uuid4().hex, input=input_info, stage="uploading", **metadata)
        suffix = input_info["suffix"]
        job.video_storage_path = f"swings/{job.analysis_id}/original{suffix}"
        self._add(job)
        from api.pose3d import init_pose
        try:
            init_pose(job)
        except Exception as exc:
            # The score job already exists. Optional display initialization
            # must not stop the original upload/analysis workflow.
            logger.warning("3D initialization failed for %s: %s", job.analysis_id, type(exc).__name__)
        return job

    def fail(self, job: Job, code: str, message: str) -> None:
        job.status, job.stage, job.finished_at = "failed", None, _now()
        job.error, job.result = {"code": code, "message": message}, None
        self._save(job)
        from api.pose3d import fail_pose
        fail_pose(job.analysis_id, code, "영상 분석이 실패하여 3D 데이터를 만들 수 없습니다.")

    def complete_mock(self, job: Job, report: dict) -> Job:
        job.status, job.stage, job.finished_at = "done", None, _now()
        job.result = report
        self._save(job)
        from api.pose3d import fail_pose
        fail_pose(job.analysis_id,"MOCK_HAS_NO_WORLD","목업 점수에는 실제 World 좌표가 없습니다. 샘플로 대체하지 않습니다.")
        return job

    def compare_features(self, features, fps: float, input_info: Dict[str, Any], mock_report=None, user_id=None) -> Job:
        """이미 추출된 피처(.npy)로 바로 비교한다. 빠르므로 동기로 처리한다."""
        job = Job(analysis_id=uuid.uuid4().hex, input=input_info, status="processing", stage="comparing", user_id=user_id)
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

    def _attach_overall_coaching(self, job: Job) -> None:
        """Capture an optional GPT candidate privately; never auto-publish it."""
        if not isinstance(job.result, dict):
            return
        sink = {}
        failure_reason = "not_configured" if not self.openai_api_key else "generation_failed"
        if self.openai_api_key:
            try:
                generate_coaching(
                    job.result, api_key=self.openai_api_key, model=self.openai_model,
                    scope="overall", review_sink=sink,
                )
            except Exception as error:
                # A coaching failure must not change score/analysis success.
                logger.warning("coaching capture failed (%s)", type(error).__name__)
        job.result["coaching"] = None
        job.result[PRIVATE_KEY] = capture_review(
            job.result, sink, context=context_for(job.analysis_id, job.user_id),
            scope="overall", failure_reason=failure_reason,
        )

    def _attach_extended_coaching(self, job: Job) -> None:
        """Merge new text into the private candidate and invalidate prior approval."""
        if not isinstance(job.result, dict):
            return
        old = job.result.get(PRIVATE_KEY) or {}
        candidate = old.get("candidate")
        if not isinstance(candidate, dict) or not self.openai_api_key:
            return
        sink = {}
        try:
            generate_extended_coaching(
                job.result, api_key=self.openai_api_key, model=self.openai_model,
                review_sink=sink,
            )
        except Exception as error:
            logger.warning("extended coaching capture failed (%s)", type(error).__name__)
        job.result[PRIVATE_KEY] = capture_extended_review(
            job.result, old, sink, context=context_for(job.analysis_id, job.user_id),
        )
        job.result["coaching"] = None

    def _merge_save_coaching(self, job: Job) -> None:
        """Merge only private coaching fields, preserving concurrent 3-D/comparison writes."""
        envelope = job.result.get(PRIVATE_KEY) if isinstance(job.result, dict) else None
        if not isinstance(envelope, dict):
            return
        with database.SessionLocal.begin() as db:
            row = db.execute(
                select(Swing).where(Swing.analysis_id == job.analysis_id).with_for_update()
            ).scalar_one_or_none()
            if row is None or not isinstance(row.result, dict):
                return
            fingerprint = report_fingerprint(row.result)
            if fingerprint is None or fingerprint != envelope.get("report_sha256"):
                return  # A newer analysis revision must be reviewed independently.
            merged = dict(row.result)
            merged["coaching"] = None
            merged[PRIVATE_KEY] = envelope
            row.result = merged

    def _run_video(self, job: Job, video_path: str, is_left: bool) -> None:
        job.status = "processing"
        skeleton = None

        def on_stage(name: str) -> None:
            job.stage = name
            self._save(job)

        try:
            self._save(job)
            if self._pipeline is None:
                on_stage("loading_models")
                self._pipeline = self._pipeline_factory()
            # 0.2 는 자르기 전 스켈레톤이 필요하다. 그 기능이 없는 파이프라인이면 0.1 로 돈다.
            use_v2 = self.model_v2 is not None and self._supports_v2(self._pipeline)
            if use_v2:
                # 0.2: 이벤트 기반. 80프레임으로 자르기 전 스켈레톤을 그대로 쓴다.
                skeleton = self._pipeline.extract_skeleton(video_path, is_left=is_left, on_stage=on_stage)
                on_stage("comparing")
                comparison = SwingComparisonV2(
                    self.model_v2,
                    skeleton.landmarks_pixel,
                    skeleton.fps,
                    quality=_skeleton_quality(skeleton),
                    handedness="left" if is_left else "right",
                    world_landmarks=_world_landmarks(skeleton),
                )
                job.result = comparison.report(include_series=True)
                _attach_motion(job.result, skeleton, comparison.events)
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
            # LLM 코칭은 분석의 선택 단계. 실패해도 분석 결과는 그대로 둔다.
            # 종합(overall+부위)을 먼저 붙이고 바로 done 으로 저장해, 앱이 종합 피드백을
            # 관절·구간 생성(느림)을 기다리지 않고 즉시 볼 수 있게 한다.
            on_stage("coaching")
            self._attach_overall_coaching(job)
            run_extended = (
                self.coaching_scope == "full"
                and isinstance(job.result, dict)
                and isinstance((job.result.get(PRIVATE_KEY) or {}).get("candidate"), dict)
            )
            if run_extended:
                # Extended text stays private until its complete revision is reviewed.
                job.result[PRIVATE_KEY]["extended_status"] = "pending"
            # 목록 화면 썸네일(영상 첫 프레임)은 done 스냅샷에 포함시킨다. done 이후에 만들면
            # 앱이 곧장 호출하는 /comparison 저장과 경쟁해 썸네일 경로가 사라질 수 있다.
            self._make_thumbnail(job, video_path)
            job.status = "done"
            job.finished_at = _now()
            job.stage = None
            # 권위 있는 done 스냅샷(종합+썸네일). done 을 외부에 노출한 이후의 추가 저장은
            # 전체 덮어쓰기(_save) 가 아니라 병합 저장만 해, 다른 writer(이전대비 비교 캐시)의
            # 변경을 지우지 않는다.
            self._save(job)
            # 관절·구간 코칭은 done 이후에 채운다. 느려도 종합 표시를 막지 않는다.
            # done 은 이미 확정 저장했으므로, 여기서 실패해도 분석을 되돌리지 않는다.
            if run_extended:
                try:
                    self._attach_extended_coaching(job)
                    self._merge_save_coaching(job)
                except Exception:
                    logger.exception("extended coaching persist failed for %s", job.analysis_id)
        except PipelineError as exc:
            job.status, job.error = "failed", {"code": exc.code, "message": exc.message}
        except Exception:  # 파이프라인 내부 예외도 작업 실패로 기록
            logger.exception("analysis %s failed", job.analysis_id)
            job.status, job.error = "failed", {"code": "INTERNAL_ERROR", "message": "분석 중 서버 오류가 발생했습니다."}
        finally:
            job.stage = None
            try:
                # done 은 try 안에서 이미 확정 저장했다(썸네일 포함, 코칭은 병합 저장).
                # 여기서 전체 덮어쓰기를 하면 그 사이 들어온 /comparison 저장을 지우므로,
                # 실패/중단 경로일 때만 상태를 저장한다.
                if job.status != "done":
                    job.finished_at = _now()
                    self._save(job)
                # Persist score first. 3D is an independent state/result and
                # never feeds smoothed world coordinates to model 0.2.
                from api.pose3d import fail_pose, persist_pose
                if job.status == 'done' and self._pose_storage_factory is not None:
                    persist_pose(job, skeleton, self._pose_storage_factory)
                else:
                    fail_pose(job.analysis_id, 'ANALYSIS_UNAVAILABLE', '영상의 3D 데이터를 생성하지 못했습니다.')
            except Exception:
                logger.exception("analysis %s state could not be saved; recover on restart", job.analysis_id)
            finally:
                try:
                    os.remove(video_path)
                except OSError:
                    pass

    def _make_thumbnail(self, job: Job, video_path: str) -> None:
        """영상 첫 프레임을 작은 JPEG 썸네일로 저장(목록 화면용). 경로는 결과 JSON에
        기록해 목록 API가 서명 URL을 만든다. 실패해도 분석엔 영향 없다(조용히 건너뜀)."""
        if self._pose_storage_factory is None:
            return
        tmp = None
        try:
            import cv2

            cap = cv2.VideoCapture(video_path)
            ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                return
            h, w = frame.shape[:2]
            if w > 0 and w > 320:  # 목록 썸네일은 작게(가로 320)
                frame = cv2.resize(frame, (320, max(1, round(h * 320 / w))), interpolation=cv2.INTER_AREA)
            fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="thumb_")
            os.close(fd)
            cv2.imwrite(tmp, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            storage = self._pose_storage_factory()
            try:
                path = f"swings/{job.analysis_id}/thumbnail.jpg"
                storage.upload(path, tmp, "image/jpeg")
                result = job.result if isinstance(job.result, dict) else {}
                result["thumbnail"] = {"storage_path": path, "bucket": storage.bucket}
                job.result = result
            finally:
                try:
                    storage.close()
                except Exception:
                    pass
        except Exception:
            logger.warning("thumbnail generation failed for %s", job.analysis_id, exc_info=True)
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def shutdown(self) -> None:
        # 정상 종료 때는 접수한 작업을 끝내고 임시 파일까지 정리한다.
        self._executor.shutdown(wait=True)
