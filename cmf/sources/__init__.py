# -*- coding: utf-8 -*-
"""Source registry. 新增数据源 = 写一个 Source 子类 + 在这里登记一行。"""
from __future__ import annotations

from typing import Dict, Iterable, List

from .base import Context, Source, SourceMeta
from .cn_courses import BilibiliSource, ChinaoocSource
from .links import LinkPortalSource
from .misc import GitHubSource, StackExchangeSource, WikipediaSource
from .papers import (
    ArxivSource,
    CrossrefSource,
    DoajSource,
    EuropePmcSource,
    OpenAlexSource,
    ZenodoSource,
)
from .textbooks import (
    GutendexSource,
    MitOcwSource,
    OpenStaxSource,
    OpenTextbookLibrarySource,
    WikibooksSource,
)
from .websearch import BaiduSource, BingSource, SogouSource

_INSTANCES: List[Source] = [
    # 中文课程 / 视频
    ChinaoocSource(),
    BilibiliSource(),
    # 开放教材
    OpenStaxSource(),
    OpenTextbookLibrarySource(),
    MitOcwSource(),
    WikibooksSource(),
    GutendexSource(),
    # 学术
    OpenAlexSource(),
    CrossrefSource(),
    DoajSource(),
    ZenodoSource(),
    ArxivSource(),
    EuropePmcSource(),
    # 通用搜索
    BingSource(),
    BaiduSource(),
    SogouSource(),
    # 百科 / 问答 / 代码
    WikipediaSource(),
    StackExchangeSource(),
    GitHubSource(),
    # 仅链接兜底
    LinkPortalSource(),
]

ALL_SOURCES: Dict[str, Source] = {s.meta.id: s for s in _INSTANCES}
DEFAULT_IDS: List[str] = [sid for sid, s in ALL_SOURCES.items() if s.meta.enabled and s.meta.tier != "link"]
LINK_IDS: List[str] = [sid for sid, s in ALL_SOURCES.items() if s.meta.tier == "link"]

ALIASES = {
    "ocw": "ocw",
    "mit": "ocw",
    "mitocw": "ocw",
    "b站": "bilibili",
    "bili": "bilibili",
    "智慧教育": "chinaooc",
    "爱课程": "chinaooc",
    "wiki": "wikipedia",
    "维基": "wikipedia",
    "se": "stackexchange",
    "so": "stackexchange",
    "gh": "github",
    "umn": "otl",
    "opentextbook": "otl",
    "zhihu": "portals",
    "all": "*",
}


def resolve(names: Iterable[str] | None) -> List[str]:
    """把用户给的 --sources 解析成 registry 里的 id 列表。"""
    if not names:
        return list(DEFAULT_IDS) + list(LINK_IDS)
    out: List[str] = []
    for raw in names:
        for token in str(raw).replace("，", ",").split(","):
            token = token.strip().lower()
            if not token:
                continue
            token = ALIASES.get(token, token)
            if token == "*":
                return list(ALL_SOURCES)
            if token not in ALL_SOURCES:
                raise KeyError(f"未知数据源: {raw}（可用: {', '.join(ALL_SOURCES)}）")
            if token not in out:
                out.append(token)
    return out


def describe_table() -> List[Dict[str, str]]:
    rows = []
    for s in _INSTANCES:
        m = s.meta
        rows.append(
            {
                "id": m.id,
                "label": m.label,
                "kind": m.kind,
                "lang": m.lang,
                "tier": m.tier,
                "enabled": "是" if m.enabled else "否",
                "note": m.note,
            }
        )
    return rows


__all__ = [
    "ALL_SOURCES",
    "DEFAULT_IDS",
    "LINK_IDS",
    "Context",
    "Source",
    "SourceMeta",
    "resolve",
    "describe_table",
]
