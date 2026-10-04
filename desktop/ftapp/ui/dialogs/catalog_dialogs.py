"""نوافذ الأقسام والخانات والملصقات والمتغيرات والأسعار والاستيراد والتصدير."""
from __future__ import annotations

import itertools
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ftapp.core.paths import sub_dir
from ftapp.models import Category, CustomField, Product, Promotion
from ftapp.services import catalog_service, excel_service, pdf_service
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.product_dialog import category_items
from ftapp.ui.widgets.common import Toast, button, error, fill_combo, info, muted
from ftapp.ui.widgets.forms import FormDialog, date_edit
from ftapp.ui.widgets.table import Column, DataTable
from ftapp.ui.widgets.worker import run_async


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class CategoryDialog(FormDialog):
    def __init__(self, parent, category_id: int | None = None, parent_id: int | None = None) -> None:
        super().__init__(parent, "تعديل قسم" if category_id else "قسم جديد")
        self.category_id = category_id
        with ctx.session() as (s, _):
            items = [(t, i) for t, i in category_items(s) if i != category_id]
            c = s.get(Category, category_id) if category_id else None
        self.name = self.line("اسم القسم *", c.name if c else "")
        self.code = self.line("الرمز المختصر", c.code if c else "", "مثال: ELC",
                              "حروف إنكليزية تُستخدم في بداية أكواد منتجات هذا القسم")
        self.code.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.parent_combo = QComboBox()
        fill_combo(self.parent_combo, items, (c.parent_id if c else parent_id), placeholder="— قسم رئيسي —")
        self.row("القسم الأب", self.parent_combo)
        margin_row = QHBoxLayout()
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 10000)
        self.margin.setSuffix(" %")
        self.margin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.has_margin = QCheckBox("تفعيل")
        self.has_margin.toggled.connect(self.margin.setEnabled)
        self.has_margin.setChecked(bool(c and c.default_margin is not None))
        self.margin.setEnabled(self.has_margin.isChecked())
        self.margin.setValue(c.default_margin or 0 if c else 0)
        margin_row.addWidget(self.margin, 1)
        margin_row.addWidget(self.has_margin)
        w = QWidget()
        w.setLayout(margin_row)
        self.row("نسبة الربح الافتراضية", w, "تُطبق على منتجات القسم التي ليس لها نسبة خاصة")
        self.color = c.color if c else "#1565C0"
        self.color_btn = QPushButton("  ")
        self.color_btn.clicked.connect(self._pick)
        self._paint()
        self.row("اللون", self.color_btn)
        self.on_save = self._do
        self.finish_layout()

    def _paint(self) -> None:
        self.color_btn.setStyleSheet(f"background: {self.color}; min-width: 60px; border-radius: 8px;")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self)
        if c.isValid():
            self.color = c.name()
            self._paint()

    def _do(self):
        with ctx.session() as (s, u):
            cat = catalog_service.save_category(s, u, self.name.text(), self.code.text(), self.parent_combo.currentData(),
                                                self.margin.value() if self.has_margin.isChecked() else None,
                                                self.color, self.category_id)
            if self.category_id:
                for p in s.query(Product).filter(Product.category_id.in_(catalog_service.descendant_ids(s, cat.id))):
                    catalog_service.recompute_price(s, p)
            return cat.id


class FieldDialog(FormDialog):
    def __init__(self, parent, field_id: int | None = None, preset_category: int | None = None) -> None:
        super().__init__(parent, "تعديل خانة" if field_id else "إضافة خانة جديدة", 500)
        self.field_id = field_id
        with ctx.session() as (s, _):
            cats = category_items(s)
            f = s.get(CustomField, field_id) if field_id else None
        self.name = self.line("اسم الخانة *", f.name if f else "", "مثال: بلد المنشأ، الضمان، اللون")
        self.type = self.combo("النوع", [(v, k) for k, v in catalog_service.FIELD_TYPES.items()],
                               f.field_type if f else "text")
        self.options = QPlainTextEdit("\n".join(f.options) if f else "")
        self.options.setPlaceholderText("خيار في كل سطر")
        self.options.setMaximumHeight(90)
        self.options_label = QLabel("الخيارات")
        self.form.addRow(self.options_label, self.options)
        self.default = self.line("القيمة الافتراضية", f.default_value if f else "")
        self.scope = QComboBox()
        fill_combo(self.scope, cats, f.category_id if f else preset_category, placeholder="كل المنتجات")
        self.row("تظهر في", self.scope, "يمكن جعل الخانة خاصة بقسم معيّن وأقسامه الفرعية")
        self.required = QCheckBox("خانة إجبارية")
        self.required.setChecked(bool(f and f.required))
        self.row("", self.required)
        self.visible = QCheckBox("مرئية للمستخدمين في تطبيق الموبايل")
        self.visible.setChecked(f.visible_to_users if f else True)
        self.row("", self.visible)
        self.type.currentIndexChanged.connect(self._type_changed)
        self._type_changed()
        self.on_save = self._do
        self.finish_layout()

    def _type_changed(self) -> None:
        is_choice = self.type.currentData() == "choice"
        self.options.setVisible(is_choice)
        self.options_label.setVisible(is_choice)

    def _do(self):
        with ctx.session() as (s, u):
            f = catalog_service.save_field(s, u, self.name.text(), self.type.currentData(), self.required.isChecked(),
                                           self.default.text(), self.options.toPlainText().splitlines(),
                                           self.scope.currentData(), self.visible.isChecked(), field_id=self.field_id)
            return f.id


