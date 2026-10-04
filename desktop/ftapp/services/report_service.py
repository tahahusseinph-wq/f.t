"""التقارير والإحصاءات ولوحة التحكم."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ftapp.core.utils import money, now, qty
from ftapp.models import Category, Invoice, InvoiceItem, Product, StockLevel, Supplier
from ftapp.services import catalog_service, finance_service, inventory_service, settings_service as settings


@dataclass
class Period:
    start: date
    end: date
    label: str = ""

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, datetime.min.time())

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end + timedelta(days=1), datetime.min.time())

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def period(name: str, ref: date | None = None) -> Period:
    today = ref or date.today()
    if name == "today":
        return Period(today, today, "اليوم")
    if name == "yesterday":
        y = today - timedelta(days=1)
        return Period(y, y, "أمس")
    if name == "week":
        return Period(today - timedelta(days=6), today, "آخر 7 أيام")
    if name == "month":
        return Period(today.replace(day=1), today, "هذا الشهر")
    if name == "30days":
        return Period(today - timedelta(days=29), today, "آخر 30 يوم")
    if name == "last_month":
        first = today.replace(day=1)
        last_prev = first - timedelta(days=1)
        return Period(last_prev.replace(day=1), last_prev, "الشهر الماضي")
    if name == "year":
        return Period(today.replace(month=1, day=1), today, "هذه السنة")
    return Period(today - timedelta(days=29), today, "آخر 30 يوم")


def _sum(session: Session, col, p: Period, kind: str) -> float:
    return money(session.scalar(select(func.coalesce(func.sum(col), 0)).where(
        Invoice.kind == kind, Invoice.status == "posted",
        Invoice.created_at >= p.start_dt, Invoice.created_at < p.end_dt)))


def kpis(session: Session, p: Period) -> dict[str, Any]:
    sales = _sum(session, Invoice.total - Invoice.tax_amount, p, "sale")
    returns = _sum(session, Invoice.total - Invoice.tax_amount, p, "return")
    cost = _sum(session, Invoice.cost_total, p, "sale")
    returns_cost = _sum(session, Invoice.cost_total, p, "return")
    count = session.scalar(select(func.count(Invoice.id)).where(
        Invoice.kind == "sale", Invoice.status == "posted",
        Invoice.created_at >= p.start_dt, Invoice.created_at < p.end_dt)) or 0
    collected = _sum(session, Invoice.paid, p, "sale")
    net_sales = money(sales - returns)
    gross = money(net_sales - (cost - returns_cost))
    expenses = finance_service.expenses_total(session, p.start, p.end)
    val = inventory_service.valuation(session)
    products = session.scalar(select(func.count(Product.id)).where(Product.is_active.is_(True))) or 0
    return {
        "sales": net_sales, "gross_sales": sales, "returns": returns, "invoices": count,
        "cost": money(cost - returns_cost), "gross_profit": gross, "expenses": expenses,
        "net_profit": money(gross - expenses), "avg_invoice": money(sales / count) if count else 0.0,
        "collected": collected, "credit": money(_sum(session, Invoice.total, p, "sale") - collected),
        "margin_percent": round(gross / net_sales * 100, 1) if net_sales else 0.0,
        "stock_cost": val["cost"], "stock_value": val["sale"], "stock_units": val["units"], "products": products,
    }


def sales_series(session: Session, p: Period, granularity: str = "auto") -> list[dict[str, Any]]:
    if granularity == "auto":
        granularity = "day" if p.days <= 45 else ("week" if p.days <= 180 else "month")
    rows = session.execute(select(Invoice.created_at, Invoice.kind, Invoice.total - Invoice.tax_amount,
                                  Invoice.cost_total)
                           .where(Invoice.status == "posted", Invoice.kind.in_(["sale", "return"]),
                                  Invoice.created_at >= p.start_dt, Invoice.created_at < p.end_dt)).all()

    def bucket(d: date) -> date:
        if granularity == "week":
            return d - timedelta(days=d.weekday())
        if granularity == "month":
            return d.replace(day=1)
        return d

    data: dict[date, dict[str, float]] = {}
    cursor = bucket(p.start)
    while cursor <= p.end:
        data[cursor] = {"sales": 0.0, "cost": 0.0}
        if granularity == "day":
            cursor += timedelta(days=1)
        elif granularity == "week":
            cursor += timedelta(days=7)
        else:
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    for created, kind, amount, cost in rows:
        b = bucket(created.date())
        sign = 1 if kind == "sale" else -1
        slot = data.setdefault(b, {"sales": 0.0, "cost": 0.0})
        slot["sales"] += sign * amount
        slot["cost"] += sign * cost
    fmt = {"day": "%m-%d", "week": "%m-%d", "month": "%Y-%m"}[granularity]
    return [{"date": d, "label": d.strftime(fmt), "sales": money(v["sales"]), "cost": money(v["cost"]),
             "profit": money(v["sales"] - v["cost"])} for d, v in sorted(data.items())]


def _item_rows(session: Session, p: Period):
    return session.execute(
        select(InvoiceItem.product_id, InvoiceItem.product_name, InvoiceItem.quantity, InvoiceItem.returned_qty,
               InvoiceItem.line_total, InvoiceItem.cost_price, Invoice.subtotal, Invoice.discount)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.kind == "sale", Invoice.status == "posted",
               Invoice.created_at >= p.start_dt, Invoice.created_at < p.end_dt)).all()


def product_sales(session: Session, p: Period) -> list[dict[str, Any]]:
    """مبيعات كل منتج ونسبته من إجمالي المبيعات (نسبة المبيع)."""
    agg: dict[Any, dict[str, Any]] = {}
    for pid, name, q, rq, line_total, cost, subtotal, discount in _item_rows(session, p):
        ratio = (subtotal - discount) / subtotal if subtotal else 1
        net_q = q - rq
        revenue = (line_total / q * net_q * ratio) if q else 0
        a = agg.setdefault(pid or name, {"product_id": pid, "name": name, "quantity": 0.0, "revenue": 0.0,
                                         "cost": 0.0})
        a["quantity"] += net_q
        a["revenue"] += revenue
        a["cost"] += cost * net_q
    total = sum(a["revenue"] for a in agg.values()) or 1
    out = []
    for a in agg.values():
        a["quantity"] = qty(a["quantity"])
        a["revenue"] = money(a["revenue"])
        a["profit"] = money(a["revenue"] - a["cost"])
        a["share"] = round(a["revenue"] / total * 100, 2)
        a["margin"] = round(a["profit"] / a["revenue"] * 100, 1) if a["revenue"] else 0.0
        out.append(a)
    out.sort(key=lambda x: x["revenue"], reverse=True)
    return out


def top_products(session: Session, p: Period, n: int = 10, by: str = "revenue") -> list[dict[str, Any]]:
    rows = product_sales(session, p)
    rows.sort(key=lambda x: x[by], reverse=True)
    return rows[:n]


def sales_by_category(session: Session, p: Period, top_level: bool = True) -> list[dict[str, Any]]:
    rows = product_sales(session, p)
    pids = [r["product_id"] for r in rows if r["product_id"]]
    cat_of: dict[int, int | None] = dict(session.execute(select(Product.id, Product.category_id)
                                                         .where(Product.id.in_(pids or [-1]))).all())
    cats = {c.id: c for c in session.scalars(select(Category))}

    def root(cid: int | None) -> int | None:
        seen = set()
        while top_level and cid and cats.get(cid) and cats[cid].parent_id and cid not in seen:
            seen.add(cid)
            cid = cats[cid].parent_id
        return cid

    agg: dict[int | None, dict[str, Any]] = defaultdict(lambda: {"revenue": 0.0, "profit": 0.0, "quantity": 0.0})
    for r in rows:
        cid = root(cat_of.get(r["product_id"]))
        agg[cid]["revenue"] += r["revenue"]
        agg[cid]["profit"] += r["profit"]
        agg[cid]["quantity"] += r["quantity"]
    total = sum(a["revenue"] for a in agg.values()) or 1
    out = [{"category_id": cid, "name": cats[cid].name if cid in cats else "بدون قسم",
            "color": cats[cid].color if cid in cats else "#9E9E9E", "revenue": money(a["revenue"]),
            "profit": money(a["profit"]), "quantity": qty(a["quantity"]),
            "share": round(a["revenue"] / total * 100, 1)} for cid, a in agg.items()]
    out.sort(key=lambda x: x["revenue"], reverse=True)
    return out


def slow_movers(session: Session, days: int | None = None) -> list[dict[str, Any]]:
    days = days or int(settings.get(session, "slow_moving_days") or 60)
    cutoff = now() - timedelta(days=days)
    qsub = (select(StockLevel.product_id, func.sum(StockLevel.quantity).label("q"))
            .group_by(StockLevel.product_id).subquery())
    rows = session.execute(select(Product, qsub.c.q).join(qsub, qsub.c.product_id == Product.id)
                           .where(Product.is_active.is_(True), qsub.c.q > 0, Product.created_at < cutoff,
                                  (Product.last_sold_at.is_(None)) | (Product.last_sold_at < cutoff))).all()
    out = []
    for p, q in rows:
        idle = (now() - (p.last_sold_at or p.created_at)).days
        out.append({"product": p, "quantity": qty(q), "idle_days": idle, "value": money(q * p.cost_price),
                    "last_sold": p.last_sold_at})
    out.sort(key=lambda x: x["value"], reverse=True)
    return out


def reorder_suggestions(session: Session, lookback_days: int = 30, lead_days: int = 7, cover_days: int = 30
                        ) -> list[dict[str, Any]]:
    """يتوقع موعد نفاد كل منتج من سرعة بيعه ويقترح كمية الطلب."""
    p = Period(date.today() - timedelta(days=lookback_days - 1), date.today())
    sold = {r["product_id"]: r["quantity"] for r in product_sales(session, p) if r["product_id"]}
    products, _ = catalog_service.search_products(session, limit=None)
    suppliers = {s.id: s.name for s in session.scalars(select(Supplier))}
    out = []
    for prod in products:
        velocity = sold.get(prod.id, 0) / lookback_days
        q = prod.quantity
        min_stock = catalog_service.min_stock_for(session, prod)
        days_left = (q / velocity) if velocity > 0 else None
        needs = (days_left is not None and days_left <= lead_days + 3) or q <= min_stock
        if not needs:
            continue
        target = max(velocity * cover_days, min_stock * 2 if velocity == 0 else 0)
        suggest = max(0.0, target - q)
        if suggest <= 0 and q > min_stock:
            continue
        suggest = max(suggest, min_stock - q + 1) if q <= min_stock else suggest
        out.append({"product": prod, "quantity": qty(q), "min_stock": min_stock, "daily_sales": round(velocity, 2),
                    "days_left": None if days_left is None else round(days_left, 1),
                    "suggested": float(round(suggest + 0.4999)) if suggest else 0.0,
                    "supplier": suppliers.get(prod.supplier_id, "بدون مورد"), "unit_cost": prod.cost_price,
                    "est_cost": money(prod.cost_price * round(suggest + 0.4999))})
    out.sort(key=lambda x: (x["days_left"] if x["days_left"] is not None else 9999, x["quantity"]))
    return out


def hourly_heatmap(session: Session, p: Period) -> list[list[float]]:
    """مصفوفة 7 أيام × 24 ساعة لمبيعات الفترة."""
    grid = [[0.0] * 24 for _ in range(7)]
    for created, total in session.execute(select(Invoice.created_at, Invoice.total).where(
            Invoice.kind == "sale", Invoice.status == "posted",
            Invoice.created_at >= p.start_dt, Invoice.created_at < p.end_dt)):
        grid[created.weekday()][created.hour] += total
    return grid


def daily_summary_text(session: Session, day: date | None = None) -> str:
    from ftapp.services import currency_service, notification_service

    p = Period(day or date.today(), day or date.today())
    k = kpis(session, p)
    fmt = lambda v: currency_service.format_amount(session, v)  # noqa: E731
    company = settings.get(session, "company")["name"]
    lines = [f"📊 التقرير اليومي — {company}", f"📅 {p.start:%Y-%m-%d}", "",
             f"💰 المبيعات: {fmt(k['sales'])}", f"🧾 عدد الفواتير: {k['invoices']}",
             f"📈 الربح الإجمالي: {fmt(k['gross_profit'])}", f"💸 المصاريف: {fmt(k['expenses'])}",
             f"✅ صافي الربح: {fmt(k['net_profit'])}"]
    top = top_products(session, p, 3)
    if top:
        lines += ["", "🏆 الأكثر مبيعاً:"] + [f"  • {t['name']} ({t['quantity']:g})" for t in top]
    alerts = notification_service.important_alerts(session, 10)
    if alerts:
        lines += ["", f"⚠️ تنبيهات ({len(alerts)}):"] + [f"  • {a.title}" for a in alerts[:10]]
    return "\n".join(lines)


def ai_context(session: Session) -> dict[str, Any]:
    """ملخص منظم للبيانات يُرسل للذكاء الاصطناعي للإجابة عن الأسئلة (بدون أي صلاحية تعديل)."""
    from ftapp.services import currency_service, notification_service

    ctx: dict[str, Any] = {"today": date.today().isoformat(),
                           "currency": currency_service.base(session).code}
    for name in ("today", "week", "month", "last_month", "year"):
        p = period(name)
        k = kpis(session, p)
        ctx[f"kpis_{name}"] = {key: k[key] for key in ("sales", "invoices", "gross_profit", "expenses", "net_profit",
                                                        "returns", "avg_invoice", "margin_percent")}
    ctx["stock"] = inventory_service.valuation(session)
    m = period("month")
    ctx["top_products_month"] = [{k: r[k] for k in ("name", "quantity", "revenue", "profit", "share")}
                                 for r in top_products(session, m, 15)]
    ctx["top_products_year"] = [{k: r[k] for k in ("name", "quantity", "revenue", "profit", "share")}
                                for r in top_products(session, period("year"), 15)]
    ctx["categories_month"] = sales_by_category(session, m)
    ctx["categories_year"] = sales_by_category(session, period("year"))
    ctx["low_stock"] = [{"name": p.name, "code": p.code, "quantity": p.quantity}
                        for p in inventory_service.low_stock_products(session)[:30]]
    ctx["slow_movers"] = [{"name": s["product"].name, "quantity": s["quantity"], "idle_days": s["idle_days"]}
                          for s in slow_movers(session)[:20]]
    ctx["reorder"] = [{"name": r["product"].name, "days_left": r["days_left"], "suggested": r["suggested"]}
                      for r in reorder_suggestions(session)[:20]]
    ctx["monthly_series_year"] = [{"month": r["label"], "sales": r["sales"], "profit": r["profit"]}
                                  for r in sales_series(session, period("year"), "month")]
    ctx["alerts"] = [a.title for a in notification_service.important_alerts(session, 20)]
    from ftapp.services import sales_service
    ctx["top_debtors"] = [{"name": c.name, "balance": c.balance}
                          for c in sorted(sales_service.list_customers(session, debtors_only=True),
                                          key=lambda c: -c.balance)[:15]]
    ctx["commissions_month"] = [{"seller": c["user"].display_name, "net": c["net"], "commission": c["commission"]}
                                for c in finance_service.commissions(session, m.start, m.end)]
    return ctx
