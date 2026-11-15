# -*- coding: utf-8 -*-
"""抓正文：把「搜索结果」变成「读得到的内容」。

做三件事：
  1. 逐条访问结果页，抽 title / meta description / 正文前 1200 字；
  2. 识别 PDF 直链（并可按需下载到本地）；
  3. 对只有 DOI 的论文，用 Unpaywall 找**合法**开放获取 PDF。
反爬/登录墙不硬刚：标记 crawl_status=blocked，报告里如实写「仅链接」。
"""
from __future__ import annotations

import logging

from pathlib import Path
from typing import Iterable, List, Optional

import requests

from .http import FetchError, HttpClient
from .models import Resource
from .textutil import extract_main_text, page_description, page_title, safe_filename

log = logging.getLogger("cmf.enrich")

REDIRECT_HOSTS = ("baidu.com/link", "www.bing.com/ck/", "sogou.com/link")


def _is_pdf(url: str, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if "application/pdf" in ct or "application/octet-stream" in ct and url.lower().split("?")[0].endswith(".pdf"):
        return True
    return url.lower().split("?")[0].endswith(".pdf")


def _title_coverage(text: str, title: str) -> float:
    """正文和标题的词重合比例——用来判断「抽到的这段是不是这页的正文」。"""
    from .textutil import tokens

    t = tokens(title)
    if not t or not text:
        return 0.0
    return len(t & tokens(text)) / len(t)


def _pick_excerpt(body: str, desc: str, title: str) -> str:
    """B站/知乎这类页面的推荐位会淹没正文，按「标题词重合度」在两个候选里选。"""
    body_cov = _title_coverage(body, title)
    desc_cov = _title_coverage(desc, title)
    if desc and len(desc) >= 40 and desc_cov > body_cov:
        return desc
    return body if len(body) >= 40 else (desc or body)


def crawl_one(res: Resource, http: HttpClient, timeout: float = 20.0) -> Resource:
    url = res.url or ""
    if not url.startswith("http"):
        res.crawl_status = "skipped"
        return res
    try:
        resp = http.get_page(url, timeout=timeout)
    except FetchError as exc:
        status = exc.status
        if status in (401, 403, 412, 429):
            res.crawl_status = "blocked"
        elif status == 404:
            res.crawl_status = "not-found"
        else:
            res.crawl_status = "error"
        res.extra["crawl_error"] = str(exc)[:160]
        return res
    except Exception as exc:  # noqa: BLE001
        res.crawl_status = "error"
        res.extra["crawl_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return res

    ctype = resp.headers.get("content-type", "")
    # 跟随跳转后的真实地址（百度/必应的跳转链接会被还原成目标站）
    if resp.url and resp.url != url and not any(h in url for h in REDIRECT_HOSTS):
        if resp.url.startswith("http") and "baidu.com/link" not in resp.url:
            res.extra.setdefault("resolved_from", url)
            res.url = resp.url

    if _is_pdf(url, ctype):
        res.pdf_url = res.pdf_url or res.url
        res.crawl_status = "pdf"
        res.extra["content_type"] = "pdf"
        return res
    if "html" not in ctype.lower() and "xml" not in ctype.lower() and ctype:
        res.crawl_status = "not-html"
        res.extra["content_type"] = ctype[:60]
        return res

    html = resp.text or ""
    if not html:
        res.crawl_status = "empty"
        return res
    title = page_title(html)
    desc = page_description(html)
    body = extract_main_text(html, 1400)
    res.crawled = True
    res.crawl_status = "ok"
    if title and len(title) > 3:
        res.extra.setdefault("page_title", title)
    # 视频页的 meta description 是「相关视频」堆出来的噪音，不能覆盖接口给的简介
    if res.kind != "video" and desc and len(desc) > len(res.description):
        res.description = desc
    if res.kind == "video":
        # B 站整页 DOM 都是别人的推荐标题，摘了就是噪音；只用接口简介，没有就不显示
        res.excerpt = res.description if len(res.description or "") >= 20 else ""
    elif body or desc:
        res.excerpt = _pick_excerpt(body, desc, f"{res.title} {res.org}")
    if not res.description and res.excerpt:
        res.description = res.excerpt[:400]
    return res


def crawl_pages(
    resources: Iterable[Resource],
    http: HttpClient,
    limit: int = 12,
    timeout: float = 20.0,
) -> int:
    """并发抓取前 limit 条（只抓有 http 链接、非「仅链接」条目）。

    走 run_with_deadline：卡住的页面到点就放弃，不拖死整次检索。
    """
    from .concurrent import Deadline, run_with_deadline

    targets = [r for r in resources if (r.url or "").startswith("http") and r.kind != "link"][:limit]
    if not targets:
        return 0
    dl = http.deadline or Deadline(None)

    def work(res: Resource) -> Resource:
        return crawl_one(res, http, min(timeout, dl.clamp(timeout)))

    run_with_deadline(work, targets, deadline=dl)
    ok = 0
    for r in targets:
        if r.crawled or r.crawl_status == "pdf":
            ok += 1
        elif not r.crawl_status:
            r.crawl_status = "timeout"
    return ok


def enrich_abstracts(resources: Iterable[Resource], http: HttpClient, cap: int = 10) -> int:
    """没摘要只有 DOI 的论文：用 OpenAlex 单条接口补摘要（比抓出版商页便宜）。"""
    fill = [
        r
        for r in resources
        if r.kind == "paper" and not r.description and (r.extra.get("doi") or "")
    ][:cap]
    filled = 0
    for r in fill:
        doi = str(r.extra.get("doi") or "").replace("https://doi.org/", "")
        if not doi:
            continue
        try:
            data = http.get_json(
                f"https://api.openalex.org/works/https://doi.org/{doi}",
                params={"mailto": "cmf-finder@example.org"},
                timeout=20,
                ttl=7 * 24 * 3600,
                retries=0,
            )
        except Exception:  # noqa: BLE001
            continue
        inv = (data or {}).get("abstract_inverted_index")
        if not inv:
            continue
        pos = {}
        for word, idxs in inv.items():
            for i in idxs or []:
                pos[int(i)] = word
        abstract = " ".join(pos[i] for i in sorted(pos))
        if abstract:
            r.description = abstract[:1500]
            filled += 1
    return filled


def resolve_oa_pdfs(resources: Iterable[Resource], http: HttpClient, cap: int = 6) -> int:
    """只有 DOI、没有全文链接的论文：查 Unpaywall 的合法 OA 副本。"""
    targets = [
        r for r in resources if r.kind == "paper" and not r.pdf_url and r.extra.get("doi")
    ][:cap]
    got = 0
    for r in targets:
        doi = str(r.extra.get("doi") or "").replace("https://doi.org/", "").strip()
        if not doi:
            continue
        try:
            data = http.get_json(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": "cmf-finder@b.com"},
                timeout=20,
                ttl=7 * 24 * 3600,
                retries=0,
            )
        except Exception:  # noqa: BLE001
            continue
        best = (data or {}).get("best_oa_location") or {}
        url = best.get("url_for_pdf") or best.get("url")
        if url:
            r.pdf_url = url
            r.extra["oa_resolved"] = True
            got += 1
    return got


def download_pdfs(
    resources: Iterable[Resource],
    http: HttpClient,
    out_dir: Path,
    max_bytes: int = 60 * 1024 * 1024,
    cap: int = 6,
    verbose: bool = False,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    got = 0
    session = requests.Session()
    session.headers.update({"User-Agent": http._session().headers.get("User-Agent", "cmf/1.0")})
    for r in [x for x in resources if x.pdf_url][:cap]:
        if http.deadline is not None and http.deadline.expired():
            break
        name = safe_filename(r.title, 70) or "material"
        dest = out_dir / f"{name}.pdf"
        if dest.exists() and dest.stat().st_size > 1024:
            r.downloaded = str(dest)
            got += 1
            continue
        try:
            with session.get(r.pdf_url, stream=True, timeout=45, allow_redirects=True) as resp:
                if resp.status_code != 200:
                    continue
                ctype = resp.headers.get("content-type", "").lower()
                if "pdf" not in ctype and not r.pdf_url.lower().endswith(".pdf"):
                    continue
                written = 0
                tmp = dest.with_suffix(".part")
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(65536):
                        written += len(chunk)
                        if written > max_bytes:
                            raise RuntimeError("超过大小上限")
                        fh.write(chunk)
                tmp.replace(dest)
                r.downloaded = str(dest)
                got += 1
                if verbose:
                    log.info("downloaded %s (%.1f MB)", dest.name, written / 1e6)
        except Exception as exc:  # noqa: BLE001
            log.debug("download failed %s: %s", r.pdf_url, exc)
            for junk in (dest.with_suffix(".part"),):
                if junk.exists():
                    junk.unlink(missing_ok=True)
    return got


def enrich(
    resources: List[Resource],
    http: HttpClient,
    crawl_limit: int = 12,
    download_dir: Optional[Path] = None,
    verbose: bool = False,
    resolve_oa: bool = True,
) -> dict:
    stats = {"crawled": 0, "abstracts": 0, "oa_pdf": 0, "downloaded": 0}
    stats["crawled"] = crawl_pages(resources, http, limit=crawl_limit)
    if resolve_oa:
        stats["abstracts"] = enrich_abstracts(resources, http, cap=8)
        stats["oa_pdf"] = resolve_oa_pdfs(resources, http, cap=6)
    if download_dir:
        stats["downloaded"] = download_pdfs(resources, http, Path(download_dir), verbose=verbose)
    return stats
