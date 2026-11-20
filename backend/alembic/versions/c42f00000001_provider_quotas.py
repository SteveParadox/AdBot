"""Shared provider quota windows."""
from alembic import op
import sqlalchemy as sa
revision = "c42f00000001"
down_revision = "b31e00000001"
branch_labels = depends_on = None


def upgrade():
    op.create_table("provider_quotas", sa.Column("key", sa.String(64), primary_key=True),
                    sa.Column("window", sa.Integer(), nullable=False),
                    sa.Column("requests", sa.Integer(), nullable=False),
                    sa.Column("tokens", sa.Integer(), nullable=False),
                    sa.Column("cooldown_until", sa.Float(), nullable=False))


def downgrade():
    op.drop_table("provider_quotas")
