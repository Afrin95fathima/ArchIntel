"""Automated exploration and conversion jobs run through the host-side runner."""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('automation_jobs',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('analysis_id', sa.String(36), nullable=True), sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('state', sa.String(20), nullable=False), sa.Column('actor_id', sa.String(36), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False), sa.Column('document', sa.JSON(), nullable=False))
    for column in ('tenant_id', 'application_id', 'analysis_id'):
        op.create_index(f'ix_automation_jobs_{column}', 'automation_jobs', [column])


def downgrade():
    op.drop_table('automation_jobs')
