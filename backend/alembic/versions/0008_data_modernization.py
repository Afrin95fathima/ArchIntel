"""Persist source data discovery, versioned plans and isolated test runs."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = depends_on = None


def identity():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('tenant_id', sa.String(36), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table('transformation_data_discovery_runs', *identity(),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('transformation_tasks.id'), nullable=False),
        sa.Column('actor_id', sa.String(36), nullable=False),
        sa.Column('state', sa.String(30), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False))
    op.create_index('ix_transformation_data_discovery_runs_tenant_id', 'transformation_data_discovery_runs', ['tenant_id'])
    op.create_index('ix_transformation_data_discovery_runs_task_id', 'transformation_data_discovery_runs', ['task_id'])
    op.create_table('transformation_data_migration_plans', *identity(),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('transformation_tasks.id'), nullable=False),
        sa.Column('discovery_id', sa.String(36), sa.ForeignKey('transformation_data_discovery_runs.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(30), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False), sa.Column('review', sa.JSON()))
    for table in ('transformation_data_migration_plans',):
        op.create_index('ix_' + table + '_tenant_id', table, ['tenant_id'])
        op.create_index('ix_' + table + '_task_id', table, ['task_id'])
        op.create_index('ix_' + table + '_discovery_id', table, ['discovery_id'])
    op.create_table('transformation_data_migration_runs', *identity(),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('transformation_tasks.id'), nullable=False),
        sa.Column('plan_id', sa.String(36), sa.ForeignKey('transformation_data_migration_plans.id'), nullable=False),
        sa.Column('actor_id', sa.String(36), nullable=False),
        sa.Column('state', sa.String(30), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False))
    op.create_index('ix_transformation_data_migration_runs_tenant_id', 'transformation_data_migration_runs', ['tenant_id'])
    op.create_index('ix_transformation_data_migration_runs_task_id', 'transformation_data_migration_runs', ['task_id'])
    op.create_index('ix_transformation_data_migration_runs_plan_id', 'transformation_data_migration_runs', ['plan_id'])


def downgrade():
    op.drop_table('transformation_data_migration_runs')
    op.drop_table('transformation_data_migration_plans')
    op.drop_table('transformation_data_discovery_runs')
