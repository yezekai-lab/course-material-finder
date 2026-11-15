#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""课程资料获取助手 · 本地网页版

    python serve.py                # http://127.0.0.1:8765
    python serve.py --port auto --open
    python serve.py --port 8801

设计上只做三件事：一个输入框、一条看得见源在动的状态带、一套能直接拿走的导出。
前端在 web/ 下（零依赖原生 JS），后端只有标准库 + requests。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import re
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmf.engine import Options, list_sources, search  # noqa: E402
from cmf.report import render_html, render_markdown  # noqa: E402
from cmf.sources import ALL_SOURCES, resolve  # noqa: E402

MAX_JOBS = 30
JOB_TTL = 1800.0  # 30 分钟
MAX_RUNNING = 3

_JOBS: dict = {}
_LOCK = threading.Lock()
_RUNNING = threading.Semaphore(MAX_RUNNING)


class Job:
    def __init__(self, query: str, total: int):
        self.id = uuid.uuid4().hex[:12]
        self.query = query
        self.total = total
        self.state = "running"  # running / done / error
        self.phase = "sources"
        self.error = ""
        self.started = time.time()
        self.sources: list = []
        self.result = None
        self.stats: dict = {}
        self.partial: dict | None = None  # 排序完成后的预览（正文还没抓）

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    def to_progress(self) -> dict:
        return {
            "job": self.id,
            "query": self.query,
            "state": self.state,
            "phase": self.phase,
            "elapsed": round(self.elapsed, 1),
            "total": self.total,
            "done": len(self.sources),
            "sources": self.sources,
            "error": self.error,
        }


def _purge() -> None:
    now = time.time()
    for jid, job in list(_JOBS.items()):
        if job.state != "running" and now - job.started > JOB_TTL:
            _JOBS.pop(jid, None)
    if len(_JOBS) > MAX_JOBS:
        for jid, _job in sorted(_JOBS.items(), key=lambda kv: kv[1].started)[: len(_JOBS) - MAX_JOBS]:
            _JOBS.pop(jid, None)


def _parse_opts(qs: dict) -> Options:
    def num(key, default, lo, hi, cast=float):
        try:
            return max(lo, min(hi, cast(qs.get(key, default))))
        except (TypeError, ValueError):
            return default

    raw_sources = (qs.get("sources") or "").strip()
    src_list = [s for s in re.split(r"[,\s]+", raw_sources) if s] or None
    return Options(
        limit=int(num("limit", 30, 5, 100, int)),
        per_source=8,
        crawl=(qs.get("crawl", "1") not in ("0", "false", "")),
        # 界面先给结果再补正文，抓 8 条足够撑住首屏；用户要看更多可以点导出/换条数
        crawl_limit=8,
        sources=src_list,
        min_score=num("minscore", 10.0, 0.0, 90.0),
        download_dir=(ROOT / "downloads") if qs.get("download") in ("1", "true") else None,
        budget=num("budget", 100.0, 10.0, 300.0),
        crawl_budget=num("crawl_budget", 35.0, 10.0, 240.0),
    )


