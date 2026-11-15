# -*- coding: utf-8 -*-
"""Data model kept deliberately small: one Resource, one SourceStatus."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 资料类型 —— 报告分组与打分都用这一套
KIND_LABELS = {
    "course": "在线课程",
    "video": "视频课",
    "textbook": "开放教材",
    "paper": "论文/预印本",
    "note": "讲义/笔记",
    "qa": "问答/题解",
    "reference": "百科/参考",
    "repo": "代码仓库",
    "dataset": "数据/实验",
    "link": "平台检索入口",
    "web": "网页资料",
}

# 语言 → 展示
LANG_LABELS = {"zh": "中文", "en": "英文", "other": "其他"}


@dataclass
class Resource:
    """A single piece of study material."""

    title: str
    url: str
    source: str  # source id, e.g. "openalex"
    source_label: str = ""  # human label, e.g. "OpenAlex 学术库"
    kind: str = "web"
    lang: str = "other"
    year: Optional[int] = None
    authors: List[str] = field(default_factory=list)
    org: str = ""  # 学校 / 期刊 / UP 主
    description: str = ""  # 元数据里的摘要/简介
    excerpt: str = ""  # 真爬下来的正文摘录
    pdf_url: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    # 状态
    crawled: bool = False
    crawl_status: str = ""  # ok / blocked / not-html / error / skipped
    downloaded: str = ""
    # 打分
    relevance: float = 0.0
    quality: float = 0.0
    score: float = 0.0

    def key(self) -> str:
        return hashlib.sha1((self.url or self.title).encode("utf-8", "replace")).hexdigest()[:16]

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def lang_label(self) -> str:
        return LANG_LABELS.get(self.lang, self.lang)

    def summary(self, width: int = 240) -> str:
        text = self.excerpt or self.description
        text = " ".join(text.split())
        return text[:width] + ("…" if len(text) > width else "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_label": self.source_label,
            "kind": self.kind,
            "kind_label": self.kind_label,
            "lang": self.lang,
            "lang_label": self.lang_label,
            "year": self.year,
            "authors": self.authors,
            "org": self.org,
            "description": self.description,
            "excerpt": self.excerpt,
            "pdf_url": self.pdf_url,
            "extra": self.extra,
            "crawled": self.crawled,
            "crawl_status": self.crawl_status,
            "downloaded": self.downloaded,
            "relevance": round(self.relevance, 4),
            "quality": round(self.quality, 4),
            "score": round(self.score, 2),
        }


@dataclass
class SourceStatus:
    id: str
    label: str
    ok: bool = False
    count: int = 0
    elapsed: float = 0.0
    error: str = ""
    skipped: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "ok": self.ok,
            "count": self.count,
            "elapsed": round(self.elapsed, 2),
            "error": self.error,
            "skipped": self.skipped,
        }


@dataclass
class SearchResult:
    query: str
    core: str
    lang: str
    resources: List[Resource] = field(default_factory=list)
    statuses: List[SourceStatus] = field(default_factory=list)
    link_portals: List[Resource] = field(default_factory=list)
    elapsed: float = 0.0
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "core": self.core,
            "lang": self.lang,
            "elapsed": round(self.elapsed, 2),
            "generated_at": self.generated_at,
            "count": len(self.resources),
            "resources": [r.to_dict() for r in self.resources],
            "portals": [r.to_dict() for r in self.link_portals],
            "sources": [s.to_dict() for s in self.statuses],
        }
