"""共享的公开网页采集基础设施。

本模块故意不依赖项目的 Pydantic 配置模型，避免采集器与配置层形成循环依赖。
适配器接受 ``SourceConfig`` 或具有同名属性的映射对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import re
import time
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol

if TYPE_CHECKING:
    from ecom_market_pulse.config import SourceConfig


DEFAULT_USER_AGENT = "ecom-market-pulse/1.0 (+public-content-collector)"
_CAPTCHA_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify that you are human",
    "unusual traffic",
    "access denied",
)


@dataclass(frozen=True, slots=True)
class DiscoveredItem:
    """发现阶段产出的候选文章，不承载任何业务分类。"""

    source_id: str
    url: str
    discovered_at: datetime
    title_hint: str | None = None
    published_at_hint: datetime | None = None
    canonical_url_hint: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawArticle:
    """一次公开 HTTP 请求的完整结果，成功和失败均可持久化。"""

    source_id: str
    item: DiscoveredItem
    request_url: str
    final_url: str | None
    status_code: int | None
    headers: Mapping[str, str]
    body: bytes | None
    fetched_at: datetime
    duration_ms: int
    content_type: str | None = None
    charset: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempts: int = 1

    @property
    def succeeded(self) -> bool:
        return self.error_code is None and self.status_code is not None and 200 <= self.status_code < 300

    def text(self) -> str:
        """按响应声明的编码解码正文；错误响应仍可供审计和验证码检测。"""
        if not self.body:
            return ""
        encoding = self.charset or _charset_from_content_type(self.content_type) or "utf-8"
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class SourceAdapter(Protocol):
    """三类发现器的稳定合同。"""

    def discover(self, source: "SourceConfig | Mapping[str, Any] | Any", since: datetime) -> list[DiscoveredItem]:
        """发现 ``since`` 之后或日期未知的公开候选文章。"""

    def fetch(
        self,
        source: "SourceConfig | Mapping[str, Any] | Any",
        item: DiscoveredItem,
    ) -> RawArticle:
        """下载候选文章原始响应；不得尝试登录、验证码或反爬绕过。"""


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    requests_per_minute: int = 10
    timeout_seconds: float = 20.0
    max_retries: int = 2

    @classmethod
    def from_source(cls, source: "SourceConfig | Mapping[str, Any] | Any") -> "FetchPolicy":
        fetch = source_value(source, "fetch", {})
        return cls(
            requests_per_minute=max(1, int(source_value(fetch, "requests_per_minute", 10))),
            timeout_seconds=max(0.1, float(source_value(fetch, "timeout_seconds", 20))),
            max_retries=max(0, int(source_value(fetch, "max_retries", 2))),
        )


class PublicHttpFetcher:
    """带速率限制和有限重试的公开 HTTP 获取器。

    它不接受认证、cookie 或代理绕过参数。401、403 和验证码页面会立即返回，
    不触发重试。调用方应把结果原样写入抓取审计表。
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._now = now
        self._sleep = sleep
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._next_request_at: dict[str, float] = {}

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "PublicHttpFetcher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(
        self,
        source: "SourceConfig | Mapping[str, Any] | Any",
        item: DiscoveredItem,
        url: str | None = None,
    ) -> RawArticle:
        target_url = url or item.url
        policy = FetchPolicy.from_source(source)
        started = self._now()
        attempt = 0
        client = self._http_client(policy)

        while True:
            attempt += 1
            self._respect_rate_limit(target_url, policy)
            try:
                response = client.get(
                    target_url,
                    headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"},
                    timeout=policy.timeout_seconds,
                )
            except Exception as exc:  # httpx raises a hierarchy rooted in HTTPError
                if attempt <= policy.max_retries:
                    self._sleep(_retry_delay_seconds(attempt))
                    continue
                return self._failure(item, target_url, started, attempt, "network_error", str(exc))

            body = bytes(response.content)
            content_type = _header_value(response.headers, "content-type")
            charset = _charset_from_content_type(content_type)
            response_text = _decode_body(body, charset)
            protected = response.status_code in (401, 403) or _looks_protected(response_text)
            if protected:
                return self._response_result(
                    item, target_url, response, started, attempt,
                    "access_protected", "站点要求登录、拒绝访问或展示验证码；采集器不会绕过保护。",
                )

            if response.status_code == 429 and attempt <= policy.max_retries:
                self._sleep(_retry_after_seconds(_header_value(response.headers, "retry-after"), attempt))
                continue
            if 500 <= response.status_code <= 599 and attempt <= policy.max_retries:
                self._sleep(_retry_delay_seconds(attempt))
                continue

            if response.status_code >= 400:
                return self._response_result(
                    item, target_url, response, started, attempt,
                    "http_error", f"HTTP {response.status_code}",
                )
            return self._response_result(item, target_url, response, started, attempt, None, None)

    def _http_client(self, policy: FetchPolicy) -> Any:
        if self._client is not None:
            return self._client
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - only relevant in an incomplete install
            raise RuntimeError("缺少 httpx 依赖，无法执行网络采集。") from exc
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(policy.timeout_seconds),
            # 公开资讯采集不依赖本机代理；避免失效的 HTTP(S)_PROXY 环境变量
            # 让所有信源在发现阶段被误判为空。
            trust_env=False,
        )
        return self._client

    def _respect_rate_limit(self, url: str, policy: FetchPolicy) -> None:
        from urllib.parse import urlsplit

        host = urlsplit(url).netloc.lower()
        interval = 60.0 / policy.requests_per_minute
        current = self._now()
        allowed_at = self._next_request_at.get(host, current)
        if allowed_at > current:
            self._sleep(allowed_at - current)
            current = self._now()
        self._next_request_at[host] = max(current, allowed_at) + interval

    def _failure(
        self,
        item: DiscoveredItem,
        request_url: str,
        started: float,
        attempts: int,
        error_code: str,
        error_message: str,
    ) -> RawArticle:
        return RawArticle(
            source_id=item.source_id,
            item=item,
            request_url=request_url,
            final_url=None,
            status_code=None,
            headers={},
            body=None,
            fetched_at=self._wall_clock(),
            duration_ms=round((self._now() - started) * 1000),
            error_code=error_code,
            error_message=error_message,
            attempts=attempts,
        )

    def _response_result(
        self,
        item: DiscoveredItem,
        request_url: str,
        response: Any,
        started: float,
        attempts: int,
        error_code: str | None,
        error_message: str | None,
    ) -> RawArticle:
        content_type = _header_value(response.headers, "content-type")
        return RawArticle(
            source_id=item.source_id,
            item=item,
            request_url=request_url,
            final_url=str(response.url),
            status_code=int(response.status_code),
            headers=dict(response.headers),
            body=bytes(response.content),
            fetched_at=self._wall_clock(),
            duration_ms=round((self._now() - started) * 1000),
            content_type=content_type,
            charset=_charset_from_content_type(content_type),
            error_code=error_code,
            error_message=error_message,
            attempts=attempts,
        )


