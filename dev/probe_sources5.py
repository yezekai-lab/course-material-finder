# -*- coding: utf-8 -*-
"""Probe round 5: last mile — official CN platforms (chinaooc / icourse163 /
xuetangx), OCW sitemap index, UMN Atom with explicit Accept, Baidu ad filter."""
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
    m = re.search(r"charset=([\w-]+)", r.headers.get("content-type", ""), re.I)
    enc = (m.group(1) if m else "utf-8").lower()
    if enc in ("gb2312", "gbk"):
        enc = "gb18030"
    try:
        return r.content.decode(enc, "replace")
    except LookupError:
        return r.content.decode("utf-8", "replace")


print("========== A. chinaooc API 探测 ==========")
api = "https://api.chinaooc.com.cn/api/v1"
tries = [
    ("GET", f"{api}/search", {"keyword": "高等数学"}),
    ("GET", f"{api}/course/search", {"keyword": "高等数学"}),
    ("GET", f"{api}/search/course", {"keyword": "高等数学"}),
    ("GET", f"{api}/courses", {"keyword": "高等数学"}),
    ("GET", "https://api.chinaooc.com.cn/api/v2/search/list", {"keyword": "高等数学"}),
    ("POST", f"{api}/search", None),
]
for method, url, params in tries:
    try:
        if method == "GET":
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=25)
        else:
            r = requests.post(url, json={"keyword": "高等数学"},
                              headers={"User-Agent": UA, "Content-Type": "application/json"}, timeout=25)
        print(f"{method} {url} -> {r.status_code} {len(r.content)}B {r.text[:140]}")
    except Exception as exc:  # noqa: BLE001
        print(f"{method} {url} -> FAILED {type(exc).__name__}")

print("\n--- smartedu 首页 JS 里的接口路径 ---")
h = (FIX / "smartedu_search.html").read_text("utf-8", "replace")
paths = set(re.findall(r'["\'](/api/[a-zA-Z0-9_/\-]{3,60})["\']', h))
print("api paths in html:", sorted(paths)[:20])
print("chinaooc refs:", sorted(set(re.findall(r'https://api\.chinaooc\.com\.cn[a-zA-Z0-9_/\-]*', h)))[:10])

print("\n========== B. icourse163 rpc + csrfKey ==========")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://www.icourse163.org/"})
try:
    s.get("https://www.icourse163.org/", timeout=30)
    print("cookies:", list(s.cookies.keys()))
    csrf = s.cookies.get("NTESSTUDYSI")
    print("csrfKey:", csrf)
    r = s.post(
        "https://www.icourse163.org/web/j/courseBean.getCourseSearchResult.rpc",
        params={"csrfKey": csrf},
        data={"searchType": 30, "keyword": "高等数学", "pageIndex": 0},
        timeout=40,
    )
    print("status", r.status_code, len(r.content), r.text[:200])
    if r.ok:
        try:
            j = r.json()
            print("code:", j.get("code"), "result keys:", list((j.get("result") or {}))[:8])
        except Exception:  # noqa: BLE001
            pass
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n========== C. xuetangx POST ==========")
for payload in (
    {"query": "高等数学", "page": 1},
    {"query": "高等数学", "page_index": 1, "page_size": 10},
):
    try:
        r = requests.post(
            "https://www.xuetangx.com/api/v1/lms/get_product_list/",
            json=payload,
            headers={"User-Agent": UA, "Referer": "https://www.xuetangx.com/search"},
            timeout=40,
        )
        print(payload, "->", r.status_code, len(r.content), r.text[:160])
    except Exception as exc:  # noqa: BLE001
        print(payload, "-> FAILED", type(exc).__name__)

print("\n========== D. OCW sitemap ==========")
for url in ("https://ocw.mit.edu/sitemap.xml", "https://ocw.mit.edu/robots.txt"):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=40)
        print(url, r.status_code, len(r.content), r.text[:300].replace("\n", " ")[:300])
    except Exception as exc:  # noqa: BLE001
        print(url, "FAILED", type(exc).__name__)

print("\n========== E. UMN Atom with explicit Accept ==========")
r = requests.get(
    "https://open.umn.edu/opentextbooks/textbooks",
    params={"q": "calculus"},
    headers={"User-Agent": UA, "Accept": "application/atom+xml"},
    timeout=40,
)
print("status", r.status_code, r.headers.get("content-type"), len(r.content))
x = text_of(r)
entries = re.findall(r"<entry>(.*?)</entry>", x, re.S)
print("entries:", len(entries))
if entries:
    (FIX / "umn_otl.xml").write_bytes(r.content)
    for e in entries[:3]:
        t = re.search(r"<title[^>]*>(.*?)</title>", e, re.S)
        l = re.search(r'<link[^>]*href="([^"]+)"', e)
        print("  -", (t.group(1) if t else "?")[:70], "|", (l.group(1) if l else "?")[:80])

print("\n========== F. Baidu 广告识别 ==========")
p = FIX / "baidu_a.html"
if p.exists():
    hb = text_of(type("R", (), {"content": p.read_bytes(), "headers": {"content-type": "text/html;charset=utf-8"}})())
    blocks = re.split(r'(?=<div[^>]*class="[^"]*result[^"]*c-container)', hb)
    real = [b for b in blocks[1:] if "c-container" in b[:200]]
    print("blocks:", len(real))
    for b in real[:6]:
        cls = re.search(r'class="([^"]*c-container[^"]*)"', b)
        h3 = re.search(r"<h3[^>]*>(.*?)</h3>", b, re.S)
        title = re.sub(r"<[^>]+>", "", h3.group(1)).strip() if h3 else ""
        print(f"   cls={cls.group(1)[:40]!r} ad={('ec_ad' in b[:400] or 'ec-tuiguang' in b[:400])} title={title[:50]!r}")
