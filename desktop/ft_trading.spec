# -*- mode: python ; coding: utf-8 -*-
# بناء تطبيق الأدمن كملف تنفيذي:  pyinstaller ft_trading.spec
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("ftapp")
    + collect_submodules("keyring.backends")
    + ["sqlalchemy.dialects.sqlite", "alembic.runtime.migration", "alembic.ddl.sqlite", "zeroconf._utils.ipaddress",
       "zeroconf._handlers.answers", "argon2._ffi", "google.genai"]
)

a = Analysis(
    ["run_ftapp.py"],
    pathex=["."],
    datas=[
        ("../assets", "assets"),
        ("templates", "templates"),
        ("migrations", "migrations"),
    ],
    hiddenimports=hidden,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtQuick3D"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FaroukToumma",
    icon="../assets/icon.ico",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FaroukToumma")
