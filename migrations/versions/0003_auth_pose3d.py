"""Verified bearer sessions and private display-pose metadata; no score changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('auth_sessions',
        sa.Column('token_hash',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.String(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revoked_at',sa.DateTime(timezone=True)))
    op.create_index('ix_auth_sessions_user_id','auth_sessions',['user_id'])
    op.create_index('ix_auth_sessions_expires_at','auth_sessions',['expires_at'])
    j=sa.JSON().with_variant(JSONB,'postgresql')
    op.create_table('pose_3d',
        sa.Column('analysis_id',sa.String(32),sa.ForeignKey('swings.analysis_id'),primary_key=True),
        sa.Column('user_id',sa.String(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),
        sa.Column('contract_version',sa.String(48),nullable=False),
        sa.Column('storage_path',sa.String()),sa.Column('storage_bucket',sa.String()),
        sa.Column('payload_sha256',sa.String(64)),sa.Column('frame_count',sa.BigInteger()),
        sa.Column('raw_size_bytes',sa.BigInteger()),sa.Column('compressed_size_bytes',sa.BigInteger()),
        sa.Column('handedness',sa.String(16)),sa.Column('coordinate_convention',sa.String()),
        sa.Column('timestamps_s',j),sa.Column('warnings',j,nullable=False),sa.Column('error',j),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("status IN ('pending', 'processing', 'ready', 'failed')",name='ck_pose3d_status'))
    op.create_index('ix_pose_3d_user_id','pose_3d',['user_id'])
    if op.get_bind().dialect.name!='sqlite':
        op.execute('ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE pose_3d ENABLE ROW LEVEL SECURITY')
        # Supabase may grant new public tables to client roles by default.
        # These tables are accessed only through the server's DB connection.
        # Touch no existing users/swings grants or shared Storage policies.
        op.execute("""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    REVOKE ALL ON auth_sessions, pose_3d FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON auth_sessions, pose_3d FROM authenticated;
                END IF;
            END $$;
        """)
def downgrade():
    op.drop_table('pose_3d');op.drop_table('auth_sessions')
