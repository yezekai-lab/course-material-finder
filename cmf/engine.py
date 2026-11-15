# -*- coding: utf-8 -*-
"""编排：解析查询 -> 并发打各数据源 -> 去重打分 -> 抓正文 -> 出结果。

并发用 cmf.concurrent（守护线程 + 预算），不用 ThreadPoolExecutor：
坏源卡在 DNS/慢速响应时，整次检索必须还能按时交报告。
"""
from __future__ import annotations

import datetime as _dt
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import enrich as enrich_mod
from .concurrent import Deadline, run_with_deadline
from .http import HttpClient, default_cache_dir
from .models import Resource, SearchResult, SourceStatus
from .query import Query, parse as parse_query
from .rank import dedupe, diversify, score_all
from .sources import ALL_SOURCES, LINK_IDS, Context, Source, resolve

log = logging.getLogger("cmf.engine")

CRAWL_BONUS = 3.0  # 能真抓到正文，说明内容可访问，值得往前排


@dataclass
class Options:
    limit: int = 30
    per_source: int = 10
    crawl: bool = True
    crawl_limit: int = 12
    sources: Optional[List[str]] = None
    min_score: float = 10.0
    download_dir: Optional[Path] = None
    cache: bool = True
    verbose: bool = False
    resolve_oa: bool = True
    budget: float = 100.0  # 检索总预算（秒）
    crawl_budget: float = 60.0  # 抓正文预算（秒）
    cache_dir: Optional[Path] = None
    # 供 Web 界面实时显示进度用；CLI 不传就好
    on_phase: Optional[Callable[[str], None]] = None
    on_source_done: Optional[Callable[[SourceStatus], None]] = None
    on_ranked: Optional[Callable[[list, int], None]] = None
    # 跑了多少秒后先用「已回来的源」排一版结果给界面看，不等最慢的那个
    early_rank_after: float = 12.0


def _run_source(src: Source, q: Query, ctx: Context) -> Tuple[SourceStatus, List[Resource]]:
    st = SourceStatus(id=src.meta.id, label=src.meta.label)
    t0 = time.time()
    try:
        items = src.fetch(q, ctx) or []
        st.count = len(items)
        st.ok = True
        return st, items
    except Exception as exc:  # noqa: BLE001
        st.ok = False
        st.error = f"{type(exc).__name__}: {exc}"[:200]
        log.debug("source %s failed: %s", src.meta.id, exc)
        return st, []
    finally:
        st.elapsed = time.time() - t0


