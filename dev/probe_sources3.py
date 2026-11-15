# -*- coding: utf-8 -*-
"""Probe round 3: verify we can actually EXTRACT structured fields, and save
real responses as offline test fixtures under tests/fixtures/.

Run: python dev/probe_sources3.py
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FIX.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers.update(
    {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
)


def save(name, content: bytes):
    (FIX / name).write_bytes(content)


def get(url, **kw):
    kw.setdefault("timeout", 45)
    r = S.get(url, **kw)
    r.raise_for_status()
    return r


def text_of(r):
    """requests guesses encoding badly for GBK pages; use declared charset."""
    ctype = r.headers.get("content-type", "")
    enc = None
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", r.content[:3000], re.I)
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    enc = (enc or "utf-8").lower()
    if enc in ("gb2312", "gbk"):
        enc = "gb18030"
    try:
        return r.content.decode(enc, "replace")
    except LookupError:
        return r.content.decode("utf-8", "replace")


print("########## 1. 百度 (SSR 结果) ##########")
r = get("https://www.baidu.com/s?wd=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6%20%E8%AF%BE%E4%BB%B6&rn=10")
save("baidu_search.html", r.content)
h = text_of(r)
print("charset-guess:", r.encoding, "| has 百度:", "百度" in h, "| len:", len(h))
blocks = re.findall(r'<div[^>]*class="[^"]*result[^"]*c-container[^"]*"[^>]*>.*?(?=<div[^>]*class="[^"]*result)', h, re.S)
print("c-container blocks:", len(blocks))
for b in blocks[:3]:
    t = re.search(r"<h3[^>]*>.*?<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", b, re.S)
    if t:
        title = re.sub(r"<[^>]+>", "", t.group(2)).strip()
        print("  -", title[:60], "|", t.group(1)[:60])

print("\n########## 2. 必应 ##########")
r = get("https://www.bing.com/search?q=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6+%E8%AF%BE%E4%BB%B6+site%3Acn", )
print("status", r.status_code)
r = get("https://www.bing.com/search?q=calculus+lecture+notes&setlang=en&count=10")
save("bing_search.html", r.content)
h = text_of(r)
items = re.findall(r'<li class="b_algo".*?</li>', h, re.S)
print("b_algo:", len(items))
for it in items[:3]:
    m = re.search(r'<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', it, re.S)
    if m:
        print("  -", re.sub(r"<[^>]+>", "", m.group(2))[:60], "|", m.group(1)[:70])

print("\n########## 3. B站搜索页 ##########")
r = get("https://search.bilibili.com/all?keyword=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6")
save("bilibili_search.html", r.content)
h = text_of(r)
bvs = re.findall(r'bvid:"(BV[0-9A-Za-z]{10})"', h)
print("bvid count:", len(set(bvs)), "sample:", list(dict.fromkeys(bvs))[:3])
titles = re.findall(r'title:"(.*?)",description', h)
print("titles:", [t[:40] for t in titles[:3]])

print("\n########## 4. 智慧教育平台 ##########")
r = get("https://higher.smartedu.cn/search?keyword=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6")
h = text_of(r)
save("smartedu_search.html", r.content)
print("len", len(h), "| has 高等数学:", "高等数学" in h, "| has __INITIAL_STATE__:", "__INITIAL_STATE__" in h)
for key in ("window.__INITIAL_STATE__", "window.__NUXT__", "nuxt", "__NUXT__", "application/json"):
    print(f"  marker {key!r}:", h.count(key))

print("\n########## 5. 中国大学MOOC ##########")
r = get("https://www.icourse163.org/search.htm?search=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6")
h = text_of(r)
save("icourse163_search.html", r.content)
for key in ("window.__INITIAL_STATE__", "courseId", "searchResult", "__NEXT_DATA__"):
    print(f"  marker {key!r}:", h.count(key))

print("\n########## 6. GitHub 仓库搜索 (无 token) ##########")
try:
    r = get("https://api.github.com/search/repositories?q=course+notes+in:name&sort=stars&per_page=3")
    j = r.json()
    print("total:", j.get("total_count"), "| items:",
          [(i["full_name"], i["stargazers_count"]) for i in j.get("items", [])[:3]])
    save("github_repos.json", r.content)
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n########## 7. 网易公开课 ##########")
try:
    r = get("https://open.163.com/search?keyword=%E9%AB%98%E7%AD%89%E6%95%B0%E5%AD%A6")
    h = text_of(r)
    print("status", r.status_code, "len", len(h), "| has 高等数学:", "高等数学" in h)
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n########## 8. MIT OCW via bing site: ##########")
try:
    r = get("https://www.bing.com/search?q=site%3Aocw.mit.edu+calculus&setlang=en&count=10")
    h = text_of(r)
    hits = re.findall(r'href="(https://ocw\.mit\.edu/courses/[^"]+)"', h)
    print("ocw course urls:", len(set(hits)), list(dict.fromkeys(hits))[:3])
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n########## 9. OpenStax 全量目录 ##########")
try:
    r = get("https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&limit=100&fields=title,meta,book_state")
    j = r.json()
    print("items:", len(j.get("items", [])), "total:", j.get("meta", {}).get("total_count"))
    print("sample:", [(i["title"], i["meta"]["slug"]) for i in j["items"][:3]])
    save("openstax_books.json", r.content)
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n########## 10. UMN Open Textbook Library (Atom) ##########")
try:
    r = get("https://open.umn.edu/opentextbooks/textbooks?q=calculus")
    x = text_of(r)
    save("umn_otl.xml", r.content)
    entries = re.findall(r"<entry>(.*?)</entry>", x, re.S)
    print("entries:", len(entries))
    for e in entries[:2]:
        t = re.search(r"<title[^>]*>(.*?)</title>", e, re.S)
        l = re.search(r'<link[^>]*href="([^"]+)"', e)
        print("  -", (t.group(1) if t else "?")[:60], "|", (l.group(1) if l else "?")[:70])
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n########## 11. arXiv ##########")
try:
    r = get("https://export.arxiv.org/api/query?search_query=all:calculus&max_results=5", timeout=90)
    x = r.text
    save("arxiv.xml", r.content)
    entries = re.findall(r"<entry>(.*?)</entry>", x, re.S)
    print("entries:", len(entries))
    for e in entries[:2]:
        t = re.search(r"<title>(.*?)</title>", e, re.S)
        i = re.search(r"<id>(.*?)</id>", e, re.S)
        print("  -", re.sub(r"\s+", " ", t.group(1))[:60] if t else "?", "|", i.group(1) if i else "?")
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n########## 12. Europe PMC ##########")
try:
    r = get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=calculus&format=json&pageSize=3&resultType=core"
    )
    j = r.json()
    print("hitCount:", j.get("hitCount"))
    for i in j.get("resultList", {}).get("result", [])[:3]:
        print("  -", i.get("title", "")[:60], "|", i.get("doi"), "| OA:", bool(i.get("isOpenAccess")))
    save("europepmc.json", r.content)
except Exception as exc:  # noqa: BLE001
    print("FAILED", exc)

print("\n########## 13. Zenodo / DOAJ / StackExchange / Wiki 解析 ##########")
checks = [
    ("zenodo", "https://zenodo.org/api/records?q=linear%20algebra&size=3",
     lambda j: [(h["metadata"].get("title", "")[:40], h.get("links", {}).get("self_html", "")) for h in j["hits"]["hits"]]),
    ("doaj", "https://doaj.org/api/search/articles/linear%20algebra?pageSize=3",
     lambda j: [(x["bibjson"].get("title", "")[:40]) for x in j["results"]]),
    ("stackexchange", "https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance&q=linked+list&site=stackoverflow&pagesize=3",
     lambda j: [(x["title"][:40], x["link"]) for x in j["items"]]),
    ("wikipedia", "https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch=%E7%BA%BF%E6%80%A7%E4%BB%A3%E6%95%B0&format=json&srlimit=3",
     lambda j: [(x["title"], x["snippet"][:30]) for x in j["query"]["search"]]),
    ("crossref", "https://api.crossref.org/works?query=linear+algebra&rows=3",
     lambda j: [(x.get("title", [""])[0][:40], x.get("DOI")) for x in j["message"]["items"]]),
    ("openalex", "https://api.openalex.org/works?search=linear%20algebra&per_page=3",
     lambda j: [(x.get("display_name", "")[:40], x.get("doi")) for x in j["results"]]),
    ("gutendex", "https://gutendex.com/books?search=algebra",
     lambda j: [(x["title"][:40], x["formats"].get("text/html")) for x in j["results"][:3]]),
    ("unpaywall", "https://api.unpaywall.org/v2/10.1038/nature12373?email=cmf@example.com",
     lambda j: [(j.get("title", "")[:50], (j.get("best_oa_location") or {}).get("url_for_pdf"))]),
]
for name, url, extract in checks:
    try:
        r = get(url)
        j = r.json()
        save(f"{name}.json", r.content)
        print(f"  {name}:", extract(j)[:3])
    except Exception as exc:  # noqa: BLE001
        print(f"  {name}: FAILED {type(exc).__name__}: {exc}")

print("\nfixtures saved to", FIX)
