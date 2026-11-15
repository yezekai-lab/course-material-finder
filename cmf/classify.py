# -*- coding: utf-8 -*-
"""把来源给的默认类型，按标题 / 摘要重分成约定的 kind。

来源只提供默认值（教材站 → textbook，搜索引擎 → web，论文库 → paper）。
能从标题看出来的学习向类型会改标；看不准就保持默认，不猜成习题或真题。
访问状态（已抓正文 / 被反爬 / 仅链接）不参与分类。
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set

from .models import Resource
from .query import Query

# 论文、百科、数据集、平台入口不改标：入口不是资料，论文标题里出现「习题」也仍是论文。
_FROZEN = {"paper", "reference", "dataset", "link"}

# 摘要只对「本身就很杂」的类型有用。教材/课程页的简介经常写「含习题、考试」，
# 不能据此把整本教材改成习题。
_SNIPPET_KINDS = {"web", "note", "video"}

# 摘要里只认复合词，避免「适合复习」「附答案」把整页改标。
_SNIPPET_RULES = [
    ("solution", re.compile(
        r"题解|习题解答|习题解析|习题详解|习题答案|真题解析|真题详解|试卷解析|"
        r"答案解析|参考答案|标准答案|(?<!完)全解|\bsolutions?\b|\banswer key\b|\bworked solutions?\b",
        re.I,
    )),
    ("exercise", re.compile(
        r"习题|练习题|课后练习|课后作业|\bhomework\b|\bassignments?\b|"
        r"\bproblem sets?\b|\bexercises?\b|\bp-?sets?\b",
        re.I,
    )),
    ("slides", re.compile(r"课件|\bpptx?\b|\bslides?\b|幻灯", re.I)),
    ("exam", re.compile(
        r"真题|试卷|试题|模拟卷|模拟题|past papers?|\bfinal exam\b|\bmidterms?\b",
        re.I,
    )),
    ("review", re.compile(
        r"复习提纲|复习大纲|复习笔记|期末复习|期中复习|考点|考纲|知识总结|章节总结|"
        r"cheatsheets?|cheat sheet",
        re.I,
    )),
    ("note", re.compile(r"讲义|笔记|教案|lecture notes|\bnotes\b|\bhandouts?\b", re.I)),
    ("explanation", re.compile(r"精讲|串讲|\btutorials?\b|\bwalkthroughs?\b", re.I)),
    ("official", re.compile(r"教学大纲|课程大纲|\bsyllabus\b", re.I)),
]

# 标题可以更宽一点：短标题里的「复习 / 答案 / 期末」就是资料类型。
_TITLE_RULES = _SNIPPET_RULES + [
    ("solution", re.compile(r"答案|解答", re.I)),
    ("exercise", re.compile(r"练习|作业", re.I)),
    ("review", re.compile(r"复习|提纲|总结", re.I)),
    ("explanation", re.compile(r"讲解", re.I)),
    ("exam", re.compile(r"期末|期中|\bfinal\b", re.I)),
    ("course", re.compile(r"慕课|中国大学mooc|爱课程|智慧教育平台|\bmoocs?\b|opencourseware|\bocw\b", re.I)),
    ("textbook", re.compile(r"教材|课本|\btextbooks?\b", re.I)),
]

_PICK_ORDER = (
    "solution", "exercise", "slides", "exam", "review",
    "note", "explanation", "official", "course", "textbook",
)


def _norm(text: str) -> str:
    return (text or "").replace("-", " ").replace("_", " ").lower()


def _hits(text: str, rules) -> Set[str]:
    found: Set[str] = set()
    if not text:
        return found
    for kind, rx in rules:
        if rx.search(text):
            found.add(kind)
    return found


def _pick(hits: Set[str], title: str, q: Optional[Query]) -> Optional[str]:
    if not hits:
        return None
    # 「教材习题解答」既像教材又像习题：题解优先，其次习题，不要落回教材。
    if "textbook" in hits and ("solution" in hits or "exercise" in hits):
        hits = set(hits)
        hits.discard("textbook")
    # 大作业不是课后习题。
    if "大作业" in title and "exercise" in hits and not re.search(r"习题|练习题|homework|exercise", title, re.I):
        hits = set(hits)
        hits.discard("exercise")
    # 「期末复习」默认是复习；用户只写了期末、没写复习时才标成试卷。
    if "exam" in hits and "review" in hits:
        exam_doc = bool(re.search(r"真题|试卷|试题|模拟|past paper|final exam|midterm", title, re.I))
        if not exam_doc:
            if q and q.wants("exam") and not q.wants("review"):
                hits = set(hits)
                hits.discard("review")
            else:
                hits = set(hits)
                hits.discard("exam")
    for kind in _PICK_ORDER:
        if kind in hits:
            return kind
    return None


def classify_kind(res: Resource, q: Optional[Query] = None) -> str:
    """返回应使用的 kind。不确定时返回原来的默认类型。"""
    default = res.kind or "web"
    if default in _FROZEN:
        return default
    title = _norm(res.title)
    hits = _hits(title, _TITLE_RULES)
    if default in _SNIPPET_KINDS:
        hits |= _hits(_norm(res.description)[:500], _SNIPPET_RULES)
    chosen = _pick(hits, title, q)
    if not chosen:
        return default
    # 只有「教材」这一个信号时，不把慕课/官方页改成教材；网页和仓库可以。
    if chosen == "textbook" and default not in {"web", "repo", "note"}:
        return default
    return chosen


def apply_kinds(resources: Iterable[Resource], q: Optional[Query] = None) -> List[Resource]:
    """就地改标。extra['kind_default'] 记下数据源给的默认类型，方便核对。"""
    out: List[Resource] = []
    for res in resources:
        new = classify_kind(res, q)
        if new != res.kind:
            extra = dict(res.extra or {})
            extra.setdefault("kind_default", res.kind)
            res.extra = extra
            res.kind = new
        out.append(res)
    return out
