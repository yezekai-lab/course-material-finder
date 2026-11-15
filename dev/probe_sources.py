# -*- coding: utf-8 -*-
"""Probe candidate data sources: reachability, format, latency.

Run:  python dev/probe_sources.py [--json]
Kept in-repo so the source list can be re-validated when upstreams change.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 CourseMaterialFinder/1.0"
)

PROBES = [
    # name, url, kind(json/html/xml), note
    ("openalex", "https://api.openalex.org/works?search=calculus&per_page=2", "json"),
    ("arxiv", "http://export.arxiv.org/api/query?search_query=all:calculus&max_results=2", "xml"),
    (
        "semanticscholar",
        "https://api.semanticscholar.org/graph/v1/paper/search?query=calculus&limit=2"
        "&fields=title,year,url,openAccessPdf",
        "json",
    ),
    ("openlibrary", "https://openlibrary.org/search.json?q=calculus&limit=2", "json"),
    ("crossref", "https://api.crossref.org/works?query=calculus&rows=2", "json"),
    ("zenodo", "https://zenodo.org/api/records?q=calculus&size=2", "json"),
    ("doab", "https://directory.doabooks.org/rest/search?query=calculus&size=2", "json"),
    ("doaj", "https://doaj.org/api/search/articles/calculus?pageSize=2", "json"),
    ("gutendex", "https://gutendex.com/books?search=calculus", "json"),
    (
        "googlebooks",
        "https://www.googleapis.com/books/v1/volumes?q=calculus&maxResults=2",
        "json",
    ),
    (
        "wikipedia_zh",
        "https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch=%E5%BE%AE%E7%A7%AF%E5%88%86"
        "&format=json&srlimit=2",
        "json",
    ),
    (
        "stackexchange",
        "https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance"
        "&q=dynamic+programming&site=stackoverflow&pagesize=2",
        "json",
    ),
    ("unpaywall", "https://api.unpaywall.org/v2/10.1038/nature12373?email=probe@example.com", "json"),
    (
        "pubmed",
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=calculus&retmode=json",
        "json",
    ),
    ("mittocw_html", "https://ocw.mit.edu/search/?q=calculus", "html"),
    (
        "openstax",
        "https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&fields=title,webview_url&limit=2",
        "json",
    ),
    ("opentextbooklib", "https://open.umn.edu/opentextbooks/search?q=calculus", "html"),
    (
        "libretexts",
        "https://math.libretexts.org/api.php?action=query&list=search&srsearch=derivative&format=json&srlimit=2",
        "json",
    ),
    (
        "bilibili",
        "https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=%E9%AB%98%E6%95%B0",
        "json",
    ),
    ("icourse163_html", "https://www.icourse163.org/search.htm?search=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6", "html"),
    ("xuetangx_html", "https://www.xuetangx.com/search?query=%E9%AB%98%E6%95%B0", "html"),
    ("smartedu_html", "https://higher.smartedu.cn/search?keyword=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6", "html"),
    ("wikibooks_zh", "https://zh.wikibooks.org/w/api.php?action=query&list=search&srsearch=%E5%BE%AE%E7%A7%AF%E5%88%86&format=json", "json"),
    ("openalex_zh", "https://api.openalex.org/works?search=%E5%BE%AE%E7%A7%AF%E5%88%86&per_page=2", "json"),
]


def probe(item):
    name, url, kind = item
    heads = {
        "User-Agent": UA,
        "Accept": "application/json,text/html,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    t0 = time.time()
    try:
        r = requests.get(url, headers=heads, timeout=25)
        ms = int((time.time() - t0) * 1000)
        body = r.content
        ok = 200 <= r.status_code < 300
        detail = ""
        if ok and kind == "json":
            try:
                j = r.json()
                detail = type(j).__name__ + " keys=" + ",".join(list(j)[:5]) if isinstance(j, dict) else type(j).__name__
            except Exception as exc:  # noqa: BLE001
                ok = False
                detail = f"json-parse-fail {exc}"
        elif ok:
            text = body.decode(r.encoding or "utf-8", "replace")
            detail = f"{len(body)}B {r.headers.get('content-type','')[:40]}"
            if len(body) < 800:
                ok = False
                detail += " (too small)"
        return {
            "name": name,
            "status": r.status_code,
            "ms": ms,
            "ok": ok,
            "bytes": len(body),
            "ctype": r.headers.get("content-type", "")[:50],
            "detail": detail[:160],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "status": None,
            "ms": int((time.time() - t0) * 1000),
            "ok": False,
            "bytes": 0,
            "ctype": "",
            "detail": f"{type(exc).__name__}: {exc}"[:160],
        }


def main():
    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(probe, p): p[0] for p in PROBES}
        for fut in as_completed(futures):
            rows.append(fut.result())
    rows.sort(key=lambda r: (not r["ok"], r["name"]))
    if "--json" in sys.argv:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print(f"{'SOURCE':<18}{'OK':<4}{'STATUS':<8}{'MS':<7}{'BYTES':<9}DETAIL")
    for r in rows:
        mark = "OK" if r["ok"] else "FAIL"
        print(
            f"{r['name']:<18}{mark:<4}{str(r['status']):<8}{r['ms']:<7}{r['bytes']:<9}{r['detail']}"
        )
    ok = sum(1 for r in rows if r["ok"])
    print(f"\n{ok}/{len(rows)} reachable")


if __name__ == "__main__":
    main()
