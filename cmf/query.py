# -*- coding: utf-8 -*-
"""Query understanding: 核心课程主体 vs. 学习意图修饰词。

"高等数学 期末复习"      -> core="高等数学", mods={exam, review}
"高等数学期末复习"        -> core="高等数学", mods={exam, review}   ← 中文没空格，按后缀剥离
"数据结构 实验 报告"      -> core="数据结构", mods={lab}
"calculus final exam"   -> core="calculus", mods={exam}

只剥「后缀」和「空格分隔的整词」：中文课程名很少以意图词开头（"课程设计"是课名不是"课程"），
按后缀剥可以避免把课名 cutter 成残废。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_SPLIT = re.compile(r"[\s,，、;；/|+]+")

# 学习意图词：出现即认为用户在意「什么形式的资料」
MODIFIERS = {
    # 考试
    "期末": "exam", "期中": "exam", "考试": "exam", "真题": "exam", "试卷": "exam",
    "往年": "exam", "题库": "exam", "答案": "answer", "解析": "answer", "题解": "answer",
    "解答": "answer",
    "exam": "exam", "final": "exam", "midterm": "exam", "pastpaper": "exam",
    # 复习
    "复习": "review", "刷题": "review", "重点": "review", "考点": "review",
    "提纲": "review", "总结": "review", "review": "review", "summary": "review",
    # 讲义/课件
    "课件": "slides", "ppt": "slides", "幻灯": "slides", "slides": "slides",
    "讲义": "notes", "笔记": "notes", "教案": "notes", "notes": "notes",
    "lecture": "notes", "handout": "notes",
    # 教材
    "教材": "textbook", "电子版": "textbook", "课本": "textbook", "textbook": "textbook",
    "ebook": "textbook",
    # 视频/课程
    "视频": "video", "网课": "video", "公开课": "video", "慕课": "video", "mooc": "video",
    "video": "video", "录像": "video",
    "课程": "course", "大纲": "syllabus", "教学大纲": "syllabus", "syllabus": "syllabus",
    # 练习
    "习题": "exercise", "作业": "exercise", "练习": "exercise", "exercise": "exercise",
    "homework": "exercise", "assignment": "exercise", "problem": "exercise",
    # 实践
    "实验": "lab", "项目": "project", "大作业": "project", "课设": "project", "lab": "lab",
    "project": "project",
    # 升学/进阶
    "考研": "kaoyan", "保研": "baoyan", "竞赛": "contest", "入门": "intro", "速成": "intro",
    "论文": "paper", "文献": "paper", "综述": "paper", "paper": "paper",
    "cheatsheet": "cheatsheet", "速查": "cheatsheet",
}
_MODS_BY_LEN = sorted(MODIFIERS, key=len, reverse=True)

# 只输课名时，搜索引擎 / GitHub / 平台入口用这些学习向词扩展，避免只搜课名。
STUDY_EXPANSIONS_ZH = ("习题", "真题", "讲义", "题解")
STUDY_EXPANSIONS_EN = ("exercises", "past papers", "lecture notes", "solutions")

# 只在「空格分隔的整词」或「结尾」时才剥的噪声词（"大学物理" 里的"大学"绝不能剥）
SAFE_NOISE = {
    "免费": "", "下载": "", "在线": "", "高清": "", "完整版": "", "全套": "",
    "最新": "", "超全": "", "整理": "", "无水印": "", "免费下载": "",
}
_NOISE_BY_LEN = sorted(SAFE_NOISE, key=len, reverse=True)


@dataclass
class Query:
    raw: str
    core: str
    terms: List[str] = field(default_factory=list)
    modifiers: Set[str] = field(default_factory=set)
    lang: str = "en"  # zh / en / mixed

    @property
    def is_zh(self) -> bool:
        return self.lang in ("zh", "mixed")

    def wants(self, tag: str) -> bool:
        return tag in self.modifiers

    def with_intent(self) -> str:
        """课名 + 用户真正写上的意图词。噪声词（免费/下载）丢掉，意图词保留。

        「高等数学 期末复习」保持原样，不会被收成只有「高等数学」。
        """
        parts = [p for p in _SPLIT.split(self.raw) if p]
        kept: List[str] = []
        for p in parts:
            if p in SAFE_NOISE or p.lower() in SAFE_NOISE:
                continue
            kept.append(p)
        text = " ".join(kept).strip()
        return text or self.core or self.raw

    def search_string(self) -> str:
        """发给搜索引擎的主查询：保留意图词，不再只返回课名。"""
        return self.with_intent()

    def _study_terms(self) -> tuple:
        if self.lang == "en" and not self.is_zh:
            return STUDY_EXPANSIONS_EN
        return STUDY_EXPANSIONS_ZH

    def engine_queries(self) -> List[str]:
        """百度 / 必应 / 搜狗实际发出的查询。

        用户写了意图词就原样搜这一条；只输课名时再扩展习题/真题/讲义/题解，
        每条单独搜（搜索引擎把空格当 AND，不能拼成一个长 AND）。
        """
        primary = self.with_intent()
        if self.modifiers:
            return [primary]
        subject = self.core or primary
        out = [primary]
        for term in self._study_terms():
            expanded = f"{subject} {term}".strip()
            if expanded and expanded not in out:
                out.append(expanded)
        return out

    def github_query(self) -> str:
        """GitHub 仓库搜索。只输课名时附上 notes/solutions/题解/讲义。"""
        subject = self.with_intent()
        if self.modifiers:
            return f"{subject} in:name,description,readme"
        if self.lang == "en" and not self.is_zh:
            extra = "exercises OR solutions OR notes OR lecture"
        else:
            extra = "习题 OR 题解 OR 讲义 OR notes OR solutions"
        head = self.core or subject
        return f"{head} ({extra}) in:name,description,readme"

    def portal_query(self) -> str:
        """平台入口链接上的检索词。付费/登录站只生成链接，不抓正文。"""
        if self.modifiers:
            return self.with_intent()
        subject = self.core or self.with_intent()
        if self.lang == "en" and not self.is_zh:
            return f"{subject} exercises notes solutions"
        return f"{subject} 习题 真题 讲义 题解"


def detect_lang(text: str) -> str:
    text = text or ""
    cjk = len(CJK_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk and latin:
        return "mixed" if cjk >= 2 else "en"
    if cjk:
        return "zh"
    return "en"


def _strip_suffix(core: str, mods: Set[str]) -> str:
    """反复剥掉结尾的意图词：'高等数学期末复习' -> '高等数学'。"""
    changed = True
    while changed and len(core) > 2:
        changed = False
        for key in _MODS_BY_LEN:
            if len(core) - len(key) < 2:
                continue
            if core.lower().endswith(key):
                mods.add(MODIFIERS[key])
                core = core[: -len(key)].strip()
                changed = True
                break
        for key in _NOISE_BY_LEN:
            if len(core) - len(key) < 2:
                continue
            if core.lower().endswith(key):
                core = core[: -len(key)].strip()
                changed = True
                break
    return core


def parse(text: str) -> Query:
    raw = " ".join((text or "").split())
    parts = [p for p in _SPLIT.split(raw) if p]
    mods: Set[str] = set()
    keep: List[str] = []
    for p in parts:
        key = p.lower()
        if key in MODIFIERS:
            mods.add(MODIFIERS[key])
            continue
        if p in SAFE_NOISE:
            continue
        keep.append(p)

    core = " ".join(keep).strip()
    core = _strip_suffix(core, mods).strip(" 的")
    if len(core.replace(" ", "")) < 2:
        core = raw
    return Query(raw=raw, core=core, terms=keep, modifiers=mods, lang=detect_lang(raw))
