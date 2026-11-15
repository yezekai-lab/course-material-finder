# -*- coding: utf-8 -*-
"""Probe round 2: fix params for failed sources, inspect HTML for SSR data,
and test general web-search backends (DDG / Mojeek / Baidu / Sogou / Bing).

Run: python dev/probe_sources2.py
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
KW = "calculus"


def show(name, r, grep=(), timeout=0):
    body = r.content
    print(f"\n=== {name} | HTTP {r.status_code} | {len(body)}B | {r.headers.get('content-type','')[:40]}")
    text = body.decode(r.encoding or "utf-8", "replace")
    for k in grep:
        hits = text.count(k)
        print(f"    count({k!r}) = {hits}")
        if hits:
            i = text.find(k)
            print("    ctx:", re.sub(r"\s+", " ", text[max(0, i - 60): i + 160])[:220])
    if not grep:
        print("    head:", re.sub(r"\s+", " ", text[:300]))
    return text


def safe(name, url, grep=(), timeout=40, headers=None, **kw):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if headers:
        h.update(headers)
    t0 = time.time()
    try:
        r = requests.get(url, headers=h, timeout=timeout, **kw)
        print(f"[{int((time.time()-t0)*1000)}ms] {name}")
        return show(name, r, grep)
    except Exception as exc:  # noqa: BLE001
        print(f"[{int((time.time()-t0)*1000)}ms] !! {name} FAILED: {type(exc).__name__}: {exc}")
        return None


tasks = [
    ("arxiv https 60s", "https://export.arxiv.org/api/query?search_query=all:calculus&max_results=2",
     ["<entry>"], dict(timeout=60)),
    ("openlibrary retry", "https://openlibrary.org/search.json?q=calculus&limit=2", ["key"], dict(timeout=60)),
    ("gutendex retry", "https://gutendex.com/books/?search=calculus", ["results"], dict(timeout=60)),
    ("unpaywall email", "https://api.unpaywall.org/v2/10.1038/nature12373?email=a@b.com", ["is_oa"], dict(timeout=40)),
    ("semanticscholar retry", "https://api.semanticscholar.org/graph/v1/paper/search?query=calculus&limit=2",
     ["data"], dict(timeout=60)),
    ("openstax v2", "https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&fields=title&limit=2", ["items"], dict(timeout=40)),
    ("openstax books list", "https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&limit=2", ["items"], dict(timeout=40)),
    ("umn otl textbooks", "https://open.umn.edu/opentextbooks/textbooks?q=calculus", ["textbook"], dict(timeout=40)),
    ("ocw api v0", "https://ocw.mit.edu/api/v0/search/?q=calculus", ["results"], dict(timeout=40)),
    ("ocw api v1", "https://ocw.mit.edu/api/v1/search/?q=calculus", ["results"], dict(timeout=40)),
    ("ocw search html", "https://ocw.mit.edu/search/?q=calculus", ["__NEXT_DATA__", "course", "lecture"], dict(timeout=40)),
    ("ddg html", "https://html.duckduckgo.com/html/?q=calculus%20lecture%20notes", ["result__a"], dict(timeout=40)),
    ("ddg lite", "https://lite.duckduckgo.com/lite/?q=calculus%20lecture%20notes", ["result-link"], dict(timeout=40)),
    ("mojeek", "https://www.mojeek.com/search?q=calculus+lecture+notes", ["<a class=\"ob\"", "results-standard"], dict(timeout=40)),
    ("baidu", "https://www.baidu.com/s?wd=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6%E8%AF%BE%E4%BB%B6", ["result c-container", "百度"], dict(timeout=40)),
    ("sogou", "https://www.sogou.com/web?query=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6", ["vrwrap", "result"], dict(timeout=40)),
    ("bing", "https://www.bing.com/search?q=calculus+lecture+notes&setlang=en", ["b_algo"], dict(timeout=40)),
    ("bilibili search html", "https://search.bilibili.com/all?keyword=%E9%AB%98%E6%95%B0", ["__INITIAL_STATE__", "bvid"], dict(timeout=40)),
    ("icourse163 html", "https://www.icourse163.org/search.htm?search=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6",
     ["courseId", "resultList", "__NEXT_DATA__", "初等数学"], dict(timeout=40)),
    ("smartedu html", "https://higher.smartedu.cn/search?keyword=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6",
     ["__NEXT_DATA__", "courseName", "resource"], dict(timeout=40)),
    ("xuetangx html", "https://www.xuetangx.com/search?query=calculus", ["__INITIAL_STATE__", "course"], dict(timeout=40)),
    ("libretexts mw api root", "https://math.libretexts.org/api.php?action=query&list=search&srsearch=derivative&format=json",
     ["query"], dict(timeout=40)),
    ("wikidata search", "https://www.wikidata.org/w/api.php?action=wbsearchentities&search=calculus&language=en&format=json",
     ["search"], dict(timeout=40)),
    ("sciencedirect no", "https://api.openalex.org/sources?search=calculus&per_page=2", ["results"], dict(timeout=40)),
]

with ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(lambda t: safe(t[0], t[1], grep=t[2], **t[3]), tasks))

print("\n\n### arxiv http fallback")
safe("arxiv http", "http://export.arxiv.org/api/query?search_query=all:calculus&max_results=2", ["<entry>"], timeout=60)
