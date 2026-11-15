# -*- coding: utf-8 -*-
"""百科 / 问答 / 代码仓库层：Wikipedia、Stack Exchange、GitHub。"""
from __future__ import annotations

import re
from typing import List

from ..models import Resource
from ..query import Query
from ..textutil import strip_html
from .base import Context, Source, SourceMeta

# Stack Exchange 站点选择：课程不同，问答站不同（值即 API 的 site 参数）
_SE_SITES = [
    (("数学", "微积分", "线性代数", "概率论", "数分", "高代", "calculus", "linear algebra", "math", "topology"), "math.stackexchange"),
    (("物理", "力学", "电磁", "量子", "热力学", "physics", "mechanics"), "physics.stackexchange"),
    (("化学", "有机化学", "无机化学", "chemistry"), "chemistry.stackexchange"),
    (("经济", "金融", "economics"), "economics.stackexchange"),
    (("统计", "statistics"), "stats.stackexchange"),
    (("生物", "biology"), "biology.stackexchange"),
]


class WikipediaSource(Source):
    meta = SourceMeta(
        id="wikipedia",
        label="维基百科",
        kind="reference",
        lang="zh",
        tier="api",
        note="概念、定义、发展史与参考文献入口，适合先建立框架",
        ttl=7 * 24 * 3600,
    )

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        host = "zh.wikipedia.org" if q.is_zh else "en.wikipedia.org"
        data = ctx.http.get_json(
            f"https://{host}/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": q.core,
                "srlimit": min(ctx.per_source, 15),
                "srprop": "snippet|wordcount|timestamp",
                "format": "json",
                "formatversion": 2,
            },
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for it in (((data or {}).get("query") or {}).get("search")) or []:
            title = it.get("title") or ""
            out.append(
                self.make(
                    title=title,
                    url=f"https://{host}/wiki/{title.replace(' ', '_')}",
                    kind="reference",
                    lang="zh" if q.is_zh else "en",
                    org="Wikipedia",
                    description=strip_html(it.get("snippet") or ""),
                    extra={"words": it.get("wordcount"), "timestamp": it.get("timestamp")},
                )
            )
        return out


class StackExchangeSource(Source):
    meta = SourceMeta(
        id="stackexchange",
        label="Stack Exchange 问答",
        kind="qa",
        lang="en",
        tier="api",
        note="按课程类型自动选站（数学/物理/化学/经济/统计/SO）",
        ttl=3600,
    )

    @staticmethod
    def _pick_site(q: Query) -> str:
        low = q.raw.lower()
        for keys, site in _SE_SITES:
            if any(k.lower() in low for k in keys):
                return site
        return "stackoverflow"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        site_name = self._pick_site(q)
        data = ctx.http.get_json(
            "https://api.stackexchange.com/2.3/search/advanced",
            params={
                "order": "desc",
                "sort": "relevance",
                "q": q.core,
                "site": site_name,
                "pagesize": min(ctx.per_source, 20),
                "filter": "withbody",
            },
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for it in ((data or {}).get("items") or []):
            title = strip_html(it.get("title") or "")
            if not title:
                continue
            out.append(
                self.make(
                    title=title,
                    url=it.get("link") or "",
                    kind="qa",
                    lang="en",
                    org=site_name,
                    authors=[(it.get("owner") or {}).get("display_name") or ""],
                    description=strip_html(it.get("body") or ""),
                    extra={
                        "score": it.get("score"),
                        "answers": it.get("answer_count"),
                        "accepted": it.get("is_answered"),
                        "tags": it.get("tags"),
                    },
                )
            )
        return out


class GitHubSource(Source):
    meta = SourceMeta(
        id="github",
        label="GitHub 仓库",
        kind="repo",
        lang="en",
        tier="api",
        note="课程笔记/习题解答/awesome 清单（未认证限 10 次/分，已重缓存）",
        ttl=12 * 3600,
    )

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        data = ctx.http.get_json(
            "https://api.github.com/search/repositories",
            params={
                "q": f"{q.core} in:name,description,readme",
                "sort": "stars",
                "order": "desc",
                "per_page": min(ctx.per_source, 20),
            },
            headers={"Accept": "application/vnd.github+json"},
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for it in ((data or {}).get("items") or []):
            name = it.get("full_name") or ""
            if not name:
                continue
            desc = it.get("description") or ""
            out.append(
                self.make(
                    title=name,
                    url=it.get("html_url") or "",
                    kind="repo",
                    lang="en" if not re.search(r"[\u4e00-\u9fff]", desc) else "zh",
                    year=self.year_of(it.get("updated_at")),
                    org=(it.get("owner") or {}).get("login") or "",
                    description=desc,
                    extra={
                        "stars": it.get("stargazers_count"),
                        "language": it.get("language"),
                        "topics": (it.get("topics") or [])[:6],
                        "forks": it.get("forks_count"),
                    },
                )
            )
        return out
