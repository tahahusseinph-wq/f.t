"""الهوية البصرية: الألوان، الخطوط، وأنماط الواجهة (فاتح/داكن) بأسلوب Claymorphism."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from ftapp.core.paths import assets_dir

# Claymorphism: ألوان باستيل ناعمة، زوايا دائرية كبيرة، إضاءة علوية وظل سفلي يعطي إحساس الصلصال
LIGHT = {
    "bg": "#E8ECF6", "surface": "#F6F7FC", "surface_hi": "#FFFFFF", "surface2": "#E6EAF5", "border": "#D5DCEC",
    "clay_hi": "#FFFFFF", "clay_lo": "#C9D2E7", "text": "#1E2742", "muted": "#6A7491", "icon": "#56607E",
    "primary": "#5B7CFA", "primary_hi": "#7E99FF", "primary_lo": "#4462DA", "primary_hover": "#4E6FF0",
    "primary_soft": "#E2E8FF", "accent": "#8FB4FF", "danger": "#EF5B70", "danger_soft": "#FFE4E8",
    "warning": "#E8892F", "warning_soft": "#FFEEDC", "success": "#2FA673", "success_soft": "#DBF5EA",
    "selection": "#DCE3FF", "row_alt": "#F3F5FB", "input": "#EDF0F8", "shadow": "#8E9CC6",
}

DARK = {
    "bg": "#191E2E", "surface": "#242A3F", "surface_hi": "#2C3350", "surface2": "#20253A", "border": "#323A57",
    "clay_hi": "#3A4366", "clay_lo": "#131725", "text": "#E7EBF7", "muted": "#99A2C0", "icon": "#B9C1DC",
    "primary": "#7B94FF", "primary_hi": "#97ACFF", "primary_lo": "#5C76E6", "primary_hover": "#8CA2FF",
    "primary_soft": "#2C3562", "accent": "#8FB4FF", "danger": "#FF7487", "danger_soft": "#41232C",
    "warning": "#FFAE5C", "warning_soft": "#3F3020", "success": "#4FD19A", "success_soft": "#1E3A30",
    "selection": "#323D6E", "row_alt": "#272E47", "input": "#1C2135", "shadow": "#03050A",
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


def clay_shadow(widget: QWidget, blur: int = 28, dy: int = 8, alpha: int = 70) -> QGraphicsDropShadowEffect:
    """ظل ناعم ممتد أسفل العنصر يعطيه إحساس الصلصال المرفوع."""
    c = QColor(_current["shadow"])
    c.setAlpha(alpha if _mode == "light" else min(255, alpha * 2))
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(c)
    widget.setGraphicsEffect(effect)
    return effect


def load_fonts() -> None:
    global FONT_FAMILY
    families = []
    for f in sorted((assets_dir() / "fonts").glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            families += QFontDatabase.applicationFontFamilies(fid)
    if families:
        FONT_FAMILY = families[0]


def _grad(top: str, bottom: str) -> str:
    return f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {top}, stop:1 {bottom})"


def stylesheet(t: dict[str, str]) -> str:
    small = compact()
    # صلصال بارز: حافة علوية مضيئة وحافة سفلية مظللة. صلصال غائر: العكس.
    raised = f"border: 2px solid {t['border']}; border-top-color: {t['clay_hi']}; border-bottom-color: {t['clay_lo']};"
    sunken = f"border: 2px solid {t['border']}; border-top-color: {t['clay_lo']}; border-bottom-color: {t['clay_hi']};"
    card_bg = _grad(t['surface_hi'], t['surface'])
    btn_bg = _grad(t['surface_hi'], t['surface2'])
    pri_bg = _grad(t['primary_hi'], t['primary'])
    pri_border = (f"border: 2px solid {t['primary']}; border-top-color: {t['primary_hi']}; "
                  f"border-bottom-color: {t['primary_lo']};")
    return f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: {9 if small else 10}pt; }}
QWidget {{ color: {t['text']}; }}
QMainWindow, QDialog, #page, #shell {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface_hi']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px; border-radius: 10px; }}

#topbar {{ background: {card_bg}; {raised} border-radius: {20 if small else 26}px; }}
#brandName {{ color: {t['text']}; font-size: 11pt; font-weight: bold; }}
#brandSub {{ color: {t['primary']}; font-size: 8pt; }}
#sectionPill {{ background: transparent; color: {t['muted']}; border: 2px solid transparent; border-radius: 17px;
               padding: {5 if small else 8}px {9 if small else 16}px; font-weight: bold; }}
#sectionPill:hover {{ background: {t['surface2']}; color: {t['text']}; }}
#sectionPill:checked {{ background: {pri_bg}; color: white; {pri_border} }}
#navPill {{ background: {btn_bg}; color: {t['text']}; {raised} border-radius: 16px;
           padding: {4 if small else 7}px {12 if small else 16}px; }}
#navPill:hover {{ color: {t['primary']}; }}
#navPill:checked {{ background: {t['primary_soft']}; color: {t['primary']}; font-weight: bold; {sunken} }}
#searchPill {{ background: {t['input']}; color: {t['muted']}; {sunken} border-radius: 18px; padding: 6px 16px; text-align: right; }}
#searchPill:hover {{ color: {t['primary']}; }}
#userChip {{ background: {btn_bg}; {raised} border-radius: 20px; padding: 3px 12px 3px 6px; font-weight: bold; }}
#userChip::menu-indicator {{ width: 0; image: none; }}
#avatar {{ background: {pri_bg}; color: white; border-radius: 15px; font-weight: bold; }}
#crumb {{ color: {t['muted']}; font-size: 9pt; font-weight: bold; }}

#pageTitle {{ font-size: {13 if small else 16}pt; font-weight: bold; }}
#pageSubtitle {{ color: {t['muted']}; }}

#card {{ background: {card_bg}; {raised} border-radius: {18 if small else 24}px; }}
#cardTitle {{ font-size: 11pt; font-weight: bold; }}
#kpiValue {{ font-size: 17pt; font-weight: bold; }}
#kpiLabel {{ color: {t['muted']}; font-size: 9pt; }}
#kpiDelta {{ font-size: 8.5pt; }}
#muted {{ color: {t['muted']}; }}
#hint {{ color: {t['muted']}; font-size: 8.5pt; }}
#error {{ color: {t['danger']}; }}
#bigTotal {{ font-size: {18 if small else 22}pt; font-weight: bold; color: {t['primary']};
            background: {t['primary_soft']}; {sunken} border-radius: 18px; padding: 6px; }}

QPushButton {{ background: {btn_bg}; {raised} border-radius: 14px; padding: {5 if small else 7}px {12 if small else 16}px; }}
QPushButton:hover {{ color: {t['primary']}; }}
QPushButton:pressed, QPushButton:checked {{ background: {t['surface2']}; {sunken} }}
QPushButton:disabled {{ color: {t['muted']}; background: {t['surface2']}; border: 2px solid {t['surface2']}; }}
QPushButton[variant="primary"] {{ background: {pri_bg}; color: white; {pri_border} font-weight: bold; }}
QPushButton[variant="primary"]:hover {{ background: {_grad(t['primary_hi'], t['primary_hover'])}; color: white; }}
QPushButton[variant="primary"]:pressed {{ background: {t['primary_lo']}; border-top-color: {t['primary_lo']}; border-bottom-color: {t['primary_hi']}; }}
QPushButton[variant="primary"]:disabled {{ background: {t['primary_soft']}; color: {t['muted']}; border: 2px solid {t['primary_soft']}; }}
QPushButton[variant="danger"] {{ background: {t['danger']}; color: white; border: 2px solid {t['danger']}; border-bottom-color: {t['clay_lo']}; }}
QPushButton[variant="danger"]:hover {{ background: {t['danger']}; color: white; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 2px solid transparent; padding: 6px 8px; border-radius: 12px; }}
QPushButton[variant="ghost"]:hover {{ background: {t['surface2']}; color: {t['text']}; }}
QPushButton[variant="soft"] {{ background: {t['primary_soft']}; color: {t['primary']}; border: 2px solid {t['primary_soft']}; border-bottom-color: {t['clay_lo']}; font-weight: bold; }}
QPushButton[variant="chip"] {{ background: {btn_bg}; {raised} border-radius: 15px; padding: 4px 12px; }}
QPushButton[variant="chip"]:checked {{ background: {pri_bg}; color: white; {pri_border} }}
QToolButton {{ background: transparent; border: none; border-radius: 10px; padding: 6px; }}
QToolButton:hover {{ background: {t['surface2']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {{ min-height: 22px; }}
QComboBox {{ min-width: 90px; }}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {{
  background: {t['input']}; {sunken} border-radius: 13px; padding: 6px 10px;
  selection-background-color: {t['primary']}; selection-color: white; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {{
  border: 2px solid {t['primary']}; }}
QLineEdit[invalid="true"] {{ border: 2px solid {t['danger']}; }}
QLineEdit#searchBox {{ border-radius: 20px; padding: 7px 16px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t['surface_hi']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 4px;
  selection-background-color: {t['selection']}; selection-color: {t['text']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; {sunken} border-radius: 7px; background: {t['input']}; }}
QCheckBox::indicator:checked {{ background: {pri_bg}; {pri_border} }}
QRadioButton::indicator {{ width: 14px; height: 14px; {sunken} border-radius: 9px; background: {t['input']}; }}
QRadioButton::indicator:checked {{ background: {t['primary']}; border: 2px solid {t['primary_lo']}; }}

QTableView, QTreeView, QListWidget, QTreeWidget, QTableWidget {{
  background: {t['surface_hi']}; alternate-background-color: {t['row_alt']}; border: 2px solid {t['surface2']};
  border-radius: 18px; gridline-color: transparent; selection-background-color: {t['selection']};
  selection-color: {t['text']}; outline: none; }}
QTableView::item, QTableWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {t['surface2']}; }}
QTreeView::item, QListWidget::item {{ padding: 6px; border-radius: 10px; }}
QTreeView::item:selected, QListWidget::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {t['surface2']}; color: {t['muted']}; border: none; padding: 9px 6px; font-weight: bold; }}
QTableCornerButton::section {{ background: {t['surface2']}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 7px 16px; margin: 2px; border-radius: 14px; border: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t['primary']}; background: {t['primary_soft']}; font-weight: bold; {sunken} }}
QTabBar::tab:hover {{ color: {t['text']}; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 3px; }}
QScrollBar::handle:vertical {{ background: {t['clay_lo']}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 3px; }}
QScrollBar::handle:horizontal {{ background: {t['clay_lo']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QMenu {{ background: {t['surface_hi']}; border: 2px solid {t['border']}; border-radius: 16px; padding: 8px; }}
QMenu::item {{ padding: 8px 22px; border-radius: 10px; }}
QMenu::item:selected {{ background: {t['selection']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
QGroupBox {{ border: 2px solid {t['surface2']}; border-radius: 16px; margin-top: 14px; padding-top: 10px; font-weight: bold; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; }}
QProgressBar {{ background: {t['input']}; border: none; border-radius: 5px; height: 10px; text-align: center; }}
QProgressBar::chunk {{ background: {pri_bg}; border-radius: 5px; }}
QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; color: {t['muted']}; }}

#badgeDanger {{ background: {t['danger_soft']}; color: {t['danger']}; border-radius: 10px; padding: 3px 10px; font-weight: bold; }}
#badgeWarning {{ background: {t['warning_soft']}; color: {t['warning']}; border-radius: 10px; padding: 3px 10px; font-weight: bold; }}
#badgeSuccess {{ background: {t['success_soft']}; color: {t['success']}; border-radius: 10px; padding: 3px 10px; font-weight: bold; }}
#badgeInfo {{ background: {t['primary_soft']}; color: {t['primary']}; border-radius: 10px; padding: 3px 10px; font-weight: bold; }}
#bellCount {{ background: {t['danger']}; color: white; border-radius: 8px; padding: 0 5px; font-size: 8pt; font-weight: bold; }}
#loginCard {{ background: {card_bg}; border-radius: 28px; {raised} }}
#loginSide {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t['primary_hi']}, stop:1 {t['primary_lo']}); border-radius: 28px; }}
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
