"""المخزون: الكميات، الحركات، اقتراحات الطلب، الصلاحية، الجرد، النقل، المستودعات."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from ftapp.services import catalog_service, excel_service, inventory_service, report_service
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.catalog_dialogs import open_path
from ftapp.ui.dialogs.inventory_dialogs import ProductPicker, StockAdjustDialog, TransferDialog, WarehouseDialog
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Toast, button, confirm, fill_combo, muted, run_safely
from ftapp.ui.widgets.forms import date_edit
from ftapp.ui.widgets.table import Column, DataTable, status_colors


def export_table(parent, table: DataTable, title: str) -> None:
    path, _ = QFileDialog.getSaveFileName(parent, "تصدير", f"{title}.xlsx", "Excel (*.xlsx)")
    if not path:
        return
    headers, rows, kinds = table.export_data()
    with ctx.session() as (s, _):
        excel_service.export_table(path, title, headers, rows, s, kinds)
    open_path(Path(path))


class InventoryPage(Page):
    title = "المخزون"
    subtitle = "الكميات، الحركات، الجرد، والتنبيهات"

    def __init__(self) -> None:
        super().__init__()
        self.can_adjust = ctx.can("inventory.adjust")
        if self.can_adjust:
            self.actions.addWidget(button("نقل بضاعة", "transfer", on_click=self._transfer))
            self.actions.addWidget(button("جرد جديد", "clipboard", "primary", on_click=self._new_count))
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self._build_stock()
        self._build_moves()
        self._build_reorder()
        self._build_expiry()
        self._build_counts()
        self._build_transfers()
        self._build_warehouses()
        self._build_slow()
        self.tabs.currentChanged.connect(lambda *_: self.refresh_now())
        ctx.signals.stock_changed.connect(self.mark_dirty)
        ctx.signals.products_changed.connect(self.mark_dirty)

    def _tab(self, title: str, icon_name: str) -> QVBoxLayout:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tabs.addTab(w, icons.icon(icon_name), title)
        return lay

    # ---------------- الكميات ----------------
    def _build_stock(self) -> None:
        lay = self._tab("الكميات", "box")
        bar = QHBoxLayout()
        self.st_wh = QComboBox()
        self.st_filter = QComboBox()
        for t_, k in (("الكل", "all"), ("منخفض ونافد", "low"), ("نافد فقط", "out")):
            self.st_filter.addItem(t_, k)
        self.st_wh.currentIndexChanged.connect(self.refresh_now)
        self.st_filter.currentIndexChanged.connect(self.refresh_now)
        bar.addWidget(QLabel("المستودع"))
        bar.addWidget(self.st_wh)
        bar.addWidget(self.st_filter)
        bar.addStretch(1)
        self.valuation = muted("")
        bar.addWidget(self.valuation)
        bar.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.stock, "كميات المخزون")))
        lay.addLayout(bar)
        self.stock = DataTable([
            Column("الكود", "code", width=150), Column("المنتج", "name", stretch=True, bold=True),
            Column("القسم", "category"), Column("الكمية", "qty", "qty", color=lambda r: status_colors(r["status"]), bold=True),
            Column("حد التنبيه", "min", "qty"), Column("الوحدة", "unit"), Column("الموقع", "location"),
            Column("الحالة", lambda r: {"ok": "متوفر", "low": "منخفض", "out": "نافد"}[r["status"]],
                   color=lambda r: status_colors(r["status"])),
        ])
        if self.can_adjust:
            self.stock.activated_row.connect(self._adjust)
            self.stock.add_menu_action("تعديل الكمية", self._adjust)
        lay.addWidget(self.stock, 1)

    def _adjust(self, row) -> None:
        if StockAdjustDialog(self, row["id"]).exec():
            self.refresh_now()

    # ---------------- الحركات ----------------
    def _build_moves(self) -> None:
        lay = self._tab("حركات المخزون", "list")
        bar = QHBoxLayout()
        self.mv_kind = QComboBox()
        self.mv_kind.addItem("كل الحركات", None)
        for k, v in inventory_service.MOVEMENT_KINDS.items():
            self.mv_kind.addItem(v, k)
        self.mv_from = date_edit(date.today() - timedelta(days=30))
        self.mv_to = date_edit()
        for w in (self.mv_kind, QLabel("من"), self.mv_from, QLabel("إلى"), self.mv_to):
            bar.addWidget(w)
        bar.addWidget(button("عرض", "search", "soft", on_click=self.refresh_now))
        bar.addStretch(1)
        bar.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.moves, "حركات المخزون")))
        lay.addLayout(bar)
        t = tokens()
        self.moves = DataTable([
            Column("التاريخ", "date", "datetime"), Column("المنتج", "name", stretch=True), Column("الكود", "code"),
            Column("النوع", "kind"), Column("الكمية", "qty", "qty", bold=True,
                                            color=lambda r: t["success"] if r["qty"] > 0 else t["danger"]),
            Column("الرصيد بعدها", "balance", "qty"), Column("المستودع", "wh"), Column("البيان", "reason"),
        ])
        lay.addWidget(self.moves, 1)

    # ---------------- اقتراحات الطلب ----------------
    def _build_reorder(self) -> None:
        lay = self._tab("اقتراحات الطلب", "sparkles")
        bar = QHBoxLayout()
        self.ro_lookback = QSpinBox()
        self.ro_lookback.setRange(7, 365)
        self.ro_lookback.setValue(30)
        self.ro_lookback.setSuffix(" يوم")
        self.ro_cover = QSpinBox()
        self.ro_cover.setRange(7, 180)
        self.ro_cover.setValue(30)
        self.ro_cover.setSuffix(" يوم")
        for w in (QLabel("حسب مبيعات آخر"), self.ro_lookback, QLabel("واطلب ما يكفي لـ"), self.ro_cover):
            bar.addWidget(w)
        bar.addWidget(button("احسب", "refresh", "soft", on_click=self.refresh_now))
        bar.addStretch(1)
        bar.addWidget(button("تصدير قائمة الطلب", "excel", on_click=lambda: export_table(self, self.reorder, "قائمة الطلب")))
        lay.addLayout(bar)
        t = tokens()
        self.reorder = DataTable([
            Column("المنتج", "name", stretch=True, bold=True), Column("المورد", "supplier"),
            Column("المتوفر", "qty", "qty"), Column("مبيع يومي", "daily", "qty"),
            Column("ينفد خلال", lambda r: f"{r['days']:g} يوم" if r["days"] is not None else "—",
                   color=lambda r: t["danger"] if (r["days"] is not None and r["days"] <= 7) else None),
            Column("الكمية المقترحة", "suggested", "qty", bold=True, color=lambda r: t["primary"]),
            Column("التكلفة التقديرية", "cost", "money"),
        ], multi=True)
        lay.addWidget(self.reorder, 1)
        self.ro_summary = muted("")
        lay.addWidget(self.ro_summary)

    # ---------------- الصلاحية ----------------
    def _build_expiry(self) -> None:
        lay = self._tab("الصلاحية والدفعات", "calendar")
        bar = QHBoxLayout()
        self.ex_days = QSpinBox()
        self.ex_days.setRange(1, 3650)
        self.ex_days.setValue(60)
        self.ex_days.setSuffix(" يوم")
        bar.addWidget(QLabel("تنتهي خلال"))
        bar.addWidget(self.ex_days)
        bar.addWidget(button("عرض", "search", "soft", on_click=self.refresh_now))
        bar.addStretch(1)
        lay.addLayout(bar)
        t = tokens()
        self.expiry = DataTable([
            Column("المنتج", "name", stretch=True, bold=True), Column("الدفعة", "batch"), Column("المستودع", "wh"),
            Column("الكمية", "qty", "qty"), Column("تاريخ الانتهاء", "expiry", "date"),
            Column("المتبقي", lambda r: "منتهي" if r["left"] < 0 else f"{r['left']} يوم",
                   color=lambda r: t["danger"] if r["left"] < 7 else t["warning"]),
        ])
        lay.addWidget(self.expiry, 1)
        lay.addWidget(muted("البيع يخصم تلقائياً من الدفعة الأقرب انتهاءً أولاً (FEFO)."))

    # ---------------- الجرد ----------------
    def _build_counts(self) -> None:
        lay = self._tab("الجرد الفعلي", "clipboard")
        top = QHBoxLayout()
        self.count_combo = QComboBox()
        self.count_combo.currentIndexChanged.connect(self._load_count)
        top.addWidget(QLabel("جلسة الجرد"))
        top.addWidget(self.count_combo, 1)
        if self.can_adjust:
            top.addWidget(button("تطبيق الجرد", "check", "primary", on_click=self._apply_count))
            top.addWidget(button("إلغاء الجلسة", "x", on_click=self._cancel_count))
        top.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.count_lines, "نتيجة الجرد")))
        lay.addLayout(top)
        if self.can_adjust:
            self.count_picker = ProductPicker(self._count_scan, "امسح الباركود أو اكتب الكود ثم Enter لعدّ قطعة")
            lay.addWidget(self.count_picker)
        t = tokens()
        self.count_lines = DataTable([
            Column("المنتج", "name", stretch=True, bold=True), Column("الكود", "code"),
            Column("في النظام", "system", "qty"), Column("المعدود", "counted", "qty", bold=True),
            Column("الفرق", "diff", "qty", bold=True,
                   color=lambda r: t["danger"] if r["diff"] < 0 else (t["success"] if r["diff"] > 0 else t["muted"])),
        ])
        if self.can_adjust:
            self.count_lines.activated_row.connect(self._edit_count_line)
        lay.addWidget(self.count_lines, 1)
        self.count_summary = muted("يمكن الجرد من الموبايل أيضاً: افتح «الجرد» في التطبيق وامسح المنتجات.")
        lay.addWidget(self.count_summary)

    def _new_count(self) -> None:
        with ctx.session() as (s, u):
            whs = inventory_service.list_warehouses(s)
            wh_id = whs[0].id
            if len(whs) > 1:
                names = [w.name for w in whs]
                name, ok = QInputDialog.getItem(self, "جرد جديد", "المستودع", names, 0, False)
                if not ok:
                    return
                wh_id = whs[names.index(name)].id
            c = inventory_service.start_count(s, u, wh_id)
            cid = c.id
        self.tabs.setCurrentIndex(4)
        self.refresh_now()
        self.count_combo.setCurrentIndex(max(0, self.count_combo.findData(cid)))

    def _count_scan(self, pid: int, name: str, code: str) -> None:
        cid = self.count_combo.currentData()
        if not cid:
            Toast.show_message(self, "ابدأ جلسة جرد أولاً", "warning")
            return
        def do():
            with ctx.session() as (s, _):
                inventory_service.set_count_line(s, cid, pid, 1, mode="add")
        if run_safely(self, do):
            self._load_count()

    def _edit_count_line(self, row) -> None:
        q, ok = QInputDialog.getDouble(self, "الكمية المعدودة", row["name"], row["counted"], 0, 1e9, 3)
        if ok:
            with ctx.session() as (s, _):
                inventory_service.set_count_line(s, self.count_combo.currentData(), row["pid"], q, mode="set")
            self._load_count()

    def _apply_count(self) -> None:
        cid = self.count_combo.currentData()
        if not cid or not confirm(self, "تطبيق الجرد سيعدّل كميات النظام لتطابق الكميات المعدودة. متابعة؟"):
            return

        def do():
            with ctx.session() as (s, u):
                return inventory_service.apply_count(s, u, cid)
        n = run_safely(self, do)
        if n is not None:
            Toast.show_message(self, f"تم تطبيق الجرد وتعديل {n if n is not True else 0} منتج", "success")
            self.refresh_now()

    def _cancel_count(self) -> None:
        cid = self.count_combo.currentData()
        if cid and confirm(self, "إلغاء جلسة الجرد؟", danger=True):
            with ctx.session() as (s, _):
                inventory_service.cancel_count(s, cid)
            self.refresh_now()

    def _load_count(self) -> None:
        cid = self.count_combo.currentData()
        if not cid:
            self.count_lines.set_rows([])
            return
        with ctx.session() as (s, _):
            c = inventory_service.get_count(s, cid)
            rows = [{"pid": l.product_id, "name": l.product.name, "code": l.product.code, "system": l.system_qty,
                     "counted": l.counted_qty, "diff": l.difference} for l in c.lines]
        self.count_lines.set_rows(rows)
        short = sum(1 for r in rows if r["diff"] < 0)
        over = sum(1 for r in rows if r["diff"] > 0)
        self.count_summary.setText(f"{len(rows)} منتج معدود • {short} ناقص • {over} زائد")

    # ---------------- النقل ----------------
    def _build_transfers(self) -> None:
        lay = self._tab("النقل بين المستودعات", "transfer")
        self.transfers = DataTable([Column("التاريخ", "date", "datetime"), Column("من", "src"), Column("إلى", "dst"),
                                    Column("الأصناف", "items", stretch=True), Column("ملاحظات", "notes")])
        lay.addWidget(self.transfers, 1)

    def _transfer(self) -> None:
        if TransferDialog(self).exec():
            self.refresh_now()

    # ---------------- المستودعات ----------------
    def _build_warehouses(self) -> None:
        lay = self._tab("المستودعات والفروع", "warehouse")
        bar = QHBoxLayout()
        if self.can_adjust:
            bar.addWidget(button("مستودع جديد", "plus", "primary", on_click=lambda: self._wh(None)))
            bar.addWidget(button("تعديل", "edit", on_click=lambda: self._wh((self.whs.current_row() or {}).get("id"))))
            bar.addWidget(button("إيقاف", "trash", on_click=self._del_wh))
        bar.addStretch(1)
        lay.addLayout(bar)
        self.whs = DataTable([Column("المستودع", "name", stretch=True, bold=True), Column("الموقع", "location"),
                              Column("افتراضي", "default", "bool"), Column("عدد الأصناف", "items", "qty"),
                              Column("قيمة المخزون (تكلفة)", "value", "money")])
        lay.addWidget(self.whs, 1)

    def _wh(self, wid) -> None:
        if wid is False:
            return
        if WarehouseDialog(self, wid).exec():
            self.refresh_now()

    def _del_wh(self) -> None:
        r = self.whs.current_row()
        if r and confirm(self, f"إيقاف المستودع «{r['name']}»؟", danger=True):
            def do():
                with ctx.session() as (s, _):
                    inventory_service.delete_warehouse(s, r["id"])
            run_safely(self, do)
            self.refresh_now()

    # ---------------- الراكد ----------------
    def _build_slow(self) -> None:
        lay = self._tab("البضاعة الراكدة", "clock")
        self.slow = DataTable([Column("المنتج", "name", stretch=True, bold=True), Column("الكمية", "qty", "qty"),
                               Column("آخر بيع", "last", "date"), Column("أيام بدون بيع", "idle", "qty"),
                               Column("القيمة المجمدة", "value", "money", bold=True)])
        lay.addWidget(self.slow, 1)
        lay.addWidget(muted("فكّر بعمل عرض أو خصم على هذه المنتجات لتحرير رأس المال."))

    # ---------------- التحديث ----------------
    def refresh(self) -> None:
        idx = self.tabs.currentIndex()
        with ctx.session() as (s, _):
            whs = inventory_service.list_warehouses(s)
            if self.st_wh.count() != len(whs) + 1:
                fill_combo(self.st_wh, [(w.name, w.id) for w in whs], self.st_wh.currentData(), "كل المستودعات")
            if idx == 0:
                wh = self.st_wh.currentData()
                flt = self.st_filter.currentData()
                products, _ = catalog_service.search_products(s, stock_filter="all" if flt == "all" else flt, limit=None)
                rows = []
                for p in products:
                    q = inventory_service.quantity_in(s, p.id, wh) if wh else p.quantity
                    status = catalog_service.stock_status(s, p)
                    rows.append({"id": p.id, "code": p.code, "name": p.name, "category": p.category.name if p.category else "",
                                 "qty": q, "min": catalog_service.min_stock_for(s, p), "unit": p.unit,
                                 "location": p.location, "status": status})
                self.stock.set_rows(rows)
                v = inventory_service.valuation(s, wh)
                from ftapp.services import currency_service
                if ctx.can("products.view_cost"):
                    self.valuation.setText(f"قيمة المخزون: {currency_service.format_amount(s, v['cost'])} تكلفة • "
                                           f"{currency_service.format_amount(s, v['sale'])} بيع")
            elif idx == 1:
                mv = inventory_service.movements(s, kind=self.mv_kind.currentData(), date_from=self.mv_from.date().toPython(),
                                                 date_to=self.mv_to.date().toPython(), limit=3000)
                self.moves.set_rows([{"date": m.created_at, "name": m.product.name, "code": m.product.code,
                                      "kind": inventory_service.MOVEMENT_KINDS.get(m.kind, m.kind), "qty": m.quantity,
                                      "balance": m.balance_after, "wh": m.warehouse.name, "reason": m.reason} for m in mv])
            elif idx == 2:
                rows = report_service.reorder_suggestions(s, self.ro_lookback.value(), 7, self.ro_cover.value())
                self.reorder.set_rows([{"id": r["product"].id, "name": r["product"].name, "supplier": r["supplier"],
                                        "qty": r["quantity"], "daily": r["daily_sales"], "days": r["days_left"],
                                        "suggested": r["suggested"], "cost": r["est_cost"]} for r in rows])
                from ftapp.services import currency_service
                self.ro_summary.setText(f"{len(rows)} منتج • التكلفة التقديرية للطلب "
                                        f"{currency_service.format_amount(s, sum(r['est_cost'] for r in rows))}")
            elif idx == 3:
                today = date.today()
                self.expiry.set_rows([{"name": b.product.name, "batch": b.batch_no, "wh": b.warehouse.name,
                                       "qty": b.quantity, "expiry": b.expiry_date,
                                       "left": (b.expiry_date - today).days}
                                      for b in inventory_service.batches(s, expiring_within=self.ex_days.value())])
            elif idx == 4:
                current = self.count_combo.currentData()
                fill_combo(self.count_combo, [(f"جرد #{c.id} — {c.warehouse.name} — {c.created_at:%Y-%m-%d}"
                                               + ("" if c.status == "open" else f" ({'مطبق' if c.status == 'applied' else 'ملغى'})"), c.id)
                                              for c in inventory_service.list_counts(s)], current)
            elif idx == 5:
                self.transfers.set_rows([{"date": t.created_at, "src": t.from_warehouse.name, "dst": t.to_warehouse.name,
                                          "items": "، ".join(f"{i.product.name} ×{i.quantity:g}" for i in t.items),
                                          "notes": t.notes} for t in inventory_service.list_transfers(s)])
            elif idx == 6:
                rows = []
                for w in inventory_service.list_warehouses(s, active_only=True):
                    v = inventory_service.valuation(s, w.id)
                    from sqlalchemy import func, select
                    from ftapp.models import StockLevel
                    items = s.scalar(select(func.count(StockLevel.id)).where(StockLevel.warehouse_id == w.id,
                                                                             StockLevel.quantity > 0))
                    rows.append({"id": w.id, "name": w.name, "location": w.location, "default": w.is_default,
                                 "items": items, "value": v["cost"]})
                self.whs.set_rows(rows)
            elif idx == 7:
                self.slow.set_rows([{"name": x["product"].name, "qty": x["quantity"], "last": x["last_sold"],
                                     "idle": x["idle_days"], "value": x["value"]} for x in report_service.slow_movers(s)])
        if idx == 4:
            self._load_count()

    def open_item(self, payload) -> None:
        if isinstance(payload, dict) and payload.get("tab") is not None:
            self.tabs.setCurrentIndex(payload["tab"])
