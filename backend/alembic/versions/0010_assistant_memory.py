"""Conversation memory for the architecture assistant."""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('assistant_messages',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('analysis_id', sa.String(36), nullable=False), sa.Column('application_id', sa.String(36), nullable=False),
        sa.Column('principal_id', sa.String(36), nullable=False), sa.Column('turn_id', sa.String(36), nullable=False),
        sa.Column('role', sa.String(12), nullable=False), sa.Column('content', sa.Text(), nullable=False), sa.Column('detail', sa.JSON(), nullable=False))
    for column in ('tenant_id', 'analysis_id', 'principal_id', 'turn_id'):
        op.create_index(f'ix_assistant_messages_{column}', 'assistant_messages', [column])


def downgrade():
    op.drop_table('assistant_messages')
