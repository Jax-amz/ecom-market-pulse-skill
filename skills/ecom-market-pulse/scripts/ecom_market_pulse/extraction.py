"""正文、元数据和 canonical URL 提取，不生成业务结论。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .collectors.base import RawArticle, source_value
from .normalization import detect_language_from_text, normalize_datetime, normalize_language, normalize_text, normalize_url


@dataclass(frozen=True, slots=True)
class ExtractedArticle:
    """从 ``RawArticle`` 中提取出的不可变正文快照。"""

    raw_article: RawArticle
    canonical_url: str | None
    title: str | None
    original_title: str | None
    author: str | None
    published_at: datetime | None
    language: str | None
    extracted_text: str
    extracted_html: str | None
    extractor_version: str
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_message is None and bool(self.extracted_text)


def extract_article(raw: RawArticle, source: Any | None = None) -> ExtractedArticle:
    """优先 trafilatura，BeautifulSoup 只作为正文与元数据的保守兜底。"""
    if not raw.succeeded:
        return ExtractedArticle(raw, None, None, raw.item.title_hint, None, raw.item.published_at_hint, None, "", None, "unavailable", raw.error_message or "抓取未成功")
    html = raw.text()
    if not html.strip():
        return ExtractedArticle(raw, None, None, raw.item.title_hint, None, raw.item.published_at_hint, None, "", None, "unavailable", "响应正文为空")

    source_timezone = str(source_value(source, "content.timezone", "UTC")) if source is not None else "UTC"
    metadata = _extract_metadata(html, raw.final_url or raw.request_url, source_timezone)
    extracted_html, extracted_text, version = _extract_with_trafilatura(html)
    if not extracted_text:
        fallback_html, fallback_text = _extract_with_beautifulsoup(html)
        extracted_html = extracted_html or fallback_html
        extracted_text = fallback_text
        version = "beautifulsoup4-fallback"

    canonical_url = normalize_url(metadata.canonical_url or raw.item.canonical_url_hint or raw.final_url or raw.request_url)
    original_title = metadata.title or raw.item.title_hint
    title = normalize_text(original_title) or None
    language = normalize_language(metadata.language) or normalize_language(source_value(source, "content.language", None))
    language = language or detect_language_from_text(extracted_text)
    published_at = metadata.published_at or raw.item.published_at_hint
    error = None if extracted_text else "未提取到正文"
    return ExtractedArticle(
        raw_article=raw,
        canonical_url=canonical_url,
        title=title,
        original_title=original_title,
        author=metadata.author,
        published_at=published_at,
        language=language,
        extracted_text=normalize_text(extracted_text),
        extracted_html=extracted_html,
        extractor_version=version,
        error_message=error,
    )


@dataclass(frozen=True, slots=True)
class _Metadata:
    canonical_url: str | None
    title: str | None
    author: str | None
    published_at: datetime | None
    language: str | None


def _extract_metadata(html: str, base_url: str, timezone: str) -> _Metadata:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - package installation is validated separately
        raise RuntimeError("缺少 beautifulsoup4 依赖，无法提取文章元数据。") from exc
    soup = BeautifulSoup(html, "html.parser")
    canonical = _link_value(soup, "canonical") or _meta_value(soup, "og:url")
    title = _meta_value(soup, "og:title") or _meta_value(soup, "twitter:title") or _text_of(soup.title)
    author = _meta_value(soup, "author") or _meta_value(soup, "article:author")
    published_raw = (
        _meta_value(soup, "article:published_time")
        or _meta_value(soup, "datePublished")
        or _meta_value(soup, "date")
        or _time_value(soup)
    )
    language = soup.html.get("lang") if soup.html else None
    return _Metadata(
        canonical_url=normalize_url(canonical, base_url),
        title=normalize_text(title) or None,
        author=normalize_text(author) or None,
        published_at=normalize_datetime(published_raw, timezone),
        language=language,
    )


def _extract_with_trafilatura(html: str) -> tuple[str | None, str, str]:
    try:
        import trafilatura
    except ImportError:
        return None, "", "unavailable"
    try:
        extracted_html = trafilatura.extract(html, output_format="html", include_comments=False, include_tables=True)
        extracted_text = trafilatura.extract(html, output_format="txt", include_comments=False, include_tables=True)
        return extracted_html, normalize_text(extracted_text), f"trafilatura-{getattr(trafilatura, '__version__', 'unknown')}"
    except Exception:
        return None, "", f"trafilatura-{getattr(trafilatura, '__version__', 'unknown')}"


def _extract_with_beautifulsoup(html: str) -> tuple[str | None, str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 beautifulsoup4 依赖，无法使用正文提取兜底。") from exc
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, noscript, nav, header, footer, aside, form, iframe, svg"):
        node.decompose()
    body = soup.select_one("article, main, [role='main'], [itemprop='articleBody']") or soup.body
    if body is None:
        return None, ""
    return str(body), normalize_text(body.get_text(" ", strip=True))


def _meta_value(soup: Any, name: str) -> str | None:
    node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"itemprop": name})
    return node.get("content") if node else None


def _link_value(soup: Any, relation: str) -> str | None:
    node = soup.find("link", attrs={"rel": lambda value: value and relation in value})
    return node.get("href") if node else None


def _time_value(soup: Any) -> str | None:
    node = soup.find("time")
    return (node.get("datetime") or node.get("content") or node.get_text(" ", strip=True)) if node else None


def _text_of(node: Any) -> str | None:
    return node.get_text(" ", strip=True) if node else None
