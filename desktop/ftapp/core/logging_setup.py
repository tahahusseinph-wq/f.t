"""إعداد سجل الأخطاء مع تدوير الملفات."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from ftapp.core.paths import sub_dir

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    log_file = sub_dir("logs") / "ftapp.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console)
    _configured = True
