"""مركز الإشعارات."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox

from ftapp.services import notification_service
from ftapp.ui.context import ctx
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import button
from ftapp.ui.widgets.table import Column, DataTable


class NotificationsPage(Page):
    title = "الإشعارات"
    subtitle = "تنبيهات المخزون والصلاحية والديون والفواتير الكبيرة"

    def __init__(self) -> None:
        super().__init__()
        self.unread = QCheckBox("غير المقروءة فقط")
        self.unread.toggled.connect(self.refresh_now)
        self.actions.addWidget(self.unread)
        self.actions.addWidget(button("فحص الآن", "refresh", on_click=self._scan))
        self.actions.addWidget(button("تحديد الكل كمقروء", "check", on_click=self._read_all))
        self.actions.addWidget(button("مسح المقروءة", "trash", on_click=self._clear))
        t = tokens()
        sev_color = lambda r: {"danger": t["danger"], "warning": t["warning"]}.get(r["severity"], t["primary"])  # noqa: E731
        self.table = DataTable([
            Column("", lambda r: "●" if not r["read"] else "", width=30, color=sev_color),
            Column("النوع", "kind", color=sev_color, bold=True), Column("العنوان", "title", stretch=True),
            Column("التفاصيل", "body", stretch=True), Column("الوقت", "time", "datetime"),
        ])
        self.table.activated_row.connect(self._open)
        self.root.addWidget(self.table, 1)
        ctx.signals.notifications_changed.connect(self.mark_dirty)

    def refresh(self) -> None:
        with ctx.session() as (s, _):
            self.table.set_rows([{"id": n.id, "kind": notification_service.KIND_LABELS.get(n.kind, n.kind),
                                  "severity": n.severity, "title": n.title, "body": n.body, "time": n.created_at,
                                  "read": n.is_read, "entity": n.entity, "entity_id": n.entity_id}
                                 for n in notification_service.list_notifications(s, self.unread.isChecked())])

    def _open(self, row) -> None:
        with ctx.session() as (s, _):
            notification_service.mark_read(s, row["id"])
        if row["entity"] == "product" and row["entity_id"]:
            ctx.signals.navigate.emit("products", {"product_id": row["entity_id"]})
        elif row["entity"] == "customer" and row["entity_id"]:
            ctx.signals.navigate.emit("customers", {"customer_id": row["entity_id"]})
        elif row["entity"] == "invoice" and row["entity_id"]:
            ctx.signals.navigate.emit("invoices", {"invoice_id": row["entity_id"]})

    def _scan(self) -> None:
        with ctx.session() as (s, _):
            notification_service.scan_all(s)
        self.refresh_now()

    def _read_all(self) -> None:
        with ctx.session() as (s, _):
            notification_service.mark_read(s)

    def _clear(self) -> None:
        with ctx.session() as (s, _):
            notification_service.clear_read(s)
