# -*- coding: utf-8 -*-
"""Probe round 6: chinaooc course schema/paging + OCW sitemap-www shape."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

print("========== chinaooc /api/v1/courses ==========")
r = requests.get(
    "https://api.chinaooc.com.cn/api/v1/courses",
    params={"keyword": "高等数学", "page": 1, "pageSize": 5},
    headers={"User-Agent": UA, "Accept": "application/json"},
    timeout=40,
)
print("status", r.status_code, len(r.content))
j = r.json()
print("top keys:", list(j))
print("countCourse:", j.get("countCourse"), "hasMore:", j.get("hasMore"))
cs = j.get("courses") or []
print("courses:", len(cs))
if cs:
    print("course keys:", list(cs[0]))
    print(json.dumps(cs[0], ensure_ascii=False, indent=1)[:2000])
(FIX / "chinaooc_courses.json").write_bytes(r.content)

for ps in (10, 20, 50):
    rr = requests.get(
        "https://api.chinaooc.com.cn/api/v1/courses",
        params={"keyword": "线性代数", "page": 1, "pageSize": ps},
        headers={"User-Agent": UA},
        timeout=40,
    )
    jj = rr.json() if rr.ok else {}
    print(f"pageSize={ps} -> {rr.status_code} n={len(jj.get('courses') or [])}")

print("\n========== OCW sitemap-www ==========")
r = requests.get("https://ocw.mit.edu/sitemap-www.xml", headers={"User-Agent": UA}, timeout=60)
print("status", r.status_code, len(r.content))
x = r.text
locs = re.findall(r"<loc>(.*?)</loc>", x)
print("locs:", len(locs))
print("first:", locs[:5])
courses = [u for u in locs if "/courses/" in u]
print("course urls:", len(courses), courses[:3])

print("\n========== 单一课程页可否抓到标题/大纲 ==========")
if courses:
    r = requests.get(courses[0], headers={"User-Agent": UA}, timeout=40)
    t = r.text
    m = re.search(r"<title>(.*?)</title>", t, re.S)
    print("status", r.status_code, "title:", (m.group(1).strip()[:120] if m else None))
    print("has 'Course Description':", "Course Description" in t, "| len:", len(t))
    d = re.search(r'<meta name="description" content="([^"]{0,300})', t)
    print("meta desc:", (d.group(1) if d else None))
