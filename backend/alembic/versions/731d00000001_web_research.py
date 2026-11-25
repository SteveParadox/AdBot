"""Durable website-free research jobs and owner-scoped conversations."""

from alembic import op
import sqlalchemy as sa

revision = "731d00000001"
down_revision = "021a00000001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("automation_jobs") as batch:
        batch.alter_column("website_id", existing_type=sa.String(36), nullable=True)
        batch.create_check_constraint(
            "ck_job_website_scope",
            "(job_type = 'research' AND website_id IS NULL) OR (job_type != 'research' AND website_id IS NOT NULL)",
        )
    op.create_table(
        "research_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_research_conversations_owner_activity", "research_conversations", ["owner", "updated_at"])
    op.create_table(
        "research_tasks",
        sa.Column("job_id", sa.String(36), sa.ForeignKey("automation_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("research_conversations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("question", sa.JSON(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("intent", sa.String(24), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )
    op.create_index("ix_research_tasks_conversation_created", "research_tasks", ["conversation_id", "created_at"])


def downgrade():
    # Refuse a schema rollback that would silently discard user research.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM automation_jobs WHERE job_type = 'research'")):
        raise RuntimeError("Remove or back up research jobs before downgrading this migration")
    op.drop_table("research_tasks")
    op.drop_table("research_conversations")
    with op.batch_alter_table("automation_jobs") as batch:
        batch.drop_constraint("ck_job_website_scope", type_="check")
        batch.alter_column("website_id", existing_type=sa.String(36), nullable=False)