def search(text: str, opts: Optional[Options] = None) -> Tuple[SearchResult, dict]:
    opts = opts or Options()
    q = parse_query(text)
    t_start = time.time()

    ids = resolve(opts.sources) if opts.sources else resolve(None)

    dl = Deadline(opts.budget)
    http = HttpClient(
        cache_dir=opts.cache_dir or default_cache_dir(),
        use_cache=opts.cache,
        default_timeout=30.0,
        retries=2,
        verbose=opts.verbose,
        deadline=dl,
    )
    ctx = Context(http=http, per_source=opts.per_source, verbose=opts.verbose)

    crawl_sources = [ALL_SOURCES[i] for i in ids if i not in LINK_IDS]
    link_sources = [ALL_SOURCES[i] for i in ids if i in LINK_IDS]
    all_sources: List[Source] = crawl_sources + link_sources

    statuses: List[SourceStatus] = []
    resources: List[Resource] = []
    portals: List[Resource] = []

    def emit(st: SourceStatus) -> None:
        if opts.on_source_done:
            try:
                opts.on_source_done(st)
            except Exception:  # noqa: BLE001  # 进度上报失败不能影响检索
                log.debug("on_source_done callback failed", exc_info=True)

    def phase(name: str) -> None:
        if opts.on_phase:
            try:
                opts.on_phase(name)
            except Exception:  # noqa: BLE001
                log.debug("on_phase callback failed", exc_info=True)

    phase("sources")
    by_index: dict = {}
    preview_done = False

    def on_done(idx: int, value, exc) -> None:  # noqa: ANN001
        src = all_sources[idx]
        if value is not None:
            st, _items = value
        else:
            st = SourceStatus(
                id=src.meta.id,
                label=src.meta.label,
                ok=False,
                error=f"{type(exc).__name__}: {exc}"[:200] if exc else "未返回结果",
            )
        by_index[idx] = st
        emit(st)

    def snapshot(partial: dict) -> None:
        """把「已经回来的源」先排一版，界面不用等最慢的那个。"""
        nonlocal preview_done
        if preview_done or not opts.on_ranked:
            return
        items: List[Resource] = []
        for value in partial.values():
            if not value:
                continue
            _st, src_items = value
            items.extend(i for i in (src_items or []) if i.kind != "link")
        if not items:
            return
        preview_done = True
        try:
            ranked = score_all(dedupe(items), q)
            ranked.sort(key=lambda r: -r.score)
            opts.on_ranked([r.to_dict() for r in ranked[: max(opts.limit, 10)]], len(ranked))
        except Exception:  # noqa: BLE001
            log.debug("early ranking failed", exc_info=True)

    results, unfinished, _errors = run_with_deadline(
        lambda s: _run_source(s, q, ctx),
        all_sources,
        deadline=dl,
        on_done=on_done,
        checkpoint_after=opts.early_rank_after,
        on_checkpoint=snapshot,
    )

    for idx, src in enumerate(all_sources):
        if idx in unfinished:
            st = SourceStatus(
                id=src.meta.id,
                label=src.meta.label,
                ok=False,
                error=f"超时：超过 {opts.budget:.0f}s 总预算，已放弃",
                elapsed=opts.budget,
            )
            emit(st)
            statuses.append(st)
            continue
        st = by_index.get(idx)
        if st is None:  # 理论上不会发生，兜底
            st = SourceStatus(id=src.meta.id, label=src.meta.label, ok=False, error="未返回结果")
        statuses.append(st)
        items = results[idx][1] if results.get(idx) else []
        if src.meta.id in LINK_IDS:
            portals.extend(items)
        else:
            resources.extend(items)

    order = {sid: i for i, sid in enumerate(ALL_SOURCES)}
    statuses.sort(key=lambda s: order.get(s.id, 99))

    phase("ranking")
    resources = score_all(dedupe(resources), q)
    resources = [r for r in resources if r.score >= opts.min_score]
    resources.sort(key=lambda r: -r.score)

    stats = {"crawled": 0, "abstracts": 0, "oa_pdf": 0, "downloaded": 0, "timed_out": len(unfinished)}
    if resources and opts.on_ranked:
        # 排序完成就先给界面一份「可读的结果」，正文慢慢补——别让人盯着空屏
        try:
            opts.on_ranked([r.to_dict() for r in resources[: max(opts.limit, 10)]], len(resources))
        except Exception:  # noqa: BLE001
            log.debug("on_ranked callback failed", exc_info=True)

    if opts.crawl and resources:
        # 抓取阶段换一份预算，别让检索阶段的剩余时间把抓取掐死
        phase("crawl")
        http.deadline = Deadline(opts.crawl_budget)
        head = resources[: max(opts.crawl_limit, 5)]
        e = enrich_mod.enrich(
            head,
            http,
            crawl_limit=opts.crawl_limit,
            download_dir=opts.download_dir,
            verbose=opts.verbose,
            resolve_oa=opts.resolve_oa,
        )
        stats.update(e)
        for r in head:
            if r.crawled or r.crawl_status == "pdf":
                r.score = min(100.0, r.score + CRAWL_BONUS)
        resources.sort(key=lambda r: -r.score)

    phase("finishing")

    resources = diversify(resources, opts.limit)
    result = SearchResult(
        query=text,
        core=q.core,
        lang=q.lang,
        resources=resources,
        statuses=statuses,
        link_portals=portals,
        elapsed=time.time() - t_start,
        generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    return result, stats


def list_sources() -> str:
    from .sources import describe_table

    rows = describe_table()
    lines = ["可用数据源：", ""]
    lines.append(f"{'ID':<14}{'默认':<6}{'类型':<14}{'说明'}")
    for r in rows:
        lines.append(f"{r['id']:<14}{r['enabled']:<6}{r['kind']:<14}{r['note']}")
    lines.append("")
    lines.append("用法：--sources openalex,arxiv,bilibili   或 --sources all")
    return "\n".join(lines)
