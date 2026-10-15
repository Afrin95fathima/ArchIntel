"""Persist projects, artifacts and immutable analysis snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def identity():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('tenant_id', sa.String(36), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table('projects', *identity(), sa.Column('name', sa.String(160), nullable=False), sa.Column('description', sa.Text(), nullable=False))
    op.create_table('applications', *identity(), sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False), sa.Column('name', sa.String(160), nullable=False), sa.Column('version', sa.String(80), nullable=False), sa.Column('source_type', sa.String(20), nullable=False))
    op.create_table('artifacts', *identity(), sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False), sa.Column('filename', sa.String(255), nullable=False), sa.Column('path', sa.Text(), nullable=False), sa.Column('sha256', sa.String(64), nullable=False), sa.Column('size', sa.Integer(), nullable=False), sa.Column('available', sa.Boolean(), nullable=False), sa.Column('manifest', sa.JSON(), nullable=False))
    op.create_table('analysis_runs', *identity(), sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False), sa.Column('artifact_id', sa.String(36), sa.ForeignKey('artifacts.id'), nullable=False), sa.Column('status', sa.String(40), nullable=False), sa.Column('progress', sa.Integer(), nullable=False), sa.Column('stage', sa.String(80), nullable=False), sa.Column('started_at', sa.DateTime(timezone=True)), sa.Column('completed_at', sa.DateTime(timezone=True)), sa.Column('error_message', sa.Text()), sa.Column('stages', sa.JSON(), nullable=False), sa.Column('result', sa.JSON()))
    for table in ('projects', 'applications', 'artifacts', 'analysis_runs'):
        op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])
    for table, column in [('applications','project_id'), ('artifacts','application_id'), ('analysis_runs','application_id'), ('analysis_runs','status')]:
        op.create_index(f'ix_{table}_{column}', table, [column])


def downgrade():
    for table in ('analysis_runs', 'artifacts', 'applications', 'projects'):
        op.drop_table(table)
