"""الإعدادات: المنشأة، عام، الطباعة، الواجهة، السيرفر، الذكاء الاصطناعي، النسخ الاحتياطي، التحديثات."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QScrollArea, QVBoxLayout, QWidget)

from ftapp import VERSION
from ftapp.core.paths import data_dir, sub_dir
from ftapp.services import (audit, auth_service, backup_service, gemini_service, secrets_service, settings_service,
                            update_service)
from ftapp.ui import icons, theme
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.auth_dialogs import password_field
from ftapp.ui.pages.base import Page
from ftapp.ui.widgets.common import Card, Toast, button, confirm, error, info, logo_label, muted
from ftapp.ui.widgets.forms import int_spin, money_spin
from ftapp.ui.widgets.worker import run_async


def _form(card: Card) -> QFormLayout:
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    f.setHorizontalSpacing(16)
    f.setVerticalSpacing(10)
    card.body.addLayout(f)
    return f


def _hrow(*widgets) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        if x == "stretch":
            lay.addStretch(1)
        else:
            lay.addWidget(x)
    return w


class SettingsPage(Page):
    title = "الإعدادات"
    subtitle = "خصّص المنظومة حسب عملك"

    def __init__(self) -> None:
        super().__init__()
        self.actions.addWidget(button("حفظ الإعدادات", "check", "primary", on_click=self._save))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.col = QVBoxLayout(body)
        self.col.setSpacing(14)
        self.col.setContentsMargins(0, 0, 8, 0)
        self._company()
        self._general()
        self._printing_ui()
        self._server()
        self._ai()
        self._backup()
        self._updates_security()
        self.col.addStretch(1)
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)

    # ---------------- البناء ----------------
    def _company(self) -> None:
        card = Card("بيانات المنشأة (تظهر على الفواتير)", icon_name="home")
        f = _form(card)
        self.c_name = QLineEdit()
        self.c_name_en = QLineEdit()
        self.c_address = QLineEdit()
        self.c_phone = QLineEdit()
        self.c_email = QLineEdit()
        self.c_tax = QLineEdit()
        self.c_footer = QLineEdit()
        self.logo = logo_label(56)
        f.addRow("الاسم", self.c_name)
        f.addRow("الاسم بالإنكليزية", self.c_name_en)
        f.addRow("العنوان", self.c_address)
        f.addRow("الهاتف", self.c_phone)
        f.addRow("البريد", self.c_email)
        f.addRow("الرقم الضريبي", self.c_tax)
        f.addRow("عبارة أسفل الفاتورة", self.c_footer)
        f.addRow("الشعار", _hrow(self.logo, button("تغيير", "image", on_click=self._logo),
                                 button("الشعار الأصلي", on_click=self._logo_reset), "stretch"))
        self.col.addWidget(card)

    def _general(self) -> None:
        card = Card("المخزون والمبيعات", icon_name="box")
        f = _form(card)
        self.g_min = QDoubleSpinBox()
        self.g_min.setRange(0, 1e6)
        self.g_slow = int_spin(1, 3650)
        self.g_expiry = int_spin(1, 3650)
        self.g_large = money_spin()
        self.g_tax = QDoubleSpinBox()
        self.g_tax.setRange(0, 100)
        self.g_tax.setSuffix(" %")
        self.g_negative = QCheckBox("السماح بالبيع حتى لو الكمية غير كافية (غير منصوح)")
        self.g_sep = QComboBox()
        for s_ in ("-", "_", ".", ""):
            self.g_sep.addItem(s_ or "بدون", s_)
        self.g_digits = int_spin(2, 8)
        f.addRow("حد التنبيه الافتراضي", self.g_min)
        f.addRow("البضاعة راكدة بعد (يوم)", self.g_slow)
        f.addRow("تنبيه الصلاحية قبل (يوم)", self.g_expiry)
        f.addRow("تنبيه الفاتورة الكبيرة من", self.g_large)
        f.addRow("نسبة الضريبة", self.g_tax)
        f.addRow("", self.g_negative)
        f.addRow("فاصل أجزاء الكود", self.g_sep)
        f.addRow("خانات الرقم التسلسلي", self.g_digits)
        self.col.addWidget(card)

    def _printing_ui(self) -> None:
        card = Card("الطباعة والواجهة", icon_name="print")
        f = _form(card)
        self.p_paper = QComboBox()
        for k, v in (("A4", "A4"), ("A5", "A5"), ("80mm", "إيصال حراري 80mm"), ("58mm", "إيصال حراري 58mm")):
            self.p_paper.addItem(v, k)
        self.p_logo = QCheckBox("إظهار الشعار على الفاتورة")
        self.u_lang = QComboBox()
        self.u_lang.addItem("العربية", "ar")
        self.u_lang.addItem("English", "en")
        self.u_theme = QComboBox()
        self.u_theme.addItem("فاتح", "light")
        self.u_theme.addItem("داكن", "dark")
        self.u_idle = int_spin(0, 600)
        self.u_idle.setSuffix(" دقيقة")
        self.u_idle.setSpecialValueText("بدون قفل")
        f.addRow("ورق الفاتورة الافتراضي", self.p_paper)
        f.addRow("", self.p_logo)
        f.addRow("اللغة", self.u_lang)
        f.addRow("المظهر", self.u_theme)
        f.addRow("قفل الشاشة بعد خمول", self.u_idle)
        self.col.addWidget(card)

    def _server(self) -> None:
        card = Card("سيرفر تطبيق الموبايل", icon_name="wifi")
        f = _form(card)
        self.s_enabled = QCheckBox("تشغيل السيرفر تلقائياً عند فتح البرنامج")
        self.s_port = int_spin(1024, 65535)
        self.s_lan = QCheckBox("السماح بالاتصال من الشبكة المحلية فقط (موصى به)")
        f.addRow("", self.s_enabled)
        f.addRow("المنفذ (Port)", self.s_port)
        f.addRow("", self.s_lan)
        f.addRow("", _hrow(button("ربط موبايل (QR)", "qr", "soft", on_click=self._pair), "stretch"))
        card.add(muted("إذا لم يتصل الموبايل: تأكد أنهما على نفس الواي فاي، واسمح للبرنامج في جدار حماية ويندوز."))
        self.col.addWidget(card)

    def _ai(self) -> None:
        card = Card("الذكاء الاصطناعي (Google Gemini)", icon_name="sparkles")
        f = _form(card)
        self.ai_enabled = QCheckBox("تفعيل ميزات الذكاء الاصطناعي")
        self.ai_key = password_field("AIza...")
        self.ai_key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.ai_model = QComboBox()
        self.ai_model.setEditable(True)
        for m in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite", "gemini-2.0-flash"):
            self.ai_model.addItem(m)
        self.ai_status = muted("")
        f.addRow("", self.ai_enabled)
        f.addRow("مفتاح API", self.ai_key)
        f.addRow("الموديل", self.ai_model)
        f.addRow("", _hrow(button("اختبار الاتصال", "wifi", "soft", on_click=self._test_ai), self.ai_status, "stretch"))
        card.add(muted("احصل على مفتاح مجاني من aistudio.google.com. المفتاح يُحفظ مشفراً على هذا الجهاز فقط."))
        self.col.addWidget(card)

    def _backup(self) -> None:
        card = Card("النسخ الاحتياطي", icon_name="database")
        f = _form(card)
        self.b_auto = QCheckBox("نسخ احتياطي تلقائي يومي")
        self.b_keep = int_spin(1, 365)
        self.b_encrypt = QCheckBox("تشفير النسخ بكلمة سر")
        self.b_password = password_field("كلمة سر النسخ الاحتياطي")
        self.b_cloud = QLineEdit()
        self.b_cloud.setPlaceholderText("مثال: مجلد Google Drive على الكمبيوتر")
        f.addRow("", self.b_auto)
        f.addRow("الاحتفاظ بآخر", self.b_keep)
        f.addRow("", self.b_encrypt)
        f.addRow("كلمة سر التشفير", self.b_password)
        f.addRow("نسخة سحابية في", _hrow(self.b_cloud, button("اختيار", on_click=self._pick_cloud)))
        card.add(muted("للنسخ السحابي: ثبّت تطبيق Google Drive للكمبيوتر واختر مجلده هنا، فتُرفع كل نسخة تلقائياً."))
        f.addRow("", _hrow(button("نسخ احتياطي الآن", "download", "primary", on_click=self._backup_now),
                           button("استرجاع نسخة", "upload", on_click=self._restore),
                           button("فتح المجلد", on_click=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(sub_dir("backups"))))),
                           "stretch"))
        self.b_list = QListWidget()
        self.b_list.setMaximumHeight(150)
        card.add(self.b_list)
        self.col.addWidget(card)

    def _updates_security(self) -> None:
        card = Card("التحديثات والأمان", icon_name="lock")
        f = _form(card)
        self.up_url = QLineEdit()
        self.up_url.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.up_url.setPlaceholderText("https://api.github.com/repos/<owner>/<repo>/releases/latest")
        self.up_auto = QCheckBox("فحص التحديثات تلقائياً يومياً")
        f.addRow("رابط التحديثات", self.up_url)
        f.addRow("", self.up_auto)
        f.addRow("", _hrow(button("فحص الآن", "refresh", on_click=self._check_update),
                           button("توليد مفتاح استرجاع جديد", "key", on_click=self._new_recovery), "stretch"))
        f.addRow("الإصدار", QLabel(VERSION))
        path = QLabel(str(data_dir()))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f.addRow("مجلد البيانات", path)
        self.col.addWidget(card)

    # ---------------- التحميل والحفظ ----------------
    def refresh(self) -> None:
        with ctx.session() as (s, _):
            g = lambda k: settings_service.get(s, k)  # noqa: E731
            c = g("company")
            self.c_name.setText(c.get("name", ""))
            self.c_name_en.setText(c.get("name_en", ""))
            self.c_address.setText(c.get("address", ""))
            self.c_phone.setText(c.get("phone", ""))
            self.c_email.setText(c.get("email", ""))
            self.c_tax.setText(c.get("tax_number", ""))
            self.c_footer.setText(c.get("invoice_footer", ""))
            self.g_min.setValue(float(g("default_min_stock") or 0))
            self.g_slow.setValue(int(g("slow_moving_days")))
            self.g_expiry.setValue(int(g("expiry_warning_days")))
            self.g_large.setValue(float(g("large_invoice_amount") or 0))
            self.g_tax.setValue(float(g("tax_rate") or 0))
            self.g_negative.setChecked(bool(g("allow_negative_stock")))
            cf = g("code_format")
            self.g_sep.setCurrentIndex(max(0, self.g_sep.findData(cf.get("separator", "-"))))
            self.g_digits.setValue(int(cf.get("serial_digits", 4)))
            pr = g("printing")
            self.p_paper.setCurrentIndex(max(0, self.p_paper.findData(pr.get("paper", "A4"))))
            self.p_logo.setChecked(pr.get("show_logo", True))
            ui = g("ui")
            self.u_lang.setCurrentIndex(max(0, self.u_lang.findData(ui.get("language", "ar"))))
            self.u_theme.setCurrentIndex(max(0, self.u_theme.findData(ui.get("theme", "light"))))
            self.u_idle.setValue(int(ui.get("idle_lock_minutes", 15)))
            sv = g("server")
            self.s_enabled.setChecked(sv.get("enabled", True))
            self.s_port.setValue(int(sv.get("port", 8765)))
            self.s_lan.setChecked(sv.get("lan_only", True))
            ai = g("gemini")
            self.ai_enabled.setChecked(ai.get("enabled", True))
            self.ai_model.setCurrentText(ai.get("model", gemini_service.DEFAULT_MODEL))
            b = g("backup")
            self.b_auto.setChecked(b.get("auto", True))
            self.b_keep.setValue(int(b.get("keep", 14)))
            self.b_encrypt.setChecked(b.get("encrypt", False))
            self.b_cloud.setText(b.get("cloud_folder", ""))
            up = g("updates")
            self.up_url.setText(up.get("check_url", ""))
            self.up_auto.setChecked(up.get("auto_check", True))
        self.ai_key.setText(secrets_service.gemini_key() or "")
        self.b_password.setText(secrets_service.backup_password() or "")
        self._load_backups()

    def _load_backups(self) -> None:
        self.b_list.clear()
        for b in backup_service.list_backups()[:30]:
            it = QListWidgetItem(icons.icon("lock" if b.encrypted else "database"),
                                 f"{b.created:%Y-%m-%d %H:%M} — {b.size / 1024:,.0f} KB — {b.path.name}")
            it.setData(Qt.ItemDataRole.UserRole, str(b.path))
            self.b_list.addItem(it)

    def _save(self) -> None:
        if self.b_encrypt.isChecked() and not self.b_password.text():
            error(self, "أدخل كلمة سر لتشفير النسخ الاحتياطية")
            return
        with ctx.session() as (s, u):
            upd = lambda k, **kw: settings_service.update(s, k, **kw)  # noqa: E731
            upd("company", name=self.c_name.text().strip(), name_en=self.c_name_en.text().strip(),
                address=self.c_address.text(), phone=self.c_phone.text(), email=self.c_email.text(),
                tax_number=self.c_tax.text(), invoice_footer=self.c_footer.text())
            settings_service.set(s, "default_min_stock", self.g_min.value())
            settings_service.set(s, "slow_moving_days", self.g_slow.value())
            settings_service.set(s, "expiry_warning_days", self.g_expiry.value())
            settings_service.set(s, "large_invoice_amount", self.g_large.value())
            settings_service.set(s, "tax_rate", self.g_tax.value())
            settings_service.set(s, "allow_negative_stock", self.g_negative.isChecked())
            upd("code_format", separator=self.g_sep.currentData(), serial_digits=self.g_digits.value())
            upd("printing", paper=self.p_paper.currentData(), show_logo=self.p_logo.isChecked())
            old_ui = settings_service.get(s, "ui")
            upd("ui", language=self.u_lang.currentData(), theme=self.u_theme.currentData(),
                idle_lock_minutes=self.u_idle.value())
            upd("server", enabled=self.s_enabled.isChecked(), port=self.s_port.value(), lan_only=self.s_lan.isChecked())
            upd("gemini", enabled=self.ai_enabled.isChecked(), model=self.ai_model.currentText().strip())
            upd("backup", auto=self.b_auto.isChecked(), keep=self.b_keep.value(), encrypt=self.b_encrypt.isChecked(),
                cloud_folder=self.b_cloud.text().strip())
            upd("updates", check_url=self.up_url.text().strip(), auto_check=self.up_auto.isChecked())
            audit.log(s, u, "settings_changed", "settings")
        secrets_service.set_gemini_key(self.ai_key.text())
        secrets_service.set_backup_password(self.b_password.text() if self.b_encrypt.isChecked() else None)
        if self.u_theme.currentData() != theme.mode():
            theme.apply(QApplication.instance(), self.u_theme.currentData())
        win = self.window()
        if hasattr(win, "idle"):
            win.idle.set_minutes(self.u_idle.value())
        msg = "تم حفظ الإعدادات"
        if old_ui.get("language") != self.u_lang.currentData():
            msg += " — تغيير اللغة يظهر بعد إعادة تسجيل الدخول"
        Toast.show_message(self, msg, "success")

    # ---------------- إجراءات ----------------
    def _logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "الشعار", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            from PySide6.QtGui import QImage
            QImage(path).save(str(data_dir() / "company_logo.png"))
            self.logo.setPixmap(logo_label(56).pixmap())
            Toast.show_message(self, "تم تغيير الشعار — يظهر في الفواتير الجديدة", "success")

    def _logo_reset(self) -> None:
        (data_dir() / "company_logo.png").unlink(missing_ok=True)
        Toast.show_message(self, "تمت استعادة الشعار الأصلي", "success")

    def _pair(self) -> None:
        win = self.window()
        if hasattr(win, "show_pairing"):
            win.show_pairing()

    def _test_ai(self) -> None:
        key, model = self.ai_key.text().strip(), self.ai_model.currentText().strip()
        self.ai_status.setText("جارِ الاختبار...")
        run_async(lambda: gemini_service.test_connection(key, model),
                  lambda _r: self.ai_status.setText("✓ يعمل بنجاح"),
                  lambda m: self.ai_status.setText(f"✗ {m}"))

    def _pick_cloud(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "مجلد النسخ السحابية")
        if d:
            self.b_cloud.setText(d)

    def _backup_now(self) -> None:
        pw = self.b_password.text() if self.b_encrypt.isChecked() else None
        cloud, keep = self.b_cloud.text().strip() or None, self.b_keep.value()

        def done(path) -> None:
            with ctx.session() as (s, u):
                audit.log(s, u, "backup", "backup", None, file=str(path))
            Toast.show_message(self, f"تم إنشاء النسخة {Path(path).name}", "success")
            self._load_backups()
        run_async(lambda: backup_service.create_backup(password=pw, keep=keep, cloud_folder=cloud), done,
                  lambda m: error(self, m))

    def _restore(self) -> None:
        item = self.b_list.currentItem()
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "اختر نسخة", str(sub_dir("backups")), "FT Backup (*.ftbak)")
        if not path:
            return
        if not confirm(self, "استرجاع النسخة سيستبدل كل البيانات الحالية بها (سيتم حفظ نسخة من الوضع الحالي أولاً).\n"
                             "سيُغلق البرنامج بعدها لتسجيل الدخول من جديد. متابعة؟", danger=True):
            return
        pw = None
        if backup_service.is_encrypted(path):
            pw, ok = QInputDialog.getText(self, "نسخة مشفرة", "كلمة سر النسخة:", QLineEdit.EchoMode.Password)
            if not ok:
                return
        try:
            backup_service.restore_backup(path, pw)
        except Exception as exc:
            error(self, str(exc))
            return
        info(self, "تم الاسترجاع بنجاح. سجّل الدخول من جديد.")
        win = self.window()
        if hasattr(win, "logout"):
            win.logout()

    def _check_update(self) -> None:
        url = self.up_url.text().strip()
        if not url:
            error(self, "أدخل رابط التحديثات أولاً")
            return

        def done(res) -> None:
            if res and res.is_newer:
                if confirm(self, f"يتوفر الإصدار {res.version}\n\n{res.notes[:400]}\n\nفتح صفحة التنزيل؟"):
                    QDesktopServices.openUrl(QUrl(res.url))
            else:
                info(self, f"أنت تستخدم آخر إصدار ({VERSION})")
        run_async(lambda: update_service.check(url), done, lambda m: error(self, m))

    def _new_recovery(self) -> None:
        if not confirm(self, "توليد مفتاح استرجاع جديد سيلغي المفتاح القديم. متابعة؟"):
            return
        with ctx.session() as (s, u):
            key = auth_service.regenerate_recovery_key(s, u)
        QGuiApplication.clipboard().setText(key)
        info(self, f"مفتاح الاسترجاع الجديد (تم نسخه):\n\n{key}\n\nاحفظه في مكان آمن.")
