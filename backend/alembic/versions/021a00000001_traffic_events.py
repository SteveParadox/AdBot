"""Durable resource-change notifications and indexed event replay."""
from alembic import op
import sqlalchemy as sa

revision = "021a00000001"
down_revision = "c42f00000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("resource_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("path", sa.String(240), nullable=False),
        sa.Column("request_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False))
    op.create_index("ix_resource_changes_owner", "resource_changes", ["owner"])
    op.create_index("ix_resource_changes_created_at", "resource_changes", ["created_at"])
    op.create_index("ix_automation_events_job_cursor", "automation_events", ["job_id", "id"])


def downgrade():
    op.drop_index("ix_automation_events_job_cursor", table_name="automation_events")
    op.drop_table("resource_changes")
