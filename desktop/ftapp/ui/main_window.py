"""النافذة الرئيسية: الشريط الجانبي، الشريط العلوي، الصفحات، وخدمات الخلفية."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from ftapp import APP_NAME, APP_NAME_EN
from ftapp.api.server import local_ips, server as api_server
from ftapp.core.paths import assets_dir
from ftapp.services import notification_service, settings_service
from ftapp.ui import icons, theme
from ftapp.ui.context import ctx
from ftapp.ui.i18n import direction, tr
from ftapp.ui.widgets.common import Toast, button, icon_button, logo_label

log = logging.getLogger(__name__)


class PageSpec:
    def __init__(self, key: str, title: str, icon_name: str, factory: Callable[[], QWidget], perm: str | None,
                 section: str) -> None:
        self.key, self.title, self.icon, self.factory, self.perm, self.section = key, title, icon_name, factory, perm, section


def page_specs() -> list[PageSpec]:
    from ftapp.ui.pages import (ai_page, categories_page, customers_page, dashboard_page, finance_page, inventory_page,
                                invoices_page, notifications_page, pos_page, products_page, purchases_page,
                                reports_page, settings_page, users_page)
    return [
        PageSpec("dashboard", "لوحة التحكم", "home", dashboard_page.DashboardPage, "dashboard.view", "الرئيسية"),
        PageSpec("notifications", "الإشعارات", "bell", notifications_page.NotificationsPage, None, "الرئيسية"),
        PageSpec("ai", "المساعد الذكي", "sparkles", ai_page.AIPage, "ai.use", "الرئيسية"),
        PageSpec("pos", "نقطة البيع", "cart", pos_page.POSPage, "sales.create", "المبيعات"),
        PageSpec("invoices", "الفواتير", "receipt", invoices_page.InvoicesPage, "sales.create", "المبيعات"),
        PageSpec("customers", "الزبائن", "users", customers_page.CustomersPage, "customers.manage", "المبيعات"),
        PageSpec("products", "المنتجات", "box", products_page.ProductsPage, "products.view", "المخزون والمشتريات"),
        PageSpec("categories", "الأقسام والخانات", "layers", categories_page.CategoriesPage, "categories.manage", "المخزون والمشتريات"),
        PageSpec("inventory", "المخزون", "warehouse", inventory_page.InventoryPage, "inventory.view", "المخزون والمشتريات"),
        PageSpec("purchases", "المشتريات", "truck", purchases_page.PurchasesPage, "purchases.manage", "المخزون والمشتريات"),
        PageSpec("finance", "المالية والورديات", "wallet", finance_page.FinancePage, "shifts.manage", "المالية والتقارير"),
        PageSpec("reports", "التقارير", "bar", reports_page.ReportsPage, "reports.view", "المالية والتقارير"),
        PageSpec("users", "المستخدمون", "user", users_page.UsersPage, "users.manage", "النظام"),
        PageSpec("settings", "الإعدادات", "settings", settings_page.SettingsPage, "settings.manage", "النظام"),
    ]


class IdleWatcher(QObject):
    """يقفل الشاشة بعد مدة خمول محددة."""

    def __init__(self, minutes: int, on_idle: Callable[[], None]) -> None:
        super().__init__()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(on_idle)
        self.set_minutes(minutes)

    def set_minutes(self, minutes: int) -> None:
        self.minutes = minutes
        if minutes > 0:
            self.timer.start(minutes * 60_000)
        else:
            self.timer.stop()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if self.minutes > 0 and event.type() in (QEvent.Type.MouseMove, QEvent.Type.KeyPress,
                                                  QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
            self.timer.start(self.minutes * 60_000)
        return False


class CommandPalette(QDialog):
    """بحث شامل: الانتقال للصفحات أو فتح منتج/فاتورة/زبون."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window_ = window
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setLayoutDirection(direction())
        self.setMinimumSize(620, 440)
        self.setStyleSheet(f"QDialog {{ background: {theme.tokens()['surface']}; border: 1px solid "
                           f"{theme.tokens()['border']}; border-radius: 14px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setPlaceholderText("ابحث عن صفحة، منتج بالاسم أو الكود، فاتورة، أو زبون...")
        self.search.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setMinimumHeight(42)
        self.list = QListWidget()
        self.list.setIconSize(QSize(18, 18))
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        hint = QLabel("Enter للفتح • Esc للإغلاق • ↑↓ للتنقل")
        hint.setObjectName("hint")
        lay.addWidget(hint)
        self.search.textChanged.connect(self._update)
        self.search.returnPressed.connect(self._activate)
        self.list.itemActivated.connect(lambda *_: self._activate())
        self.search.installEventFilter(self)
        self._update("")

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if event.key() == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
        return False

    def _add(self, text: str, icon_name: str, action: tuple) -> None:
        item = QListWidgetItem(icons.icon(icon_name), text)
        item.setData(Qt.ItemDataRole.UserRole, action)
        self.list.addItem(item)

    def _update(self, text: str) -> None:
        from ftapp.core.db import session_scope
        from ftapp.services import catalog_service, sales_service

        self.list.clear()
        q = text.strip()
        for spec in self.window_.visible_specs:
            if not q or q in spec.title:
                self._add(f"الانتقال إلى: {spec.title}", spec.icon, ("page", spec.key, None))
        if len(q) >= 2:
            with session_scope() as s:
                if ctx.can("products.view"):
                    items, _ = catalog_service.search_products(s, q, limit=8)
                    for p in items:
                        self._add(f"منتج: {p.name} — {p.code}", "box", ("page", "products", {"product_id": p.id}))
                if ctx.can("sales.create"):
                    for inv in sales_service.list_invoices(s, None, search=q, limit=5):
                        self._add(f"فاتورة: {inv.number} — {inv.customer_name or 'زبون نقدي'}", "receipt",
                                  ("page", "invoices", {"invoice_id": inv.id}))
                if ctx.can("customers.manage"):
                    for c in sales_service.list_customers(s, q)[:5]:
                        self._add(f"زبون: {c.name} {c.phone}", "users", ("page", "customers", {"customer_id": c.id}))
        if self.list.count():
            self.list.setCurrentRow(0)

    def _activate(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        kind, key, payload = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        self.window_.navigate(key, payload)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {ctx.display_name}")
        self.setWindowIcon(QIcon(str(assets_dir() / "icon.png")))
        self.setLayoutDirection(direction())
        screen = QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(min(900, screen.width()), min(540, screen.height()))
        self.resize(min(1400, screen.width()), min(860, screen.height()))
        if screen.width() < 1500 or screen.height() < 820:
            self.setWindowState(Qt.WindowState.WindowMaximized)
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.visible_specs = [s for s in page_specs() if s.perm is None or ctx.can(s.perm)]
        self.locked = False
        self.logout_requested = False

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_topbar())
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        rw = QWidget()
        rw.setLayout(right)
        outer.addWidget(rw, 1)
        self.setCentralWidget(central)

        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_palette)
        QShortcut(QKeySequence("F2"), self, activated=lambda: self.navigate("pos"))
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._new_product)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.lock)

        ctx.signals.navigate.connect(self.navigate)
        ctx.signals.notifications_changed.connect(self._update_bell)
        ctx.signals.notification_popup.connect(self._popup)
        ctx.signals.settings_changed.connect(self._update_server_status)

        with ctx.session() as (s, _):
            ui_cfg = settings_service.get(s, "ui")
        self.idle = IdleWatcher(int(ui_cfg.get("idle_lock_minutes") or 0), self.lock)
        QApplication.instance().installEventFilter(self.idle)

        self._bell_timer = QTimer(self)
        self._bell_timer.timeout.connect(self._update_bell)
        self._bell_timer.start(60_000)
        self._update_bell()
        self._update_server_status()
        keys = [s.key for s in self.visible_specs]
        start = next((k for k in ("dashboard", "pos") if k in keys), keys[0] if keys else None)
        if start:
            self.navigate(start)

    # ---------------- البناء ----------------
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(200 if theme.compact() else 238)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setSpacing(2)
        brand = QHBoxLayout()
        brand.addWidget(logo_label(46))
        names = QVBoxLayout()
        names.setSpacing(0)
        n1 = QLabel("فاروق الطعمة")
        n1.setObjectName("brandName")
        n2 = QLabel(APP_NAME_EN)
        n2.setObjectName("brandSub")
        names.addWidget(n1)
        names.addWidget(n2)
        brand.addLayout(names, 1)
        lay.addLayout(brand)
        lay.addSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        nav = QVBoxLayout(inner)
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(3)
        group = QButtonGroup(self)
        group.setExclusive(True)
        section = None
        for spec in self.visible_specs:
            if spec.section != section:
                section = spec.section
                lbl = QLabel(tr(section))
                lbl.setObjectName("navSection" if nav.count() else "navSectionFirst")
                nav.addWidget(lbl)
            btn = QPushButton(f"  {tr(spec.title)}")
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setIcon(icons.icon(spec.icon, "#C9D4E0"))
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=spec.key: self.navigate(k))
            group.addButton(btn)
            nav.addWidget(btn)
            self.nav_buttons[spec.key] = btn
        nav.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        user_box = QFrame()
        user_box.setStyleSheet("background: #121A23; border-radius: 12px;")
        ub = QHBoxLayout(user_box)
        ub.setContentsMargins(10, 8, 6, 8)
        avatar = QLabel(ctx.display_name[:1] or "؟")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet("background: #1565C0; color: white; border-radius: 17px; font-weight: bold;")
        ub.addWidget(avatar)
        info = QVBoxLayout()
        info.setSpacing(0)
        nm = QLabel(ctx.display_name)
        nm.setStyleSheet("color: white; font-weight: bold;")
        from ftapp.services.permissions import ROLES
        rl = QLabel(ROLES.get(ctx.role, ctx.role))
        rl.setStyleSheet("color: #7F93A8; font-size: 8pt;")
        info.addWidget(nm)
        info.addWidget(rl)
        ub.addLayout(info, 1)
        ub.addWidget(icon_button("lock", tr("قفل الشاشة"), self.lock, "#9FB3C8"))
        ub.addWidget(icon_button("logout", tr("تسجيل الخروج"), self.logout, "#9FB3C8"))
        lay.addWidget(user_box)
        return side

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(60)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 8, 20, 8)
        self.crumb = QLabel("")
        self.crumb.setObjectName("crumb")
        lay.addWidget(self.crumb)
        lay.addSpacing(16)
        search = QPushButton(f"  {tr('بحث شامل... (Ctrl+K)')}")
        search.setIcon(icons.icon("search"))
        search.setMinimumWidth(200 if theme.compact() else 360)
        search.setStyleSheet(f"text-align: right; border-radius: 18px; background: {theme.tokens()['surface2']};"
                             f"border: 1px solid transparent; color: {theme.tokens()['muted']}; padding: 8px 14px;")
        search.setCursor(Qt.CursorShape.PointingHandCursor)
        search.clicked.connect(self.open_palette)
        lay.addWidget(search)
        lay.addStretch(1)
        self.server_btn = QPushButton()
        self.server_btn.setProperty("variant", "ghost")
        self.server_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.server_btn.clicked.connect(self.show_pairing)
        lay.addWidget(self.server_btn)
        if ctx.can("sales.create"):
            lay.addWidget(button("بيع جديد", "cart", "primary", on_click=lambda: self.navigate("pos"),
                                 tooltip="F2"))
        theme_btn = icon_button("moon" if theme.mode() == "light" else "sun", "تبديل الوضع الليلي", self.toggle_theme)
        lay.addWidget(theme_btn)
        bell_box = QWidget()
        bl = QHBoxLayout(bell_box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(icon_button("bell", tr("الإشعارات"), lambda: self.navigate("notifications")))
        self.bell_count = QLabel("")
        self.bell_count.setObjectName("bellCount")
        bl.addWidget(self.bell_count)
        lay.addWidget(bell_box)
        return bar

    # ---------------- التنقل ----------------
    def navigate(self, key: str, payload=None) -> None:
        spec = next((s for s in self.visible_specs if s.key == key), None)
        if spec is None:
            return
        page = self.pages.get(key)
        if page is None:
            try:
                page = spec.factory()
            except Exception as exc:
                log.exception("failed to open page %s", key)
                Toast.show_message(self, f"تعذر فتح الصفحة: {exc}", "danger")
                return
            self.pages[key] = page
            # تمرير الصفحة داخل منطقة تمرير: إن صغرت الشاشة تظهر أشرطة تمرير بدل أن تختفي العناصر
            wrapper = QScrollArea()
            wrapper.setWidgetResizable(True)
            wrapper.setFrameShape(QFrame.Shape.NoFrame)
            wrapper.setWidget(page)
            page._wrapper = wrapper
            self.stack.addWidget(wrapper)
        self.stack.setCurrentWidget(getattr(page, "_wrapper", page))
        if key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)
        self.crumb.setText(f"{tr(spec.section)}  ›  {tr(spec.title)}")
        if payload is not None and hasattr(page, "open_item"):
            QTimer.singleShot(0, lambda: page.open_item(payload))

    def open_palette(self) -> None:
        CommandPalette(self).exec()

    def _new_product(self) -> None:
        if ctx.can("products.edit"):
            self.navigate("products", {"new": True})

    # ---------------- الحالة ----------------
    def _update_bell(self) -> None:
        try:
            with ctx.session() as (s, _):
                n = notification_service.unread_count(s)
        except Exception:
            return
        self.bell_count.setText(str(n) if n else "")
        self.bell_count.setVisible(bool(n))

    def _popup(self, severity: str, title: str, body: str) -> None:
        kind = {"danger": "danger", "warning": "warning"}.get(severity, "info")
        Toast.show_message(self, f"{title}\n{body}".strip(), kind, 5000)

    def _update_server_status(self) -> None:
        t = theme.tokens()
        if api_server.running:
            self.server_btn.setText(f"  {tr('السيرفر يعمل')} • {local_ips()[0]}:{api_server.port}")
            self.server_btn.setIcon(icons.icon("wifi", t["success"]))
            self.server_btn.setToolTip("اضغط لعرض رمز QR لربط الموبايل")
        else:
            self.server_btn.setText(f"  {tr('السيرفر متوقف')}")
            self.server_btn.setIcon(icons.icon("wifi", t["danger"]))
            self.server_btn.setToolTip(api_server.error or "سيرفر الموبايل غير مفعّل")

    def show_pairing(self) -> None:
        from ftapp.ui.dialogs.pairing_dialog import PairingDialog

        PairingDialog(self).exec()
        self._update_server_status()

    def toggle_theme(self) -> None:
        new = "dark" if theme.mode() == "light" else "light"
        with ctx.session() as (s, _):
            settings_service.update(s, "ui", theme=new)
        theme.apply(QApplication.instance(), new)
        Toast.show_message(self, "تم تغيير المظهر. بعض العناصر تتحدث بالكامل بعد إعادة الدخول.", "info")

    # ---------------- الجلسة ----------------
    def lock(self) -> None:
        if self.locked:
            return
        from ftapp.ui.dialogs.auth_dialogs import LoginDialog

        self.locked = True
        self.hide()
        dlg = LoginDialog(locked_username=ctx.username)
        ok = dlg.exec() == QDialog.DialogCode.Accepted and dlg.user_id == ctx.user_id
        self.locked = False
        if ok:
            self.show()
            self.idle.set_minutes(self.idle.minutes)
        else:
            self.logout()

    def logout(self) -> None:
        self.logout_requested = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        QApplication.instance().removeEventFilter(self.idle)
        super().closeEvent(event)
