"""customer payment method (cash / shamcash)

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('customer_payments') as batch:
        batch.add_column(sa.Column('method', sa.String(length=16), nullable=False, server_default='cash'))


def downgrade() -> None:
    with op.batch_alter_table('customer_payments') as batch:
        batch.drop_column('method')
