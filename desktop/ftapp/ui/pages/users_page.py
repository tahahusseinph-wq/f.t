"""المستخدمون والصلاحيات والأجهزة المتصلة."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QTabWidget, QVBoxLayout,
                               QWidget)

from ftapp.models import User
from ftapp.services import auth_service, permissions
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.auth_dialogs import StrengthBar, password_field
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Toast, button, confirm, muted, run_safely
from ftapp.ui.widgets.forms import FormDialog
from ftapp.ui.widgets.table import Column, DataTable


class UserDialog(FormDialog):
    def __init__(self, parent, user_id: int | None = None) -> None:
        super().__init__(parent, "تعديل مستخدم" if user_id else "مستخدم جديد", 620)
        self.user_id = user_id
        with ctx.session() as (s, _):
            u = s.get(User, user_id) if user_id else None
            self.overrides = dict(u.permissions or {}) if u else {}
        self.username = self.line("اسم المستخدم *", u.username if u else "")
        self.username.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.username.setEnabled(u is None)
        self.full_name = self.line("الاسم الكامل", u.full_name if u else "")
        self.phone = self.line("الهاتف", u.phone if u else "")
        self.role = self.combo("الدور", [(v, k) for k, v in permissions.ROLES.items()], u.role if u else "viewer")
        self.role.currentIndexChanged.connect(self._role_changed)
        self.password = password_field("اتركها فارغة لعدم التغيير" if u else "")
        self.strength = StrengthBar()
        self.password.textChanged.connect(self.strength.update_for)
        self.row("كلمة السر" + ("" if u else " *"), self.password)
        self.row("", self.strength)
        self.commission = QDoubleSpinBox()
        self.commission.setRange(0, 100)
        self.commission.setSuffix(" %")
        self.commission.setValue(u.commission_rate if u else 0)
        self.row("نسبة العمولة", self.commission)
        self.active = QCheckBox("الحساب فعّال")
        self.active.setChecked(u.is_active if u else True)
        self.row("", self.active)
        box = QGroupBox("الصلاحيات")
        grid = QGridLayout(box)
        self.perm_checks: dict[str, QCheckBox] = {}
        for i, (perm, label) in enumerate(permissions.PERMISSIONS.items()):
            cb = QCheckBox(label)
            if perm in permissions.OPT_IN:
                cb.setText(label + " ⚠")
                cb.setToolTip("صلاحية حساسة لا تُمنح تلقائياً حتى للأدمن")
            self.perm_checks[perm] = cb
            grid.addWidget(cb, i // 2, i % 2)
        self.root.insertWidget(self.root.count() - 1, box)
        self.root.insertWidget(self.root.count() - 1, muted("الصلاحيات تُضبط تلقائياً حسب الدور، ويمكنك تخصيصها لكل مستخدم."))
        self._role_changed(initial=True)
        self.on_save = self._do
        self.finish_layout()

    def _role_changed(self, *_args, initial: bool = False) -> None:
        role = self.role.currentData()
        defaults = permissions.ROLE_DEFAULTS.get(role, set())
        if not initial:
            self.overrides = {}
        for perm, cb in self.perm_checks.items():
            granted = self.overrides.get(perm, perm in defaults)
            cb.setChecked(bool(granted))
            cb.setEnabled(role != "admin" or perm in permissions.OPT_IN)

    def _collect(self) -> dict:
        defaults = permissions.ROLE_DEFAULTS.get(self.role.currentData(), set())
        return {perm: cb.isChecked() for perm, cb in self.perm_checks.items() if cb.isChecked() != (perm in defaults)}

    def _do(self):
        with ctx.session() as (s, actor):
            if self.user_id:
                u = auth_service.update_user(s, actor, self.user_id, full_name=self.full_name.text(),
                                             phone=self.phone.text(), role=self.role.currentData(),
                                             is_active=self.active.isChecked(), commission_rate=self.commission.value(),
                                             permissions=self._collect(), new_password=self.password.text() or None)
            else:
                u = auth_service.create_user(s, actor, self.username.text(), self.password.text(),
                                             self.role.currentData(), self.full_name.text(), self.phone.text(),
                                             self.commission.value(), self._collect(), self.active.isChecked())
            return u.id


class ChangePasswordDialog(FormDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent, "تغيير كلمة السر")
        self.old = password_field()
        self.new1 = password_field()
        self.new2 = password_field()
        self.row("كلمة السر الحالية", self.old)
        self.row("الجديدة", self.new1)
        self.row("تأكيد الجديدة", self.new2)
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        from ftapp.services.errors import ValidationError
        if self.new1.text() != self.new2.text():
            raise ValidationError("كلمتا السر غير متطابقتين")
        with ctx.session() as (s, u):
            auth_service.change_password(s, u, self.old.text(), self.new1.text())
        return True


class UsersPage(Page):
    title = "المستخدمون"
    subtitle = "الحسابات، الأدوار، الصلاحيات، والأجهزة"

    def __init__(self) -> None:
        super().__init__()
        self.actions.addWidget(button("تغيير كلمة سري", "key", on_click=lambda: ChangePasswordDialog(self).exec()))
        self.actions.addWidget(button("مستخدم جديد", "plus", "primary", on_click=lambda: self._edit(None)))
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        w = QWidget()
        lay = QVBoxLayout(w)
        t = tokens()
        self.users = DataTable([
            Column("اسم المستخدم", "username", bold=True), Column("الاسم", "name", stretch=True),
            Column("الدور", "role"), Column("العمولة", "commission", "percent"),
            Column("آخر دخول", "last", "datetime"),
            Column("الحالة", lambda r: "فعّال" if r["active"] else "موقوف",
                   color=lambda r: t["success"] if r["active"] else t["danger"]),
        ])
        self.users.activated_row.connect(lambda r: self._edit(r["id"]))
        self.users.add_menu_action("تعديل", lambda r: self._edit(r["id"]))
        self.users.add_menu_action("حذف", self._delete)
        lay.addWidget(self.users, 1)
        lay.addWidget(muted("المستخدمون يدخلون من تطبيق الموبايل بنفس اسم المستخدم وكلمة السر. "
                            "المستخدم «بحث فقط» يرى كود المنتج وسعره والخانات المسموحة فقط."))
        self.tabs.addTab(w, icons.icon("users"), "الحسابات")
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        bar = QHBoxLayout()
        bar.addWidget(button("فصل الجهاز المحدد", "x", "danger", on_click=self._revoke))
        bar.addStretch(1)
        l2.addLayout(bar)
        self.devices = DataTable([Column("المستخدم", "user", bold=True), Column("الجهاز", "device", stretch=True),
                                  Column("العنوان", "ip"), Column("تاريخ الدخول", "created", "datetime"),
                                  Column("آخر نشاط", "seen", "datetime")])
        l2.addWidget(self.devices, 1)
        self.tabs.addTab(w2, icons.icon("phone"), "الأجهزة المتصلة")
        ctx.signals.users_changed.connect(self.mark_dirty)
        ctx.signals.devices_changed.connect(self.mark_dirty)

    def refresh(self) -> None:
        with ctx.session() as (s, _):
            self.users.set_rows([{"id": u.id, "username": u.username, "name": u.full_name,
                                  "role": permissions.ROLES.get(u.role, u.role), "commission": u.commission_rate,
                                  "last": u.last_login, "active": u.is_active} for u in auth_service.list_users(s)])
            self.devices.set_rows([{"id": d.id, "user": d.user.display_name, "device": d.device_name, "ip": d.ip,
                                    "created": d.created_at, "seen": d.last_seen} for d in auth_service.list_devices(s)])

    def _edit(self, uid) -> None:
        if UserDialog(self, uid).exec():
            self.refresh_now()

    def _delete(self, row) -> None:
        if confirm(self, f"حذف المستخدم «{row['username']}»؟", danger=True):
            def do():
                with ctx.session() as (s, u):
                    auth_service.delete_user(s, u, row["id"])
            if run_safely(self, do, "تم حذف المستخدم"):
                self.refresh_now()

    def _revoke(self) -> None:
        r = self.devices.current_row()
        if r and confirm(self, f"فصل جهاز «{r['device']}»؟ سيحتاج المستخدم لتسجيل الدخول من جديد."):
            with ctx.session() as (s, u):
                auth_service.revoke_device(s, u, r["id"])
            Toast.show_message(self, "تم فصل الجهاز", "success")
            self.refresh_now()
