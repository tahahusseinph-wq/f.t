"""المصاريف، الصندوق والورديات، عمولات البائعين."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ftapp.core.utils import money, now
from ftapp.models import CustomerPayment, Expense, ExpenseCategory, Invoice, Shift, User
from ftapp.services import audit
from ftapp.services.errors import NotFound, ValidationError


# ---------------- المصاريف ----------------

def list_expense_categories(session: Session) -> list[ExpenseCategory]:
    return list(session.scalars(select(ExpenseCategory).order_by(ExpenseCategory.name)))


def save_expense_category(session: Session, name: str, category_id: int | None = None) -> ExpenseCategory:
    if not name.strip():
        raise ValidationError("أدخل اسم التصنيف")
    cat = session.get(ExpenseCategory, category_id) if category_id else None
    if cat is None:
        cat = ExpenseCategory()
        session.add(cat)
    cat.name = name.strip()
    session.flush()
    return cat


def delete_expense_category(session: Session, category_id: int) -> None:
    cat = session.get(ExpenseCategory, category_id)
    if cat:
        session.delete(cat)


def add_expense(session: Session, actor: User | None, amount: float, category_id: int | None, description: str = "",
                expense_date: date | None = None, paid_from_cash: bool = True, expense_id: int | None = None
                ) -> Expense:
    if amount <= 0:
        raise ValidationError("أدخل مبلغاً صحيحاً")
    exp = session.get(Expense, expense_id) if expense_id else None
    if exp is None:
        exp = Expense(user_id=actor.id if actor else None)
        shift = current_shift(session, actor) if actor and paid_from_cash else None
        exp.shift_id = shift.id if shift else None
        session.add(exp)
    exp.amount, exp.category_id, exp.description = money(amount), category_id, description
    exp.expense_date, exp.paid_from_cash = expense_date or date.today(), paid_from_cash
    session.flush()
    audit.log(session, actor, "expense", "expense", exp.id, amount=amount)
    return exp


def delete_expense(session: Session, expense_id: int) -> None:
    exp = session.get(Expense, expense_id)
    if exp:
        session.delete(exp)


def list_expenses(session: Session, date_from: date | None = None, date_to: date | None = None,
                  category_id: int | None = None) -> list[Expense]:
    stmt = select(Expense).options(selectinload(Expense.category)).order_by(Expense.expense_date.desc(), Expense.id.desc())
    if date_from:
        stmt = stmt.where(Expense.expense_date >= date_from)
    if date_to:
        stmt = stmt.where(Expense.expense_date <= date_to)
    if category_id:
        stmt = stmt.where(Expense.category_id == category_id)
    return list(session.scalars(stmt))


def expenses_total(session: Session, date_from: date, date_to: date) -> float:
    return money(session.scalar(select(func.coalesce(func.sum(Expense.amount), 0))
                                .where(Expense.expense_date >= date_from, Expense.expense_date <= date_to)))


# ---------------- الورديات ----------------

def current_shift(session: Session, user: User | None) -> Shift | None:
    if user is None:
        return None
    return session.scalar(select(Shift).where(Shift.user_id == user.id, Shift.status == "open")
                          .order_by(Shift.id.desc()))


def open_shift(session: Session, actor: User, opening_cash: float = 0.0) -> Shift:
    if current_shift(session, actor):
        raise ValidationError("لديك وردية مفتوحة مسبقاً")
    if opening_cash < 0:
        raise ValidationError("الرصيد الافتتاحي لا يمكن أن يكون سالباً")
    shift = Shift(user_id=actor.id, opening_cash=money(opening_cash))
    session.add(shift)
    session.flush()
    audit.log(session, actor, "shift_opened", "shift", shift.id, opening=opening_cash)
    return shift


def shift_summary(session: Session, shift: Shift) -> dict[str, float]:
    def total(kind: str) -> float:
        return money(session.scalar(select(func.coalesce(func.sum(Invoice.paid), 0))
                                    .where(Invoice.shift_id == shift.id, Invoice.kind == kind,
                                           Invoice.status == "posted")))

    def count(kind: str) -> int:
        return session.scalar(select(func.count(Invoice.id)).where(Invoice.shift_id == shift.id, Invoice.kind == kind,
                                                                    Invoice.status == "posted")) or 0

    sales_cash = total("sale")
    refunds = total("return")
    payments = money(session.scalar(select(func.coalesce(func.sum(CustomerPayment.amount), 0))
                                    .where(CustomerPayment.shift_id == shift.id)))
    expenses = money(session.scalar(select(func.coalesce(func.sum(Expense.amount), 0))
                                    .where(Expense.shift_id == shift.id, Expense.paid_from_cash.is_(True))))
    sales_total = money(session.scalar(select(func.coalesce(func.sum(Invoice.total), 0))
                                       .where(Invoice.shift_id == shift.id, Invoice.kind == "sale",
                                              Invoice.status == "posted")))
    expected = money(shift.opening_cash + sales_cash - refunds + payments - expenses)
    return {"opening": shift.opening_cash, "sales_cash": sales_cash, "sales_total": sales_total,
            "credit_sales": money(sales_total - sales_cash), "refunds": refunds, "payments": payments,
            "expenses": expenses, "expected": expected, "invoices": count("sale"), "returns": count("return")}


def close_shift(session: Session, actor: User, actual_cash: float, notes: str = "", shift_id: int | None = None
                ) -> Shift:
    shift = session.get(Shift, shift_id) if shift_id else current_shift(session, actor)
    if shift is None or shift.status != "open":
        raise NotFound("لا توجد وردية مفتوحة")
    summary = shift_summary(session, shift)
    shift.expected_cash = summary["expected"]
    shift.actual_cash = money(actual_cash)
    shift.difference = money(actual_cash - summary["expected"])
    shift.closed_at = now()
    shift.status = "closed"
    shift.notes = notes
    audit.log(session, actor, "shift_closed", "shift", shift.id, expected=shift.expected_cash,
              actual=actual_cash, difference=shift.difference)
    return shift


def list_shifts(session: Session, user_id: int | None = None, limit: int = 300) -> list[Shift]:
    stmt = select(Shift).options(selectinload(Shift.user)).order_by(Shift.id.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(Shift.user_id == user_id)
    return list(session.scalars(stmt))


# ---------------- العمولات ----------------

def commissions(session: Session, date_from: date, date_to: date) -> list[dict]:
    start = datetime.combine(date_from, datetime.min.time())
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
    out = []
    for user in session.scalars(select(User).order_by(User.username)):
        def total(kind: str) -> float:
            return money(session.scalar(select(func.coalesce(func.sum(Invoice.total - Invoice.tax_amount), 0))
                                        .where(Invoice.user_id == user.id, Invoice.kind == kind,
                                               Invoice.status == "posted", Invoice.created_at >= start,
                                               Invoice.created_at < end)))
        sales, returns = total("sale"), total("return")
        count = session.scalar(select(func.count(Invoice.id)).where(
            Invoice.user_id == user.id, Invoice.kind == "sale", Invoice.status == "posted",
            Invoice.created_at >= start, Invoice.created_at < end)) or 0
        if not sales and not returns:
            continue
        net = money(sales - returns)
        out.append({"user": user, "invoices": count, "sales": sales, "returns": returns, "net": net,
                    "rate": user.commission_rate, "commission": money(net * (user.commission_rate or 0) / 100)})
    return out
