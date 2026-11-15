# -*- coding: utf-8 -*-
"""Ranking & dedupe.

score = 100 * (0.60*相关度 + 0.20*源质量 + 0.10*时效 + 0.10*语言匹配)
相关度只用「查询核心词的 token 覆盖率」算——做过实测，标题命中权重 0.7 足够，
再复杂就得引入向量模型，对「找一个课程资料」这种场景收益很低。
"""
from __future__ import annotations

import math
import time
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .models import Resource
from .query import Query
from .textutil import jaccard, norm_title, normalize_url, tokens

# 各数据源的质量先验（0~1）：官方课程库/开放教材库最高，搜索引擎最低
SOURCE_QUALITY = {
    "ocw": 0.95,
    "openstax": 0.95,
    "chinaooc": 0.92,
    "otl": 0.90,
    "openalex": 0.88,
    "europepmc": 0.88,
    "crossref": 0.85,
    "arxiv": 0.85,
    "doaj": 0.82,
    "wikibooks": 0.80,
    "bilibili": 0.78,
    "wikipedia": 0.75,
    "github": 0.70,
    "zenodo": 0.70,
    "stackexchange": 0.72,
    "gutendex": 0.62,
    "bing": 0.55,
    "baidu": 0.52,
    "sogou": 0.50,
    "portals": 0.40,
}

# 用户意图 → 哪种资料类型加分
WANT_BOOST = {
    "video": {"video": 0.18, "course": 0.12},
    "course": {"course": 0.18, "video": 0.10},
    "textbook": {"textbook": 0.18},
    "slides": {"textbook": 0.05, "web": 0.08, "note": 0.12},
    "notes": {"note": 0.15, "textbook": 0.05},
    "exam": {"web": 0.05, "qa": 0.05, "note": 0.05},
    "exercise": {"qa": 0.12, "textbook": 0.06},
    "paper": {"paper": 0.18},
    "lab": {"repo": 0.10, "dataset": 0.10},
    "project": {"repo": 0.12},
    "intro": {"course": 0.06, "textbook": 0.06},
}
KIND_INTENT = {"video": "video", "course": "course", "textbook": "textbook"}

# 资料类型对「学生找课程资料」的默认有用程度
KIND_UTILITY = {
    "course": 0.92,
    "textbook": 1.00,
    "note": 0.95,
    "video": 0.86,
    "qa": 0.80,
    "repo": 0.80,
    "paper": 0.76,
    "reference": 0.70,
    "dataset": 0.70,
    "web": 0.72,
    "link": 0.30,
}
# 意图 × 类型的修正：想找期末卷子时，一篇「高数教学法论文」不是他要的
INTENT_KIND_UTILITY = {
    ("exam", "paper"): 0.45,
    ("exam", "web"): 0.90,
    ("exam", "note"): 1.00,
    ("exercise", "paper"): 0.45,
    ("review", "paper"): 0.45,
    ("slides", "paper"): 0.50,
    ("notes", "paper"): 0.50,
    ("textbook", "paper"): 0.50,
    ("video", "paper"): 0.45,
    ("course", "paper"): 0.55,
    ("kaoyan", "paper"): 0.60,
    ("paper", "paper"): 1.15,
    ("paper", "web"): 0.50,
    ("paper", "video"): 0.50,
}

EXAM_HINTS = ("期末", "期中", "真题", "试卷", "答案", "考点", "复习", "提纲", "题库", "习题")


def _coverage(q: Set[str], hay: Set[str]) -> float:
    if not q:
        return 0.0
    return len(q & hay) / len(q)


def relevance(res: Resource, q: Query, q_tokens: Set[str]) -> float:
    title_t = tokens(res.title)
    desc_t = tokens(f"{res.description} {res.org} {' '.join(res.authors)} {res.extra.get('tags', '')}")
    cov_title = _coverage(q_tokens, title_t)
    cov_all = _coverage(q_tokens, title_t | desc_t)
    rel = 0.7 * cov_title + 0.3 * cov_all
    # 核心词整体出现（中文标题里常见），再加一点
    if q.core and q.core.lower() in (res.title or "").lower():
        rel = min(1.0, rel + 0.12)
    # 意图匹配
    for mod in q.modifiers:
        rel += WANT_BOOST.get(mod, {}).get(res.kind, 0.0)
    # 想找考试资料时，标题里带「期末/真题/考点」的才真相关
    if (q.wants("exam") or q.wants("review")) and any(h in res.title for h in EXAM_HINTS):
        rel += 0.10
    return max(0.0, min(1.0, rel))


def utility(res: Resource, q: Query | None = None) -> float:
    u = KIND_UTILITY.get(res.kind, 0.7)
    if q:
        for mod in q.modifiers:
            u *= INTENT_KIND_UTILITY.get((mod, res.kind), 1.0)
    return u


