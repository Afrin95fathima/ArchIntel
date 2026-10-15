"""Bounded source tasks, changesets, contracts and build attempts."""
from alembic import op
import sqlalchemy as sa
revision = '0007'
down_revision = '0006'
branch_labels = depends_on = None


def identity():
    return [sa.Column('id', sa.String(36), primary_key=True), sa.Column('tenant_id', sa.String(36), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table('transformation_tasks', *identity(),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('version_id', sa.String(36), sa.ForeignKey('architecture_versions.id'), nullable=False),
        sa.Column('assessment_id', sa.String(36), sa.ForeignKey('modernization_assessments.id'), nullable=False),
        sa.Column('repository_id', sa.String(36), sa.ForeignKey('security_repositories.id'), nullable=False),
        sa.Column('actor_id', sa.String(36), nullable=False), sa.Column('state', sa.String(30), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.Column('document', sa.JSON(), nullable=False), sa.Column('history', sa.JSON(), nullable=False), sa.UniqueConstraint('tenant_id', 'fingerprint'))
    common = lambda: [*identity(), sa.Column('task_id', sa.String(36), sa.ForeignKey('transformation_tasks.id'), nullable=False), sa.Column('actor_id', sa.String(36), nullable=False), sa.Column('document', sa.JSON(), nullable=False)]
    op.create_table('transformation_changesets', *common(), sa.Column('state', sa.String(30), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('approval', sa.JSON()))
    op.create_table('transformation_contracts', *common(), sa.Column('review', sa.JSON()))
    op.create_table('transformation_builds', *common(), sa.Column('kind', sa.String(20), nullable=False), sa.Column('state', sa.String(30), nullable=False))
    for table in ('transformation_tasks', 'transformation_changesets', 'transformation_contracts', 'transformation_builds'):
        op.create_index('ix_' + table + '_tenant_id', table, ['tenant_id'])
        op.create_index('ix_' + table + ('_version_id' if table == 'transformation_tasks' else '_task_id'), table, ['version_id' if table == 'transformation_tasks' else 'task_id'])


def downgrade():
    for table in ('transformation_builds', 'transformation_contracts', 'transformation_changesets', 'transformation_tasks'): op.drop_table(table)
