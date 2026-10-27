"""内置公开信源采集器。"""

from .base import DiscoveredItem, PublicHttpFetcher, RawArticle, SourceAdapter
from .amz123 import Amz123MorningNewsAdapter
from .amz123_flash import Amz123FlashNewsAdapter
from .amazon_ads import AmazonAdsWhatsNewAdapter
from .amazon_global_selling import AmazonGlobalSellingNewsAdapter
from .html import HtmlSourceAdapter
from .rss import RssSourceAdapter
from .sitemap import SitemapSourceAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    "rss": RssSourceAdapter,
    "html": HtmlSourceAdapter,
    "sitemap": SitemapSourceAdapter,
    "amz123-zb": Amz123MorningNewsAdapter,
    "amz123-kx": Amz123FlashNewsAdapter,
    "amazon-global-selling-cn": AmazonGlobalSellingNewsAdapter,
    "amazon-ads-whats-new": AmazonAdsWhatsNewAdapter,
}


def create_adapter(adapter_type: str, **kwargs: object) -> SourceAdapter:
    """按配置创建内置 adapter；新增类型只需在此注册。"""
    try:
        return ADAPTERS[adapter_type.lower()](**kwargs)
    except KeyError as exc:
        raise ValueError(f"不支持的信源 adapter 类型：{adapter_type}") from exc


__all__ = [
    "ADAPTERS",
    "AmazonAdsWhatsNewAdapter",
    "Amz123MorningNewsAdapter",
    "Amz123FlashNewsAdapter",
    "AmazonGlobalSellingNewsAdapter",
    "DiscoveredItem",
    "HtmlSourceAdapter",
    "PublicHttpFetcher",
    "RawArticle",
    "RssSourceAdapter",
    "SitemapSourceAdapter",
    "SourceAdapter",
    "create_adapter",
]
