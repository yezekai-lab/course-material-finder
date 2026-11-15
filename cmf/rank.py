# -*- coding: utf-8 -*-
"""Ranking & dedupe.

score = 100 * (0.60*相关度 + 0.20*源质量 + 0.10*时效 + 0.10*语言匹配)
相关度只用「查询词的 token 覆盖率」算。默认有用程度偏向习题、真题、题解、
讲义和复习，教材/官方课可以留下，但不再压过这些学习资料。
"""
from __future__ import annotations

import math
import time
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .models import Resource
from .query import Query
from .textutil import jaccard, norm_title, normalize_url, tokens

# 各数据源的质量先验（0~1）。
# 能稳定露出习题/真题/讲义/复习的源略高；开放教材和官方慕课保留但不再最高；
# 论文库默认压低，只有用户明确要论文时再加回来（见 quality()）。
SOURCE_QUALITY = {
    "bilibili": 0.84,
    "stackexchange": 0.78,
    "github": 0.76,
    "ocw": 0.78,
    "openstax": 0.76,
    "baidu": 0.74,
    "chinaooc": 0.74,
    "otl": 0.74,
    "bing": 0.72,
    "wikibooks": 0.70,
    "wikipedia": 0.66,
    "sogou": 0.62,
    "openalex": 0.58,
    "arxiv": 0.58,
    "zenodo": 0.56,
    "crossref": 0.56,
    "doaj": 0.54,
    "europepmc": 0.50,
    "gutendex": 0.48,
    "portals": 0.40,
}

PAPER_SOURCES = {"openalex", "crossref", "doaj", "arxiv", "europepmc"}
COURSE_SOURCES = {"chinaooc", "ocw"}

# 用户意图 → 哪种资料类型在相关度上加分。
# 找习题时不加教材：教材可以留下，但不能因为意图词被抬上去。
WANT_BOOST = {
    "video": {"video": 0.16, "explanation": 0.12, "course": 0.08},
    "course": {"course": 0.16, "video": 0.08, "official": 0.04},
    "textbook": {"textbook": 0.16},
    "slides": {"slides": 0.16, "note": 0.06},
    "notes": {"note": 0.16, "review": 0.06, "slides": 0.04},
    "exam": {"exam": 0.16, "solution": 0.10, "review": 0.08, "exercise": 0.05, "qa": 0.04},
    "exercise": {"exercise": 0.16, "solution": 0.12, "qa": 0.06, "note": 0.04},
    "answer": {"solution": 0.16, "exercise": 0.08, "exam": 0.05, "qa": 0.04},
    "review": {"review": 0.16, "note": 0.08, "video": 0.08, "explanation": 0.08},
    "kaoyan": {"exam": 0.12, "review": 0.10, "video": 0.10, "exercise": 0.08, "solution": 0.08},
    "cheatsheet": {"review": 0.14, "note": 0.10, "slides": 0.06},
    "paper": {"paper": 0.18, "reference": 0.04},
    "lab": {"repo": 0.10, "dataset": 0.10},
    "project": {"repo": 0.12},
    "intro": {"video": 0.08, "explanation": 0.08, "note": 0.05, "course": 0.04},
    "syllabus": {"official": 0.16, "course": 0.06},
}

# 默认有用程度：只输课名时，学习向类型不低于教材。
# 教材/课程留在中上，论文和百科默认靠后。
KIND_UTILITY = {
    "exercise": 1.00,
    "exam": 1.00,
    "solution": 1.00,
    "review": 0.98,
    "note": 0.98,
    "slides": 0.96,
    "explanation": 0.96,
    "video": 0.94,
    "qa": 0.90,
    "repo": 0.72,
    "web": 0.70,
    "textbook": 0.62,
    "course": 0.60,
    "official": 0.58,
    "reference": 0.64,
    "dataset": 0.50,
    "paper": 0.38,
    "link": 0.30,
}
STUDY_KIND_SET = {
    "exercise", "exam", "solution", "review", "explanation", "note", "slides", "video", "qa",
}

