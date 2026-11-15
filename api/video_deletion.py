"""Delete exactly one original video; analysis and pose rows are never updated.

Intent -> Storage removal -> DB tombstone. A crash/network/commit failure leaves
the intent and original path durable, so the same authenticated DELETE can resume.
PostgreSQL row locks serialize callers; Storage removal is also idempotent.
"""
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from api.database import Pose3D, Swing
from api.storage import StorageError, StorageObjectNotFound
from api.video_validation import VIDEO_TYPES


def video_status(row):
    if row.video_deleted_at is not None:
        return "deleted"
    if row.video_delete_requested_at is not None:
        return "deleting"
    return "available" if row.video_storage_path else "unavailable"


def locked_swing(db, analysis_id, user_id):
    row = db.scalar(select(Swing).where(Swing.analysis_id == analysis_id)
                    .execution_options(populate_existing=True).with_for_update())
    if row is None:
        raise HTTPException(404, "분석 결과를 찾을 수 없습니다.")
    if row.user_id != user_id:
        raise HTTPException(403, "이 분석에 접근할 권한이 없습니다.")
    return row


def _target(row, storage):
    # Match the existing uploader's canonical object key, never user filenames,
    # request bodies, arbitrary folders, or a pose3d path.
    allowed = {f"swings/{row.analysis_id}/original{suffix}" for suffix in VIDEO_TYPES}
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row.analysis_id)
            or row.video_storage_path not in allowed
            or row.storage_bucket != storage.bucket):
        raise HTTPException(409, "원본 영상 저장 경로를 검증할 수 없어 삭제하지 않았습니다.")


def delete_original_video(db, analysis_id, user_id, storage_factory):
    row = locked_swing(db, analysis_id, user_id)
    if row.video_deleted_at is not None:
        return {"analysis_id": analysis_id, "video_status": "deleted", "already_deleted": True}
    if row.status not in ("done", "failed") or row.stage == "uploading":
        raise HTTPException(409, "분석 진행 중에는 원본 영상을 삭제할 수 없습니다.")
    pose = db.get(Pose3D, analysis_id)
    if pose is not None and pose.status in ("pending", "processing"):
        raise HTTPException(409, "3D 생성 중에는 원본 영상을 삭제할 수 없습니다.")
    if not row.video_storage_path:
        raise HTTPException(404, "삭제할 원본 영상 정보가 없습니다.")
    storage = storage_factory()
    _target(row, storage)
    if row.video_delete_requested_at is None:
        row.video_delete_requested_at = datetime.now(timezone.utc)
    db.commit()  # A failed intent commit must never delete bytes.

    row = locked_swing(db, analysis_id, user_id)
    if row.video_deleted_at is not None:
        return {"analysis_id": analysis_id, "video_status": "deleted", "already_deleted": True}
    _target(row, storage)
    try:
        storage.delete(row.storage_bucket, row.video_storage_path)
    except StorageObjectNotFound:
        pass  # Missing already, including a prior successful delete/failed commit.
    except StorageError:
        db.rollback()
        raise HTTPException(502, "원본 영상 삭제를 완료하지 못했습니다. 다시 삭제를 요청해주세요. 분석 기록은 유지됩니다.") from None
    row.video_deleted_at = datetime.now(timezone.utc)
    row.video_storage_path = None
    row.storage_bucket = None
    row.video_size_bytes = None
    row.content_type = None
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "영상 삭제 상태를 저장하지 못했습니다. 다시 삭제를 요청하면 상태를 복구합니다.") from None
    return {"analysis_id": analysis_id, "video_status": "deleted", "already_deleted": False}
