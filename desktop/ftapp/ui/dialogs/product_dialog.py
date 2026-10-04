"""نافذة إضافة/تعديل منتج بكل تفاصيله."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ftapp.core.utils import fmt_qty
from ftapp.models import CustomField, Product
from ftapp.services import (catalog_service, codegen_service, currency_service, gemini_service, inventory_service,
                            settings_service)
from ftapp.services.errors import ValidationError
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Toast, button, confirm, error, fill_combo, muted
from ftapp.ui.widgets.forms import date_edit, money_spin, qty_spin
from ftapp.ui.widgets.table import Column, DataTable
from ftapp.ui.widgets.worker import run_async


def category_items(session) -> list[tuple[str, int]]:
    return [(("    " * depth) + ("└ " if depth else "") + c.name, c.id) for c, depth in catalog_service.category_tree(session)]


class FieldEditor:
    """ودجت مناسب لكل نوع خانة مخصصة."""

    def __init__(self, fld: CustomField, value: str) -> None:
        self.field = fld
        t = fld.field_type
        if t == "bool":
            self.widget = QCheckBox("نعم")
            self.widget.setChecked(value == "1")
        elif t == "choice":
            self.widget = QComboBox()
            self.widget.addItem("—", "")
            for opt in fld.options:
                self.widget.addItem(opt, opt)
            i = self.widget.findData(value)
            self.widget.setCurrentIndex(max(i, 0))
        elif t == "date":
            self.widget = QDateEdit()
            self.widget.setCalendarPopup(True)
            self.widget.setDisplayFormat("yyyy-MM-dd")
            self.widget.setSpecialValueText("—")
            self.widget.setMinimumDate(QDate(1900, 1, 1))
            if value:
                d = date.fromisoformat(value[:10])
                self.widget.setDate(QDate(d.year, d.month, d.day))
            else:
                self.widget.setDate(self.widget.minimumDate())
        elif t == "number":
            self.widget = QSpinBox()
            self.widget.setRange(-10**9, 10**9)
            self.widget.setSpecialValueText(" ")
            self.widget.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            self.widget.setValue(int(float(value)) if value else 0)
        elif t == "decimal":
            self.widget = QDoubleSpinBox()
            self.widget.setRange(-10**12, 10**12)
            self.widget.setDecimals(3)
            self.widget.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            self.widget.setValue(float(value) if value else 0)
        else:
            self.widget = QLineEdit(value)
            if t == "url":
                self.widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                self.widget.setPlaceholderText("https://")
            if t == "image":
                self.widget.setPlaceholderText("مسار صورة أو رابط")

    def value(self) -> str:
        w, t = self.widget, self.field.field_type
        if t == "bool":
            return "1" if w.isChecked() else "0"
        if t == "choice":
            return w.currentData() or ""
        if t == "date":
            return "" if w.date() == w.minimumDate() else w.date().toPython().isoformat()
        if t == "number":
            return str(w.value()) if w.value() else ""
        if t == "decimal":
            return str(w.value()) if w.value() else ""
        return w.text().strip()

    def set_value(self, value: str) -> None:
        w, t = self.widget, self.field.field_type
        try:
            if t == "bool":
                w.setChecked(value.strip() in ("1", "نعم", "yes", "true"))
            elif t == "choice":
                i = w.findText(value)
                if i >= 0:
                    w.setCurrentIndex(i)
            elif t in ("number", "decimal"):
                import re
                num = re.findall(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
                if num:
                    w.setValue(float(num[0]) if t == "decimal" else int(float(num[0])))
            elif t == "date":
                d = date.fromisoformat(value[:10])
                w.setDate(QDate(d.year, d.month, d.day))
            else:
                w.setText(value)
        except (ValueError, TypeError):
            pass


class ProductDialog(QDialog):
    def __init__(self, parent: QWidget | None, product_id: int | None = None, preset: dict | None = None) -> None:
        super().__init__(parent)
        self.product_id = product_id
        self.preset = preset or {}
        self.saved_id: int | None = None
        self.field_editors: dict[int, FieldEditor] = {}
        self.pending_values: dict[int, str] = {}
        self.pending_images: list[tuple[bytes, str]] = []
        self.setWindowTitle("تعديل منتج" if product_id else "منتج جديد")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(980, 720)
        self.can_cost = ctx.can("products.view_cost")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        head = QHBoxLayout()
        self.heading = QLabel(self.windowTitle())
        self.heading.setObjectName("pageTitle")
        head.addWidget(self.heading)
        head.addStretch(1)
        self.stock_badge = QLabel()
        head.addWidget(self.stock_badge)
        root.addLayout(head)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        with ctx.session() as (s, _):
            self._load_refs(s)
            self._build_basic()
            self._build_pricing(s)
            self._build_fields_tab()
            self._build_details()
            self._build_images()
            if product_id:
                self._build_history(s)
            self._load(s)

        self.error_label = QLabel()
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)
        row = QHBoxLayout()
        if product_id and ctx.can("products.edit"):
            row.addWidget(button("طباعة ملصق", "barcode", on_click=self._print_label))
        row.addStretch(1)
        row.addWidget(button("إلغاء", on_click=self.reject))
        if product_id is None:
            row.addWidget(button("حفظ وإضافة آخر", "plus", on_click=lambda: self._save(again=True)))
        self.save_btn = button("حفظ", "check", "primary", on_click=self._save)
        self.save_btn.setEnabled(ctx.can("products.edit"))
        row.addWidget(self.save_btn)
        root.addLayout(row)
        self.name.setFocus()

    # ------------------------------------------------------------------
    def _load_refs(self, s) -> None:
        self.cats = category_items(s)
        self.brands = catalog_service.brands(s)
        self.suppliers = [(sp.name, sp.id) for sp in catalog_service.list_suppliers(s)]
        self.warehouses = [(w.name, w.id) for w in inventory_service.list_warehouses(s)]
        self.tiers = [(t.name, t.id) for t in catalog_service.list_tiers(s) if not t.is_default]
        self.cur = currency_service.base(s)
        self.default_min = settings_service.get(s, "default_min_stock")

    def _scroll_tab(self, title: str, icon_name: str) -> QVBoxLayout:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(w)
        self.tabs.addTab(sc, icons.icon(icon_name), title)
        return lay

    def _form(self, lay: QVBoxLayout) -> QFormLayout:
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(10)
        lay.addLayout(f)
        return f

    def _build_basic(self) -> None:
        lay = self._scroll_tab("البيانات الأساسية", "box")
        f = self._form(lay)
        self.name = QLineEdit()
        self.name.setPlaceholderText("مثال: سماعة بلوتوث Xiaomi Buds 4")
        f.addRow("اسم المنتج *", self.name)

        code_row = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.code.setPlaceholderText("اتركه فارغاً للتوليد التلقائي")
        code_row.addWidget(self.code, 1)
        code_row.addWidget(button("توليد كود", "refresh", "soft", on_click=self._gen_code,
                                  tooltip="كود مقارب لاسم المنتج والقسم والماركة"))
        if ctx.can("ai.use"):
            code_row.addWidget(button("اقتراح بالذكاء", "sparkles", on_click=self._ai_code))
        f.addRow("الكود", self._wrap(code_row))

        bc_row = QHBoxLayout()
        self.barcode = QLineEdit()
        self.barcode.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.barcode.setPlaceholderText("امسح الباركود بالقارئ أو ولّد باركوداً داخلياً")
        bc_row.addWidget(self.barcode, 1)
        bc_row.addWidget(button("باركود داخلي", "barcode", on_click=self._gen_barcode))
        f.addRow("الباركود", self._wrap(bc_row))

        self.category = QComboBox()
        fill_combo(self.category, self.cats, placeholder="— بدون قسم —")
        self.category.currentIndexChanged.connect(self._category_changed)
        f.addRow("القسم", self.category)
        self.brand = QComboBox()
        self.brand.setEditable(True)
        self.brand.addItems([""] + self.brands)
        f.addRow("الماركة", self.brand)
        self.model = QLineEdit()
        f.addRow("الموديل", self.model)
        self.unit = QComboBox()
        self.unit.setEditable(True)
        self.unit.addItems(catalog_service.UNITS)
        f.addRow("الوحدة", self.unit)
        self.supplier = QComboBox()
        fill_combo(self.supplier, self.suppliers, placeholder="— بدون —")
        f.addRow("المورد", self.supplier)
        self.location = QLineEdit()
        self.location.setPlaceholderText("مثال: رف A-3")
        f.addRow("الموقع في المستودع", self.location)
        flags = QHBoxLayout()
        self.active = QCheckBox("فعّال (يظهر للبيع)")
        self.active.setChecked(True)
        self.track_expiry = QCheckBox("يتبع تاريخ صلاحية")
        flags.addWidget(self.active)
        flags.addWidget(self.track_expiry)
        flags.addStretch(1)
        f.addRow("", self._wrap(flags))
        self.variant_info = muted("")
        lay.addWidget(self.variant_info)
        lay.addStretch(1)

    def _build_pricing(self, s) -> None:
        lay = self._scroll_tab("التسعير والمخزون", "money")
        f = self._form(lay)
        sym = self.cur.symbol
        self.cost = money_spin(suffix=sym)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(-100, 10000)
        self.margin.setDecimals(2)
        self.margin.setSuffix(" %")
        self.margin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.inherit_margin = QCheckBox("استخدم نسبة ربح القسم")
        self.price = money_spin(suffix=sym)
        self.price_locked = QCheckBox("سعر ثابت (لا يتغير مع التكلفة)")
        self.actual_margin = muted("")
        if self.can_cost:
            f.addRow("سعر التكلفة", self.cost)
            m_row = QHBoxLayout()
            m_row.addWidget(self.margin, 1)
            m_row.addWidget(self.inherit_margin)
            f.addRow("نسبة الربح (نسبة المبيع)", self._wrap(m_row))
        p_row = QHBoxLayout()
        p_row.addWidget(self.price, 1)
        p_row.addWidget(self.price_locked)
        f.addRow("سعر البيع (مفرّق)", self._wrap(p_row))
        f.addRow("", self.actual_margin)
        for w in (self.cost, self.margin):
            w.valueChanged.connect(self._recalc_price)
        self.inherit_margin.toggled.connect(self._recalc_price)
        self.price_locked.toggled.connect(self._recalc_price)
        self.price.valueChanged.connect(self._update_margin_label)

        self.tier_spins: dict[int, QDoubleSpinBox] = {}
        if self.tiers:
            box = QGridLayout()
            box.setHorizontalSpacing(12)
            for i, (name, tid) in enumerate(self.tiers):
                sp = money_spin(suffix=sym)
                sp.setSpecialValueText("تلقائي")
                self.tier_spins[tid] = sp
                box.addWidget(QLabel(name), i, 0)
                box.addWidget(sp, i, 1)
            f.addRow("أسعار الشرائح", self._wrap(box))
            f.addRow("", muted("اترك السعر «تلقائي» ليُحسب من نسبة ربح الشريحة أو سعر المفرّق."))

        self.min_stock = qty_spin()
        self.use_default_min = QCheckBox(f"الافتراضي ({fmt_qty(self.default_min)})")
        self.use_default_min.toggled.connect(lambda c: self.min_stock.setEnabled(not c))
        ms_row = QHBoxLayout()
        ms_row.addWidget(self.min_stock, 1)
        ms_row.addWidget(self.use_default_min)
        f.addRow("حد التنبيه (أقل كمية)", self._wrap(ms_row))
        f.addRow("", muted("عند وصول الكمية لهذا الحد أو أقل يظهر تنبيه في لوحة التحكم والموبايل."))

        if self.product_id is None:
            self.initial_qty = qty_spin()
            self.initial_wh = QComboBox()
            fill_combo(self.initial_wh, self.warehouses)
            self.initial_expiry = date_edit()
            f.addRow("الكمية الافتتاحية", self.initial_qty)
            if len(self.warehouses) > 1:
                f.addRow("في المستودع", self.initial_wh)
            self.expiry_row_label = QLabel("تاريخ الصلاحية")
            f.addRow(self.expiry_row_label, self.initial_expiry)
            self.track_expiry.toggled.connect(lambda c: (self.initial_expiry.setVisible(c),
                                                         self.expiry_row_label.setVisible(c)))
            self.initial_expiry.setVisible(False)
            self.expiry_row_label.setVisible(False)
        else:
            self.stock_table = DataTable([Column("المستودع", "wh", stretch=True), Column("الكمية", "qty", "qty")])
            self.stock_table.setMaximumHeight(160)
            f.addRow("الكمية الحالية", self.stock_table)
            if ctx.can("inventory.adjust"):
                f.addRow("", button("تعديل الكمية", "edit", "soft", on_click=self._adjust_stock))
        lay.addStretch(1)

    def _build_fields_tab(self) -> None:
        lay = self._scroll_tab("الخانات المخصصة", "list")
        top = QHBoxLayout()
        top.addWidget(muted("خانات تضيفها بنفسك. الخانات المرئية للمستخدمين تظهر في تطبيق الموبايل."), 1)
        if ctx.can("categories.manage"):
            top.addWidget(button("إضافة خانة", "plus", "soft", on_click=self._add_field))
        lay.addLayout(top)
        self.fields_form = QFormLayout()
        self.fields_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.fields_form.setVerticalSpacing(10)
        lay.addLayout(self.fields_form)
        lay.addStretch(1)

    def _build_details(self) -> None:
        lay = self._scroll_tab("التفاصيل والمواصفات", "info")
        if ctx.can("ai.use"):
            ai_row = QHBoxLayout()
            self.ai_btn = button("جلب التفاصيل بالذكاء الاصطناعي", "sparkles", "primary", on_click=self._ai_details)
            self.ai_status = muted("")
            ai_row.addWidget(self.ai_btn)
            ai_row.addWidget(self.ai_status, 1)
            lay.addLayout(ai_row)
        lay.addWidget(QLabel("تفاصيل المنتج"))
        self.details = QPlainTextEdit()
        self.details.setPlaceholderText("وصف المنتج، طريقة الاستخدام، الضمان...")
        self.details.setMinimumHeight(110)
        lay.addWidget(self.details)
        lay.addWidget(QLabel("المواصفات"))
        self.specs = QTableWidget(0, 2)
        self.specs.setHorizontalHeaderLabels(["المواصفة", "القيمة"])
        self.specs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.specs.verticalHeader().setVisible(False)
        self.specs.setMinimumHeight(170)
        lay.addWidget(self.specs)
        srow = QHBoxLayout()
        srow.addWidget(button("إضافة مواصفة", "plus", on_click=lambda: self._add_spec("", "")))
        srow.addWidget(button("حذف المحدد", "trash", on_click=lambda: self.specs.removeRow(self.specs.currentRow())))
        srow.addStretch(1)
        lay.addLayout(srow)
        lay.addWidget(QLabel("ملاحظات داخلية"))
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(80)
        lay.addWidget(self.notes)

    def _build_images(self) -> None:
        lay = self._scroll_tab("الصور", "image")
        row = QHBoxLayout()
        row.addWidget(button("إضافة صورة", "plus", on_click=self._add_image))
        if ctx.can("ai.use"):
            row.addWidget(button("تعرّف على المنتج من صورة", "camera", "soft", on_click=self._identify_image))
        row.addWidget(button("حذف المحددة", "trash", on_click=self._remove_image))
        row.addStretch(1)
        lay.addLayout(row)
        self.images = QListWidget()
        self.images.setViewMode(QListWidget.ViewMode.IconMode)
        self.images.setIconSize(QSize(150, 150))
        self.images.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.images.setSpacing(10)
        self.images.setMinimumHeight(360)
        lay.addWidget(self.images, 1)

    def _build_history(self, s) -> None:
        lay = self._scroll_tab("سجل الأسعار والحركات", "clock")
        sym = self.cur.symbol
        cols = [Column("التاريخ", "changed_at", "datetime"), Column("السعر القديم", "old_price", "money", symbol=sym),
                Column("السعر الجديد", "new_price", "money", symbol=sym, bold=True)]
        if self.can_cost:
            cols += [Column("التكلفة القديمة", "old_cost", "money", symbol=sym),
                     Column("التكلفة الجديدة", "new_cost", "money", symbol=sym)]
        cols.append(Column("السبب", "reason", stretch=True))
        self.history = DataTable(cols)
        self.history.setMinimumHeight(180)
        lay.addWidget(QLabel("سجل تغيّر الأسعار"))
        lay.addWidget(self.history)
        from ftapp.ui.widgets.charts import SalesChart
        self.price_chart = SalesChart()
        self.price_chart.setMinimumHeight(200)
        lay.addWidget(self.price_chart)
        lay.addWidget(QLabel("آخر حركات المخزون"))
        self.moves = DataTable([Column("التاريخ", "date", "datetime"), Column("النوع", "kind"),
                                Column("الكمية", "qty", "qty", color=lambda r: tokens()["success"] if r["qty"] > 0 else tokens()["danger"]),
                                Column("الرصيد", "balance", "qty"), Column("المستودع", "wh"),
                                Column("البيان", "reason", stretch=True)])
        self.moves.setMinimumHeight(200)
        lay.addWidget(self.moves)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    # ------------------------------------------------------------------
    def _load(self, s) -> None:
        if not self.product_id:
            pre = self.preset
            self.name.setText(pre.get("name", ""))
            self.code.setText(pre.get("code", ""))
            self.barcode.setText(pre.get("barcode", ""))
            if pre.get("category_id"):
                self.category.setCurrentIndex(max(0, self.category.findData(pre["category_id"])))
            self.use_default_min.setChecked(True)
            self.inherit_margin.setChecked(True)
            self._rebuild_fields(s, {})
            self._recalc_price()
            return
        p = s.get(Product, self.product_id)
        self.heading.setText(f"تعديل: {p.name}")
        self.name.setText(p.name)
        self.code.setText(p.code)
        self.barcode.setText(p.barcode or "")
        self.category.setCurrentIndex(max(0, self.category.findData(p.category_id)))
        self.brand.setCurrentText(p.brand)
        self.model.setText(p.model)
        self.unit.setCurrentText(p.unit)
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(p.supplier_id)))
        self.location.setText(p.location)
        self.active.setChecked(p.is_active)
        self.track_expiry.setChecked(p.track_expiry)
        self.cost.setValue(p.cost_price)
        self.inherit_margin.setChecked(p.margin is None)
        self.margin.setValue(p.margin if p.margin is not None else (catalog_service.effective_margin(s, p) or 0))
        self.price_locked.setChecked(p.price_locked)
        self.price.setValue(p.sale_price)
        for tp in p.tier_prices:
            if tp.tier_id in self.tier_spins:
                self.tier_spins[tp.tier_id].setValue(tp.price)
        self.use_default_min.setChecked(p.min_stock is None)
        self.min_stock.setValue(p.min_stock or 0)
        self.details.setPlainText(p.details)
        for k, v in (p.specs or {}).items():
            self._add_spec(k, str(v))
        self.notes.setPlainText(p.notes)
        self._rebuild_fields(s, {fv.field_id: fv.value for fv in p.field_values})
        for img in p.images:
            self._add_image_item(str(catalog_service.image_path(img)), img.id)
        self.stock_table.set_rows([{"wh": lvl.warehouse.name, "qty": lvl.quantity} for lvl in p.stock_levels])
        status = catalog_service.stock_status(s, p)
        kind = {"out": "badgeDanger", "low": "badgeWarning"}.get(status, "badgeSuccess")
        self.stock_badge.setObjectName(kind)
        self.stock_badge.setText(f"  الكمية: {fmt_qty(p.quantity)} {p.unit}  ")
        if p.parent_id:
            self.variant_info.setText(f"هذا متغير من المنتج: {p.parent.name} ({p.variant_label})")
        elif p.variants:
            self.variant_info.setText(f"لهذا المنتج {len(p.variants)} متغيرات: " + "، ".join(v.variant_label for v in p.variants[:8]))
        self.history.set_rows(catalog_service.price_history(s, p.id))
        hist = catalog_service.price_history(s, p.id)
        if hist:
            self.price_chart.set_data([h.changed_at.strftime("%y-%m-%d") for h in hist], [h.new_price for h in hist],
                                      [h.new_cost for h in hist] if self.can_cost else None)
        mv = inventory_service.movements(s, product_id=p.id, limit=100)
        self.moves.set_rows([{"date": m.created_at, "kind": inventory_service.MOVEMENT_KINDS.get(m.kind, m.kind),
                              "qty": m.quantity, "balance": m.balance_after, "wh": m.warehouse.name,
                              "reason": m.reason} for m in mv])
        self._recalc_price()

    def _rebuild_fields(self, s, values: dict[int, str]) -> None:
        current = {fid: ed.value() for fid, ed in self.field_editors.items()}
        current.update({k: v for k, v in values.items()})
        current.update(self.pending_values)
        while self.fields_form.rowCount():
            self.fields_form.removeRow(0)
        self.field_editors.clear()
        fields = catalog_service.list_fields(s, self.category.currentData())
        if not fields:
            self.fields_form.addRow(muted("لا توجد خانات مخصصة لهذا القسم بعد."))
        for fld in fields:
            ed = FieldEditor(fld, current.get(fld.id, fld.default_value))
            label = fld.name + (" *" if fld.required else "")
            if not fld.visible_to_users:
                label += " 🔒"
                ed.widget.setToolTip("مخفية عن المستخدمين")
            self.fields_form.addRow(label, ed.widget)
            self.field_editors[fld.id] = ed

    def _category_changed(self) -> None:
        with ctx.session() as (s, _):
            self._rebuild_fields(s, {})
        self._recalc_price()

    def _category_margin(self) -> float | None:
        with ctx.session() as (s, _):
            for cid in catalog_service.ancestor_ids(s, self.category.currentData()):
                from ftapp.models import Category
                c = s.get(Category, cid)
                if c and c.default_margin is not None:
                    return c.default_margin
        return None

    def _recalc_price(self) -> None:
        inherit = self.inherit_margin.isChecked()
        cat_margin = self._category_margin() if inherit else None
        if inherit:
            self.margin.blockSignals(True)
            self.margin.setValue(cat_margin or 0)
            self.margin.blockSignals(False)
        self.margin.setEnabled(not inherit)
        margin = cat_margin if inherit else self.margin.value()
        if not self.price_locked.isChecked() and margin is not None and self.cost.value() > 0:
            self.price.blockSignals(True)
            self.price.setValue(catalog_service.price_from_margin(self.cost.value(), margin))
            self.price.blockSignals(False)
        self.price.setReadOnly(not self.price_locked.isChecked() and margin is not None and self.cost.value() > 0)
        self._update_margin_label()

    def _update_margin_label(self) -> None:
        if not self.can_cost:
            return
        cost, price = self.cost.value(), self.price.value()
        if cost > 0:
            m = (price - cost) / cost * 100
            color = tokens()["danger"] if m < 0 else tokens()["success"]
            self.actual_margin.setText(f"الربح بالقطعة: {price - cost:,.2f} {self.cur.symbol} — نسبة فعلية {m:.1f}%")
            self.actual_margin.setStyleSheet(f"color: {color};")
        else:
            self.actual_margin.setText("")

    def _add_spec(self, key: str, value: str) -> None:
        r = self.specs.rowCount()
        self.specs.insertRow(r)
        self.specs.setItem(r, 0, QTableWidgetItem(key))
        self.specs.setItem(r, 1, QTableWidgetItem(value))

    def _collect_specs(self) -> dict[str, str]:
        out = {}
        for r in range(self.specs.rowCount()):
            k = (self.specs.item(r, 0).text() if self.specs.item(r, 0) else "").strip()
            v = (self.specs.item(r, 1).text() if self.specs.item(r, 1) else "").strip()
            if k:
                out[k] = v
        return out

    # ------------------------------------------------------------------
    def _gen_code(self) -> None:
        if not self.name.text().strip():
            self.error_label.setText("أدخل اسم المنتج أولاً لتوليد الكود")
            return
        with ctx.session() as (s, _):
            self.code.setText(codegen_service.generate_code(s, self.name.text(), self.category.currentData(),
                                                            self.brand.currentText(), self.model.text(),
                                                            self.product_id))

    def _gen_barcode(self) -> None:
        with ctx.session() as (s, _):
            self.barcode.setText(codegen_service.generate_internal_barcode(s))

    def _ai_code(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.error_label.setText("أدخل اسم المنتج أولاً")
            return
        cat = self.category.currentText().strip(" └")
        brand, model = self.brand.currentText(), self.model.text()
        Toast.show_message(self, "جارِ طلب اقتراح كود من Gemini...")

        def work():
            from ftapp.core.db import session_scope
            from ftapp.models import Product as P
            from sqlalchemy import select
            with session_scope() as s:
                examples = list(s.scalars(select(P.code).order_by(P.id.desc()).limit(8)))
                return gemini_service.suggest_code(s, name, cat, brand, model, examples).code
        run_async(work, lambda code: self.code.setText(code), lambda msg: error(self, msg))

    def _ai_details(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.error_label.setText("أدخل اسم المنتج أولاً ثم اطلب التفاصيل")
            return
        field_names = [ed.field.name for ed in self.field_editors.values()]
        brand, model = self.brand.currentText(), self.model.text()
        self.ai_btn.setEnabled(False)
        self.ai_status.setText("⏳ جارِ البحث عن تفاصيل المنتج...")

        def work():
            from ftapp.core.db import session_scope
            with session_scope() as s:
                return gemini_service.fetch_product_details(s, name, brand, model, field_names=field_names)

        def done(details) -> None:
            self.ai_btn.setEnabled(True)
            self.ai_status.setText("")
            from ftapp.ui.dialogs.ai_dialogs import AIDetailsPreview
            dlg = AIDetailsPreview(self, details, [ed.field for ed in self.field_editors.values()])
            if dlg.exec():
                self._apply_ai(dlg.selection())

        def fail(msg: str) -> None:
            self.ai_btn.setEnabled(True)
            self.ai_status.setText("")
            error(self, msg)
        run_async(work, done, fail)

    def _apply_ai(self, sel: dict[str, Any]) -> None:
        if sel.get("description"):
            current = self.details.toPlainText().strip()
            self.details.setPlainText((current + "\n\n" if current else "") + sel["description"])
        existing = self._collect_specs()
        for k, v in sel.get("specs", {}).items():
            if k not in existing:
                self._add_spec(k, v)
        for fid, value in sel.get("fields", {}).items():
            if fid in self.field_editors:
                self.field_editors[fid].set_value(value)
        if sel.get("category"):
            idx = next((i for i in range(self.category.count())
                        if self.category.itemText(i).strip(" └") == sel["category"]), -1)
            if idx >= 0:
                self.category.setCurrentIndex(idx)
        Toast.show_message(self, "تم تطبيق التفاصيل المختارة. راجعها ثم احفظ.", "success")

    def _add_field(self) -> None:
        from ftapp.ui.dialogs.catalog_dialogs import FieldDialog

        dlg = FieldDialog(self, preset_category=self.category.currentData())
        if dlg.exec():
            with ctx.session() as (s, _):
                self._rebuild_fields(s, {})

    def _add_image_item(self, path: str, image_id: int | None) -> None:
        pm = QPixmap(path)
        item = QListWidgetItem(icons.QIcon(pm) if not pm.isNull() else icons.icon("image"), "")
        item.setData(Qt.ItemDataRole.UserRole, image_id)
        item.setData(Qt.ItemDataRole.UserRole + 1, path)
        self.images.addItem(item)

    def _add_image(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "اختر صوراً", "", "Images (*.png *.jpg *.jpeg *.webp)")
        for path in paths:
            if self.product_id:
                with ctx.session() as (s, _):
                    img = catalog_service.add_image(s, self.product_id, path)
                    self._add_image_item(str(catalog_service.image_path(img)), img.id)
            else:
                self.pending_images.append((Path(path).read_bytes(), Path(path).suffix.lower() or ".jpg"))
                self._add_image_item(path, None)

    def _remove_image(self) -> None:
        for item in self.images.selectedItems():
            image_id = item.data(Qt.ItemDataRole.UserRole)
            if image_id:
                with ctx.session() as (s, _):
                    catalog_service.remove_image(s, image_id)
            else:
                path = item.data(Qt.ItemDataRole.UserRole + 1)
                self.pending_images = [p for p in self.pending_images if p[0] != Path(path).read_bytes()]
            self.images.takeItem(self.images.row(item))

    def _identify_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "صورة المنتج", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        data = Path(path).read_bytes()
        mime = "image/png" if path.lower().endswith(".png") else ("image/webp" if path.lower().endswith(".webp") else "image/jpeg")
        Toast.show_message(self, "⏳ جارِ التعرف على المنتج من الصورة...")

        def done(res) -> None:
            if not self.name.text().strip():
                self.name.setText(res.name)
            if res.brand and not self.brand.currentText():
                self.brand.setCurrentText(res.brand)
            if res.model and not self.model.text():
                self.model.setText(res.model)
            if res.barcode and not self.barcode.text():
                self.barcode.setText(res.barcode)
            if res.description and not self.details.toPlainText().strip():
                self.details.setPlainText(res.description)
            for spec in res.specs:
                self._add_spec(spec.name, spec.value)
            if self.product_id is None:
                self.pending_images.append((data, Path(path).suffix.lower()))
                self._add_image_item(path, None)
            Toast.show_message(self, f"تم التعرف: {res.name} (الثقة: {res.confidence})", "success")
        run_async(lambda: gemini_service.identify_from_image(None, data, mime), done, lambda m: error(self, m))

    def _adjust_stock(self) -> None:
        from ftapp.ui.dialogs.inventory_dialogs import StockAdjustDialog

        if StockAdjustDialog(self, self.product_id).exec():
            with ctx.session() as (s, _):
                p = s.get(Product, self.product_id)
                self.stock_table.set_rows([{"wh": lvl.warehouse.name, "qty": lvl.quantity} for lvl in p.stock_levels])
                self.stock_badge.setText(f"  الكمية: {fmt_qty(p.quantity)} {p.unit}  ")

    def _print_label(self) -> None:
        from ftapp.ui.dialogs.catalog_dialogs import LabelsDialog

        LabelsDialog(self, [self.product_id]).exec()

    # ------------------------------------------------------------------
    def _input(self) -> catalog_service.ProductInput:
        data = catalog_service.ProductInput(
            name=self.name.text(), code=self.code.text(), barcode=self.barcode.text(),
            category_id=self.category.currentData(), brand=self.brand.currentText().strip(),
            model=self.model.text().strip(), unit=self.unit.currentText().strip() or "قطعة",
            cost_price=self.cost.value(), margin=None if self.inherit_margin.isChecked() else self.margin.value(),
            price_locked=self.price_locked.isChecked(), sale_price=self.price.value(),
            min_stock=None if self.use_default_min.isChecked() else self.min_stock.value(),
            supplier_id=self.supplier.currentData(), location=self.location.text().strip(),
            details=self.details.toPlainText().strip(), specs=self._collect_specs(),
            notes=self.notes.toPlainText().strip(), is_active=self.active.isChecked(),
            track_expiry=self.track_expiry.isChecked(),
            custom_values={fid: ed.value() for fid, ed in self.field_editors.items()},
            tier_prices={tid: sp.value() for tid, sp in self.tier_spins.items()},
        )
        if self.product_id is None:
            data.initial_quantity = self.initial_qty.value()
            data.initial_warehouse_id = self.initial_wh.currentData()
            if self.track_expiry.isChecked():
                data.initial_expiry = self.initial_expiry.date().toPython()
        return data

    def _save(self, again: bool = False) -> None:
        self.error_label.clear()
        try:
            with ctx.session() as (s, user):
                if self.product_id:
                    old = s.get(Product, self.product_id)
                    base = catalog_service.product_input_from(old)
                    data = self._input()
                    data.variant_attrs, data.parent_id = base.variant_attrs, base.parent_id
                    if not self.can_cost:
                        data.cost_price, data.margin = base.cost_price, base.margin
                    p = catalog_service.update_product(s, user, self.product_id, data)
                else:
                    p = catalog_service.create_product(s, user, self._input())
                    for blob, ext in self.pending_images:
                        catalog_service.add_image_bytes(s, p.id, blob, ext)
                self.saved_id = p.id
                code = p.code
        except ValidationError as exc:
            self.error_label.setText(str(exc))
            return
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("save product failed")
            self.error_label.setText(f"خطأ غير متوقع: {exc}")
            return
        Toast.show_message(self.parent() or self, f"تم حفظ المنتج ({code})", "success")
        if again:
            preset = {"category_id": self.category.currentData()}
            self.done(2)
            ProductDialog(self.parent(), None, preset).exec()
            return
        self.accept()

    def reject(self) -> None:
        if self.product_id is None and self.name.text().strip() and not confirm(self, "إغلاق بدون حفظ؟"):
            return
        super().reject()
