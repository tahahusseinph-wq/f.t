"""product warranty; company rename and new default invoice terms

Revision ID: 0004
Revises: 0003
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NAMES = {"مجموعة فاروق الطعمة التجارية": "مجموعة الطعمة التجارية",
             "Farouk Toumma Trading Group": "Al-Toumma Trading Group"}
OLD_TERMS = "البضاعة المباعة لا تُرد ولا تُستبدل إلا بموجب هذه الفاتورة وخلال 7 أيام."
NEW_TERMS = "البضاعة التي تُباع لا تُرد ولا تُستبدل أبداً."


def _update_setting(conn, key: str, fix) -> None:
    row = conn.execute(sa.text("SELECT value FROM settings WHERE key = :k"), {"k": key}).fetchone()
    if row is None or row[0] is None:
        return
    value = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    if isinstance(value, dict) and fix(value):
        conn.execute(sa.text("UPDATE settings SET value = :v WHERE key = :k"),
                     {"v": json.dumps(value, ensure_ascii=False), "k": key})


def upgrade() -> None:
    with op.batch_alter_table('products') as batch:
        batch.add_column(sa.Column('warranty', sa.String(length=64), nullable=False, server_default=''))
    with op.batch_alter_table('invoice_items') as batch:
        batch.add_column(sa.Column('warranty', sa.String(length=64), nullable=False, server_default=''))

    conn = op.get_bind()

    def company(v: dict) -> bool:
        changed = False
        for field in ("name", "name_en"):
            if v.get(field) in OLD_NAMES:
                v[field] = OLD_NAMES[v[field]]
                changed = True
        return changed

    def invoice(v: dict) -> bool:
        if v.get("terms") == OLD_TERMS:
            v["terms"] = NEW_TERMS
            return True
        return False

    _update_setting(conn, "company", company)
    _update_setting(conn, "invoice", invoice)


def downgrade() -> None:
    with op.batch_alter_table('invoice_items') as batch:
        batch.drop_column('warranty')
    with op.batch_alter_table('products') as batch:
        batch.drop_column('warranty')
