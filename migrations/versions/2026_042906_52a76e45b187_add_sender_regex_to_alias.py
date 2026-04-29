"""Add sender_regex to Alias

Revision ID: 52a76e45b187
Revises: 4a9f8c2e1b3d
Create Date: 2026-04-29 06:16:36.286528

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '52a76e45b187'
down_revision = '4a9f8c2e1b3d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alias', sa.Column('sender_regex', sa.String(length=512), nullable=True))


def downgrade():
    op.drop_column('alias', 'sender_regex')
