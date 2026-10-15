"""Add canonical architecture versions, evidence, facts and projection outbox."""
from alembic import op
import sqlalchemy as sa
revision='0005'
down_revision='0004'
branch_labels=depends_on=None

def identity():
    return [sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False)]

def version_ref():return sa.Column('version_id',sa.String(36),sa.ForeignKey('architecture_versions.id'),nullable=False)

def upgrade():
    op.create_table('architecture_versions',*identity(),sa.Column('application_id',sa.String(36),sa.ForeignKey('applications.id'),nullable=False),sa.Column('analysis_id',sa.String(36),sa.ForeignKey('analysis_runs.id'),nullable=False),sa.Column('parent_id',sa.String(36),sa.ForeignKey('architecture_versions.id')),sa.Column('name',sa.String(160),nullable=False),sa.Column('fingerprint',sa.String(64),nullable=False),sa.Column('manifest',sa.JSON(),nullable=False),sa.Column('document',sa.JSON(),nullable=False),sa.UniqueConstraint('tenant_id','fingerprint'))
    op.create_table('architecture_evidence',*identity(),version_ref(),sa.Column('kind',sa.String(30),nullable=False),sa.Column('document',sa.JSON(),nullable=False))
    op.create_table('architecture_facts',*identity(),version_ref(),sa.Column('classification',sa.String(30),nullable=False),sa.Column('document',sa.JSON(),nullable=False))
    op.create_table('architecture_projections',*identity(),version_ref(),sa.Column('state',sa.String(20),nullable=False),sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('content_hash',sa.String(64),nullable=False),sa.Column('error_code',sa.String(60)),sa.UniqueConstraint('version_id'))
    op.create_table('architecture_discovery',*identity(),version_ref(),sa.Column('priority',sa.Integer(),nullable=False),sa.Column('state',sa.String(20),nullable=False),sa.Column('document',sa.JSON(),nullable=False),sa.Column('history',sa.JSON(),nullable=False))
    for table in ('architecture_versions','architecture_evidence','architecture_facts','architecture_projections','architecture_discovery'):
        op.create_index('ix_'+table+'_tenant_id',table,['tenant_id'])
        if table!='architecture_versions':op.create_index('ix_'+table+'_version_id',table,['version_id'])
    op.create_index('ix_architecture_versions_application_id','architecture_versions',['application_id'])

def downgrade():
    for table in ('architecture_discovery','architecture_projections','architecture_facts','architecture_evidence','architecture_versions'):op.drop_table(table)
