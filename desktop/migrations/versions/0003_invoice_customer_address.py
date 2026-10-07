"""invoice customer address

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('invoices') as batch:
        batch.add_column(sa.Column('customer_address', sa.String(length=256), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('invoices') as batch:
        batch.drop_column('customer_address')
