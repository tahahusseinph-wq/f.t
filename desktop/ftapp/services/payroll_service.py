"""الموظفون والرواتب (يومي / أسبوعي / شهري) والسلف التي تُخصم من الرواتب اللاحقة.

كل راتب أو سلفة تُسجَّل أيضاً كمصروف (تصنيف «رواتب» أو «سلف الموظفين») حتى يظهر في صافي الربح،
وتخرج من صندوق الوردية إذا كانت مدفوعة منه.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ftapp.core.utils import money
from ftapp.models import Employee, EmployeeTransaction, ExpenseCategory, User
from ftapp.services import audit, finance_service
from ftapp.services.errors import NotFound, ValidationError

PERIODS = {"daily": "يومي", "weekly": "أسبوعي", "monthly": "شهري"}
KINDS = {"salary": "راتب", "advance": "سلفة"}


def _category(session: Session, name: str) -> int:
    cat = session.scalar(select(ExpenseCategory).where(ExpenseCategory.name == name))
    if cat is None:
        cat = ExpenseCategory(name=name)
        session.add(cat)
        session.flush()
    return cat.id


def list_employees(session: Session, active_only: bool = False) -> list[Employee]:
    stmt = select(Employee).order_by(Employee.is_active.desc(), Employee.name)
    if active_only:
        stmt = stmt.where(Employee.is_active.is_(True))
    return list(session.scalars(stmt))


def get_employee(session: Session, employee_id: int) -> Employee:
    emp = session.get(Employee, employee_id)
    if emp is None:
        raise NotFound("الموظف غير موجود")
    return emp


def save_employee(session: Session, name: str, pay_period: str = "monthly", salary: float = 0.0, phone: str = "",
                  notes: str = "", is_active: bool = True, employee_id: int | None = None) -> Employee:
    if not name.strip():
        raise ValidationError("أدخل اسم الموظف")
    if pay_period not in PERIODS:
        raise ValidationError("فترة الراتب غير معروفة")
    if salary < 0:
        raise ValidationError("الراتب لا يمكن أن يكون سالباً")
    emp = session.get(Employee, employee_id) if employee_id else None
    if emp is None:
        emp = Employee()
        session.add(emp)
    emp.name, emp.pay_period, emp.salary = name.strip(), pay_period, money(salary)
    emp.phone, emp.notes, emp.is_active = phone.strip(), notes, is_active
    session.flush()
    return emp


def delete_employee(session: Session, employee_id: int) -> None:
    emp = get_employee(session, employee_id)
    if session.scalar(select(func.count(EmployeeTransaction.id)).where(EmployeeTransaction.employee_id == emp.id)):
        emp.is_active = False  # له سجل رواتب: يُوقف بدل الحذف
    else:
        session.delete(emp)


def outstanding_advances(session: Session, employee_id: int) -> float:
    """السلف غير المخصومة بعد = مجموع السلف − مجموع ما خُصم من الرواتب."""
    adv = session.scalar(select(func.coalesce(func.sum(EmployeeTransaction.amount), 0))
                         .where(EmployeeTransaction.employee_id == employee_id, EmployeeTransaction.kind == "advance"))
    ded = session.scalar(select(func.coalesce(func.sum(EmployeeTransaction.deducted), 0))
                         .where(EmployeeTransaction.employee_id == employee_id, EmployeeTransaction.kind == "salary"))
    return money((adv or 0) - (ded or 0))


def period_range(pay_period: str, ref: date | None = None) -> tuple[date, date]:
    """فترة الراتب الافتراضية المنتهية في التاريخ المرجعي."""
    ref = ref or date.today()
    if pay_period == "daily":
        return ref, ref
    if pay_period == "weekly":
        return ref - timedelta(days=6), ref
    start = ref.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def last_paid_to(session: Session, employee_id: int) -> date | None:
    return session.scalar(select(func.max(EmployeeTransaction.period_to))
                          .where(EmployeeTransaction.employee_id == employee_id, EmployeeTransaction.kind == "salary"))


def pay_salary(session: Session, actor: User | None, employee_id: int, amount: float, deduct: float = 0.0,
               period_from: date | None = None, period_to: date | None = None, pay_date: date | None = None,
               from_cash: bool = True, notes: str = "") -> EmployeeTransaction:
    """amount: الراتب الإجمالي للفترة، deduct: ما يُخصم من السلف، والصافي يُدفع للموظف."""
    emp = get_employee(session, employee_id)
    if amount <= 0:
        raise ValidationError("أدخل مبلغ الراتب")
    owed = outstanding_advances(session, emp.id)
    if deduct < 0 or deduct > owed + 0.005:
        raise ValidationError(f"الخصم يجب أن يكون بين 0 و{owed:,.2f} (السلف المستحقة)")
    if deduct > amount + 0.005:
        raise ValidationError("الخصم أكبر من الراتب")
    net = money(amount - deduct)
    pay_date = pay_date or date.today()
    tx = EmployeeTransaction(employee_id=emp.id, kind="salary", amount=money(amount), deducted=money(deduct), net=net,
                             period_from=period_from, period_to=period_to, pay_date=pay_date,
                             user_id=actor.id if actor else None, notes=notes)
    session.add(tx)
    session.flush()
    period = f" ({period_from:%Y-%m-%d} → {period_to:%Y-%m-%d})" if period_from and period_to else ""
    if net > 0:
        desc = f"راتب {PERIODS[emp.pay_period]}: {emp.name}{period}" + (f" — خُصم من السلف {deduct:,.2f}" if deduct else "")
        exp = finance_service.add_expense(session, actor, net, _category(session, "رواتب"), desc, pay_date, from_cash,
                                          kind="salary")
        tx.expense_id = exp.id
    audit.log(session, actor, "salary_paid", "employee", emp.id, amount=amount, deducted=deduct, net=net)
    session.flush()
    return tx


def give_advance(session: Session, actor: User | None, employee_id: int, amount: float, pay_date: date | None = None,
                 from_cash: bool = True, notes: str = "") -> EmployeeTransaction:
    emp = get_employee(session, employee_id)
    if amount <= 0:
        raise ValidationError("أدخل مبلغ السلفة")
    pay_date = pay_date or date.today()
    tx = EmployeeTransaction(employee_id=emp.id, kind="advance", amount=money(amount), net=money(amount),
                             pay_date=pay_date, user_id=actor.id if actor else None, notes=notes)
    session.add(tx)
    session.flush()
    exp = finance_service.add_expense(session, actor, amount, _category(session, "سلف الموظفين"),
                                      f"سلفة: {emp.name}" + (f" — {notes}" if notes else ""), pay_date, from_cash,
                                      kind="advance")
    tx.expense_id = exp.id
    audit.log(session, actor, "advance_given", "employee", emp.id, amount=amount)
    session.flush()
    return tx


def delete_transaction(session: Session, actor: User | None, tx_id: int) -> None:
    tx = session.get(EmployeeTransaction, tx_id)
    if tx is None:
        return
    if tx.kind == "advance":
        remaining = outstanding_advances(session, tx.employee_id) - tx.amount
        if remaining < -0.005:
            raise ValidationError("هذه السلفة خُصمت من راتب، احذف الراتب أولاً")
    if tx.expense_id:
        finance_service.delete_expense(session, tx.expense_id)
    audit.log(session, actor, "payroll_deleted", "employee", tx.employee_id, kind=tx.kind, amount=tx.amount)
    session.delete(tx)


def list_transactions(session: Session, employee_id: int | None = None, date_from: date | None = None,
                      date_to: date | None = None) -> list[EmployeeTransaction]:
    stmt = (select(EmployeeTransaction).options(selectinload(EmployeeTransaction.employee))
            .order_by(EmployeeTransaction.pay_date.desc(), EmployeeTransaction.id.desc()))
    if employee_id:
        stmt = stmt.where(EmployeeTransaction.employee_id == employee_id)
    if date_from:
        stmt = stmt.where(EmployeeTransaction.pay_date >= date_from)
    if date_to:
        stmt = stmt.where(EmployeeTransaction.pay_date <= date_to)
    return list(session.scalars(stmt))


def summary(session: Session) -> list[dict]:
    """ملخص لكل موظف: الراتب، آخر فترة مدفوعة، السلف المستحقة."""
    out = []
    for emp in list_employees(session):
        out.append({"employee": emp, "period": PERIODS.get(emp.pay_period, emp.pay_period), "salary": emp.salary,
                    "last_paid": last_paid_to(session, emp.id), "advances": outstanding_advances(session, emp.id)})
    return out
