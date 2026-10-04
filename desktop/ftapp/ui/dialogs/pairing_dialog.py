"""ربط الموبايل: رمز QR، حالة السيرفر، والأجهزة المتصلة."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel

from ftapp.api.server import local_ips, pairing_payload, server as api_server
from ftapp.core.paths import logo_path
from ftapp.services import auth_service, barcode_service, settings_service
from ftapp.ui.context import ctx
from ftapp.ui.widgets.common import Card, button, confirm, muted
from ftapp.ui.widgets.table import Column, DataTable


class PairingDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ربط تطبيق الموبايل")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(860, 560)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)

        left = Card("امسح الرمز من تطبيق الموبايل", icon_name="qr")
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumSize(300, 300)
        left.add(self.qr)
        self.addr = QLabel()
        self.addr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.addr.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.addr.setStyleSheet("font-size: 12pt; font-weight: bold;")
        left.add(self.addr)
        left.add(muted("الموبايل والكمبيوتر يجب أن يكونا على نفس الراوتر (نفس شبكة الواي فاي). "
                       "إذا لم يعمل المسح، أدخل العنوان يدوياً في التطبيق."))
        self.toggle_btn = button("", on_click=self._toggle)
        left.add(self.toggle_btn)
        lay.addWidget(left, 1)

        right = Card("الأجهزة المتصلة", icon_name="phone")
        self.table = DataTable([
            Column("المستخدم", lambda d: d["user"], stretch=True),
            Column("الجهاز", lambda d: d["device"]),
            Column("العنوان", lambda d: d["ip"]),
            Column("آخر نشاط", lambda d: d["last_seen"], "datetime"),
        ])
        right.add(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(button("تحديث", "refresh", on_click=self._load_devices))
        row.addStretch(1)
        if ctx.can("users.manage"):
            row.addWidget(button("فصل الجهاز المحدد", "x", "danger", on_click=self._revoke))
        right.body.addLayout(row)
        lay.addWidget(right, 1)
        ctx.signals.devices_changed.connect(self._load_devices)
        self._render()
        self._load_devices()

    def _render(self) -> None:
        with ctx.session() as (s, _):
            cfg = settings_service.get(s, "server")
            sid = auth_service.server_id(s)
            company = settings_service.get(s, "company").get("name", "")
        port = api_server.port or cfg.get("port", 8765)
        if api_server.running:
            payload = pairing_payload(sid, company, port)
            pm = QPixmap()
            pm.loadFromData(barcode_service.qr_with_logo(payload, str(logo_path())))
            self.qr.setPixmap(pm.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
            self.addr.setText("  أو  ".join(f"{ip}:{port}" for ip in local_ips()))
            self.toggle_btn.setText("إيقاف السيرفر")
            self.toggle_btn.setProperty("variant", "danger")
        else:
            self.qr.setText(api_server.error or "السيرفر متوقف")
            self.addr.setText("")
            self.toggle_btn.setText("تشغيل السيرفر")
            self.toggle_btn.setProperty("variant", "primary")
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)
        self.toggle_btn.setEnabled(ctx.can("settings.manage"))

    def _toggle(self) -> None:
        with ctx.session() as (s, _):
            cfg = settings_service.get(s, "server")
            sid = auth_service.server_id(s)
            company = settings_service.get(s, "company").get("name", "")
            if api_server.running:
                api_server.stop()
                cfg["enabled"] = False
            else:
                api_server.start(int(cfg.get("port", 8765)), bool(cfg.get("lan_only", True)), sid, company)
                cfg["enabled"] = api_server.running
            settings_service.set(s, "server", cfg)
        self._render()

    def _load_devices(self) -> None:
        with ctx.session() as (s, _):
            rows = [{"id": d.id, "user": d.user.display_name, "device": d.device_name, "ip": d.ip,
                     "last_seen": d.last_seen} for d in auth_service.list_devices(s)]
        self.table.set_rows(rows)

    def _revoke(self) -> None:
        row = self.table.current_row()
        if row and confirm(self, f"فصل الجهاز «{row['device']}» للمستخدم {row['user']}؟", danger=True):
            with ctx.session() as (s, u):
                auth_service.revoke_device(s, u, row["id"])
            self._load_devices()
