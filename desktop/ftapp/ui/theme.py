"""الهوية البصرية: الألوان، الخطوط، وأنماط الواجهة (فاتح/داكن)."""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from ftapp.core.paths import assets_dir

LIGHT = {
    "bg": "#F3F6FA", "surface": "#FFFFFF", "surface2": "#EEF3F9", "border": "#DCE4EE", "text": "#0D1B2A",
    "muted": "#5B6B7B", "icon": "#4A5A6A", "primary": "#1565C0", "primary_hover": "#0F539F",
    "primary_soft": "#E3F0FC", "accent": "#6BB8E6", "sidebar": "#0B0F14", "sidebar_text": "#C9D4E0",
    "sidebar_active": "#1565C0", "sidebar_hover": "#18212B", "danger": "#E53935", "danger_soft": "#FDECEC",
    "warning": "#F57C00", "warning_soft": "#FFF3E0", "success": "#2E7D32", "success_soft": "#E8F5E9",
    "selection": "#D6E8FB", "row_alt": "#F8FAFD", "input": "#FFFFFF", "shadow": "rgba(13,27,42,0.06)",
}

DARK = {
    "bg": "#0E1319", "surface": "#161D25", "surface2": "#1D2631", "border": "#293443", "text": "#E6EDF3",
    "muted": "#93A1B0", "icon": "#B4C1CE", "primary": "#4A9BE8", "primary_hover": "#6BB0F0",
    "primary_soft": "#1A2C42", "accent": "#6BB8E6", "sidebar": "#080B0F", "sidebar_text": "#B7C4D1",
    "sidebar_active": "#1565C0", "sidebar_hover": "#121A23", "danger": "#EF5350", "danger_soft": "#3A1F22",
    "warning": "#FFA726", "warning_soft": "#3A2A16", "success": "#66BB6A", "success_soft": "#1C3320",
    "selection": "#1E3A5C", "row_alt": "#18202A", "input": "#111820", "shadow": "rgba(0,0,0,0.3)",
}

_current = dict(LIGHT)
_mode = "light"
FONT_FAMILY = "Cairo"


def compact() -> bool:
    """شاشة صغيرة (لابتوب 1366x768 مثلاً): نصغّر الخط والهوامش حتى لا تختفي العناصر."""
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return False
    g = screen.availableGeometry()
    return g.width() < 1500 or g.height() < 820


def tokens() -> dict[str, str]:
    return _current


def mode() -> str:
    return _mode


def load_fonts() -> None:
    global FONT_FAMILY
    families = []
    for f in sorted((assets_dir() / "fonts").glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            families += QFontDatabase.applicationFontFamilies(fid)
    if families:
        FONT_FAMILY = families[0]


def stylesheet(t: dict[str, str]) -> str:
    return f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: {9 if compact() else 10}pt; }}
QWidget {{ color: {t['text']}; }}
QMainWindow, QDialog, #page {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px; border-radius: 6px; }}

#sidebar {{ background: {t['sidebar']}; border: none; }}
#sidebar QLabel {{ color: {t['sidebar_text']}; }}
#brandName {{ color: #FFFFFF; font-size: 11pt; font-weight: bold; }}
#brandSub {{ color: {t['accent']}; font-size: 8pt; }}
#navButton {{ background: transparent; color: {t['sidebar_text']}; border: none; border-radius: 10px;
             padding: 9px 14px; text-align: right; font-size: 10pt; }}
#navButton:hover {{ background: {t['sidebar_hover']}; color: #FFFFFF; }}
#navButton:checked {{ background: {t['sidebar_active']}; color: #FFFFFF; font-weight: bold; }}
#navSection {{ color: #5F7186; font-size: 8pt; padding: 10px 14px 2px 14px; }}

#topbar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
#pageTitle {{ font-size: {13 if compact() else 15}pt; font-weight: bold; }}
#pageSubtitle {{ color: {t['muted']}; }}

#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
#cardTitle {{ font-size: 11pt; font-weight: bold; }}
#kpiValue {{ font-size: 17pt; font-weight: bold; }}
#kpiLabel {{ color: {t['muted']}; font-size: 9pt; }}
#kpiDelta {{ font-size: 8.5pt; }}
#muted {{ color: {t['muted']}; }}
#hint {{ color: {t['muted']}; font-size: 8.5pt; }}
#error {{ color: {t['danger']}; }}
#bigTotal {{ font-size: {18 if compact() else 22}pt; font-weight: bold; color: {t['primary']}; }}

QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 9px; padding: {5 if compact() else 7}px {10 if compact() else 14}px; }}
QPushButton:hover {{ border-color: {t['primary']}; color: {t['primary']}; }}
QPushButton:pressed {{ background: {t['surface2']}; }}
QPushButton:disabled {{ color: {t['muted']}; background: {t['surface2']}; border-color: {t['border']}; }}
QPushButton[variant="primary"] {{ background: {t['primary']}; color: white; border: 1px solid {t['primary']}; font-weight: bold; }}
QPushButton[variant="primary"]:hover {{ background: {t['primary_hover']}; color: white; }}
QPushButton[variant="danger"] {{ background: {t['danger']}; color: white; border: 1px solid {t['danger']}; }}
QPushButton[variant="danger"]:hover {{ background: {t['danger']}; color: white; }}
QPushButton[variant="ghost"] {{ background: transparent; border: none; padding: 6px 8px; }}
QPushButton[variant="ghost"]:hover {{ background: {t['surface2']}; color: {t['text']}; }}
QPushButton[variant="soft"] {{ background: {t['primary_soft']}; color: {t['primary']}; border: none; font-weight: bold; }}
QPushButton[variant="chip"] {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 14px; padding: 4px 12px; }}
QPushButton[variant="chip"]:checked {{ background: {t['primary']}; color: white; border-color: {t['primary']}; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; }}
QToolButton:hover {{ background: {t['surface2']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {{ min-height: 22px; }}
QComboBox {{ min-width: 90px; }}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {{
  background: {t['input']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 6px 8px;
  selection-background-color: {t['primary']}; selection-color: white; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {{
  border: 1.5px solid {t['primary']}; }}
QLineEdit[invalid="true"] {{ border: 1.5px solid {t['danger']}; }}
QLineEdit#searchBox {{ border-radius: 18px; padding: 7px 14px; background: {t['surface2']}; border: 1px solid transparent; }}
QLineEdit#searchBox:focus {{ background: {t['input']}; border: 1.5px solid {t['primary']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']}; selection-background-color: {t['selection']}; selection-color: {t['text']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border: 1.5px solid {t['border']}; border-radius: 5px; background: {t['input']}; }}
QCheckBox::indicator:checked {{ background: {t['primary']}; border-color: {t['primary']}; }}

QTableView, QTreeView, QListWidget, QTreeWidget, QTableWidget {{
  background: {t['surface']}; alternate-background-color: {t['row_alt']}; border: 1px solid {t['border']};
  border-radius: 10px; gridline-color: transparent; selection-background-color: {t['selection']};
  selection-color: {t['text']}; outline: none; }}
QTableView::item, QTableWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {t['surface2']}; }}
QTreeView::item, QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QTreeView::item:selected, QListWidget::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
QHeaderView::section {{ background: {t['surface2']}; color: {t['muted']}; border: none; padding: 8px 6px; font-weight: bold; }}
QTableCornerButton::section {{ background: {t['surface2']}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 8px 16px; margin: 0 2px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t['primary']}; border-bottom: 2px solid {t['primary']}; font-weight: bold; }}
QTabBar::tab:hover {{ color: {t['text']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['selection']}; }}
QGroupBox {{ border: 1px solid {t['border']}; border-radius: 10px; margin-top: 14px; padding-top: 10px; font-weight: bold; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; }}
QProgressBar {{ background: {t['surface2']}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {t['primary']}; border-radius: 4px; }}
QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; color: {t['muted']}; }}

#badgeDanger {{ background: {t['danger_soft']}; color: {t['danger']}; border-radius: 8px; padding: 2px 8px; font-weight: bold; }}
#badgeWarning {{ background: {t['warning_soft']}; color: {t['warning']}; border-radius: 8px; padding: 2px 8px; font-weight: bold; }}
#badgeSuccess {{ background: {t['success_soft']}; color: {t['success']}; border-radius: 8px; padding: 2px 8px; font-weight: bold; }}
#badgeInfo {{ background: {t['primary_soft']}; color: {t['primary']}; border-radius: 8px; padding: 2px 8px; font-weight: bold; }}
#bellCount {{ background: {t['danger']}; color: white; border-radius: 8px; padding: 0 5px; font-size: 8pt; font-weight: bold; }}
#loginCard {{ background: {t['surface']}; border-radius: 20px; border: 1px solid {t['border']}; }}
#loginSide {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0B0F14, stop:1 #12355E); border-radius: 20px; }}
"""


def apply(app: QApplication, theme: str = "light") -> None:
    global _mode
    _mode = "dark" if theme == "dark" else "light"
    _current.clear()
    _current.update(DARK if _mode == "dark" else LIGHT)
    font = QFont(FONT_FAMILY, 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(stylesheet(_current))
    from ftapp.ui import icons
    icons.pixmap.cache_clear()
