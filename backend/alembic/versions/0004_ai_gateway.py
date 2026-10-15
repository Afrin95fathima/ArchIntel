"""Add tenant-owned provider registrations and content-free invocation records."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=depends_on=None


def identity():
    return [sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False)]


def upgrade():
    op.create_table('ai_providers',*identity(),sa.Column('name',sa.String(120),nullable=False),sa.Column('adapter',sa.String(30),nullable=False),sa.Column('destination',sa.String(40),nullable=False),sa.Column('endpoint',sa.String(200),nullable=False),sa.Column('model',sa.String(120),nullable=False),sa.Column('model_digest',sa.String(80),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False))
    op.create_index('ix_ai_providers_tenant_id','ai_providers',['tenant_id'])
    op.create_table('ai_invocations',*identity(),sa.Column('principal_id',sa.String(36),nullable=False),sa.Column('provider_id',sa.String(36),nullable=False),sa.Column('resource',sa.String(120),nullable=False),sa.Column('outcome',sa.String(30),nullable=False),sa.Column('reason',sa.String(80),nullable=False),sa.Column('metadata_json',sa.JSON(),nullable=False))
    op.create_index('ix_ai_invocations_tenant_id','ai_invocations',['tenant_id'])


def downgrade():
    op.drop_table('ai_invocations')
    op.drop_table('ai_providers')
