"""مسارات التطبيق: البيانات، النسخ الاحتياطية، الأصول (تعمل أيضاً داخل PyInstaller)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ftapp import APP_ID


def _bundle_root() -> Path:
    # داخل PyInstaller تكون الملفات في sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[3]


def assets_dir() -> Path:
    return _bundle_root() / "assets"


def templates_dir() -> Path:
    root = _bundle_root()
    candidate = root / "desktop" / "templates"
    return candidate if candidate.exists() else root / "templates"


def migrations_dir() -> Path:
    root = _bundle_root()
    candidate = root / "desktop" / "migrations"
    return candidate if candidate.exists() else root / "migrations"


def data_dir() -> Path:
    override = os.environ.get("FT_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_ID
    else:
        base = Path.home() / ".local" / "share" / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def sub_dir(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "ft_trading.db"


def logo_path() -> Path:
    custom = data_dir() / "company_logo.png"
    return custom if custom.exists() else assets_dir() / "logo.png"
