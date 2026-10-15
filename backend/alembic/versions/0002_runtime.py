"""Add isolated runtime sessions and sanitized span evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = depends_on = None


def upgrade():
    op.create_table('runtime_sessions',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('analysis_id', sa.String(36), sa.ForeignKey('analysis_runs.id'), nullable=False),
        sa.Column('name', sa.String(160), nullable=False), sa.Column('environment', sa.String(80), nullable=False),
        sa.Column('status', sa.String(30), nullable=False), sa.Column('token_hash', sa.String(64), nullable=False),
        *[sa.Column(n, sa.DateTime(timezone=True)) for n in ['started_at','ended_at','last_received_at']],
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        *[sa.Column(n, sa.Integer(), nullable=False) for n in ['span_count','trace_count','dropped_count']],
        sa.Column('settings', sa.JSON(), nullable=False), sa.Column('result', sa.JSON()))
    for name in ['tenant_id','application_id','analysis_id']:
        op.create_index('ix_runtime_sessions_'+name, 'runtime_sessions', [name])
    op.create_table('runtime_events', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('runtime_sessions.id'), nullable=False),
        sa.Column('trace_id', sa.String(32), nullable=False), sa.Column('span_id', sa.String(16), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False), sa.Column('data', sa.JSON(), nullable=False),
        sa.UniqueConstraint('session_id','trace_id','span_id',name='uq_runtime_span'))
    op.create_index('ix_runtime_events_session_id','runtime_events',['session_id'])
    op.create_index('ix_runtime_events_received_at','runtime_events',['received_at'])


def downgrade():
    op.drop_table('runtime_events')
    op.drop_table('runtime_sessions')
