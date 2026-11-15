# -*- coding: utf-8 -*-
"""通用搜索引擎层：抓结果页。

必应 = 英文/全球覆盖，百度 = 中文覆盖。两者都是把结果渲染在 HTML 里的
（实测 1.3MB 的服务端直出页面），所以能爬；但都需要低频 + 百度还要 cookie 预热。
广告位（百度 ec-pc-* 容器）会被过滤掉。
"""
from __future__ import annotations

import re
from typing import List
from urllib.parse import quote_plus

from ..models import Resource
from ..query import Query
from ..textutil import strip_html
from .base import Context, Source, SourceMeta


def _round_robin(batches: List[List[Resource]], limit: int) -> List[Resource]:
    """几条查询的结果轮流取，避免第一条（往往是课名本身）占满名额。"""
    out: List[Resource] = []
    seen = set()
    idx = 0
    progressed = True
    while len(out) < limit and progressed:
        progressed = False
        for batch in batches:
            if idx >= len(batch):
                continue
            progressed = True
            item = batch[idx]
            key = item.url or item.title
            if key not in seen:
                seen.add(key)
                out.append(item)
                if len(out) >= limit:
                    break
        idx += 1
    return out


def _search_pages(src: Source, q: Query, ctx: Context, fetch_html, parse) -> List[Resource]:
    """用户写了意图就搜这一条；只输课名时按习题/真题/讲义/题解扩展。

    扩展查询失败不影响已经拿到的主查询。付费站不在这里，它们只走 portals。
    """
    batches: List[List[Resource]] = []
    for i, term in enumerate(q.engine_queries()):
        timeout = src.meta.timeout if i == 0 else min(12.0, src.meta.timeout)
        try:
            html = fetch_html(term, timeout)
        except Exception:
            if i == 0:
                raise
            break
        batches.append(parse(html, src, ctx))
    return _round_robin(batches, ctx.per_source)


class BingSource(Source):
    meta = SourceMeta(
        id="bing",
        label="必应网页搜索",
        kind="web",
        lang="mixed",
        tier="engine",
        note="抓取结果页，覆盖笔记站/课程主页/论坛贴；只输课名时会追加习题/真题/讲义/题解",
        ttl=1800,
    )
    API = "https://www.bing.com/search"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        def fetch_html(term: str, timeout: float) -> str:
            params = {"q": term, "count": max(ctx.per_source * 2, 20), "setlang": "zh-hans" if q.is_zh else "en"}
            return ctx.http.get_text(self.API, params=params, timeout=timeout, ttl=self.meta.ttl)

        return _search_pages(self, q, ctx, fetch_html, _parse_bing)


def _parse_bing(html: str, src: Source, ctx: Context) -> List[Resource]:
    out: List[Resource] = []
    if not html:
        return out
    starts = [m.start() for m in re.finditer(r'<li class="b_algo"', html)]
    ends = [m.start() for m in re.finditer(r'<li class="b_(?:pag|ans|algo)', html)]
    for i, s in enumerate(starts):
        nxt = next((e for e in ends if e > s), len(html))
        block = html[s:nxt]
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url, title = m.group(1), strip_html(m.group(2))
        if not title or url.startswith("https://www.bing.com") or "javascript:" in url:
            continue
        snippet = ""
        sm = re.search(r'<p class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>', block, re.S)
        if not sm:
            sm = re.search(r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', block, re.S)
        if sm:
            snippet = strip_html(sm.group(1))
        out.append(
            src.make(
                title=title,
                url=url,
                kind="web",
                lang="zh" if re.search(r"[\u4e00-\u9fff]", title) else "en",
                description=snippet,
                extra={"engine": "bing"},
            )
        )
        if len(out) >= ctx.per_source:
            break
    return out


class BaiduSource(Source):
    meta = SourceMeta(
        id="baidu",
        label="百度网页搜索",
        kind="web",
        lang="zh",
        tier="engine",
        note="中文资源覆盖最广；需 cookie 预热，广告位已过滤。只输课名时追加习题/真题/讲义/题解",
        ttl=1800,
        timeout=35,
    )
    API = "https://www.baidu.com/s"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        def fetch_html(term: str, timeout: float) -> str:
            return ctx.http.get_text(
                self.API,
                params={"wd": term, "rn": max(ctx.per_source * 2, 20)},
                headers={"Referer": "https://www.baidu.com/"},
                warmup="https://www.baidu.com/",
                timeout=timeout,
                ttl=self.meta.ttl,
            )

        return _search_pages(self, q, ctx, fetch_html, _parse_baidu)


def _parse_baidu(html: str, src: Source, ctx: Context) -> List[Resource]:
    out: List[Resource] = []
    if not html or ("安全验证" in html and "c-container" not in html):
        return out
    positions = [m.start() for m in re.finditer(r'<div[^>]*class="[^"]*\bc-container\b[^"]*"', html)]
    for i, s in enumerate(positions):
        nxt = positions[i + 1] if i + 1 < len(positions) else min(len(html), s + 30000)
        block = html[s:nxt]
        cls_m = re.search(r'class="([^"]*)"', block[:300])
        cls = cls_m.group(1) if cls_m else ""
        if "ec-pc" in cls or "ec_ad" in cls:  # 广告位
            continue
        h3 = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        if not h3:
            continue
        title = strip_html(h3.group(1))
        if not title:
            continue
        mu = re.search(r'\bmu="([^"]+)"', block)
        href = re.search(r'<a[^>]*href="(https?://[^"]+)"', h3.group(1)) or re.search(
            r'<a[^>]*href="(https?://[^"]+)"', block
        )
        url = (mu.group(1) if mu else (href.group(1) if href else ""))
        if not url or "baidu.com" in url and "/link?" in url:
            # 百度跳转链接仍可用（浏览器会 302），保留
            pass
        snippet = ""
        sm = re.search(r'<span class="[^"]*content-right[^"]*"[^>]*>(.*?)</span>', block, re.S)
        if sm:
            snippet = strip_html(sm.group(1))
        if not snippet:
            body = strip_html(block)
            snippet = body.replace(title, " ", 1).strip()[:400]
        out.append(
            src.make(
                title=title,
                url=url,
                kind="web",
                lang="zh",
                description=snippet,
                extra={"engine": "baidu"},
            )
        )
        if len(out) >= ctx.per_source:
            break
    return out


class SogouSource(Source):
    """搜狗结果页 JS 壳较重，仅作为可选补充（默认关闭）。"""

    meta = SourceMeta(
        id="sogou",
        label="搜狗网页搜索",
        kind="web",
        lang="zh",
        tier="engine",
        enabled=False,
        note="结果页为 JS 渲染，抽取率低，默认关闭",
        ttl=1800,
    )
    API = "https://www.sogou.com/web"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        def fetch_html(term: str, timeout: float) -> str:
            return ctx.http.get_text(
                self.API,
                params={"query": term},
                warmup="https://www.sogou.com/",
                timeout=timeout,
                ttl=self.meta.ttl,
            )

        def parse(html: str, src: Source, ctx: Context) -> List[Resource]:
            out = []
            for m in re.finditer(
                r'<h3[^>]*class="vr-title"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                html or "",
                re.S,
            ):
                title = strip_html(m.group(2))
                if not title:
                    continue
                url = m.group(1)
                if url.startswith("/link?"):
                    url = "https://www.sogou.com" + url
                out.append(src.make(title=title, url=url, kind="web", lang="zh"))
            return out[: ctx.per_source]

        return _search_pages(self, q, ctx, fetch_html, parse)


def portal_query_url(base: str, q: str) -> str:
    return base.format(q=quote_plus(q))
