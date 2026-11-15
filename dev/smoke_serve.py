# -*- coding: utf-8 -*-
"""网页版冒烟测试：静态资源 + API 全链路（启动一个真实检索任务）。

先起服务，再跑：
    python dev/smoke_serve.py http://127.0.0.1:8765
    python dev/smoke_serve.py http://127.0.0.1:8765 --full
"""
from __future__ import annotations

import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
FULL = "--full" in sys.argv
fails = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' :: ' + extra) if extra and not cond else ''}")
    if not cond:
        fails.append(name)


print(f"== smoke: {BASE} ==")

r = requests.get(f"{BASE}/health", timeout=10)
check("health", r.status_code == 200 and r.json().get("ok") is True, r.text[:120])

r = requests.get(f"{BASE}/", timeout=10)
html = r.text
check("index 200", r.status_code == 200)
check("index has search box", 'id="q"' in html and 'id="go"' in html)
check("index loads app.js", "/app.js" in html and "/app.css" in html)

r = requests.get(f"{BASE}/app.css", timeout=10)
check("app.css", r.status_code == 200 and "text/css" in r.headers.get("content-type", ""))

r = requests.get(f"{BASE}/app.js", timeout=10)
check("app.js", r.status_code == 200 and "javascript" in r.headers.get("content-type", ""))

r = requests.get(f"{BASE}/api/bootstrap", timeout=10)
boot = r.json()
check("bootstrap sources", r.status_code == 200 and len(boot.get("sources", [])) >= 15,
      str(len(boot.get("sources", []))))
check("bootstrap fields", all(k in boot["sources"][0] for k in ("id", "label", "lang", "tier")))

r = requests.get(f"{BASE}/api/start", params={"q": "线性代数", "limit": 10, "crawl": 0}, timeout=30)
job = r.json()
check("start job", r.status_code == 200 and len(job.get("job", "")) > 5 and job.get("total", 0) > 5,
      json.dumps(job, ensure_ascii=False)[:160])
jid = job["job"]

phases = set()
sources_seen = 0
state = None
preview_ready = False
required = 180 if FULL else 90
t0 = time.time()
while time.time() - t0 < required:
    p = requests.get(f"{BASE}/api/progress", params={"job": jid}, timeout=15).json()
    state = p.get("state")
    phases.add(p.get("phase"))
    sources_seen = max(sources_seen, len(p.get("sources", [])))
    if not preview_ready and p.get("phase") in ("crawl", "finishing"):
        part = requests.get(f"{BASE}/api/partial", params={"job": jid}, timeout=10).json()
        preview_ready = bool(part.get("ready") and part.get("resources"))
    if state in ("done", "error"):
        break
    time.sleep(0.4)

check("job finished", state == "done", f"state={state}")
check("progress saw sources", sources_seen > 5, str(sources_seen))
check("progress saw phases", len(phases) >= 2, str(phases))
check("progressive preview", preview_ready or "done" in phases, f"preview={preview_ready}")

r = requests.get(f"{BASE}/api/result", params={"job": jid}, timeout=20)
res = r.json()
check("result resources", r.status_code == 200 and len(res.get("resources", [])) > 0,
      str(len(res.get("resources", []))))
check("result has stats", isinstance(res.get("stats"), dict))
check("result has portals", len(res.get("portals", [])) > 5, str(len(res.get("portals", []))))
kind = res["resources"][0]
check("resource schema", all(k in kind for k in ("title", "url", "kind_label", "score", "source_label")))

for fmt, marker in (("md", "# 课程资料检索报告"), ("html", "<!doctype html"), ("csv", "title,")):
    r = requests.get(f"{BASE}/api/export", params={"job": jid, "fmt": fmt}, timeout=20)
    body = r.content.decode("utf-8-sig", "replace") if fmt == "csv" else r.text
    check(f"export {fmt}", r.status_code == 200 and marker in body,
          f"{r.status_code} len={len(body)}")

r = requests.get(f"{BASE}/api/export", params={"job": jid, "fmt": "json"}, timeout=20)
check("export json", r.status_code == 200 and len(r.json().get("resources", [])) > 0)

r = requests.get(f"{BASE}/api/progress", params={"job": "nope"}, timeout=10)
check("unknown job -> 404", r.status_code == 404)

r = requests.get(f"{BASE}/api/start", params={"q": "x", "sources": "no-such"}, timeout=20)
check("bad source -> 400", r.status_code == 400, f"{r.status_code} {r.text[:80]}")

print("\nRESULT:", "PASS" if not fails else f"FAIL {fails}")
sys.exit(0 if not fails else 1)
