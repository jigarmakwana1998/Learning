"""replace local password storage with Supabase identities"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("auth_subject", sa.String(36), nullable=True))
        batch.create_unique_constraint("uq_users_auth_subject", ["auth_subject"])
        batch.drop_column("password_hash")


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("password_hash", sa.String(512), nullable=True))
        batch.drop_constraint("uq_users_auth_subject", type_="unique")
        batch.drop_column("auth_subject")
