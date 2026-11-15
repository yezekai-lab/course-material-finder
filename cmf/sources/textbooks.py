# -*- coding: utf-8 -*-
"""开放教材层：OpenStax、UMN Open Textbook Library、MIT OCW、Wikibooks、公版书。

这一层解决「整门课的教材/讲义从哪来」——都是可合法下载的开放教育资源（OER）。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List

from ..models import Resource
from ..query import Query
from ..textutil import strip_html, tokens
from .base import Context, Source, SourceMeta

# ------------------------------------------------------------------- OpenStax


class OpenStaxSource(Source):
    """OpenStax 只有 129 本教材，全量拉下来本地匹配比「搜索接口」更准。"""

    meta = SourceMeta(
        id="openstax",
        label="OpenStax 开放教材",
        kind="textbook",
        lang="en",
        tier="index",
        note="Rice 大学开放教材，理工/经济/生医覆盖全，可免费下载 PDF",
        ttl=24 * 3600,
    )
    API = "https://openstax.org/apps/cms/api/v2/pages/"

    def _catalogue(self, ctx: Context) -> List[Dict]:
        cached = ctx.extra.get("openstax_catalogue")
        if cached is not None:
            return cached
        books: List[Dict] = []
        offset = 0
        while offset < 400:
            data = ctx.http.get_json(
                self.API,
                params={"type": "books.Book", "limit": 100, "offset": offset, "fields": "title"},
                timeout=self.meta.timeout,
                ttl=self.meta.ttl,
            )
            items = (data or {}).get("items") or []
            books.extend(items)
            total = ((data or {}).get("meta") or {}).get("total_count") or 0
            offset += len(items)
            if not items or offset >= total:
                break
        ctx.extra["openstax_catalogue"] = books
        return books

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        q_tokens = tokens(q.core)
        scored = []
        for b in self._catalogue(ctx):
            meta = b.get("meta") or {}
            title = b.get("title") or ""
            slug = meta.get("slug") or ""
            hay = f"{title} {slug.replace('-', ' ')}"
            overlap = len(q_tokens & tokens(hay))
            if overlap == 0:
                continue
            scored.append((overlap, title, slug, meta.get("html_url") or f"https://openstax.org/details/books/{slug}"))
        scored.sort(key=lambda x: -x[0])
        out = []
        for overlap, title, slug, url in scored[: ctx.per_source]:
            out.append(
                self.make(
                    title=title,
                    url=url,
                    kind="textbook",
                    lang="en",
                    org="OpenStax (Rice University)",
                    description="开放获取大学教材，可在线看、可下 PDF，附习题与教师资源。",
                    extra={"slug": slug, "match": overlap},
                )
            )
        return out


# --------------------------------------------------- UMN Open Textbook Library


class OpenTextbookLibrarySource(Source):
    meta = SourceMeta(
        id="otl",
        label="Open Textbook Library",
        kind="textbook",
        lang="en",
        tier="api",
        note="明尼苏达大学维护的开放教材目录，含评审意见",
        ttl=3600,
    )
    API = "https://open.umn.edu/opentextbooks/textbooks"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        resp = ctx.http.request(
            self.API,
            params={"q": q.core},
            headers={"Accept": "application/atom+xml"},
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out: List[Resource] = []
        body = resp.text or ""
        for chunk in re.findall(r"<entry>(.*?)</entry>", body, re.S):
            title = _xml_text(chunk, "title")
            link = _xml_attr(chunk, "link", "href")
            updated = _xml_text(chunk, "updated")
            summary = _xml_text(chunk, "summary") or _xml_text(chunk, "content")
            if not title or not link:
                continue
            out.append(
                self.make(
                    title=title,
                    url=link,
                    kind="textbook",
                    lang="en",
                    # Atom 的 <updated> 是 feed 时间戳，不是出版年，不能当 year 用
                    org="Open Textbook Library",
                    description=strip_html(summary),
                    extra={"updated": updated},
                )
            )
        return out[: ctx.per_source]


def _xml_text(chunk: str, tag: str) -> str:
    m = re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), chunk, re.S)
    if not m:
        return ""
    raw = m.group(1)
    raw = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", raw, flags=re.S)
    return strip_html(raw)


def _xml_attr(chunk: str, tag: str, attr: str) -> str:
    m = re.search(r"<%s[^>]*\b%s=[\"']([^\"']+)[\"']" % (tag, attr), chunk)
    return m.group(1) if m else ""


# ------------------------------------------------------------------ MIT OCW


class MitOcwSource(Source):
    """MIT OCW 没有公开搜索 API，但 sitemap 索引里列了全部 2500+ 门课。
    抓一次索引（7 天缓存）→ 本地按 slug 里的课程名做关键词匹配。"""

    meta = SourceMeta(
        id="ocw",
        label="MIT OpenCourseWare",
        kind="course",
        lang="en",
        tier="index",
        note="麻省理工全课程公开资料（讲义/习题/考试/录像）",
        ttl=7 * 24 * 3600,
    )
    SITEMAP = "https://ocw.mit.edu/sitemap.xml"

    def _slugs(self, ctx: Context) -> List[str]:
        cached = ctx.extra.get("ocw_slugs")
        if cached is not None:
            return cached
        text = ctx.http.get_text(self.SITEMAP, timeout=60, ttl=self.meta.ttl)
        locs = re.findall(r"<loc>(.*?)</loc>", text)
        slugs = []
        for loc in locs:
            m = re.search(r"/courses/([^/]+)/sitemap\.xml$", loc)
            if m:
                slugs.append(m.group(1))
        ctx.extra["ocw_slugs"] = slugs
        return slugs

    @staticmethod
    def _title_from_slug(slug: str) -> str:
        words = slug.replace("-", " ")
        # 去掉课程编号：res 18 010 a 2020 vision... -> a 2020 vision...
        words = re.sub(r"^(?:res\s+)?(?:\d+[a-z]*\s+)+", "", words, flags=re.I)
        words = re.sub(r"\b(fall|spring|summer|january|iap|winter)\s+\d{4}\b", "", words, flags=re.I)
        words = re.sub(r"\s+", " ", words).strip(" -")
        return words.title() if words.isascii() else words

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        q_tokens = tokens(q.core) | tokens(q.raw)
        scored = []
        for slug in self._slugs(ctx):
            hay = slug.replace("-", " ")
            overlap = len(q_tokens & tokens(hay))
            if overlap:
                scored.append((overlap, slug))
        scored.sort(key=lambda x: -x[0])
        out = []
        seen = set()
        for overlap, slug in scored:
            if slug in seen:
                continue
            seen.add(slug)
            out.append(
                self.make(
                    title=self._title_from_slug(slug),
                    url=f"https://ocw.mit.edu/courses/{slug}/",
                    kind="course",
                    lang="en",
                    year=self.year_of(slug),
                    org="MIT OpenCourseWare",
                    description="麻省理工公开课：含课程讲义、作业、考试与部分录像，CC BY-NC-SA 授权。",
                    extra={"slug": slug, "match": overlap},
                )
            )
            if len(out) >= ctx.per_source:
                break
        return out


# ----------------------------------------------------------------- Wikibooks


class WikibooksSource(Source):
    meta = SourceMeta(
        id="wikibooks",
        label="维基教科书",
        kind="textbook",
        lang="zh",
        tier="api",
        note="协作编写的开放教材，中文覆盖数理化与计算机基础",
        ttl=24 * 3600,
    )

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        host = "zh.wikibooks.org" if q.is_zh else "en.wikibooks.org"
        data = ctx.http.get_json(
            f"https://{host}/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": q.core,
                "srlimit": min(ctx.per_source, 20),
                "srprop": "snippet|timestamp|wordcount",
                "format": "json",
                "formatversion": 2,
            },
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        items = (((data or {}).get("query") or {}).get("search")) or []
        out = []
        for it in items:
            title = it.get("title") or ""
            out.append(
                self.make(
                    title=title,
                    url=f"https://{host}/wiki/{title.replace(' ', '_')}",
                    kind="textbook",
                    lang="zh" if q.is_zh else "en",
                    org="Wikibooks",
                    description=strip_html(it.get("snippet") or ""),
                    extra={"words": it.get("wordcount")},
                )
            )
        return out


# ------------------------------------------------------------------- Gutendex


class GutendexSource(Source):
    meta = SourceMeta(
        id="gutendex",
        label="Project Gutenberg 公版书",
        kind="textbook",
        lang="en",
        tier="api",
        enabled=False,
        note="公版经典全文（文学/哲学/科学史课程读物）；实测常超时，默认关闭，需要时 --sources gutendex",
        ttl=24 * 3600,
        timeout=45,
    )

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        data = ctx.http.get_json(
            "https://gutendex.com/books",
            params={"search": q.core},
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for b in ((data or {}).get("results") or [])[: ctx.per_source]:
            formats = b.get("formats") or {}
            html_url = formats.get("text/html") or formats.get("text/html; charset=utf-8")
            pdf_url = formats.get("application/pdf")
            out.append(
                self.make(
                    title=b.get("title") or "",
                    url=html_url or f"https://www.gutenberg.org/ebooks/{b.get('id')}",
                    kind="textbook",
                    lang="en",
                    org="Project Gutenberg",
                    authors=[a.get("name", "") for a in (b.get("authors") or [])],
                    pdf_url=pdf_url or "",
                    description="公版全文（可整本下载，适合文学/思想史课程原典阅读）。",
                    extra={
                        "downloads": b.get("download_count"),
                        "subjects": (b.get("subjects") or [])[:5],
                        "gutenberg_id": b.get("id"),
                    },
                )
            )
        return out
