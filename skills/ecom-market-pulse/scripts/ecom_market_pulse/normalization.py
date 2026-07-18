"""文章 URL、时间、语言和文本的无损确定性规范化。"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import html
import re
import unicodedata
from typing import Iterable
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from .collectors.base import parse_datetime


_TRACKING_PARAMETER_NAMES = {
    "_ga",
    "_gl",
    "clickid",
    "dclid",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ref",
    "ref_",
    "referrer",
    "sc_campaign",
    "sc_channel",
    "sc_content",
    "sc_medium",
    "sc_source",
}


def normalize_url(value: str | None, base_url: str | None = None) -> str | None:
    """移除已知 tracking 参数、fragment 和非根目录末尾的斜杠。"""
    if not value:
        return None
    url = urljoin(base_url, value) if base_url else value
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        return None
    netloc = hostname
    if parts.username:
        # URL 中的用户信息不能作为 canonical URL 的一部分。
        netloc = hostname
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    path = quote(unicodedata.normalize("NFC", parts.path or "/"), safe="/%:@!$&'()*+,;=-._~")
    if path != "/":
        path = path.rstrip("/") or "/"
    query_pairs = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not is_tracking_parameter(key)
    ]
    query = urlencode(sorted(query_pairs), doseq=True, safe="/:@")
    return urlunsplit((scheme, netloc, path, query, ""))


def is_tracking_parameter(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized.startswith("utm_") or normalized in _TRACKING_PARAMETER_NAMES


def normalize_text(value: str | None) -> str:
    """规范化 Unicode、HTML 实体和所有空白，但不改写事实文本。"""
    if not value:
        return ""
    text = html.unescape(value).replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def content_sha256(value: str | None) -> str:
    """返回清洗正文的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def raw_sha256(value: bytes | None) -> str:
    """返回原始响应体的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(value or b"").hexdigest()


def normalize_datetime(value: str | datetime | None, default_timezone: str = "UTC") -> datetime | None:
    """统一为 UTC；无法确定的日期永远返回 ``None``。"""
    return parse_datetime(value, default_timezone)


def normalize_language(value: str | None) -> str | None:
    """将 ``en-US``、``zh_Hans`` 等标签收敛为 ISO 639-1 主语言代码。"""
    if not value:
        return None
    primary = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return primary if re.fullmatch(r"[a-z]{2,3}", primary) else None


def detect_language_from_text(value: str | None) -> str | None:
    """无外部模型的保守语言提示；混合或文本过短时不猜测。"""
    text = normalize_text(value)
    if len(text) < 20:
        return None
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk >= 8 and cjk > latin:
        return "zh"
    if latin >= 20 and latin > cjk * 2:
        return "en"
    return None
