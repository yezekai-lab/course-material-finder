# -*- coding: utf-8 -*-
"""HTTP layer: per-host politeness, retries, on-disk cache, charset handling.

Why not just requests.get everywhere:
  * 百度/必应/B站 需要 cookie 预热 + 低频，否则 412 / 验证页；
  * arXiv 单次响应可达 40s，必须长超时 + 缓存，否则一次搜索拖死；
  * 同一关键词重复搜索很常见，缓存能把二次搜索压到 1s 内。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests

log = logging.getLogger("cmf.http")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
}

# 每主机最小请求间隔（秒）—— 对搜索引擎更保守
HOST_INTERVAL = {
    "www.baidu.com": 2.0,
    "www.bing.com": 1.5,
    "cn.bing.com": 1.5,
    "api.bilibili.com": 1.2,
    "www.bilibili.com": 1.2,
    "search.bilibili.com": 1.2,
    "export.arxiv.org": 3.0,
    "api.openalex.org": 0.25,
    "api.crossref.org": 0.5,
    "api.github.com": 6.5,  # 未认证搜索配额 10/min
    "zenodo.org": 0.5,
    "www.ebi.ac.uk": 0.5,
    "doaj.org": 1.0,
    "openstax.org": 1.0,
    "open.umn.edu": 1.0,
    "api.chinaooc.com.cn": 0.5,
    "zh.wikipedia.org": 0.4,
    "zh.wikibooks.org": 0.4,
    "api.stackexchange.com": 1.0,
    "gutendex.com": 1.0,
    "api.unpaywall.org": 0.3,
    "ocw.mit.edu": 1.0,
}
DEFAULT_INTERVAL = 0.15

_RATE_LOCK = threading.Lock()
_LAST_HIT: Dict[str, float] = {}
_TLS = threading.local()


class FetchError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


@dataclass
class Response:
    url: str
    status: int
    content: bytes
    text: str
    headers: Dict[str, str]
    from_cache: bool = False

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise FetchError(f"JSON 解析失败: {exc}", self.status, self.url) from exc


class HttpClient:
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        use_cache: bool = True,
        default_timeout: float = 30.0,
        retries: int = 2,
        verbose: bool = False,
        deadline: "Any" = None,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.use_cache = use_cache and self.cache_dir is not None
        self.default_timeout = default_timeout
        self.retries = retries
        self.verbose = verbose
        self.deadline = deadline  # cmf.concurrent.Deadline，用来压制单请求时长
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ cache
    def _cache_path(self, key: str) -> Path:
        assert self.cache_dir is not None
        return self.cache_dir / key[:2] / f"{key}.json"

    def _cache_get(self, key: str, ttl: float) -> Optional[Response]:
        if not self.use_cache:
            return None
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            payload = json.loads(p.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if ttl > 0 and time.time() - payload.get("ts", 0) > ttl:
            return None
        return Response(
            url=payload.get("url", ""),
            status=payload.get("status", 200),
            content=b"",  # 缓存只存文本，够用
            text=payload.get("text", ""),
            headers=payload.get("headers", {}),
            from_cache=True,
        )

    def _cache_put(self, key: str, resp: Response) -> None:
        if not self.use_cache:
            return
        p = self._cache_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": time.time(),
            "url": resp.url,
            "status": resp.status,
            "text": resp.text[:3_000_000],
            "headers": {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "content-type", "etag")},
        }
        try:
            p.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
        except Exception as exc:  # noqa: BLE001
            log.debug("cache write failed: %s", exc)

    # ----------------------------------------------------------------- session
    def _session(self) -> requests.Session:
        s = getattr(_TLS, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update(BASE_HEADERS)
            _TLS.session = s
        return s

    @staticmethod
    def _throttle(host: str) -> None:
        interval = HOST_INTERVAL.get(host, DEFAULT_INTERVAL)
        if interval <= 0:
            return
        with _RATE_LOCK:
            last = _LAST_HIT.get(host, 0.0)
            wait = interval - (time.time() - last)
            if wait > 0:
                time.sleep(min(wait, interval))
            _LAST_HIT[host] = time.time()

    @staticmethod
    def _decode(resp: requests.Response) -> str:
        ctype = resp.headers.get("content-type", "")
        enc = None
        m = re.search(r"charset=([\w\-]+)", ctype, re.I)
        if m:
            enc = m.group(1)
        if not enc:
            m2 = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", resp.content[:4000], re.I)
            if m2:
                enc = m2.group(1).decode("ascii", "ignore")
        enc = (enc or "").lower()
        if enc in ("gb2312", "gbk", "gb_2312-80"):
            enc = "gb18030"
        if enc:
            try:
                return resp.content.decode(enc, "replace")
            except LookupError:
                pass
        return resp.content.decode("utf-8", "replace")

    # ------------------------------------------------------------------ request
    def request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
        json_body: Any = None,
        timeout: Optional[float] = None,
        ttl: float = 3600.0,
        method: str = "GET",
        allow_status: tuple = (200,),
        warmup: Optional[str] = None,
        retries: Optional[int] = None,
    ) -> Response:
        timeout = timeout or self.default_timeout
        attempts = self.retries if retries is None else retries
        if self.deadline is not None:
            # 剩余预算不够就别再重试，也别给一个超出预算的超时
            timeout = self.deadline.clamp(timeout)
            if self.deadline.expired():
                attempts = 0
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        key_raw = json.dumps(
            {"m": method, "u": url, "p": params, "d": data, "j": json_body, "h": sorted((headers or {}).items())},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        key = hashlib.sha1(key_raw.encode("utf-8")).hexdigest()
        cached = self._cache_get(key, ttl)
        if cached is not None:
            return cached

        s = self._session()
        if warmup:
            try:
                self._throttle(re.sub(r"^https?://", "", warmup).split("/")[0].lower())
                s.get(warmup, timeout=min(timeout, 20), headers={"User-Agent": UA})
            except Exception as exc:  # noqa: BLE001
                log.debug("warmup failed %s: %s", warmup, exc)

        last_exc: Optional[Exception] = None
        for attempt in range(attempts + 1):
            self._throttle(host)
            try:
                if self.verbose:
                    log.info("GET %s params=%s", url, params)
                resp = s.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    json=json_body,
                    headers=headers,
                    timeout=timeout,
                )
                text = self._decode(resp)
                out = Response(
                    url=resp.url,
                    status=resp.status_code,
                    content=resp.content,
                    text=text,
                    headers=dict(resp.headers),
                )
                if resp.status_code in allow_status or 200 <= resp.status_code < 300:
                    if 200 <= resp.status_code < 300:
                        self._cache_put(key, out)
                    return out
                if resp.status_code in (429, 403, 412, 503, 502, 500) and attempt < attempts:
                    wait = (0.8 * (2**attempt)) + random.uniform(0, 0.4)
                    log.debug("HTTP %s on %s, retry in %.1fs", resp.status_code, url, wait)
                    time.sleep(wait)
                    continue
                raise FetchError(f"HTTP {resp.status_code}", resp.status_code, url)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt < attempts:
                    time.sleep(0.6 * (2**attempt) + random.uniform(0, 0.3))
                    continue
            except FetchError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
        raise FetchError(f"{type(last_exc).__name__}: {last_exc}", None, url)

    # --------------------------------------------------------------- shorthands
    def get_text(self, url: str, **kw) -> str:
        return self.request(url, **kw).text

    def get_json(self, url: str, **kw) -> Any:
        return self.request(url, **kw).json()

    def get_page(self, url: str, timeout: float = 20.0) -> Response:
        """Fetch an arbitrary page for the crawl stage."""
        return self.request(url, timeout=timeout, ttl=6 * 3600, retries=0)


def default_cache_dir() -> Path:
    base = os.environ.get("CMF_CACHE_DIR")
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent / ".cmf-cache"
