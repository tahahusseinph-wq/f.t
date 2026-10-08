"""multi-currency cash drawer, currency exchange, employees and payroll, no tax, Gemini 3.8 Flash

Revision ID: 0005
Revises: 0004
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_MODEL = "gemini-3.8-flash"
OLD_MODELS = {"", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash"}


def _get(conn, key: str):
    row = conn.execute(sa.text("SELECT value FROM settings WHERE key = :k"), {"k": key}).fetchone()
    if row is None or row[0] is None:
        return None
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]


def _put(conn, key: str, value) -> None:
    exists = conn.execute(sa.text("SELECT 1 FROM settings WHERE key = :k"), {"k": key}).fetchone()
    payload = {"v": json.dumps(value, ensure_ascii=False), "k": key}
    if exists:
        conn.execute(sa.text("UPDATE settings SET value = :v WHERE key = :k"), payload)
    else:
        conn.execute(sa.text("INSERT INTO settings (key, value) VALUES (:k, :v)"), payload)


def upgrade() -> None:
    with op.batch_alter_table('shifts') as batch:
        batch.add_column(sa.Column('opening_balances', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('expected_balances', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('actual_balances', sa.JSON(), nullable=True))
    with op.batch_alter_table('invoices') as batch:
        batch.add_column(sa.Column('ref_rate', sa.Float(), nullable=False, server_default='0'))
    with op.batch_alter_table('customer_payments') as batch:
        batch.add_column(sa.Column('currency_code', sa.String(length=8), nullable=False, server_default=''))
        batch.add_column(sa.Column('currency_amount', sa.Float(), nullable=False, server_default='0'))

    op.create_table('cash_movements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('shift_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('currency_code', sa.String(length=8), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('ref_type', sa.String(length=16), nullable=False),
        sa.Column('ref_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], name=op.f('fk_cash_movements_shift_id_shifts'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_cash_movements_user_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cash_movements')))
    with op.batch_alter_table('cash_movements') as batch:
        batch.create_index(batch.f('ix_cash_movements_shift_id'), ['shift_id'], unique=False)
        batch.create_index(batch.f('ix_cash_movements_created_at'), ['created_at'], unique=False)

    op.create_table('currency_exchanges',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('shift_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('direction', sa.String(length=8), nullable=False),
        sa.Column('currency_code', sa.String(length=8), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('counter_code', sa.String(length=8), nullable=False),
        sa.Column('counter_amount', sa.Float(), nullable=False),
        sa.Column('rate_used', sa.Float(), nullable=False),
        sa.Column('rate_official', sa.Float(), nullable=False),
        sa.Column('profit', sa.Float(), nullable=False),
        sa.Column('customer_name', sa.String(length=128), nullable=False),
        sa.Column('notes', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], name=op.f('fk_currency_exchanges_shift_id_shifts'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_currency_exchanges_user_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_currency_exchanges')))
    with op.batch_alter_table('currency_exchanges') as batch:
        batch.create_index(batch.f('ix_currency_exchanges_created_at'), ['created_at'], unique=False)

    op.create_table('employees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('phone', sa.String(length=32), nullable=False),
        sa.Column('pay_period', sa.String(length=16), nullable=False),
        sa.Column('salary', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_employees')))

    op.create_table('employee_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('deducted', sa.Float(), nullable=False),
        sa.Column('net', sa.Float(), nullable=False),
        sa.Column('period_from', sa.Date(), nullable=True),
        sa.Column('period_to', sa.Date(), nullable=True),
        sa.Column('pay_date', sa.Date(), nullable=False),
        sa.Column('expense_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_employee_transactions_employee_id_employees'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['expense_id'], ['expenses.id'], name=op.f('fk_employee_transactions_expense_id_expenses'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_employee_transactions_user_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_employee_transactions')))
    with op.batch_alter_table('employee_transactions') as batch:
        batch.create_index(batch.f('ix_employee_transactions_employee_id'), ['employee_id'], unique=False)
        batch.create_index(batch.f('ix_employee_transactions_pay_date'), ['pay_date'], unique=False)

    conn = op.get_bind()
    # لا توجد ضريبة: تصفير النسبة
    if _get(conn, "tax_rate"):
        _put(conn, "tax_rate", 0.0)
    # أحدث موديل Gemini Flash
    gem = _get(conn, "gemini")
    if isinstance(gem, dict) and (gem.get("model") or "") in OLD_MODELS:
        gem["model"] = NEW_MODEL
        _put(conn, "gemini", gem)
    # تصنيف مصاريف للسلف إن لم يوجد
    if conn.execute(sa.text("SELECT 1 FROM expense_categories LIMIT 1")).fetchone() is not None:
        for name in ("رواتب", "سلف الموظفين"):
            if conn.execute(sa.text("SELECT 1 FROM expense_categories WHERE name = :n"), {"n": name}).fetchone() is None:
                conn.execute(sa.text("INSERT INTO expense_categories (name) VALUES (:n)"), {"n": name})


def downgrade() -> None:
    op.drop_table('employee_transactions')
    op.drop_table('employees')
    op.drop_table('currency_exchanges')
    op.drop_table('cash_movements')
    with op.batch_alter_table('customer_payments') as batch:
        batch.drop_column('currency_amount')
        batch.drop_column('currency_code')
    with op.batch_alter_table('invoices') as batch:
        batch.drop_column('ref_rate')
    with op.batch_alter_table('shifts') as batch:
        batch.drop_column('actual_balances')
        batch.drop_column('expected_balances')
        batch.drop_column('opening_balances')
