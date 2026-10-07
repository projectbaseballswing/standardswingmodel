"""Persist video locations, job state and existing analysis reports."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    sqlite = op.get_bind().dialect.name == "sqlite"
    # SQLite cannot ADD a non-constant timestamp default to a populated table.
    with op.batch_alter_table("users", recreate="always" if sqlite else "auto") as batch:
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                                   server_default=sa.func.now()))
    json_type = sa.JSON().with_variant(JSONB, "postgresql")
    op.create_table(
        "swings",
        sa.Column("analysis_id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        sa.Column("video_storage_path", sa.String()),
        sa.Column("storage_bucket", sa.String()),
        sa.Column("video_size_bytes", sa.BigInteger()),
        sa.Column("content_type", sa.String()),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("input", json_type, nullable=False),
        sa.Column("error", json_type),
        sa.Column("result", json_type),
        sa.CheckConstraint("status IN ('queued', 'processing', 'done', 'failed')", name="ck_swings_status"),
    )
    op.create_index("ix_swings_user_id", "swings", ["user_id"])
    op.create_index("ix_swings_worker_id", "swings", ["worker_id"])
    if not sqlite:
        # SQLAlchemy connects as the backend DB role. No client-side table access.
        op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE swings ENABLE ROW LEVEL SECURITY")


def downgrade():
    op.drop_table("swings")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("created_at")
