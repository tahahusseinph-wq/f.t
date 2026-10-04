"""تشغيل سيرفر الـ API في خيط منفصل داخل تطبيق الأدمن، مع الإعلان عنه على الشبكة (mDNS)."""
from __future__ import annotations

import json
import logging
import socket
import threading
import time

import uvicorn

from ftapp.api.app import create_app

log = logging.getLogger(__name__)
SERVICE_TYPE = "_fttrading._tcp.local."


def local_ips() -> list[str]:
    """عناوين IP المحلية للجهاز (لعرضها في QR الاقتران)."""
    ips: list[str] = []
    try:
        # لا يُرسل أي شيء فعلياً؛ فقط لمعرفة واجهة الشبكة الافتراضية
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


def pairing_payload(server_id: str, company: str, port: int) -> str:
    return json.dumps({"t": "ft", "id": server_id, "n": company, "h": local_ips(), "p": port},
                      ensure_ascii=False, separators=(",", ":"))


class ApiServer:
    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._zeroconf = None
        self._service_info = None
        self.port: int | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._server and self._server.started and self._thread and self._thread.is_alive())

    def start(self, port: int = 8765, lan_only: bool = True, server_id: str = "", company: str = "") -> None:
        if self.running:
            return
        self.error = None
        config = uvicorn.Config(create_app(lan_only=lan_only), host="0.0.0.0", port=port, log_level="warning",
                                access_log=False, lifespan="off")
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        self.port = port

        def run() -> None:
            try:
                self._server.run()
            except SystemExit:
                self.error = f"المنفذ {port} مستخدم من برنامج آخر"
            except Exception as exc:  # pragma: no cover
                self.error = str(exc)
                log.exception("api server crashed")

        self._thread = threading.Thread(target=run, name="api-server", daemon=True)
        self._thread.start()
        for _ in range(50):
            if self._server.started or not self._thread.is_alive():
                break
            time.sleep(0.1)
        if not self._server.started and not self.error:
            self.error = f"تعذر تشغيل السيرفر على المنفذ {port}"
        if self.running:
            log.info("API server listening on %s:%s", local_ips(), port)
            self._register_mdns(port, server_id, company)

    def stop(self) -> None:
        self._unregister_mdns()
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def _register_mdns(self, port: int, server_id: str, company: str) -> None:
        try:
            from zeroconf import ServiceInfo, Zeroconf

            ips = [socket.inet_aton(ip) for ip in local_ips() if not ip.startswith("127.")]
            if not ips:
                return
            name = f"FT-{server_id or 'server'}.{SERVICE_TYPE}"
            self._service_info = ServiceInfo(SERVICE_TYPE, name, addresses=ips, port=port,
                                             properties={"id": server_id, "app": "ft-trading",
                                                         "name": company.encode("utf-8")[:200]},
                                             server=f"ft-{server_id or 'server'}.local.")
            self._zeroconf = Zeroconf()
            self._zeroconf.register_service(self._service_info)
        except Exception:
            log.warning("mDNS registration failed", exc_info=True)
            self._zeroconf = None

    def _unregister_mdns(self) -> None:
        if self._zeroconf and self._service_info:
            try:
                self._zeroconf.unregister_service(self._service_info)
                self._zeroconf.close()
            except Exception:
                pass
        self._zeroconf = None
        self._service_info = None


server = ApiServer()
