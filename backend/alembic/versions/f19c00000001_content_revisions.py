"""Add opaque content revision tokens without changing existing content."""
import uuid
from alembic import op
import sqlalchemy as sa
revision='f19c00000001'
down_revision='e18a00000001'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('content_sections',sa.Column('revision',sa.String(36),nullable=True))
    table=sa.table('content_sections',sa.column('key',sa.String(80)),sa.column('revision',sa.String(36)))
    bind=op.get_bind()
    for key in bind.execute(sa.select(table.c.key)).scalars().all():
        bind.execute(table.update().where(table.c.key==key).values(revision=str(uuid.uuid4())))
    with op.batch_alter_table('content_sections') as batch:
        batch.alter_column('revision',existing_type=sa.String(36),nullable=False)

def downgrade():
    with op.batch_alter_table('content_sections') as batch:
        batch.drop_column('revision')
