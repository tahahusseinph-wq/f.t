"""معالج الإعداد الأول، شاشة الدخول، واستعادة الحساب."""
from __future__ import annotations

import shutil

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QStackedWidget, QVBoxLayout, QWidget)

from ftapp import APP_NAME, APP_NAME_EN, VERSION
from ftapp.core import security
from ftapp.core.db import session_scope
from ftapp.core.paths import data_dir
from ftapp.services import auth_service
from ftapp.services.bootstrap import KNOWN_CURRENCIES
from ftapp.services.errors import ServiceError
from ftapp.ui import icons
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import button, info, logo_label
from ftapp.ui.widgets.forms import money_spin
from ftapp.ui.widgets.worker import run_async


def password_field(placeholder: str = "") -> QLineEdit:
    le = QLineEdit()
    le.setEchoMode(QLineEdit.EchoMode.Password)
    le.setPlaceholderText(placeholder)
    action = le.addAction(icons.icon("lock"), QLineEdit.ActionPosition.TrailingPosition)
    action.setToolTip("إظهار/إخفاء")

    def toggle() -> None:
        hidden = le.echoMode() == QLineEdit.EchoMode.Password
        le.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
    action.triggered.connect(toggle)
    return le


class StrengthBar(QProgressBar):
    LABELS = ["ضعيفة جداً", "ضعيفة", "مقبولة", "جيدة", "قوية"]
    COLORS = ["#E53935", "#E53935", "#FB8C00", "#43A047", "#2E7D32"]

    def __init__(self) -> None:
        super().__init__()
        self.setRange(0, 4)
        self.setTextVisible(False)
        self.setFixedHeight(6)
        self.label = QLabel("")
        self.label.setObjectName("hint")

    def update_for(self, password: str) -> None:
        score = security.password_strength(password)
        self.setValue(score)
        self.setStyleSheet(f"QProgressBar::chunk {{ background: {self.COLORS[score]}; border-radius: 3px; }}")
        self.label.setText(f"قوة كلمة السر: {self.LABELS[score]}" if password else "")


def _side_panel(subtitle: str) -> QFrame:
    side = QFrame()
    side.setObjectName("loginSide")
    side.setMinimumWidth(320)
    lay = QVBoxLayout(side)
    lay.setContentsMargins(30, 40, 30, 30)
    lay.addStretch(1)
    logo = logo_label(150)
    lay.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
    name = QLabel(APP_NAME)
    name.setStyleSheet("color: white; font-size: 16pt; font-weight: bold;")
    name.setAlignment(Qt.AlignmentFlag.AlignCenter)
    name.setWordWrap(True)
    en = QLabel(APP_NAME_EN)
    en.setStyleSheet(f"color: {tokens()['accent']}; font-size: 10pt;")
    en.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sub = QLabel(subtitle)
    sub.setStyleSheet("color: #9FB3C8;")
    sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sub.setWordWrap(True)
    lay.addSpacing(10)
    lay.addWidget(name)
    lay.addWidget(en)
    lay.addSpacing(8)
    lay.addWidget(sub)
    lay.addStretch(2)
    ver = QLabel(f"الإصدار {VERSION}")
    ver.setStyleSheet("color: #5F7186; font-size: 8pt;")
    ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(ver)
    return side


# =====================================================================
# معالج الإعداد الأول
# =====================================================================

