"""Persist administrator-managed outbound identities."""
from alembic import op
import sqlalchemy as sa
revision='e18a00000001'
down_revision='d17c0a000001'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('user_agent_config',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('payload',sa.JSON(),nullable=False),sa.Column('updated_at',sa.Float(),nullable=False),sa.CheckConstraint('id = 1'),sa.CheckConstraint('revision >= 0'))
    op.create_table('user_agent_audit',sa.Column('id',sa.Integer(),primary_key=True,autoincrement=True),sa.Column('administrator',sa.String(64),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('timestamp',sa.Float(),nullable=False))

def downgrade():
    op.drop_table('user_agent_audit')
    op.drop_table('user_agent_config')
