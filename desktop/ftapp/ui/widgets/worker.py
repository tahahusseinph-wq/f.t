"""تنفيذ العمليات الطويلة (الذكاء الاصطناعي، التصدير، الشبكة) خارج الخيط الرئيسي."""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)
_keep: set["Task"] = set()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self) -> None:
        from ftapp.services.errors import ServiceError

        try:
            result = self.fn()
        except ServiceError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            log.exception("background task failed")
            self.signals.failed.emit(f"حدث خطأ: {exc}")
        else:
            self.signals.done.emit(result)
        finally:
            _keep.discard(self)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None] | None = None,
              on_error: Callable[[str], None] | None = None) -> Task:
    task = Task(fn)
    if on_done:
        task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    _keep.add(task)
    QThreadPool.globalInstance().start(task)
    return task
