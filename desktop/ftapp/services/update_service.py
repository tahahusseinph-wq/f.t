"""فحص وجود إصدار جديد من التطبيق."""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from ftapp import VERSION


@dataclass
class UpdateInfo:
    version: str
    url: str
    notes: str = ""
    apk_url: str = ""

    @property
    def is_newer(self) -> bool:
        return parse_version(self.version) > parse_version(VERSION)


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "0")
    return tuple(int(n) for n in nums[:4]) or (0,)


def check(url: str, timeout: float = 10) -> UpdateInfo | None:
    """يدعم ملف JSON بسيط {version,url,notes,apk_url} أو رابط GitHub releases/latest."""
    if not url:
        return None
    resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if "tag_name" in data:  # GitHub API
        apk = next((a["browser_download_url"] for a in data.get("assets", [])
                    if a.get("name", "").endswith(".apk")), "")
        exe = next((a["browser_download_url"] for a in data.get("assets", [])
                    if a.get("name", "").endswith((".exe", ".zip"))), data.get("html_url", ""))
        return UpdateInfo(data["tag_name"].lstrip("v"), exe, data.get("body", "") or "", apk)
    return UpdateInfo(str(data.get("version", "0")), data.get("url", ""), data.get("notes", ""),
                      data.get("apk_url", ""))
