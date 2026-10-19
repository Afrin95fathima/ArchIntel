"""Persist structured ingestion limit rejections."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('analysis_runs', sa.Column('limit_details', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('analysis_runs', 'limit_details')
