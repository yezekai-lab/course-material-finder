# -*- coding: utf-8 -*-
"""Probe round 4: fix remaining parsers (Baidi cookies, bilibili API, smartedu
Nuxt payload, OpenStax fields, UMN Atom shape, OCW via site: filter)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def text_of(r):
    ctype = r.headers.get("content-type", "")
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    enc = m.group(1) if m else "utf-8"
    enc = enc.lower()
    if enc in ("gb2312", "gbk"):
        enc = "gb18030"
    try:
        return r.content.decode(enc, "replace")
    except LookupError:
        return r.content.decode("utf-8", "replace")


print("========== A. UMN OTL fixture shape ==========")
p = FIX / "umn_otl.xml"
if p.exists():
    x = p.read_text("utf-8", "replace")
    print("len", len(x))
    print(x[:600].replace("\n", " ")[:600])
    print("count <entry:", x.count("<entry"), "| count <title:", x.count("<title"))

print("\n========== B. OpenStax fields ==========")
for f in ("title,meta", "title", "meta"):
    try:
        r = requests.get(
            "https://openstax.org/apps/cms/api/v2/pages/",
            params={"type": "books.Book", "limit": 3, "fields": f},
            headers={"User-Agent": UA},
            timeout=40,
        )
        print(f, r.status_code, len(r.content))
        if r.ok:
            j = r.json()
            print("   total:", j.get("meta", {}).get("total_count"), "items:", len(j.get("items", [])))
            print("   sample:", json.dumps(j["items"][0], ensure_ascii=False)[:220])
    except Exception as exc:  # noqa: BLE001
        print(f, "FAILED", exc)

print("\n========== C. Bilibili: warm-up cookies + JSON API ==========")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://www.bilibili.com/", "Accept-Language": "zh-CN,zh;q=0.9"})
try:
    s.get("https://www.bilibili.com/", timeout=40)
    print("cookies:", list(s.cookies.keys()))
    r = s.get(
        "https://api.bilibili.com/x/web-interface/search/type",
        params={"search_type": "video", "keyword": "高等数学", "page": 1, "page_size": 20},
        timeout=40,
    )
    print("api status", r.status_code, len(r.content))
    if r.ok:
        j = r.json()
        print("code:", j.get("code"), "msg:", j.get("message"))
        res = (j.get("data") or {}).get("result") or []
        print("results:", len(res))
        for it in res[:3]:
            print("   -", re.sub(r"<[^>]+>", "", it.get("title", ""))[:50], "|", it.get("bvid"), "|", it.get("author"))
        (FIX / "bilibili_api.json").write_bytes(r.content)
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n========== D. Bilibili html anchors ==========")
h = (FIX / "bilibili_search.html").read_text("utf-8", "replace")
anchors = re.findall(r'href="(//www\.bilibili\.com/video/BV[0-9A-Za-z]{10}[^"]*)"', h)
print("anchor count:", len(anchors), anchors[:3])
# try object-level extraction: bvid + title inside one JS object
objs = re.findall(r'\{[^{}]{0,400}?bvid:"(BV[0-9A-Za-z]{10})"[^{}]{0,400}?\}', h)
print("bvid objects:", len(objs))
m = re.search(r'bvid:"(BV[0-9A-Za-z]{10})".{0,600}?title:"((?:[^"\\]|\\.)*)"', h, re.S)
print("pair sample:", (m.group(1), m.group(2)[:80]) if m else None)

print("\n========== E. smartedu Nuxt payload ==========")
sm = (FIX / "smartedu_search.html").read_text("utf-8", "replace")
i = sm.find("__NUXT__")
print("ctx:", sm[max(0, i - 80): i + 300].replace("\n", " ")[:380])
print("course-like keys:", {k: sm.count(k) for k in ("courseTitle", "courseName", "schoolName", "teacherName", "resourceType")})
urls = re.findall(r'href="(/course/[^"]+)"', sm)
print("course hrefs:", len(urls), urls[:3])

print("\n========== F. icourse163 searchResult ctx ==========")
ic = (FIX / "icourse163_search.html").read_text("utf-8", "replace")
i = ic.find("searchResult")
print("ctx:", ic[max(0, i - 200): i + 400].replace("\n", " ")[:560])
print("has 高等数学:", "高等数学" in ic, "| has 课程:", "课程" in ic)
print("script srcs:", len(re.findall(r"<script[^>]+src=", ic)))

print("\n========== G. Baidu with cookie warm-up ==========")
s2 = requests.Session()
s2.headers.update(
    {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.baidu.com/",
    }
)
try:
    s2.get("https://www.baidu.com/", timeout=40)
    print("cookies:", list(s2.cookies.keys())[:6])
    for q in ("高等数学 课件", "线性代数 教材"):
        r = s2.get("https://www.baidu.com/s", params={"wd": q, "rn": 10}, timeout=40)
        h2 = text_of(r)
        n = len(re.findall(r'class="[^"]*c-container', h2))
        titles = re.findall(r"<h3[^>]*>.*?<a[^>]*>(.*?)</a>", h2, re.S)
        print(f"  {q}: {r.status_code} len={len(h2)} containers={n} titles={len(titles)}")
        if titles:
            print("    first:", re.sub(r"<[^>]+>", "", titles[0])[:60])
        if "安全验证" in h2 or "wappass" in h2:
            print("    -> anti-bot page")
        (FIX / f"baidu_{'a' if q.startswith('高') else 'b'}.html").write_bytes(r.content)
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n========== H. OCW via bing site: filter to course pages ==========")
r = requests.get(
    "https://www.bing.com/search",
    params={"q": "site:ocw.mit.edu/courses calculus", "count": 20},
    headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
    timeout=40,
)
h3 = text_of(r)
slugs = re.findall(r"https://ocw\.mit\.edu/courses/([a-z0-9\-]+)/", h3)
seen = list(dict.fromkeys(slugs))
print("slugs:", len(seen), seen[:5])

print("\n========== I. unpaywall email variants ==========")
for em in ("a@b.com", "cmf.finder@gmail.com"):
    r = requests.get(
        f"https://api.unpaywall.org/v2/10.1038/nature12373?email={em}", headers={"User-Agent": UA}, timeout=40
    )
    print(em, r.status_code, len(r.content))
    if r.ok:
        j = r.json()
        print("   ", j.get("title", "")[:50], "| best_oa:", (j.get("best_oa_location") or {}).get("url_for_pdf"))
        break

print("\n========== J. 学堂在线 API ==========")
try:
    r = requests.get(
        "https://www.xuetangx.com/api/v1/lms/get_product_list/",
        params={"query": "高等数学", "page": 1},
        headers={"User-Agent": UA, "Referer": "https://www.xuetangx.com/"},
        timeout=40,
    )
    print("status", r.status_code, len(r.content), r.text[:200])
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)
