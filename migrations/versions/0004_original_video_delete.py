"""Track recoverable original-video deletion; preserve every analysis row."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("swings", sa.Column("video_delete_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("swings", sa.Column("video_deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Destructive to deletion history, never restores deleted Storage bytes.
    op.drop_column("swings", "video_deleted_at")
    op.drop_column("swings", "video_delete_requested_at")
