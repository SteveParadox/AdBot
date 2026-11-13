"""Add content sections and migrate existing display copy."""
import json
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = "d17c0a000001"
down_revision = "37745660af92"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "content_sections",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("published", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_content_sections_status", "content_sections", ["status"])
    defaults = json.loads((Path(__file__).parents[2] / "app/content_defaults.json").read_text(encoding="utf-8"))
    op.bulk_insert(table, [dict(key=k, status="published", position=i, draft=v, published=v, updated_at=0)
                           for i, (k, v) in enumerate(defaults.items())])


def downgrade():
    op.drop_index("ix_content_sections_status", table_name="content_sections")
    op.drop_table("content_sections")
