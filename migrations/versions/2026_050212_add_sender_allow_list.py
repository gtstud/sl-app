"""Add sender_allow_list to Alias

Revision ID: 52a76e45b188
Revises: 52a76e45b187
Create Date: 2026-05-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '52a76e45b188'
down_revision = '52a76e45b187'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alias', sa.Column('sender_allow_list', sa.Text(), nullable=True))
    op.drop_column('alias', 'sender_allow_regex')


def downgrade():
    op.add_column('alias', sa.Column('sender_allow_regex', sa.String(length=512), nullable=True))
    op.drop_column('alias', 'sender_allow_list')