def quality(res: Resource, q: Query | None = None) -> float:
    base = SOURCE_QUALITY.get(res.source, 0.55)
    ex = res.extra or {}
    # 社区热度信号：对数压缩，避免一个 10 万星的仓库压死所有结果
    if res.source == "github" and ex.get("stars"):
        base += min(0.12, math.log10(max(int(ex["stars"]), 1)) / 50)
    if res.source == "bilibili" and ex.get("play"):
        play = int(ex["play"]) if str(ex["play"]).isdigit() else 0
        if play:
            base += min(0.10, math.log10(play) / 60)
    if res.source in ("openalex", "crossref") and ex.get("citations"):
        base += min(0.08, math.log10(max(int(ex["citations"]), 1)) / 60)
    if ex.get("is_oa") or res.pdf_url:
        base += 0.04  # 有合法全文，能直接用
    if res.extra.get("national"):
        base += 0.03  # 国家级课程
    return max(0.0, min(1.0, base * utility(res, q)))


def recency(res: Resource, now_year: int | None = None) -> float:
    now_year = now_year or time.localtime().tm_year
    if not res.year:
        return 0.45
    age = max(0, now_year - int(res.year))
    return max(0.15, 1.0 - age / 18)


def lang_fit(res: Resource, q: Query) -> float:
    if q.lang == "zh":
        return 1.0 if res.lang == "zh" else 0.55
    if q.lang == "en":
        return 1.0 if res.lang == "en" else 0.6
    return 0.8


def score_all(resources: Sequence[Resource], q: Query) -> List[Resource]:
    q_tokens = tokens(q.core) | tokens(q.raw)
    for r in resources:
        r.relevance = relevance(r, q, q_tokens)
        r.quality = quality(r, q)
        r.score = min(
            100.0,
            100.0
            * (
                0.60 * r.relevance
                + 0.20 * r.quality
                + 0.10 * recency(r)
                + 0.10 * lang_fit(r, q)
            ),
        )
    return list(resources)


def dedupe(resources: Iterable[Resource]) -> List[Resource]:
    """同 URL 或近同标题合并；保留元数据更全、质量更高的一条。"""
    by_url: Dict[str, Resource] = {}
    kept: List[Resource] = []
    for r in resources:
        key = normalize_url(r.url) or norm_title(r.title)
        if key and key in by_url:
            _merge(by_url[key], r)
            continue
        # 标题指纹近同（同类型）也算重复
        fp = norm_title(r.title)
        dup = None
        if fp:
            for k in kept:
                if k.kind != r.kind:
                    continue
                kp = norm_title(k.title)
                if not kp:
                    continue
                if kp == fp or jaccard(tokens(k.title), tokens(r.title)) >= 0.90:
                    dup = k
                    break
                # 包含关系：'高等数学讲义' vs '高等数学讲义完整版'
                shorter, longer = (kp, fp) if len(kp) <= len(fp) else (fp, kp)
                if len(shorter) >= 6 and shorter in longer and len(shorter) / len(longer) >= 0.6:
                    dup = k
                    break
        if dup is not None:
            _merge(dup, r)
            continue
        if key:
            by_url[key] = r
        kept.append(r)
    return kept


def _merge(dst: Resource, src: Resource) -> None:
    """把 src 的信息补进 dst（不重复）。"""
    if src.quality > dst.quality and not dst.excerpt:
        dst.source, dst.source_label = src.source, src.source_label
    dst.description = dst.description or src.description
    dst.excerpt = dst.excerpt or src.excerpt
    dst.pdf_url = dst.pdf_url or src.pdf_url
    if not dst.year and src.year:
        dst.year = src.year
    if not dst.org and src.org:
        dst.org = src.org
    if len(src.authors) > len(dst.authors):
        dst.authors = src.authors
    for k, v in (src.extra or {}).items():
        dst.extra.setdefault(k, v)


def diversify(resources: List[Resource], limit: int, max_per_source: int = 3) -> List[Resource]:
    """防止单一源刷榜：每个源最多 max_per_source 条进最终列表。"""
    if limit <= 0:
        return resources
    out: List[Resource] = []
    counts: Dict[str, int] = {}
    overflow: List[Resource] = []
    for r in resources:
        if len(out) >= limit:
            break
        if counts.get(r.source, 0) >= max_per_source:
            overflow.append(r)
            continue
        counts[r.source] = counts.get(r.source, 0) + 1
        out.append(r)
    if len(out) < limit:
        out.extend(overflow[: limit - len(out)])
    return out


def top_by_kind(resources: List[Resource], kind: str, n: int) -> List[Resource]:
    return [r for r in resources if r.kind == kind][:n]


def group_by_kind(resources: List[Resource]) -> List[Tuple[str, List[Resource]]]:
    from .models import KIND_LABELS

    order = ["course", "video", "textbook", "note", "paper", "qa", "repo", "dataset", "reference", "web", "link"]
    buckets: Dict[str, List[Resource]] = {}
    for r in resources:
        buckets.setdefault(r.kind, []).append(r)
    return [(k, buckets[k]) for k in order if k in buckets] + [
        (k, v) for k, v in buckets.items() if k not in order
    ]