def start_job(qs: dict) -> dict:
    query = (qs.get("q") or "").strip()
    if not query:
        raise ValueError("缺少参数 q")
    opts = _parse_opts(qs)
    try:
        total = len(resolve(opts.sources) if opts.sources else resolve(None))
    except KeyError as exc:
        raise ValueError(str(exc).strip("'")) from exc
    job = Job(query, total)

    def on_phase(name: str) -> None:
        job.phase = name

    def on_source_done(st) -> None:  # noqa: ANN001
        with _LOCK:
            job.sources.append(st.to_dict())

    def on_ranked(items: list, total: int) -> None:
        job.partial = {"resources": items, "total": total, "elapsed": round(job.elapsed, 1)}

    opts.on_phase = on_phase
    opts.on_source_done = on_source_done
    opts.on_ranked = on_ranked

    def work() -> None:
        acquired = _RUNNING.acquire(timeout=180)
        if not acquired:
            job.state, job.error = "error", "服务器忙：并发检索已满，请稍后重试"
            return
        try:
            result, stats = search(query, opts)
            job.result, job.stats = result, stats
            job.phase = "done"
            job.state = "done"
        except Exception as exc:  # noqa: BLE001
            job.state = "error"
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            _RUNNING.release()

    with _LOCK:
        _purge()
        _JOBS[job.id] = job
    threading.Thread(target=work, name=f"job-{job.id}", daemon=True).start()
    return {"job": job.id, "total": total}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "CourseMaterialFinder/2.0"

    def log_message(self, fmt, *args):  # 安静
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------------ output
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, code: int, message: str) -> None:
        self._json({"error": message}, code)

    # -------------------------------------------------------------------- GET
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path == "/app.css":
                return self._static("app.css")
            if path == "/app.js":
                return self._static("app.js")
            if path == "/api/bootstrap":
                return self._bootstrap()
            if path == "/api/start":
                try:
                    return self._json(start_job(qs))
                except ValueError as exc:
                    return self._error(400, str(exc))
            if path == "/api/progress":
                return self._progress(qs)
            if path == "/api/result":
                return self._result(qs)
            if path == "/api/partial":
                return self._partial(qs)
            if path == "/api/export":
                return self._export(qs)
            if path == "/health":
                return self._json({"ok": True, "sources": len(ALL_SOURCES), "jobs": len(_JOBS)})
            if path == "/sources":
                return self._send(200, list_sources().encode("utf-8"), "text/plain; charset=utf-8")
            return self._error(404, "not found")
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"{type(exc).__name__}: {exc}")

    # ---------------------------------------------------------------- handlers
    def _static(self, name: str) -> None:
        p = WEB / name
        if not p.exists():
            return self._error(404, f"缺少静态文件 web/{name}")
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        if name.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        if name.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        self._send(200, p.read_bytes(), ctype)

    def _bootstrap(self) -> None:
        rows = [
            {
                "id": s.meta.id,
                "label": s.meta.label,
                "kind": s.meta.kind,
                "lang": s.meta.lang,
                "tier": s.meta.tier,
                "enabled": s.meta.enabled,
                "note": s.meta.note,
            }
            for s in ALL_SOURCES.values()
        ]
        self._json({"sources": rows, "total": len(rows)})

    def _job(self, qs: dict) -> Job | None:
        jid = qs.get("job", "")
        return _JOBS.get(jid)

    def _progress(self, qs: dict) -> None:
        job = self._job(qs)
        if not job:
            return self._error(404, "任务不存在或已过期")
        self._json(job.to_progress())

    def _result(self, qs: dict) -> None:
        job = self._job(qs)
        if not job:
            return self._error(404, "任务不存在或已过期")
        if job.state != "done":
            return self._json({"state": job.state, "error": job.error})
        payload = job.result.to_dict()
        payload["stats"] = job.stats
        payload["state"] = "done"
        self._json(payload)

    def _partial(self, qs: dict) -> None:
        """排序完成、正文未抓完时的预览结果；让界面 10 秒级就能看到东西。"""
        job = self._job(qs)
        if not job:
            return self._error(404, "任务不存在或已过期")
        if not job.partial:
            return self._json({"state": job.state, "ready": False})
        payload = dict(job.partial)
        payload.update({"state": job.state, "phase": job.phase, "ready": True})
        self._json(payload)

    def _export(self, qs: dict) -> None:
        job = self._job(qs)
        if not job or job.state != "done":
            return self._error(404, "任务不存在、未完成或已过期")
        fmt = (qs.get("fmt") or "md").lower()
        stem = re.sub(r'[\\/:*?"<>|\s]+', "-", f"{job.result.generated_at[:10]}-{job.result.core}")[:60]
        if fmt == "md":
            body, ctype = render_markdown(job.result, job.stats).encode("utf-8"), "text/markdown; charset=utf-8"
            ext = "md"
        elif fmt == "html":
            body, ctype = render_html(job.result, job.stats).encode("utf-8"), "text/html; charset=utf-8"
            ext = "html"
        elif fmt == "json":
            payload = job.result.to_dict()
            payload["stats"] = job.stats
            body, ctype, ext = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8", "json"
        elif fmt == "csv":
            buf = io.StringIO()
            from cmf.report import CSV_FIELDS, _access

            w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
            w.writeheader()
            for r in job.result.resources:
                w.writerow({
                    "title": r.title, "url": r.url, "source": r.source, "source_label": r.source_label,
                    "kind": r.kind_label, "lang": r.lang_label, "year": r.year or "", "org": r.org,
                    "authors": "; ".join(r.authors[:4]), "score": f"{r.score:.1f}",
                    "relevance": f"{r.relevance:.2f}", "quality": f"{r.quality:.2f}",
                    "crawl_status": _access(r), "pdf_url": r.pdf_url, "summary": r.summary(300),
                })
            body, ctype, ext = buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", "csv"
        else:
            return self._error(400, f"不支持的导出格式：{fmt}")

        ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "-", stem) or "report"
        utf_name = f"{stem}.{ext}"
        disp = f"attachment; filename=\"{ascii_name}.{ext}\"; filename*=UTF-8''{stub_quote(utf_name)}"
        self._send(200, body, ctype, {"Content-Disposition": disp})


def stub_quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text, safe="")


def find_free_port(host: str, wanted: int, span: int = 40) -> int:
    import socket

    for port in range(wanted, wanted + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"从 {wanted} 起的 {span} 个端口都被占用，请用 --port 指定其它端口。")


def main() -> int:
    ap = argparse.ArgumentParser(description="课程资料获取助手 · 本地网页版")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="8765", help="端口，或 auto（自动找空闲端口）")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--verbose", action="store_true", help="打印访问日志")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            # 控制台已经是 GBK/UTF-8 就尊重它；只在纯 ASCII 环境（被管道接管）时兜底
            if (getattr(stream, "encoding", "") or "").lower() in ("", "ascii", "ansi_x3.4-1968"):
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    wanted = 8765
    if str(args.port).lower() != "auto":
        try:
            wanted = int(args.port)
        except ValueError:
            raise SystemExit("--port 需要是整数或 auto")
    port = find_free_port(args.host, wanted)

    srv = ThreadingHTTPServer((args.host, port), Handler)
    srv.verbose = args.verbose  # type: ignore[attr-defined]
    url = f"http://{args.host}:{port}/"
    print(f"\n  课程资料获取助手  →  {url}")
    print(f"  数据源 {len(ALL_SOURCES)} 个 ｜ Ctrl+C 停止\n")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