def source_value(source: Any, path: str, default: Any = None) -> Any:
    """兼容 Pydantic 模型、普通对象和 Mapping 的松耦合字段读取。"""
    current = source
    for key in path.split("."):
        if current is None:
            return default
        if isinstance(current, Mapping):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return default if current is None else current


def source_id(source: Any) -> str:
    value = source_value(source, "id", None) or source_value(source, "source_id", None)
    if not value:
        raise ValueError("信源配置缺少 id。")
    return str(value)


def parse_datetime(value: str | datetime | None, default_timezone: str = "UTC") -> datetime | None:
    """解析发现页的常见日期格式；无法确认时返回 ``None``。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
    if parsed.tzinfo is None:
        try:
            from zoneinfo import ZoneInfo

            parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))
        except Exception:
            parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_metadata(**values: str | None) -> Mapping[str, str]:
    """仅保留字符串元数据，避免发现对象混入站点特有且不可序列化的数据。"""
    return {key: value for key, value in values.items() if value is not None}


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, flags=re.I)
    return match.group(1) if match else None


def _header_value(headers: Mapping[str, Any], name: str) -> str | None:
    """同时兼容 httpx 的大小写无关 Headers 和测试中的普通字典。"""
    direct = headers.get(name)
    if direct is not None:
        return str(direct)
    normalized = name.lower()
    for key, value in headers.items():
        if str(key).lower() == normalized:
            return str(value)
    return None


def _decode_body(body: bytes, charset: str | None) -> str:
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _looks_protected(text: str) -> bool:
    lowered = text[:100_000].lower()
    return any(marker in lowered for marker in _CAPTCHA_MARKERS)


def _retry_delay_seconds(attempt: int) -> float:
    return min(30.0, float(2 ** (attempt - 1)))


def _retry_after_seconds(value: str | None, attempt: int) -> float:
    if value:
        try:
            return max(0.0, min(120.0, float(value)))
        except ValueError:
            retry_at = parse_datetime(value)
            if retry_at is not None:
                return max(0.0, min(120.0, (retry_at - datetime.now(UTC)).total_seconds()))
    return _retry_delay_seconds(attempt)
