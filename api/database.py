"""기존 회원 ORM과 스윙 분석 영속 저장. 스키마 변경은 Alembic으로 실행한다."""

from datetime import datetime, timezone
import re

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, BigInteger, create_engine, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from api.settings import settings


def utcnow():
    return datetime.now(timezone.utc)


def create_database_engine(url: str):
    if not url:
        raise RuntimeError("DATABASE_URL을 .env에 설정하고 alembic upgrade head를 실행하세요.")
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    options = {"pool_pre_ping": True, "hide_parameters": True}
    if parsed.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
    db_engine = create_engine(parsed, **options)
    if settings.database_schema:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", settings.database_schema):
            raise ValueError("SWING_DATABASE_SCHEMA must be a simple lowercase identifier")
        if parsed.get_backend_name() == "postgresql":
            @event.listens_for(db_engine, "connect")
            def select_schema(connection, _):
                # Resolve users, swings and new tables in exactly one schema.
                # Staging never falls through to production public tables.
                before = connection.autocommit
                connection.autocommit = True
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('search_path', %s, false)", (settings.database_schema,))
                finally:
                    connection.autocommit = before
    if parsed.get_backend_name() == "sqlite":
        @event.listens_for(db_engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return db_engine


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    # 스펙의 "id" = 로그인용 사용자 아이디 (문자열)
    user_id: Mapped[str] = mapped_column("id", String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    nickname: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class Swing(Base):
    """기존 analysis_id 하나에 업로드와 피드백을 함께 저장한다."""

    __tablename__ = "swings"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'processing', 'done', 'failed')", name="ck_swings_status"),
    )

    analysis_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    video_storage_path: Mapped[str | None] = mapped_column(String)
    storage_bucket: Mapped[str | None] = mapped_column(String)
    video_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String)
    worker_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    error: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Pose3D(Base):
    __tablename__ = "pose_3d"
    __table_args__ = (CheckConstraint("status IN ('pending', 'processing', 'ready', 'failed')", name="ck_pose3d_status"),)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("swings.analysis_id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    contract_version: Mapped[str] = mapped_column(String(48), default="EXP008-pose3d-v1")
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_bucket: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frame_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    compressed_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    handedness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    coordinate_convention: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamps_s: Mapped[list | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    warnings: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
    error: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


engine = create_database_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    """FastAPI 의존성: 요청마다 DB 세션을 열고 닫는다."""
    with SessionLocal() as session:
        yield session
