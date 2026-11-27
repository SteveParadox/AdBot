"""Persistent controls, supervisor records and distributed identity coordination."""

from alembic import op
import sqlalchemy as sa

revision = "a20d00000001"
down_revision = "f19c00000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("automation_jobs", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "automation_jobs", sa.Column("manual_release", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE automation_jobs ADD COLUMN depends_on VARCHAR(36) REFERENCES automation_jobs(id)"
        )
    else:
        op.add_column("automation_jobs", sa.Column("depends_on", sa.String(36), nullable=True))
        op.create_foreign_key(
            "fk_job_dependency", "automation_jobs", "automation_jobs", ["depends_on"], ["id"]
        )
    op.create_table(
        "automation_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.CheckConstraint("id=1", name="automation_control_singleton"),
    )
    op.bulk_insert(
        sa.table(
            "automation_control",
            sa.column("id", sa.Integer()),
            sa.column("revision", sa.Integer()),
            sa.column("policy", sa.JSON()),
            sa.column("updated_at", sa.Float()),
        ),
        [dict(id=1, revision=0, policy={}, updated_at=0)],
    )
    op.create_table(
        "operational_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_operational_events_code", "operational_events", ["code"])
    op.create_index("ix_operational_events_created_at", "operational_events", ["created_at"])
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_worker_heartbeats_expires_at", "worker_heartbeats", ["expires_at"])
    op.create_table(
        "selection_counters",
        sa.Column("name", sa.String(120), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )
    op.create_table(
        "shared_proxy_health",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("retry_at", sa.Float(), nullable=False),
        sa.Column("observed_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "network_assignments",
        sa.Column("job_id", sa.String(36), sa.ForeignKey("automation_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("token", sa.String(36), nullable=False),
        sa.Column("user_agent", sa.String(2048), nullable=False),
        sa.Column("endpoint", sa.String(40), nullable=True),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_network_assignments_expires_at", "network_assignments", ["expires_at"])


def downgrade():
    for name in [
        "network_assignments",
        "shared_proxy_health",
        "selection_counters",
        "worker_heartbeats",
        "operational_events",
        "automation_control",
    ]:
        op.drop_table(name)
    if op.get_bind().dialect.name == "sqlite":
        # Later rebuilds can turn SQLite's inline self-reference into a table
        # constraint. Drop it explicitly before dropping the referenced column.
        with op.batch_alter_table(
            "automation_jobs", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s"}
        ) as batch:
            batch.drop_constraint("fk_automation_jobs_depends_on", type_="foreignkey")
            for column in ("depends_on", "priority", "manual_release"):
                batch.drop_column(column)
    else:
        op.drop_constraint("fk_job_dependency", "automation_jobs", type_="foreignkey")
        for column in ["depends_on", "priority", "manual_release"]:
            op.drop_column("automation_jobs", column)
