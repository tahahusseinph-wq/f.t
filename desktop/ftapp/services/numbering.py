"""ترقيم تسلسلي آمن للفواتير والمستندات."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ftapp.models import Counter

PREFIXES = {
    "sale": "INV",
    "return": "RET",
    "quotation": "QUO",
    "purchase": "PUR",
}


def next_number(session: Session, name: str) -> int:
    counter = session.get(Counter, name)
    if counter is None:
        counter = Counter(name=name, value=0)
        session.add(counter)
    counter.value += 1
    session.flush()
    return counter.value


def next_document_number(session: Session, kind: str) -> str:
    from datetime import date

    n = next_number(session, kind)
    prefix = PREFIXES.get(kind, kind.upper()[:3])
    return f"{prefix}-{date.today():%y}-{n:06d}"