class TierDialog(FormDialog):
    def __init__(self, parent, tier_id: int | None = None) -> None:
        super().__init__(parent, "شريحة سعر")
        self.tier_id = tier_id
        from ftapp.models import PriceTier
        with ctx.session() as (s, _):
            t = s.get(PriceTier, tier_id) if tier_id else None
        self.name = self.line("اسم الشريحة *", t.name if t else "", "مثال: جملة")
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 10000)
        self.margin.setSuffix(" %")
        self.margin.setSpecialValueText("بدون (سعر المفرّق)")
        self.margin.setValue(t.default_margin or 0 if t else 0)
        self.row("نسبة الربح على التكلفة", self.margin, "تُستخدم عندما لا يكون للمنتج سعر محدد لهذه الشريحة")
        self.on_save = lambda: self._save_tier()
        self.finish_layout()

    def _save_tier(self):
        with ctx.session() as (s, _):
            return catalog_service.save_tier(s, self.name.text(), self.margin.value() or None, self.tier_id).id


class PromotionDialog(FormDialog):
    def __init__(self, parent, promotion_id: int | None = None, product_id: int | None = None) -> None:
        super().__init__(parent, "عرض / خصم مؤقت", 520)
        self.promotion_id = promotion_id
        with ctx.session() as (s, _):
            cats = category_items(s)
            promo = s.get(Promotion, promotion_id) if promotion_id else None
            products, _ = catalog_service.search_products(s, limit=None)
            prods = [(f"{p.name} — {p.code}", p.id) for p in products]
        self.name = self.line("اسم العرض *", promo.name if promo else "", "مثال: عرض رمضان")
        self.percent = QDoubleSpinBox()
        self.percent.setRange(0, 99.99)
        self.percent.setSuffix(" %")
        self.percent.setValue(promo.percent if promo else 10)
        self.row("نسبة الخصم", self.percent)
        self.kind_product = QRadioButton("منتج محدد")
        self.kind_cat = QRadioButton("قسم كامل")
        kr = QHBoxLayout()
        kr.addWidget(self.kind_product)
        kr.addWidget(self.kind_cat)
        kw = QWidget()
        kw.setLayout(kr)
        self.row("يطبق على", kw)
        self.product = QComboBox()
        self.product.setEditable(True)
        fill_combo(self.product, prods, promo.product_id if promo else product_id)
        self.row("المنتج", self.product)
        self.category = QComboBox()
        fill_combo(self.category, cats, promo.category_id if promo else None)
        self.row("القسم", self.category)
        self.start = date_edit(promo.start_date if promo else date.today())
        self.end = date_edit(promo.end_date if promo else date.today() + timedelta(days=7))
        self.row("من تاريخ", self.start)
        self.row("إلى تاريخ", self.end)
        self.active = QCheckBox("مفعّل")
        self.active.setChecked(promo.is_active if promo else True)
        self.row("", self.active)
        is_cat = bool(promo and promo.category_id)
        self.kind_cat.setChecked(is_cat)
        self.kind_product.setChecked(not is_cat)
        self.kind_product.toggled.connect(self._kind)
        self._kind()
        self.on_save = self._do
        self.finish_layout()

    def _kind(self) -> None:
        self.product.setEnabled(self.kind_product.isChecked())
        self.category.setEnabled(not self.kind_product.isChecked())

    def _do(self):
        with ctx.session() as (s, _):
            return catalog_service.save_promotion(
                s, self.name.text(), self.percent.value(), self.start.date().toPython(), self.end.date().toPython(),
                self.product.currentData() if self.kind_product.isChecked() else None,
                None if self.kind_product.isChecked() else self.category.currentData(), self.active.isChecked(),
                self.promotion_id).id


