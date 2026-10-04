"""الأقسام، الخانات المخصصة، ما يراه المستخدمون، شرائح الأسعار، والعروض."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)
from sqlalchemy import func, select

from ftapp.models import Product
from ftapp.services import catalog_service, settings_service
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.catalog_dialogs import CategoryDialog, FieldDialog, PromotionDialog, TierDialog
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Card, Toast, button, confirm, muted, run_safely
from ftapp.ui.widgets.table import Column, DataTable


class CategoriesPage(Page):
    title = "الأقسام والخانات"
    subtitle = "نظّم البضاعة وحدد ما يظهر للمستخدمين"

    def __init__(self) -> None:
        super().__init__()
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self._build_categories()
        self._build_fields()
        self._build_visibility()
        self._build_tiers()
        self._build_promos()
        ctx.signals.products_changed.connect(self.mark_dirty)

    # ---------------- الأقسام ----------------
    def _build_categories(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(button("قسم رئيسي جديد", "plus", "primary", on_click=lambda: self._cat_dialog(None, None)))
        bar.addWidget(button("قسم فرعي", "plus", on_click=self._add_sub))
        bar.addWidget(button("تعديل", "edit", on_click=self._edit_cat))
        bar.addWidget(button("حذف", "trash", on_click=self._delete_cat))
        bar.addStretch(1)
        lay.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["القسم", "الرمز", "نسبة الربح", "عدد المنتجات"])
        self.tree.setColumnWidth(0, 320)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit_cat())
        lay.addWidget(self.tree, 1)
        lay.addWidget(muted("نسبة ربح القسم تُطبق تلقائياً على منتجاته التي ليس لها نسبة خاصة. الأقسام الفرعية ترث نسبة القسم الأب."))
        self.tabs.addTab(w, icons.icon("layers"), "الأقسام")

    def _cat_dialog(self, cat_id, parent_id) -> None:
        if CategoryDialog(self, cat_id, parent_id).exec():
            self.refresh_now()

    def _current_cat(self) -> int | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def _add_sub(self) -> None:
        cid = self._current_cat()
        if cid is None:
            Toast.show_message(self, "حدد القسم الأب أولاً", "warning")
            return
        self._cat_dialog(None, cid)

    def _edit_cat(self) -> None:
        cid = self._current_cat()
        if cid:
            self._cat_dialog(cid, None)

    def _delete_cat(self) -> None:
        cid = self._current_cat()
        if not cid or not confirm(self, "حذف القسم المحدد؟", danger=True):
            return

        def do():
            with ctx.session() as (s, u):
                catalog_service.delete_category(s, u, cid)
        if run_safely(self, do, "تم حذف القسم"):
            self.refresh_now()

    # ---------------- الخانات ----------------
    def _build_fields(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(button("إضافة خانة", "plus", "primary", on_click=lambda: self._field_dialog(None)))
        bar.addWidget(button("تعديل", "edit", on_click=lambda: self._field_dialog(self._cur_field())))
        bar.addWidget(button("حذف", "trash", on_click=self._delete_field))
        bar.addWidget(button("تحريك لأعلى", "upload", on_click=lambda: self._move_field(-1)))
        bar.addWidget(button("تحريك لأسفل", "download", on_click=lambda: self._move_field(1)))
        bar.addStretch(1)
        lay.addLayout(bar)
        t = tokens()
        self.fields = DataTable([
            Column("اسم الخانة", "name", stretch=True, bold=True), Column("النوع", "type"),
            Column("تظهر في", "scope"), Column("إجبارية", "required", "bool"),
            Column("مرئية للمستخدمين", lambda r: "✓ نعم" if r["visible"] else "🔒 مخفية",
                   color=lambda r: t["success"] if r["visible"] else t["muted"]),
            Column("مستخدمة في", lambda r: f"{r['used']} منتج"),
        ])
        self.fields.activated_row.connect(lambda r: self._field_dialog(r["id"]))
        self.fields.add_menu_action("تبديل الظهور للمستخدمين", self._toggle_visible)
        lay.addWidget(self.fields, 1)
        lay.addWidget(muted("الخانات المخفية 🔒 تظهر فقط للأدمن والمدير، ولا تُرسل إطلاقاً لتطبيق موبايل المستخدمين."))
        self.tabs.addTab(w, icons.icon("list"), "الخانات المخصصة")

    def _cur_field(self) -> int | None:
        r = self.fields.current_row()
        return r["id"] if r else None

    def _field_dialog(self, fid) -> None:
        if FieldDialog(self, fid).exec():
            self.refresh_now()

    def _delete_field(self) -> None:
        r = self.fields.current_row()
        if r and confirm(self, f"حذف الخانة «{r['name']}» وكل قيمها من المنتجات ({r['used']})؟", danger=True):
            with ctx.session() as (s, u):
                catalog_service.delete_field(s, u, r["id"])
            self.refresh_now()

    def _toggle_visible(self, r) -> None:
        from ftapp.models import CustomField
        with ctx.session() as (s, _):
            f = s.get(CustomField, r["id"])
            f.visible_to_users = not f.visible_to_users
        self.refresh_now()

    def _move_field(self, delta: int) -> None:
        r = self.fields.current_row()
        if not r:
            return
        ids = [x["id"] for x in self.fields.rows()]
        i = ids.index(r["id"])
        j = max(0, min(len(ids) - 1, i + delta))
        ids[i], ids[j] = ids[j], ids[i]
        with ctx.session() as (s, _):
            catalog_service.reorder_fields(s, ids)
        self.refresh_now()
        self.fields.selectRow(j)

    # ---------------- ما يراه المستخدمون ----------------
    def _build_visibility(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        card = Card("الحقول الأساسية التي يراها المستخدم في الموبايل", icon_name="phone")
        card.add(muted("المستخدم العادي يبحث عن كود المنتج ويرى فقط الحقول المحددة هنا. "
                       "الأدمن والمدير يرون كل شيء دائماً."))
        grid = QGridLayout()
        self.vis_checks: dict[str, QCheckBox] = {}
        for i, (key, label) in enumerate(settings_service.BUILTIN_FIELDS.items()):
            cb = QCheckBox(label)
            if key in ("name", "code"):
                cb.setEnabled(False)
            self.vis_checks[key] = cb
            grid.addWidget(cb, i // 3, i % 3)
        card.body.addLayout(grid)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("حفظ", "check", "primary", on_click=self._save_vis))
        card.body.addLayout(row)
        lay.addWidget(card)
        lay.addStretch(1)
        self.tabs.addTab(w, icons.icon("lock"), "ما يراه المستخدمون")

    def _save_vis(self) -> None:
        vis = {k: cb.isChecked() for k, cb in self.vis_checks.items()}
        vis["name"] = vis["code"] = True
        with ctx.session() as (s, _):
            settings_service.set(s, "builtin_visibility", vis)
        Toast.show_message(self, "تم حفظ إعدادات الظهور", "success")

    # ---------------- الشرائح ----------------
    def _build_tiers(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(button("شريحة جديدة", "plus", "primary", on_click=lambda: self._tier(None)))
        bar.addWidget(button("تعديل", "edit", on_click=lambda: self._tier((self.tiers.current_row() or {}).get("id"))))
        bar.addWidget(button("حذف", "trash", on_click=self._del_tier))
        bar.addStretch(1)
        lay.addLayout(bar)
        self.tiers = DataTable([Column("الشريحة", "name", stretch=True, bold=True),
                                Column("نسبة الربح الافتراضية", "margin", "percent"),
                                Column("افتراضية", "default", "bool")])
        self.tiers.activated_row.connect(lambda r: self._tier(r["id"]))
        lay.addWidget(self.tiers, 1)
        lay.addWidget(muted("كل زبون يمكن ربطه بشريحة (مفرّق/جملة...) فيُحسب له السعر تلقائياً في نقطة البيع."))
        self.tabs.addTab(w, icons.icon("tag"), "شرائح الأسعار")

    def _tier(self, tid) -> None:
        if tid is False:
            return
        if TierDialog(self, tid).exec():
            self.refresh_now()

    def _del_tier(self) -> None:
        r = self.tiers.current_row()
        if r and confirm(self, f"حذف الشريحة «{r['name']}»؟", danger=True):
            def do():
                with ctx.session() as (s, _):
                    catalog_service.delete_tier(s, r["id"])
            run_safely(self, do)
            self.refresh_now()

    # ---------------- العروض ----------------
    def _build_promos(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(button("عرض جديد", "plus", "primary", on_click=lambda: self._promo(None)))
        bar.addWidget(button("تعديل", "edit", on_click=lambda: self._promo((self.promos.current_row() or {}).get("id"))))
        bar.addWidget(button("حذف", "trash", on_click=self._del_promo))
        bar.addStretch(1)
        lay.addLayout(bar)
        t = tokens()
        self.promos = DataTable([
            Column("العرض", "name", stretch=True, bold=True), Column("على", "target"),
            Column("الخصم", "percent", "percent"), Column("من", "start", "date"), Column("إلى", "end", "date"),
            Column("الحالة", "state", color=lambda r: t["success"] if r["state"] == "ساري" else t["muted"]),
        ])
        self.promos.activated_row.connect(lambda r: self._promo(r["id"]))
        lay.addWidget(self.promos, 1)
        self.tabs.addTab(w, icons.icon("percent"), "العروض والخصومات")

    def _promo(self, pid) -> None:
        if PromotionDialog(self, pid).exec():
            self.refresh_now()

    def _del_promo(self) -> None:
        r = self.promos.current_row()
        if r and confirm(self, f"حذف العرض «{r['name']}»؟", danger=True):
            with ctx.session() as (s, _):
                catalog_service.delete_promotion(s, r["id"])
            self.refresh_now()

    # ---------------- التحميل ----------------
    def refresh(self) -> None:
        with ctx.session() as (s, _):
            counts = dict(s.execute(select(Product.category_id, func.count(Product.id)).group_by(Product.category_id)).all())
            self.tree.clear()
            nodes = {}
            for c, _d in catalog_service.category_tree(s):
                it = QTreeWidgetItem([c.name, c.code, f"{c.default_margin:g}%" if c.default_margin is not None else "—",
                                      str(counts.get(c.id, 0))])
                it.setIcon(0, icons.icon("layers", c.color))
                it.setData(0, Qt.ItemDataRole.UserRole, c.id)
                parent = nodes.get(c.parent_id)
                (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
                nodes[c.id] = it
            self.tree.expandAll()

            from ftapp.models import ProductFieldValue
            used = dict(s.execute(select(ProductFieldValue.field_id, func.count(ProductFieldValue.id))
                                  .where(ProductFieldValue.value != "").group_by(ProductFieldValue.field_id)).all())
            self.fields.set_rows([{"id": f.id, "name": f.name, "type": catalog_service.FIELD_TYPES[f.field_type],
                                   "scope": f.category.name if f.category else "كل المنتجات", "required": f.required,
                                   "visible": f.visible_to_users, "used": used.get(f.id, 0)}
                                  for f in catalog_service.list_fields(s, all_fields=True)])
            vis = settings_service.builtin_visibility(s)
            for k, cb in self.vis_checks.items():
                cb.setChecked(bool(vis.get(k)))
            self.tiers.set_rows([{"id": t.id, "name": t.name, "margin": t.default_margin, "default": t.is_default}
                                 for t in catalog_service.list_tiers(s)])
            today = date.today()
            self.promos.set_rows([{
                "id": p.id, "name": p.name, "percent": p.percent, "start": p.start_date, "end": p.end_date,
                "target": (p.product.name if p.product else (f"قسم {p.category.name}" if p.category else "")),
                "state": ("ساري" if p.is_active and p.start_date <= today <= p.end_date else
                          ("منتهي" if p.end_date < today else ("قادم" if p.is_active else "معطل")))}
                for p in catalog_service.list_promotions(s)])