class SetupWizard(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — الإعداد الأول")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(980, 640)
        self.recovery_key = ""
        self.logo_file: str | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(18)
        outer.addWidget(_side_panel("مرحباً بك! لنجهّز المنظومة في أربع خطوات بسيطة"))

        card = QFrame()
        card.setObjectName("loginCard")
        col = QVBoxLayout(card)
        col.setContentsMargins(34, 28, 34, 24)
        self.steps_label = QLabel()
        self.steps_label.setObjectName("hint")
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setWordWrap(True)
        col.addWidget(self.steps_label)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        col.addSpacing(10)
        self.stack = QStackedWidget()
        col.addWidget(self.stack, 1)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        col.addWidget(self.error)
        nav = QHBoxLayout()
        self.back_btn = button("السابق", on_click=self._back)
        self.next_btn = button("التالي", "check", "primary", on_click=self._next)
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        nav.addWidget(self.next_btn)
        col.addLayout(nav)
        outer.addWidget(card, 1)

        self._build_account()
        self._build_company()
        self._build_ai()
        self._build_recovery()
        self._go(0)

    # ---- الخطوات ----
    STEPS = [
        ("حساب المدير (الأدمن)", "أنشئ اسم مستخدم وكلمة سر جديدة. ستستخدمهما للدخول من الكمبيوتر والموبايل."),
        ("بيانات المنشأة والعملات", "تظهر هذه البيانات على الفواتير وملفات الإكسل."),
        ("الذكاء الاصطناعي (اختياري)", "أدخل مفتاح Google Gemini لجلب تفاصيل المنتجات تلقائياً. يمكنك تخطي هذه الخطوة."),
        ("مفتاح الاسترجاع", "احفظ هذا المفتاح في مكان آمن. ستحتاجه إذا نسيت كلمة السر. لن يظهر مرة أخرى!"),
    ]

    def _page(self) -> tuple[QWidget, QFormLayout]:
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(16)
        self.stack.addWidget(w)
        return w, form

    def _build_account(self) -> None:
        _, f = self._page()
        self.full_name = QLineEdit("فاروق الطعمة")
        self.username = QLineEdit("admin")
        self.username.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.password = password_field("8 أحرف على الأقل، أحرف وأرقام")
        self.password2 = password_field("أعد كتابة كلمة السر")
        self.strength = StrengthBar()
        self.password.textChanged.connect(self.strength.update_for)
        f.addRow("الاسم الكامل", self.full_name)
        f.addRow("اسم المستخدم", self.username)
        f.addRow("كلمة السر", self.password)
        f.addRow("", self.strength)
        f.addRow("", self.strength.label)
        f.addRow("تأكيد كلمة السر", self.password2)

    def _build_company(self) -> None:
        _, f = self._page()
        self.company = QLineEdit(APP_NAME)
        self.company_en = QLineEdit(APP_NAME_EN)
        self.address = QLineEdit()
        self.address.setPlaceholderText("مثال: دمشق - الحريقة")
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("مثال: 0944 000 000")
        logo_row = QHBoxLayout()
        self.logo_preview = logo_label(48)
        logo_btn = button("تغيير الشعار", "image", on_click=self._pick_logo)
        logo_row.addWidget(self.logo_preview)
        logo_row.addWidget(logo_btn)
        logo_row.addStretch(1)
        logo_w = QWidget()
        logo_w.setLayout(logo_row)
        self.base_cur = QComboBox()
        self.second_cur = QComboBox()
        self.second_cur.addItem("بدون عملة ثانية", None)
        for code, (name, symbol, _) in KNOWN_CURRENCIES.items():
            self.base_cur.addItem(f"{name} ({symbol})", code)
            self.second_cur.addItem(f"{name} ({symbol})", code)
        self.second_cur.setCurrentIndex(self.second_cur.findData("SYP"))
        self.rate = money_spin(10**9, 2)
        self.rate.setValue(13000)
        self.rate_label = QLabel()
        self.rate_label.setObjectName("hint")

        def update_rate_label() -> None:
            b, s = self.base_cur.currentData(), self.second_cur.currentData()
            self.rate.setEnabled(bool(s) and s != b)
            self.rate_label.setText(f"كم {s} يساوي 1 {b}؟ (يمكن تعديله لاحقاً من الإعدادات)" if s else "")
        self.base_cur.currentIndexChanged.connect(update_rate_label)
        self.second_cur.currentIndexChanged.connect(update_rate_label)
        update_rate_label()
        f.addRow("اسم المنشأة", self.company)
        f.addRow("الاسم بالإنكليزية", self.company_en)
        f.addRow("العنوان", self.address)
        f.addRow("الهاتف", self.phone)
        f.addRow("الشعار", logo_w)
        f.addRow("العملة الأساسية", self.base_cur)
        f.addRow("العملة الثانية", self.second_cur)
        f.addRow("سعر الصرف", self.rate)
        f.addRow("", self.rate_label)

    def _build_ai(self) -> None:
        w, f = self._page()
        self.gemini_key = password_field("AIza...")
        self.gemini_key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        test_row = QHBoxLayout()
        self.test_btn = button("اختبار المفتاح", "wifi", "soft", on_click=self._test_key)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        tw = QWidget()
        tw.setLayout(test_row)
        f.addRow("مفتاح Gemini API", self.gemini_key)
        f.addRow("", tw)
        how = QLabel("للحصول على مفتاح مجاني: ادخل إلى aistudio.google.com ← Get API key ← Create API key، "
                     "ثم انسخه هنا. المفتاح يُحفظ مشفّراً على جهازك فقط.")
        how.setObjectName("hint")
        how.setWordWrap(True)
        f.addRow("", how)

    def _build_recovery(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)
        self.key_label = QLabel()
        self.key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.key_label.setStyleSheet(f"font-family: monospace; font-size: 20pt; font-weight: bold; letter-spacing: 2px;"
                                     f"background: {tokens()['primary_soft']}; color: {tokens()['primary']};"
                                     f"border: 2px dashed {tokens()['primary']}; border-radius: 12px; padding: 18px;")
        self.key_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        lay.addWidget(self.key_label)
        row = QHBoxLayout()
        row.addWidget(button("نسخ", "copy", on_click=lambda: QGuiApplication.clipboard().setText(self.recovery_key)))
        row.addWidget(button("حفظ في ملف", "download", on_click=self._save_key))
        row.addStretch(1)
        lay.addLayout(row)
        self.saved_check = QCheckBox("لقد حفظت مفتاح الاسترجاع في مكان آمن")
        lay.addWidget(self.saved_check)
        lay.addStretch(1)
        self.stack.addWidget(w)

    # ---- التنقل ----
    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        title, sub = self.STEPS[index]
        self.steps_label.setText(f"الخطوة {index + 1} من {len(self.STEPS)}")
        self.title.setText(title)
        self.subtitle.setText(sub)
        self.error.clear()
        self.back_btn.setVisible(0 < index < 3)
        self.next_btn.setText({2: "إنهاء الإعداد", 3: "ابدأ العمل"}.get(index, "التالي"))

    def _back(self) -> None:
        self._go(max(0, self.stack.currentIndex() - 1))

    def _next(self) -> None:
        i = self.stack.currentIndex()
        self.error.clear()
        if i == 0:
            try:
                auth_service.validate_username(self.username.text())
            except ServiceError as exc:
                self.error.setText(str(exc))
                return
            err = security.validate_password(self.password.text())
            if err:
                self.error.setText(err)
                return
            if self.password.text() != self.password2.text():
                self.error.setText("كلمتا السر غير متطابقتين")
                return
            self._go(1)
        elif i == 1:
            if not self.company.text().strip():
                self.error.setText("أدخل اسم المنشأة")
                return
            self._go(2)
        elif i == 2:
            self._finish_setup()
        elif i == 3:
            if not self.saved_check.isChecked():
                self.error.setText("تأكد من حفظ مفتاح الاسترجاع ثم ضع إشارة على المربع")
                return
            self.accept()

    def _finish_setup(self) -> None:
        from ftapp.services import settings_service

        data = auth_service.SetupData(
            username=self.username.text().strip(), password=self.password.text(), full_name=self.full_name.text(),
            company_name=self.company.text().strip(), company_address=self.address.text(),
            company_phone=self.phone.text(), base_currency=self.base_cur.currentData(),
            secondary_currency=self.second_cur.currentData(), secondary_rate=self.rate.value(),
            gemini_key=self.gemini_key.text().strip())
        try:
            with session_scope() as s:
                self.recovery_key = auth_service.run_setup(s, data)
                company = settings_service.get(s, "company")
                company["name_en"] = self.company_en.text().strip()
                settings_service.set(s, "company", company)
            if self.logo_file:
                shutil.copy2(self.logo_file, data_dir() / "company_logo.png")
        except ServiceError as exc:
            self.error.setText(str(exc))
            return
        self.key_label.setText(self.recovery_key)
        self._go(3)

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "اختر الشعار", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.logo_file = path
            from PySide6.QtGui import QPixmap
            self.logo_preview.setPixmap(QPixmap(path).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                                             Qt.TransformationMode.SmoothTransformation))

    def _test_key(self) -> None:
        from ftapp.services import gemini_service

        key = self.gemini_key.text().strip()
        if not key:
            self.test_result.setText("أدخل المفتاح أولاً")
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText("جارِ الاختبار...")

        def ok(_res) -> None:
            self.test_btn.setEnabled(True)
            self.test_result.setStyleSheet(f"color: {tokens()['success']};")
            self.test_result.setText("✓ المفتاح يعمل بنجاح")

        def fail(msg: str) -> None:
            self.test_btn.setEnabled(True)
            self.test_result.setStyleSheet(f"color: {tokens()['danger']};")
            self.test_result.setText(msg)
        run_async(lambda: gemini_service.test_connection(key), ok, fail)

    def _save_key(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "حفظ مفتاح الاسترجاع", "مفتاح_الاسترجاع.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"{APP_NAME}\nمفتاح الاسترجاع: {self.recovery_key}\nاسم المستخدم: {self.username.text()}\n")
            info(self, "تم حفظ المفتاح. احتفظ بالملف في مكان آمن (فلاشة أو ورقة مطبوعة).")

    def reject(self) -> None:
        # لا يمكن إغلاق المعالج بعد إنشاء الحساب دون رؤية المفتاح
        if self.stack.currentIndex() == 3:
            return
        super().reject()


# =====================================================================
# تسجيل الدخول
# =====================================================================

class LoginDialog(QDialog):
    def __init__(self, locked_username: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(900, 560)
        self.user_id: int | None = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(18)
        outer.addWidget(_side_panel("منظومة إدارة المستودع والمبيعات"))
        card = QFrame()
        card.setObjectName("loginCard")
        col = QVBoxLayout(card)
        col.setContentsMargins(46, 40, 46, 30)
        col.setSpacing(12)
        col.addStretch(1)
        title = QLabel("قفل الشاشة" if locked_username else "تسجيل الدخول")
        title.setObjectName("pageTitle")
        col.addWidget(title)
        sub = QLabel("أدخل كلمة السر للمتابعة" if locked_username else "أهلاً بعودتك، سجّل دخولك للمتابعة")
        sub.setObjectName("pageSubtitle")
        col.addWidget(sub)
        col.addSpacing(16)
        col.addWidget(QLabel("اسم المستخدم"))
        self.username = QLineEdit(locked_username or "")
        self.username.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.username.setEnabled(not locked_username)
        self.username.setMinimumHeight(40)
        col.addWidget(self.username)
        col.addWidget(QLabel("كلمة السر"))
        self.password = password_field()
        self.password.setMinimumHeight(40)
        col.addWidget(self.password)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        col.addWidget(self.error)
        self.login_btn = button("تسجيل الدخول", "lock", "primary", on_click=self._login)
        self.login_btn.setMinimumHeight(42)
        self.login_btn.setDefault(True)
        col.addWidget(self.login_btn)
        forgot = button("نسيت كلمة السر؟", variant="ghost", on_click=self._forgot)
        col.addWidget(forgot, 0, Qt.AlignmentFlag.AlignLeft)
        col.addStretch(2)
        outer.addWidget(card, 1)
        (self.password if locked_username else self.username).setFocus()

    def _login(self) -> None:
        try:
            with session_scope() as s:
                user = auth_service.authenticate(s, self.username.text(), self.password.text())
                self.user_id = user.id
        except ServiceError as exc:
            self.error.setText(str(exc))
            self.password.selectAll()
            self.password.setFocus()
            return
        self.accept()

    def _forgot(self) -> None:
        RecoveryDialog(self).exec()


class RecoveryDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("استعادة حساب الأدمن")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        t = QLabel("استعادة حساب الأدمن")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        hint = QLabel("أدخل مفتاح الاسترجاع الذي ظهر لك عند الإعداد الأول، ثم اختر كلمة سر جديدة.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        form = QFormLayout()
        self.key = QLineEdit()
        self.key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX-XXXX")
        self.key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.username = QLineEdit("admin")
        self.username.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.pw1 = password_field()
        self.pw2 = password_field()
        form.addRow("مفتاح الاسترجاع", self.key)
        form.addRow("اسم مستخدم الأدمن", self.username)
        form.addRow("كلمة السر الجديدة", self.pw1)
        form.addRow("تأكيدها", self.pw2)
        lay.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("إلغاء", on_click=self.reject))
        row.addWidget(button("استعادة", "key", "primary", on_click=self._do))
        lay.addLayout(row)

    def _do(self) -> None:
        if self.pw1.text() != self.pw2.text():
            self.error.setText("كلمتا السر غير متطابقتين")
            return
        try:
            with session_scope() as s:
                new_key = auth_service.reset_with_recovery_key(s, self.key.text(), self.username.text(), self.pw1.text())
        except ServiceError as exc:
            self.error.setText(str(exc))
            return
        info(self, f"تم تغيير كلمة السر بنجاح.\n\nمفتاح الاسترجاع الجديد (احفظه):\n{new_key}")
        QGuiApplication.clipboard().setText(new_key)
        self.accept()
