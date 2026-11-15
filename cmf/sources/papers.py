# -*- coding: utf-8 -*-
"""学术层：OpenAlex / Crossref / DOAJ / Zenodo / arXiv / Europe PMC。

用途：课程论文、大作业、竞赛、考研复试找文献。全部为免费开放接口。
OpenAlex 的 abstract_inverted_index 可以直接还原摘要，不用再抓页面。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..models import Resource
from ..query import Query
from ..textutil import strip_html
from .base import Context, Source, SourceMeta


def _openalex_abstract(inv: Any) -> str:
    if not isinstance(inv, dict) or not inv:
        return ""
    pos: Dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs or []:
            pos[int(i)] = word
    if not pos:
        return ""
    return " ".join(pos[i] for i in sorted(pos))


class OpenAlexSource(Source):
    meta = SourceMeta(
        id="openalex",
        label="OpenAlex 学术图谱",
        kind="paper",
        lang="mixed",
        tier="api",
        note="2.5 亿条学术记录，含开放获取链接，中英文通吃",
        ttl=3600,
    )
    API = "https://api.openalex.org/works"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        data = ctx.http.get_json(
            self.API,
            params={
                "search": q.core,
                "per_page": min(ctx.per_source, 25),
                "mailto": "cmf-finder@example.org",
            },
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for w in ((data or {}).get("results") or []):
            title = w.get("display_name") or w.get("title") or ""
            if not title:
                continue
            loc = (w.get("primary_location") or {}).get("source") or {}
            oa = w.get("open_access") or {}
            doi = w.get("doi") or ""
            landing = (w.get("primary_location") or {}).get("landing_page_url") or ""
            # 优先给能直接读的落地页，其次 DOI，最后才是 OpenAlex 自己的条目页
            url = landing or doi or (w.get("id") or "")
            out.append(
                self.make(
                    title=title,
                    url=url,
                    kind="paper",
                    lang="en" if (w.get("language") or "en") == "en" else "other",
                    year=w.get("publication_year"),
                    authors=[
                        ((a.get("author") or {}).get("display_name") or "")
                        for a in (w.get("authorships") or [])
                    ],
                    org=loc.get("display_name") or "",
                    description=_openalex_abstract(w.get("abstract_inverted_index")),
                    pdf_url=oa.get("oa_url") or "",
                    extra={
                        "type": w.get("type"),
                        "citations": w.get("cited_by_count"),
                        "is_oa": oa.get("is_oa"),
                        "doi": doi,
                        "venue": loc.get("display_name"),
                    },
                )
            )
        return out[: ctx.per_source]


class CrossrefSource(Source):
    meta = SourceMeta(
        id="crossref",
        label="Crossref DOI 库",
        kind="paper",
        lang="en",
        tier="api",
        note="期刊/会议论文权威元数据，带 DOI 可直接定位原文",
        ttl=3600,
    )
    API = "https://api.crossref.org/works"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        data = ctx.http.get_json(
            self.API,
            params={
                "query": q.core,
                "rows": min(ctx.per_source, 20),
                "select": "title,DOI,URL,issued,author,container-title,abstract,type,link,is-referenced-by-count",
                "mailto": "cmf-finder@example.org",
            },
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        items = (((data or {}).get("message") or {}).get("items")) or []
        out = []
        for it in items:
            titles = it.get("title") or []
            title = titles[0] if titles else ""
            if not title:
                continue
            issued = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
            year = issued[0] if issued else None
            pdf = ""
            for link in it.get("link") or []:
                if "pdf" in (link.get("content-type") or "").lower():
                    pdf = link.get("URL") or ""
                    break
            doi = it.get("DOI") or ""
            out.append(
                self.make(
                    title=title,
                    url=it.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                    kind="paper",
                    lang="en",
                    year=year,
                    authors=[
                        " ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "")
                        for a in (it.get("author") or [])
                    ],
                    org=((it.get("container-title") or [""])[0]) or "",
                    description=strip_html(it.get("abstract") or ""),
                    pdf_url=pdf,
                    extra={
                        "doi": doi,
                        "type": it.get("type"),
                        "citations": it.get("is-referenced-by-count"),
                    },
                )
            )
        return out[: ctx.per_source]


class DoajSource(Source):
    meta = SourceMeta(
        id="doaj",
        label="DOAJ 开放获取期刊",
        kind="paper",
        lang="en",
        tier="api",
        note="全部可免费下载全文，无付费墙",
        ttl=3600,
    )

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        data = ctx.http.get_json(
            f"https://doaj.org/api/search/articles/{q.core}",
            params={"pageSize": min(ctx.per_source, 20)},
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for r in ((data or {}).get("results") or []):
            bib = r.get("bibjson") or {}
            title = bib.get("title") or ""
            if not title:
                continue
            url = ""
            for link in bib.get("link") or []:
                if (link.get("type") or "").lower() == "fulltext":
                    url = link.get("url") or ""
                    break
            if not url:
                for ident in bib.get("identifier") or []:
                    if (ident.get("type") or "").lower() == "doi":
                        url = f"https://doi.org/{ident.get('id')}"
                        break
            out.append(
                self.make(
                    title=title,
                    url=url or "https://doaj.org/",
                    kind="paper",
                    lang="en",
                    year=bib.get("year"),
                    authors=[a.get("name", "") for a in (bib.get("author") or [])],
                    org=((bib.get("journal") or {}).get("title")) or "",
                    description=strip_html(bib.get("abstract") or ""),
                    extra={"keywords": (bib.get("keywords") or [])[:6]},
                )
            )
        return out[: ctx.per_source]


class ZenodoSource(Source):
    meta = SourceMeta(
        id="zenodo",
        label="Zenodo 开放仓库",
        kind="dataset",
        lang="en",
        tier="api",
        note="课程数据集/实验代码/讲义/预印本，CERN 托管",
        ttl=3600,
    )

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        data = ctx.http.get_json(
            "https://zenodo.org/api/records",
            params={"q": q.core, "size": min(ctx.per_source, 20)},
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for h in (((data or {}).get("hits") or {}).get("hits")) or []:
            md = h.get("metadata") or {}
            title = md.get("title") or ""
            if not title:
                continue
            rtype = ((md.get("resource_type") or {}).get("title")) or ""
            kind = "dataset" if "dataset" in rtype.lower() or "software" in rtype.lower() else "paper"
            pdf = ""
            for f in h.get("files") or []:
                name = (f.get("key") or "").lower()
                if name.endswith(".pdf"):
                    pdf = (f.get("links") or {}).get("self") or ""
                    break
            out.append(
                self.make(
                    title=title,
                    url=((h.get("links") or {}).get("self_html")) or "",
                    kind=kind,
                    lang="en",
                    year=self.year_of(md.get("publication_date")),
                    authors=[c.get("name", "") for c in (md.get("creators") or [])],
                    org="Zenodo",
                    description=strip_html(md.get("description") or ""),
                    pdf_url=pdf,
                    extra={"doi": md.get("doi") or h.get("doi"), "type": rtype},
                )
            )
        return out[: ctx.per_source]


class ArxivSource(Source):
    meta = SourceMeta(
        id="arxiv",
        label="arXiv 预印本",
        kind="paper",
        lang="en",
        tier="api",
        note="数理化/CS/EE 最新预印本（响应可能达 40s，已长超时+缓存）",
        ttl=6 * 3600,
        timeout=60,
    )
    API = "https://export.arxiv.org/api/query"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        core = q.core.strip()
        term = f'all:"{core}"' if " " in core else f"all:{core}"
        text = ctx.http.get_text(
            self.API,
            params={
                "search_query": term,
                "start": 0,
                "max_results": min(ctx.per_source, 20),
                "sortBy": "relevance",
            },
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for chunk in re.findall(r"<entry>(.*?)</entry>", text or "", re.S):
            title = _tag(chunk, "title")
            summary = _tag(chunk, "summary")
            aid = _tag(chunk, "id")
            published = _tag(chunk, "published")
            if not title:
                continue
            pdf = ""
            for link_tag in re.findall(r"<link\b[^>]*>", chunk):
                href = re.search(r'href="([^"]+)"', link_tag)
                if not href:
                    continue
                attrs = link_tag.lower()
                if 'title="pdf"' in attrs or "application/pdf" in attrs:
                    pdf = href.group(1)
                    break
            authors = [_tag(a, "name") for a in re.findall(r"<author>(.*?)</author>", chunk, re.S)]
            out.append(
                self.make(
                    title=re.sub(r"\s+", " ", title),
                    url=aid,
                    kind="paper",
                    lang="en",
                    year=self.year_of(published),
                    authors=authors,
                    org="arXiv",
                    description=re.sub(r"\s+", " ", summary),
                    pdf_url=pdf,
                    extra={"arxiv_id": aid.rsplit("/", 1)[-1] if aid else ""},
                )
            )
        return out[: ctx.per_source]


def _tag(chunk: str, tag: str) -> str:
    m = re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), chunk, re.S)
    return strip_html(m.group(1)) if m else ""


class EuropePmcSource(Source):
    meta = SourceMeta(
        id="europepmc",
        label="Europe PMC 生医文献",
        kind="paper",
        lang="en",
        tier="api",
        note="医学/生命科学/药学课程必备，含开放全文",
        ttl=3600,
    )
    API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        data = ctx.http.get_json(
            self.API,
            params={
                "query": q.core,
                "format": "json",
                "pageSize": min(ctx.per_source, 20),
                "resultType": "core",
            },
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        out = []
        for r in (((data or {}).get("resultList") or {}).get("result")) or []:
            title = strip_html(r.get("title") or "")
            if not title:
                continue
            doi = r.get("doi") or ""
            pmid = r.get("pmid") or ""
            url = ""
            for ft in (((r.get("fullTextUrlList") or {}).get("fullTextUrl")) or []):
                if (ft.get("documentStyle") or "").upper() in ("PDF", "HTML") and ft.get("url"):
                    url = ft["url"]
                    if (ft.get("documentStyle") or "").upper() == "PDF":
                        break
            if not url:
                url = f"https://doi.org/{doi}" if doi else (
                    f"https://europepmc.org/article/MED/{pmid}" if pmid else ""
                )
            pdf = next(
                (
                    ft.get("url")
                    for ft in (((r.get("fullTextUrlList") or {}).get("fullTextUrl")) or [])
                    if (ft.get("documentStyle") or "").upper() == "PDF" and ft.get("availability") == "Open access"
                ),
                "",
            )
            out.append(
                self.make(
                    title=title,
                    url=url,
                    kind="paper",
                    lang="en",
                    year=self.year_of(r.get("pubYear")),
                    authors=[a.strip() for a in (r.get("authorString") or "").split(",") if a.strip()],
                    org=r.get("journalTitle") or "",
                    description=strip_html(r.get("abstractText") or ""),
                    pdf_url=pdf,
                    extra={"doi": doi, "pmid": pmid, "oa": r.get("isOpenAccess")},
                )
            )
        return out[: ctx.per_source]