class LabelsDialog(QDialog):
    """طباعة ملصقات باركود للمنتجات المحددة."""

    def __init__(self, parent, product_ids: list[int]) -> None:
        super().__init__(parent)
        self.setWindowTitle("طباعة ملصقات الباركود")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(700, 520)
        lay = QVBoxLayout(self)
        t = QLabel("ملصقات الباركود")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["المنتج", "الكود", "عدد الملصقات"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        with ctx.session() as (s, _):
            for pid in product_ids:
                p = s.get(Product, pid)
                if not p:
                    continue
                r = self.table.rowCount()
                self.table.insertRow(r)
                it = QTableWidgetItem(p.name)
                it.setData(Qt.ItemDataRole.UserRole, p.id)
                self.table.setItem(r, 0, it)
                self.table.setItem(r, 1, QTableWidgetItem(p.barcode or p.code))
                sp = QSpinBox()
                sp.setRange(0, 1000)
                sp.setValue(max(1, int(p.quantity)) if p.quantity < 50 else 1)
                self.table.setCellWidget(r, 2, sp)
        lay.addWidget(self.table, 1)
        opts = QHBoxLayout()
        self.size = QComboBox()
        for w, h in ((50, 30), (40, 25), (60, 40), (38, 25), (70, 50)):
            self.size.addItem(f"{w}×{h} ملم", (w, h))
        self.sheet = QComboBox()
        self.sheet.addItem("طابعة ملصقات (ملصق لكل صفحة)", "single")
        self.sheet.addItem("ورقة A4 (شبكة)", "a4")
        self.price = QCheckBox("إظهار السعر")
        self.price.setChecked(True)
        self.company = QCheckBox("إظهار اسم المنشأة")
        self.company.setChecked(True)
        for w in (QLabel("المقاس"), self.size, self.sheet, self.price, self.company):
            opts.addWidget(w)
        opts.addStretch(1)
        lay.addLayout(opts)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("إغلاق", on_click=self.reject))
        row.addWidget(button("إنشاء PDF وطباعة", "print", "primary", on_click=self._go))
        lay.addLayout(row)

    def _go(self) -> None:
        w, h = self.size.currentData()
        with ctx.session() as (s, _):
            items = []
            for r in range(self.table.rowCount()):
                p = s.get(Product, self.table.item(r, 0).data(Qt.ItemDataRole.UserRole))
                items.append((p, self.table.cellWidget(r, 2).value()))
            if not any(n for _, n in items):
                error(self, "حدد عدد الملصقات")
                return
            path = sub_dir("labels") / f"labels_{date.today():%Y%m%d}_{len(items)}.pdf"
            pdf_service.labels_pdf(s, items, path, w, h, self.sheet.currentData(), self.price.isChecked(),
                                   self.company.isChecked())
        open_path(path)
        self.accept()


