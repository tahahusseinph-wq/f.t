"""النسخ الاحتياطي والاسترجاع (مع تشفير اختياري ونسخة سحابية عبر مجلد مزامنة)."""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ftapp import VERSION
from ftapp.core import db as dbm
from ftapp.core.paths import data_dir, db_path, sub_dir
from ftapp.services.errors import ValidationError

log = logging.getLogger(__name__)

MAGIC = b"FTBAK1"
EXT = ".ftbak"


@dataclass
class BackupInfo:
    path: Path
    created: datetime
    size: int
    encrypted: bool


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _snapshot_db(target: Path) -> None:
    """نسخة متسقة من قاعدة البيانات أثناء عمل التطبيق (sqlite backup API)."""
    src = sqlite3.connect(str(dbm.engine().url.database or db_path()))
    dst = sqlite3.connect(str(target))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()


def create_backup(target_dir: Path | str | None = None, password: str | None = None, keep: int | None = None,
                  cloud_folder: str | None = None, label: str = "") -> Path:
    target = Path(target_dir) if target_dir else sub_dir("backups")
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_db = sub_dir("tmp") / f"snapshot_{stamp}.db"
    _snapshot_db(tmp_db)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp_db, "ft_trading.db")
        zf.writestr("meta.json", json.dumps({"version": VERSION, "created": stamp, "label": label}))
        images = data_dir() / "images"
        if images.exists():
            for f in images.iterdir():
                if f.is_file():
                    zf.write(f, f"images/{f.name}")
        logo = data_dir() / "company_logo.png"
        if logo.exists():
            zf.write(logo, "company_logo.png")
    tmp_db.unlink(missing_ok=True)
    payload = buf.getvalue()

    if password:
        salt = os.urandom(16)
        payload = MAGIC + salt + Fernet(_derive_key(password, salt)).encrypt(payload)
    name = f"ft_backup_{stamp}{('_' + label) if label else ''}{EXT}"
    out = target / name
    out.write_bytes(payload)
    log.info("backup created: %s", out)

    if cloud_folder:
        try:
            dest = Path(cloud_folder)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(out, dest / name)
        except OSError:
            log.exception("cloud backup copy failed")
    if keep:
        prune(target, keep)
    return out


def prune(folder: Path, keep: int) -> None:
    files = sorted(folder.glob(f"ft_backup_*{EXT}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def is_encrypted(path: Path | str) -> bool:
    with open(path, "rb") as fh:
        return fh.read(len(MAGIC)) == MAGIC


def list_backups(folder: Path | str | None = None) -> list[BackupInfo]:
    folder = Path(folder) if folder else sub_dir("backups")
    out = []
    for f in folder.glob(f"*{EXT}"):
        st = f.stat()
        out.append(BackupInfo(f, datetime.fromtimestamp(st.st_mtime), st.st_size, is_encrypted(f)))
    return sorted(out, key=lambda b: b.created, reverse=True)


def restore_backup(path: Path | str, password: str | None = None) -> None:
    """يستبدل قاعدة البيانات الحالية بالنسخة. يجب إعادة تشغيل الواجهة بعدها."""
    raw = Path(path).read_bytes()
    if raw.startswith(MAGIC):
        if not password:
            raise ValidationError("هذه النسخة مشفرة، أدخل كلمة سر النسخ الاحتياطي")
        salt = raw[len(MAGIC):len(MAGIC) + 16]
        try:
            raw = Fernet(_derive_key(password, salt)).decrypt(raw[len(MAGIC) + 16:])
        except InvalidToken:
            raise ValidationError("كلمة سر النسخة غير صحيحة")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValidationError("ملف النسخة تالف أو غير صالح")
    if "ft_trading.db" not in zf.namelist():
        raise ValidationError("ملف النسخة لا يحتوي قاعدة بيانات")

    # نسخة أمان من الوضع الحالي قبل الاسترجاع
    try:
        create_backup(label="before_restore")
    except Exception:
        log.exception("pre-restore backup failed")

    db_file = Path(dbm.engine().url.database or db_path())
    dbm.dispose()
    for suffix in ("-wal", "-shm"):
        Path(str(db_file) + suffix).unlink(missing_ok=True)
    db_file.write_bytes(zf.read("ft_trading.db"))
    images = data_dir() / "images"
    for name in zf.namelist():
        if name.startswith("images/") and not name.endswith("/"):
            images.mkdir(exist_ok=True)
            (images / Path(name).name).write_bytes(zf.read(name))
        elif name == "company_logo.png":
            (data_dir() / name).write_bytes(zf.read(name))
    dbm.init_engine(db_file)
    dbm.run_migrations()
    log.info("backup restored from %s", path)


def auto_backup_if_due(session, force: bool = False) -> Path | None:
    from ftapp.services import secrets_service, settings_service as settings

    cfg = settings.get(session, "backup")
    if not cfg.get("auto") and not force:
        return None
    last = cfg.get("last")
    if not force and last:
        try:
            if (datetime.now() - datetime.fromisoformat(last)).total_seconds() < 20 * 3600:
                return None
        except ValueError:
            pass
    password = secrets_service.backup_password() if cfg.get("encrypt") else None
    path = create_backup(password=password, keep=int(cfg.get("keep") or 14), cloud_folder=cfg.get("cloud_folder") or None)
    cfg["last"] = datetime.now().isoformat(timespec="seconds")
    settings.set(session, "backup", cfg)
    session.commit()
    return path
