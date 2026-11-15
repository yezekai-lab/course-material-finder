# -*- coding: utf-8 -*-
"""Source base class + shared helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..http import HttpClient
from ..models import Resource
from ..query import Query
from ..textutil import strip_html


@dataclass
class SourceMeta:
    id: str
    label: str  # 中文展示名
    kind: str  # 默认资料类型
    lang: str  # zh / en / mixed
    tier: str  # api / engine / index / link
    enabled: bool = True
    note: str = ""
    timeout: float = 30.0
    ttl: float = 3600.0  # 结果缓存时长（秒），0 = 不缓存


class Context:
    """Everything a source needs, injected (no globals, easy to test)."""

    def __init__(self, http: HttpClient, per_source: int = 12, verbose: bool = False):
        self.http = http
        self.per_source = per_source
        self.verbose = verbose
        self.extra: Dict[str, Any] = {}


class Source:
    meta: SourceMeta

    # ------------------------------------------------------------------ helpers
    def make(self, **kw) -> Resource:
        kw.setdefault("source", self.meta.id)
        kw.setdefault("source_label", self.meta.label)
        kw.setdefault("kind", self.meta.kind)
        if not kw.get("lang"):
            kw["lang"] = self.meta.lang
        title = strip_html(kw.get("title") or "")
        kw["title"] = " ".join(title.split()) or "(无标题)"
        desc = strip_html(kw.get("description") or "")
        kw["description"] = " ".join(desc.split())[:1500]
        return Resource(**kw)

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------- utils
    @staticmethod
    def clean_authors(raw: Optional[List[str]], limit: int = 4) -> List[str]:
        out = []
        for a in raw or []:
            a = " ".join(str(a or "").split())
            if a:
                out.append(a)
        return out[:limit]

    @staticmethod
    def year_of(value: Any) -> Optional[int]:
        if not value:
            return None
        import re

        m = re.search(r"(1[89]\d{2}|20\d{2})", str(value))
        return int(m.group(1)) if m else None