# 意图 × 类型的乘数。论文在找课的时候再乘一次，明确要论文时才抬回去。
INTENT_KIND_UTILITY = {
    ("exam", "paper"): 0.35,
    ("exam", "reference"): 0.70,
    ("exam", "textbook"): 0.70,
    ("exam", "course"): 0.72,
    ("exam", "official"): 0.70,
    ("exercise", "paper"): 0.40,
    ("exercise", "reference"): 0.70,
    ("exercise", "textbook"): 0.65,
    ("exercise", "course"): 0.70,
    ("exercise", "official"): 0.70,
    ("answer", "paper"): 0.40,
    ("answer", "textbook"): 0.68,
    ("answer", "course"): 0.72,
    ("review", "paper"): 0.40,
    ("review", "reference"): 0.75,
    ("review", "textbook"): 0.75,
    ("review", "course"): 0.75,
    ("slides", "paper"): 0.45,
    ("slides", "textbook"): 0.75,
    ("notes", "paper"): 0.45,
    ("notes", "textbook"): 0.75,
    ("kaoyan", "paper"): 0.45,
    ("kaoyan", "textbook"): 0.70,
    ("video", "paper"): 0.45,
    ("course", "paper"): 0.55,
    ("intro", "paper"): 0.50,
    ("textbook", "paper"): 0.55,
    ("textbook", "textbook"): 1.70,
    ("textbook", "exercise"): 0.85,
    ("textbook", "exam"): 0.80,
    ("paper", "paper"): 3.00,
    ("paper", "reference"): 1.25,
    ("paper", "web"): 0.55,
    ("paper", "video"): 0.45,
    ("paper", "exam"): 0.50,
    ("paper", "exercise"): 0.50,
    ("paper", "solution"): 0.50,
    ("paper", "review"): 0.50,
    ("paper", "note"): 0.55,
    ("paper", "textbook"): 0.70,
    ("paper", "course"): 0.60,
    ("course", "course"): 1.35,
    ("video", "course"): 1.25,
    ("video", "video"): 1.12,
    ("syllabus", "official"): 1.40,
}

# 标题里出现这些词，说明这条真的是用户要的那种资料（相关度小幅加分，上限仍是 1）。
TITLE_HINTS = {
    "exam": ("期末", "期中", "真题", "试卷", "试题", "past paper", "final", "midterm"),
    "review": ("复习", "考点", "提纲", "考纲", "cheatsheet"),
    "exercise": ("习题", "练习", "作业", "homework", "exercise", "problem set"),
    "answer": ("题解", "答案", "解析", "solution"),
    "notes": ("讲义", "笔记", "notes", "handout"),
    "slides": ("课件", "ppt", "slides", "幻灯"),
    "kaoyan": ("考研",),
    "cheatsheet": ("cheatsheet", "速查", "考点"),
}

# 最终名单里，教材/课程/论文不能按「每个源 3 条」无限占坑。
DEFAULT_KIND_CAPS = {
    "textbook": 4,
    "course": 3,
    "official": 2,
    "paper": 2,
    "reference": 2,
}
DEFAULT_FAMILY_CAPS = {"canonical": 8}


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
    # 意图匹配。加分按类型给，找习题时不会加到教材上。
    for mod in q.modifiers:
        rel += WANT_BOOST.get(mod, {}).get(res.kind, 0.0)
    title_l = (res.title or "").lower()
    for mod in q.modifiers:
        if any(h.lower() in title_l for h in TITLE_HINTS.get(mod, ())):
            rel += 0.08
            break
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
    # 本科课查询默认压着论文库；用户明确要论文时再抬回来。
    if q and q.wants("paper") and res.source in PAPER_SOURCES:
        base += 0.14
    if q and (q.wants("course") or q.wants("video") or q.wants("syllabus")) and res.source in COURSE_SOURCES:
        base += 0.08
    # 仓库名/简介已经标成题解、讲义、习题时，比一个普通代码仓库更有用。
    if res.source == "github" and res.kind in STUDY_KIND_SET:
        base += 0.05
    # 社区热度信号：对数压缩，避免一个 10 万星的仓库压死所有结果
    if res.source == "github" and ex.get("stars"):
        base += min(0.12, math.log10(max(int(ex["stars"]), 1)) / 50)
    if res.source == "bilibili" and ex.get("play"):
        play = int(ex["play"]) if str(ex["play"]).isdigit() else 0
        if play:
            base += min(0.10, math.log10(play) / 60)
    if res.source in ("openalex", "crossref") and ex.get("citations"):
        base += min(0.06, math.log10(max(int(ex["citations"]), 1)) / 80)
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


