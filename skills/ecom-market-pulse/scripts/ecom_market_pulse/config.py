"""YAML 配置、环境变量插值和脱敏快照。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator

from .models import PrimaryCategory, SourceClass, SourceType


ENVIRONMENT_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
REDACTED_VALUE = "<redacted>"
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
    }
)
_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|credential|password|secret|token)\s*=\s*([^\s,&]+)"
)


class ConfigurationError(ValueError):
    """配置文件或环境变量无法安全满足运行前置条件。"""


class MissingEnvironmentVariableError(ConfigurationError):
    """YAML 中引用的环境变量不存在或为空。"""


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class DiscoveryConfig(ConfigModel):
    type: SourceType
    url: str = Field(..., min_length=1)
    # ``selector``/``selectors`` 是通用配置入口；细分字段同时兼容内置 HTML adapter。
    selector: str | None = Field(None, min_length=1)
    selectors: dict[str, str] = Field(default_factory=dict)
    item_selector: str | None = Field(None, min_length=1)
    link_selector: str | None = Field(None, min_length=1)
    title_selector: str | None = Field(None, min_length=1)
    date_selector: str | None = Field(None, min_length=1)
    pagination_selector: str | None = Field(None, min_length=1)
    url_pattern: str | None = Field(None, min_length=1)
    include_regex: str | None = Field(None, min_length=1)
    exclude_regex: str | None = Field(None, min_length=1)
    max_items: int | None = Field(None, ge=1, le=10_000)
    max_sitemaps: int | None = Field(None, ge=1, le=1_000)

    @field_validator("url")
    @classmethod
    def validate_public_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("discovery.url 必须是完整的 http 或 https URL")
        return value

    @field_validator("selectors")
    @classmethod
    def validate_selectors(cls, selectors: dict[str, str]) -> dict[str, str]:
        if any(not name.strip() or not selector.strip() for name, selector in selectors.items()):
            raise ValueError("discovery.selectors 不能包含空名称或空选择器")
        return selectors

    @field_validator("include_regex", "exclude_regex")
    @classmethod
    def validate_regular_expression(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"非法正则表达式：{value}") from exc
        return value

    @model_validator(mode="after")
    def apply_selector_aliases(self) -> DiscoveryConfig:
        """让 YAML 中紧凑的 selectors 映射可直接供内置 HTML adapter 使用。"""

        selector_keys = {
            "item_selector": ("item_selector", "item"),
            "link_selector": ("link_selector", "link"),
            "title_selector": ("title_selector", "title"),
            "date_selector": ("date_selector", "date"),
            "pagination_selector": ("pagination_selector", "pagination"),
        }
        if self.selector and self.item_selector is None:
            self.item_selector = self.selector
        for field_name, aliases in selector_keys.items():
            if getattr(self, field_name) is not None:
                continue
            for alias in aliases:
                selected = self.selectors.get(alias)
                if selected:
                    setattr(self, field_name, selected)
                    break
        return self


class FetchConfig(ConfigModel):
    interval_minutes: int = Field(..., ge=1, le=24 * 60)
    requests_per_minute: int = Field(..., ge=1, le=600)
    timeout_seconds: int = Field(..., ge=1, le=600)
    max_retries: int = Field(..., ge=0, le=10)


class ContentConfig(ConfigModel):
    language: str = Field(..., min_length=2, max_length=35)
    timezone: str = Field(..., min_length=1)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区：{value}") from exc
        return value


class SourceConfig(ConfigModel):
    id: str = Field(..., min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(..., min_length=1)
    enabled: bool
    source_class: SourceClass
    homepage_url: str = Field(..., min_length=1)
    discovery: DiscoveryConfig
    category_hints: list[PrimaryCategory] = Field(..., min_length=1, max_length=3)
    fetch: FetchConfig
    content: ContentConfig

    @field_validator("homepage_url")
    @classmethod
    def validate_homepage_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("homepage_url 必须是完整的 http 或 https URL")
        return value


class PulseConfig(ConfigModel):
    """工作区 config.yaml 的无密钥部分。"""

    timezone: str = Field("Asia/Shanghai")
    sources: list[SourceConfig] = Field(..., min_length=1)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区：{value}") from exc
        return value

    @model_validator(mode="after")
    def validate_source_ids(self) -> PulseConfig:
        source_ids = [source.id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("sources.id 必须唯一")
        return self


def load_config(path: str | Path, environ: Mapping[str, str] | None = None) -> PulseConfig:
    """读取 YAML、展开 ``${ENV_VAR}`` 并校验工作区配置。"""

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigurationError(f"配置文件不存在：{config_path}")

    try:
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"YAML 解析失败：{config_path}") from exc

    if not isinstance(raw_config, dict):
        raise ConfigurationError("配置根节点必须是 YAML 对象")

    try:
        expanded_config = interpolate_environment(raw_config, environ=environ)
        return PulseConfig.model_validate(expanded_config)
    except (MissingEnvironmentVariableError, ValidationError) as exc:
        raise ConfigurationError(f"配置校验失败：{exc}") from exc


def interpolate_environment(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    """递归展开 YAML 值中的 ``${ENV_VAR}``，缺失变量立即失败。"""

    environment = os.environ if environ is None else environ
    if isinstance(value, str):
        return ENVIRONMENT_PATTERN.sub(_environment_replacer(environment), value)
    if isinstance(value, list):
        return [interpolate_environment(item, environment) for item in value]
    if isinstance(value, dict):
        return {key: interpolate_environment(item, environment) for key, item in value.items()}
    return value


def redacted_snapshot(value: Any) -> dict[str, Any] | list[Any] | str | int | float | bool | None:
    """返回可持久化的配置快照，不保留 API Key、Cookie、Token 等敏感值。"""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    if isinstance(value, SecretStr):
        return REDACTED_VALUE
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED_VALUE if _is_sensitive_key(str(key)) else redacted_snapshot(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redacted_snapshot(item) for item in value]
    if isinstance(value, str):
        return _INLINE_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED_VALUE}", value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)


def redacted_snapshot_json(value: Any) -> str:
    """生成稳定排序的脱敏 JSON，用于 runs.config_json 与配置哈希。"""

    return json.dumps(redacted_snapshot(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _environment_replacer(environ: Mapping[str, str]):
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = environ.get(name)
        if resolved is None or not resolved.strip():
            raise MissingEnvironmentVariableError(f"缺少环境变量：{name}")
        return resolved

    return replace


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


__all__ = [
    "ConfigurationError",
    "ContentConfig",
    "DiscoveryConfig",
    "FetchConfig",
    "MissingEnvironmentVariableError",
    "PulseConfig",
    "REDACTED_VALUE",
    "SourceConfig",
    "interpolate_environment",
    "load_config",
    "redacted_snapshot",
    "redacted_snapshot_json",
]
