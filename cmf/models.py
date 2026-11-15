# -*- coding: utf-8 -*-
"""Data model kept deliberately small: one Resource, one SourceStatus."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 资料类型。打分用具体 kind；kind_family 只用于展示和筛选。
# 学习向在前，教材/官方次之，其余在后。筛选与导出都按这个顺序。
STUDY_KINDS = [
    "exercise", "exam", "solution", "review", "explanation",
    "note", "slides", "video", "qa",
]
CANONICAL_KINDS = ["textbook", "official", "course"]
OTHER_KINDS = ["paper", "reference", "repo", "dataset", "web", "link"]
KIND_ORDER = STUDY_KINDS + CANONICAL_KINDS + OTHER_KINDS

KIND_LABELS = {
    "exercise": "习题/作业",
    "exam": "真题/试卷",
    "solution": "题解/答案",
    "review": "复习/考点",
    "explanation": "讲解",
    "note": "讲义/笔记",
    "slides": "课件",
    "video": "视频课",
    "qa": "问答",
    "textbook": "教材",
    "official": "官方文档",
    "course": "在线课程",
    "paper": "论文/预印本",
    "reference": "百科/参考",
    "repo": "代码仓库",
    "dataset": "数据/实验",
    "web": "网页资料",
    "link": "平台检索入口",
}

KIND_FAMILY = {k: "study" for k in STUDY_KINDS}
KIND_FAMILY.update({k: "canonical" for k in CANONICAL_KINDS})
KIND_FAMILY.update({k: "other" for k in OTHER_KINDS})

FAMILY_LABELS = {
    "study": "学习向",
    "canonical": "教材/官方",
    "other": "其他",
}

FAMILY_SECTION = {
    "study": "学习向资料",
    "canonical": "教材与官方文档",
    "other": "其他",
}

# 语言 → 展示
LANG_LABELS = {"zh": "中文", "en": "英文", "other": "其他"}


def kind_family_of(kind: str) -> str:
    return KIND_FAMILY.get(kind or "", "other")


def kind_family_label_of(kind: str) -> str:
    return FAMILY_LABELS.get(kind_family_of(kind), "其他")


def family_counts(resources: List["Resource"]) -> Dict[str, int]:
    """三组计数。link 不进主结果，这里也不计。"""
    counts = {"study": 0, "canonical": 0, "other": 0}
    for r in resources:
        if r.kind == "link":
            continue
        fam = kind_family_of(r.kind)
        counts[fam] = counts.get(fam, 0) + 1
    return counts


def family_count_line(resources: List["Resource"]) -> str:
    c = family_counts(resources)
    return f"学习向 {c['study']} · 教材/官方 {c['canonical']} · 其他 {c['other']}"


def present_kinds(resources: List["Resource"]) -> List[tuple]:
    """筛选顺序：学习向（有结果的）→ 教材/官方 → 其他。"""
    have = {}
    for r in resources:
        have.setdefault(r.kind, KIND_LABELS.get(r.kind, r.kind))
    ordered = [(k, have[k]) for k in KIND_ORDER if k in have]
    ordered += [(k, label) for k, label in have.items() if k not in KIND_ORDER]
    return ordered


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
    def kind_family(self) -> str:
        return kind_family_of(self.kind)

    @property
    def kind_family_label(self) -> str:
        return FAMILY_LABELS.get(self.kind_family, "其他")

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
            "kind_family": self.kind_family,
            "kind_family_label": self.kind_family_label,
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