def _caps_for(q: Query | None, limit: int) -> Tuple[Dict[str, int], Dict[str, int]]:
    kind_caps = dict(DEFAULT_KIND_CAPS)
    family_caps = dict(DEFAULT_FAMILY_CAPS)
    if q is None:
        return kind_caps, family_caps
    if q.wants("paper"):
        kind_caps["paper"] = max(limit, 1)
    if q.wants("textbook"):
        kind_caps["textbook"] = max(8, limit // 2)
        family_caps["canonical"] = max(family_caps.get("canonical", 8), kind_caps["textbook"] + 2)
    if q.wants("course") or q.wants("video"):
        kind_caps["course"] = max(6, limit // 3)
        family_caps["canonical"] = max(family_caps.get("canonical", 8), kind_caps["course"] + 2)
    if q.wants("syllabus"):
        kind_caps["official"] = max(6, kind_caps.get("official", 2))
        family_caps["canonical"] = max(family_caps.get("canonical", 8), kind_caps["official"] + 2)
    return kind_caps, family_caps


def diversify(
    resources: List[Resource],
    limit: int,
    max_per_source: int = 3,
    max_per_kind: Dict[str, int] | None = None,
    q: Query | None = None,
) -> List[Resource]:
    """每个源有上限，教材/课程/论文还有类型上限。

    类型上限优先于「把名单凑满」：先收下学习向结果，教材只占少量坑。
    只有剩下的全是被封顶的类型时，才放宽上限，避免整页空白。
    """
    from .models import kind_family_of

    if limit <= 0:
        return list(resources)
    kind_caps, family_caps = _caps_for(q, limit)
    if max_per_kind:
        kind_caps.update(max_per_kind)

    out: List[Resource] = []
    source_counts: Dict[str, int] = {}
    kind_counts: Dict[str, int] = {}
    family_counts: Dict[str, int] = {}
    deferred_source: List[Resource] = []
    deferred_kind: List[Resource] = []

    def kind_blocked(kind: str) -> bool:
        cap = kind_caps.get(kind)
        if cap is not None and kind_counts.get(kind, 0) >= cap:
            return True
        fam = kind_family_of(kind)
        fam_cap = family_caps.get(fam)
        return fam_cap is not None and family_counts.get(fam, 0) >= fam_cap

    def add(r: Resource) -> None:
        out.append(r)
        source_counts[r.source] = source_counts.get(r.source, 0) + 1
        kind_counts[r.kind] = kind_counts.get(r.kind, 0) + 1
        fam = kind_family_of(r.kind)
        family_counts[fam] = family_counts.get(fam, 0) + 1

    for r in resources:
        if len(out) >= limit:
            break
        if kind_blocked(r.kind):
            deferred_kind.append(r)
            continue
        if source_counts.get(r.source, 0) >= max_per_source:
            deferred_source.append(r)
            continue
        add(r)

    if len(out) < limit:
        for r in deferred_source:
            if len(out) >= limit:
                break
            if kind_blocked(r.kind):
                deferred_kind.append(r)
                continue
            add(r)

    if len(out) < limit:
        for r in deferred_kind:
            if len(out) >= limit:
                break
            add(r)
    return out


def top_by_kind(resources: List[Resource], kind: str, n: int) -> List[Resource]:
    return [r for r in resources if r.kind == kind][:n]


def group_by_kind(resources: List[Resource]) -> List[Tuple[str, List[Resource]]]:
    from .models import KIND_ORDER

    buckets: Dict[str, List[Resource]] = {}
    for r in resources:
        buckets.setdefault(r.kind, []).append(r)
    ordered = [(k, buckets[k]) for k in KIND_ORDER if k in buckets]
    ordered += [(k, v) for k, v in buckets.items() if k not in KIND_ORDER]
    return ordered


def group_by_family(resources: List[Resource]) -> List[Tuple[str, List[Resource]]]:
    """分类清单：学习向资料 → 教材与官方文档 → 其他。同一族里按 kind 顺序，族内保持原排序。"""
    from .models import KIND_ORDER, kind_family_of

    buckets: Dict[str, List[Resource]] = {"study": [], "canonical": [], "other": []}
    index = {k: i for i, k in enumerate(KIND_ORDER)}
    for r in resources:
        if r.kind == "link":
            continue
        buckets.setdefault(kind_family_of(r.kind), []).append(r)
    sections: List[Tuple[str, List[Resource]]] = []
    for fam in ("study", "canonical", "other"):
        items = buckets.get(fam) or []
        if not items:
            continue
        items = sorted(items, key=lambda r: index.get(r.kind, 99))
        sections.append((fam, items))
    return sections


def rank_resources(resources: Sequence[Resource], q: Query) -> List[Resource]:
    """分类 → 去重 → 打分 → 按分排序。引擎的预览和最终结果都走这里。"""
    from .classify import apply_kinds

    items = apply_kinds(list(resources), q)
    items = score_all(dedupe(items), q)
    items.sort(key=lambda r: -r.score)
    return items