class VariantsDialog(QDialog):
    """إنشاء متغيرات (ألوان/مقاسات...) لمنتج أساسي."""

    def __init__(self, parent, product_id: int) -> None:
        super().__init__(parent)
        self.product_id = product_id
        self.setWindowTitle("متغيرات المنتج")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(680, 560)
        with ctx.session() as (s, _):
            p = s.get(Product, product_id)
            self.pname = p.name
        lay = QVBoxLayout(self)
        t = QLabel(f"متغيرات: {self.pname}")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        lay.addWidget(muted("أدخل الخصائص وقيمها مفصولة بفاصلة. سيتم إنشاء كل التركيبات كمنتجات فرعية لكل منها كود وكمية."))
        self.attrs = QTableWidget(2, 2)
        self.attrs.setHorizontalHeaderLabels(["الخاصية", "القيم (مفصولة بفاصلة)"])
        self.attrs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.attrs.verticalHeader().setVisible(False)
        self.attrs.setItem(0, 0, QTableWidgetItem("اللون"))
        self.attrs.setItem(0, 1, QTableWidgetItem("أسود، أبيض"))
        self.attrs.setItem(1, 0, QTableWidgetItem("المقاس"))
        self.attrs.setItem(1, 1, QTableWidgetItem(""))
        self.attrs.setMaximumHeight(150)
        lay.addWidget(self.attrs)
        r = QHBoxLayout()
        r.addWidget(button("إضافة خاصية", "plus", on_click=lambda: self.attrs.insertRow(self.attrs.rowCount())))
        r.addWidget(button("معاينة التركيبات", "refresh", "soft", on_click=self._preview))
        r.addStretch(1)
        lay.addLayout(r)
        self.preview = QListWidget()
        lay.addWidget(self.preview, 1)
        self.copy_price = QCheckBox("نسخ سعر المنتج الأساسي للمتغيرات")
        self.copy_price.setChecked(True)
        lay.addWidget(self.copy_price)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("إلغاء", on_click=self.reject))
        row.addWidget(button("إنشاء المتغيرات", "check", "primary", on_click=self._create))
        lay.addLayout(row)

    def _combos(self) -> list[dict[str, str]]:
        import re
        names, values = [], []
        for r in range(self.attrs.rowCount()):
            k = (self.attrs.item(r, 0).text() if self.attrs.item(r, 0) else "").strip()
            v = (self.attrs.item(r, 1).text() if self.attrs.item(r, 1) else "").strip()
            vals = [x.strip() for x in re.split(r"[,،]", v) if x.strip()]
            if k and vals:
                names.append(k)
                values.append(vals)
        return [dict(zip(names, combo)) for combo in itertools.product(*values)] if names else []

    def _preview(self) -> None:
        self.preview.clear()
        for c in self._combos():
            self.preview.addItem(f"{self.pname} - {' '.join(c.values())}")

    def _create(self) -> None:
        combos = self._combos()
        if not combos:
            error(self, "أدخل خاصية واحدة على الأقل مع قيمها")
            return
        try:
            with ctx.session() as (s, u):
                created = catalog_service.create_variants(s, u, self.product_id, combos, self.copy_price.isChecked())
                n = len(created)
        except Exception as exc:
            error(self, str(exc))
            return
        info(self, f"تم إنشاء {n} متغير. يمكنك تعديل كمية وسعر كل متغير من قائمة المنتجات.")
        self.accept()


class BulkPriceDialog(QDialog):
    def __init__(self, parent, product_ids: list[int] | None = None) -> None:
        super().__init__(parent)
        self.product_ids = product_ids or []
        self.setWindowTitle("تحديث الأسعار الجماعي")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(860, 600)
        lay = QVBoxLayout(self)
        t = QLabel("تحديث الأسعار الجماعي")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        lay.addWidget(muted("مفيد عند تغيّر سعر الصرف أو سعر المورد: عدّل أسعار قسم أو ماركة كاملة بنسبة مئوية."))
        f = QHBoxLayout()
        with ctx.session() as (s, _):
            cats = category_items(s)
            brands = catalog_service.brands(s)
            sups = [(x.name, x.id) for x in catalog_service.list_suppliers(s)]
        self.scope = QComboBox()
        if self.product_ids:
            self.scope.addItem(f"المنتجات المحددة ({len(self.product_ids)})", "selected")
        self.scope.addItem("قسم", "category")
        self.scope.addItem("ماركة", "brand")
        self.scope.addItem("مورد", "supplier")
        self.scope.addItem("كل المنتجات", "all")
        self.value = QComboBox()
        self.cats, self.brands, self.sups = cats, [(b, b) for b in brands], sups
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.percent = QDoubleSpinBox()
        self.percent.setRange(-90, 1000)
        self.percent.setSuffix(" %")
        self.percent.setValue(10)
        self.target = QComboBox()
        self.target.addItem("التكلفة وسعر البيع معاً", "both")
        self.target.addItem("سعر البيع فقط", "price")
        self.target.addItem("التكلفة فقط (السعر يتبع نسبة الربح)", "cost")
        for w in (QLabel("النطاق"), self.scope, self.value, QLabel("النسبة"), self.percent, self.target):
            f.addWidget(w)
        f.addWidget(button("معاينة", "refresh", "soft", on_click=self._preview))
        lay.addLayout(f)
        self.table = DataTable([Column("المنتج", "name", stretch=True), Column("التكلفة الحالية", "oc", "money"),
                                Column("التكلفة الجديدة", "nc", "money", bold=True), Column("السعر الحالي", "op", "money"),
                                Column("السعر الجديد", "np", "money", bold=True)])
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.summary = muted("")
        row.addWidget(self.summary, 1)
        row.addWidget(button("إلغاء", on_click=self.reject))
        row.addWidget(button("تطبيق التحديث", "check", "primary", on_click=self._apply))
        lay.addLayout(row)
        self._scope_changed()

    def _scope_changed(self) -> None:
        kind = self.scope.currentData()
        items = {"category": self.cats, "brand": self.brands, "supplier": self.sups}.get(kind, [])
        fill_combo(self.value, items)
        self.value.setVisible(bool(items))

    def _filter(self) -> catalog_service.BulkPriceFilter:
        kind, val = self.scope.currentData(), self.value.currentData()
        return catalog_service.BulkPriceFilter(
            category_id=val if kind == "category" else None, brand=val if kind == "brand" else None,
            supplier_id=val if kind == "supplier" else None,
            product_ids=self.product_ids if kind == "selected" else None)

    def _preview(self) -> None:
        with ctx.session() as (s, _):
            rows = catalog_service.bulk_price_preview(s, self._filter(), self.percent.value(), self.target.currentData())
            data = [{"name": p.name, "oc": oc, "nc": nc, "op": op, "np": np_} for p, oc, nc, op, np_ in rows]
        self.table.set_rows(data)
        self.summary.setText(f"سيتم تعديل {len(data)} منتج")

    def _apply(self) -> None:
        from ftapp.ui.widgets.common import confirm
        self._preview()
        if not self.table.rows():
            error(self, "لا توجد منتجات ضمن هذا النطاق")
            return
        if not confirm(self, f"تطبيق تعديل {self.percent.value():+g}% على {len(self.table.rows())} منتج؟"):
            return
        with ctx.session() as (s, u):
            n = catalog_service.bulk_price_apply(s, u, self._filter(), self.percent.value(), self.target.currentData())
        Toast.show_message(self.parent(), f"تم تحديث أسعار {n} منتج", "success")
        self.accept()


class ExportDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("تصدير جرد البضاعة إلى Excel")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(560, 600)
        lay = QVBoxLayout(self)
        t = QLabel("تصدير الجرد")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        lay.addWidget(muted("سيتم إنشاء مجلد «جرد_التاريخ» يحتوي ملف Excel منسق: ورقة ملخص + ورقة لكل قسم."))
        lay.addWidget(QLabel("الأعمدة"))
        self.cols = QListWidget()
        with ctx.session() as (s, _):
            choices = excel_service.export_column_choices(s)
        for key, title in choices:
            if key in ("cost_price", "cost_value", "margin") and not ctx.can("products.view_cost"):
                continue
            it = QListWidgetItem(title)
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if key in excel_service.DEFAULT_EXPORT_COLUMNS
                             or key.startswith("cf:") else Qt.CheckState.Unchecked)
            self.cols.addItem(it)
        lay.addWidget(self.cols, 1)
        self.per_cat = QCheckBox("ورقة منفصلة لكل قسم")
        self.per_cat.setChecked(True)
        self.inactive = QCheckBox("تضمين المنتجات الموقوفة")
        lay.addWidget(self.per_cat)
        lay.addWidget(self.inactive)
        frow = QHBoxLayout()
        self.folder = QLineEdit(str(Path.home() / "Documents"))
        frow.addWidget(QLabel("حفظ في"))
        frow.addWidget(self.folder, 1)
        frow.addWidget(button("تغيير", on_click=self._pick))
        lay.addLayout(frow)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("إلغاء", on_click=self.reject))
        self.go_btn = button("تصدير", "excel", "primary", on_click=self._go)
        row.addWidget(self.go_btn)
        lay.addLayout(row)

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "اختر مجلد الحفظ", self.folder.text())
        if d:
            self.folder.setText(d)

    def _go(self) -> None:
        keys = [self.cols.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.cols.count())
                if self.cols.item(i).checkState() == Qt.CheckState.Checked]
        folder, per_cat, inactive = self.folder.text(), self.per_cat.isChecked(), self.inactive.isChecked()
        self.go_btn.setEnabled(False)
        self.go_btn.setText("جارِ التصدير...")

        def work():
            from ftapp.core.db import session_scope
            with session_scope() as s:
                user = ctx.user(s)
                return excel_service.export_inventory(s, user, folder, keys, inactive, per_cat)

        def done(res) -> None:
            open_path(res.folder)
            Toast.show_message(self.parent(), f"تم تصدير {res.products} منتج إلى {res.excel.name}", "success")
            self.accept()

        def fail(msg: str) -> None:
            self.go_btn.setEnabled(True)
            self.go_btn.setText("تصدير")
            error(self, msg)
        run_async(work, done, fail)


class ImportDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("استيراد منتجات من Excel")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(940, 680)
        self.path: str | None = None
        lay = QVBoxLayout(self)
        t = QLabel("استيراد من Excel")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        top = QHBoxLayout()
        top.addWidget(button("اختيار ملف", "upload", "primary", on_click=self._pick))
        top.addWidget(button("تنزيل قالب جاهز", "download", on_click=self._template))
        self.file_label = muted("لم يتم اختيار ملف")
        top.addWidget(self.file_label, 1)
        lay.addLayout(top)
        lay.addWidget(QLabel("ربط الأعمدة: اختر ما يقابل كل عمود من الملف"))
        self.mapping = QTableWidget(0, 3)
        self.mapping.setHorizontalHeaderLabels(["عمود الملف", "مثال", "يقابل"])
        self.mapping.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.mapping.verticalHeader().setVisible(False)
        lay.addWidget(self.mapping, 1)
        opts = QHBoxLayout()
        self.update_existing = QCheckBox("تحديث المنتجات الموجودة (حسب الكود/الباركود)")
        self.update_existing.setChecked(True)
        self.create_cats = QCheckBox("إنشاء الأقسام غير الموجودة")
        self.create_cats.setChecked(True)
        opts.addWidget(self.update_existing)
        opts.addWidget(self.create_cats)
        opts.addStretch(1)
        lay.addLayout(opts)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(130)
        lay.addWidget(self.result)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("إغلاق", on_click=self.reject))
        row.addWidget(button("تجربة بدون حفظ", "search", on_click=lambda: self._run(True)))
        row.addWidget(button("استيراد", "check", "primary", on_click=lambda: self._run(False)))
        lay.addLayout(row)

    def _template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "حفظ القالب", "قالب_استيراد_المنتجات.xlsx", "Excel (*.xlsx)")
        if path:
            open_path(excel_service.import_template(path))

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "ملف Excel", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            prev = excel_service.read_preview(path)
        except Exception as exc:
            error(self, f"تعذر قراءة الملف: {exc}")
            return
        self.path = path
        self.file_label.setText(f"{Path(path).name} — {prev['total']} صف")
        with ctx.session() as (s, _):
            fields = [(f.id, f.name) for f in catalog_service.list_fields(s, all_fields=True)]
        auto = excel_service.auto_map(prev["headers"], fields)
        targets = [("— تجاهل —", None)] + [(v, k) for k, v in excel_service.IMPORT_TARGETS.items()] + \
                  [(f"خانة: {name}", f"cf:{fid}") for fid, name in fields]
        self.mapping.setRowCount(0)
        for i, h in enumerate(prev["headers"]):
            self.mapping.insertRow(i)
            self.mapping.setItem(i, 0, QTableWidgetItem(h))
            sample = next((str(r[i]) for r in prev["rows"] if i < len(r) and r[i] not in (None, "")), "")
            self.mapping.setItem(i, 1, QTableWidgetItem(sample[:60]))
            cb = QComboBox()
            fill_combo(cb, targets, auto.get(i))
            self.mapping.setCellWidget(i, 2, cb)

    def _run(self, dry: bool) -> None:
        if not self.path:
            error(self, "اختر ملفاً أولاً")
            return
        mapping = {}
        for i in range(self.mapping.rowCount()):
            key = self.mapping.cellWidget(i, 2).currentData()
            if key:
                if key in mapping.values():
                    error(self, f"الحقل «{self.mapping.cellWidget(i, 2).currentText()}» مربوط بأكثر من عمود")
                    return
                mapping[i] = key
        try:
            with ctx.session() as (s, u):
                res = excel_service.import_products(s, u, self.path, mapping, None, self.update_existing.isChecked(),
                                                    self.create_cats.isChecked(), dry_run=dry)
                if dry:
                    s.rollback()
        except Exception as exc:
            error(self, str(exc))
            return
        lines = [("نتيجة التجربة (لم يُحفظ شيء):" if dry else "تم الاستيراد:"),
                 f"منتجات جديدة: {res.created}", f"منتجات محدثة: {res.updated}", f"تم تجاهل: {res.skipped}"]
        if res.errors:
            lines.append(f"أخطاء ({len(res.errors)}):")
            lines += [f"  صف {r}: {m}" for r, m in res.errors[:50]]
        self.result.setPlainText("\n".join(lines))
        if not dry:
            Toast.show_message(self.parent(), f"تم استيراد {res.created} وتحديث {res.updated} منتج", "success")
