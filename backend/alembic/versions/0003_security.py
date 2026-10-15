"""Add security state without rewriting existing analysis or runtime records."""
from alembic import op
import sqlalchemy as sa
from app.access import models as security

revision = '0003'
down_revision = '0002'
branch_labels = depends_on = None
TABLES = [security.Workspace, security.SecurityState, security.Principal, security.Credential,
          security.LoginWindow, security.PolicyRevision, security.SourceRepository,
          security.SourceGrant, security.AuditEvent]


def upgrade():
    bind = op.get_bind()
    for model in TABLES:
        model.__table__.create(bind)
    # Existing local ownership is retained. Bootstrap never rewrites snapshots.
    bind.execute(sa.text("INSERT INTO security_workspaces (id,name,audit_sequence,audit_head) VALUES (:id,:name,0,:head)"),
                 dict(id='local', name='Existing local workspace', head='0'*64))
    if bind.dialect.name == 'sqlite':
        for action in ('UPDATE', 'DELETE'):
            op.execute(f"CREATE TRIGGER audit_no_{action.lower()} BEFORE {action} ON security_audit_events BEGIN SELECT RAISE(ABORT, 'Audit events are append-only'); END")
    else:
        op.execute("CREATE FUNCTION archintel_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Audit events are append-only'; END; $$")
        op.execute('CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON security_audit_events FOR EACH ROW EXECUTE FUNCTION archintel_audit_immutable()')


def downgrade():
    if op.get_bind().dialect.name != 'sqlite':
        op.execute('DROP TRIGGER audit_immutable ON security_audit_events')
        op.execute('DROP FUNCTION archintel_audit_immutable()')
    for model in reversed(TABLES):
        model.__table__.drop(op.get_bind())
