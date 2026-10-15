"""Immutable modernization assessments and append-only planning reviews."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = depends_on = None


def identity():
    return [sa.Column('id', sa.String(36), primary_key=True), sa.Column('tenant_id', sa.String(36), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table('modernization_assessments', *identity(),
        sa.Column('version_id', sa.String(36), sa.ForeignKey('architecture_versions.id'), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('actor_id', sa.String(36), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False), sa.Column('projection_state', sa.String(20), nullable=False),
        sa.Column('projection_attempts', sa.Integer(), nullable=False), sa.Column('projection_error', sa.String(60)),
        sa.UniqueConstraint('tenant_id', 'fingerprint'))
    op.create_table('modernization_reviews', *identity(),
        sa.Column('assessment_id', sa.String(36), sa.ForeignKey('modernization_assessments.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.Column('actor_id', sa.String(36), nullable=False),
        sa.Column('state', sa.String(30), nullable=False), sa.Column('note', sa.String(2000), nullable=False),
        sa.UniqueConstraint('assessment_id', 'revision'))
    for table, reference in [('modernization_assessments', 'version_id'), ('modernization_reviews', 'assessment_id')]:
        op.create_index('ix_' + table + '_tenant_id', table, ['tenant_id'])
        op.create_index('ix_' + table + '_' + reference, table, [reference])


def downgrade():
    op.drop_table('modernization_reviews')
    op.drop_table('modernization_assessments')
