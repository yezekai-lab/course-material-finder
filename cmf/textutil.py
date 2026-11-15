# -*- coding: utf-8 -*-
"""Text / URL helpers. No third-party deps: bs4 is not installed by default."""
from __future__ import annotations

import html as html_mod
import re
import unicodedata
from typing import Iterable, List, Set
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ---------------------------------------------------------------- HTML -> text

_BLOCK_TAGS = (
    "p|div|br|li|ul|ol|h1|h2|h3|h4|h5|h6|tr|td|th|table|section|article|"
    "header|footer|blockquote|pre|figure|figcaption|dd|dt|dl|hr"
)
_STRIP_TAGS = r"script|style|noscript|svg|iframe|template|nav|form|aside|button|select"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\u00a0\u3000]+")


def strip_html(text) -> str:
    """Tags out, entities in, whitespace collapsed. Handles the highlight spans
    that Baidu/Bilibili/chinaooc embed (<span class="...">高等数学</span>).

    Defensive about types: upstream APIs occasionally return dict/list values
    (chinaooc 的 tags 就是 [{'tagName': ...}]）。
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        if isinstance(text, dict):
            for k in ("tagName", "name", "title", "text", "value", "keyword", "label"):
                if text.get(k):
                    return strip_html(text[k])
            return ""
        if isinstance(text, (list, tuple)):
            return " ".join(x for x in (strip_html(i) for i in text) if x)
        return str(text)
    if not text:
        return ""
    s = re.sub(r"<(%s)\b[^>]*>.*?</\1>" % _STRIP_TAGS, " ", text, flags=re.S | re.I)
    s = re.sub(r"<(%s)\b[^>]*>" % _BLOCK_TAGS, "\n", s, flags=re.I)
    s = _TAG_RE.sub("", s)
    s = html_mod.unescape(s)
    s = s.replace("\u200b", "").replace("\ufeff", "")
    s = _WS_RE.sub(" ", s)
    lines = [ln.strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def squash(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").replace("\r", " ").replace("\n", " ")).strip()


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\'](?:description|Description)["\'][^>]+content=["\'](.*?)["\']',
    re.S | re.I,
)
_META_DESC_RE2 = re.compile(
    r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\'](?:description|Description)["\']',
    re.S | re.I,
)
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', re.S | re.I
)


def page_title(html: str) -> str:
    m = _TITLE_RE.search(html or "")
    return squash(html_mod.unescape(_TAG_RE.sub("", m.group(1)))) if m else ""


def page_description(html: str) -> str:
    for rx in (_META_DESC_RE, _META_DESC_RE2, _OG_DESC_RE):
        m = rx.search(html or "")
        if m:
            return squash(html_mod.unescape(_TAG_RE.sub("", m.group(1))))
    return ""


NAV_LINES = {
    "首页", "课程", "教材", "资讯", "登录", "注册", "搜索", "下一页", "上一页",
    "查看更多", "展开", "收起", "关闭", "目录", "评论", "收藏", "分享", "举报",
    "虚仿实验", "教师教研", "研究生教育", "创课平台", "课外成长", "专题",
    "慕课西部行", "番剧", "直播", "游戏中心", "会员购", "漫画", "赛事", "投稿",
    "课程总结", "收起全部章节", "关闭课程总结", "扫码下载", "客户端",
}

# 站点级样板句，出现在正文最前面
BOILERPLATE = re.compile(
    r"^\s*(?:skip to (?:main )?content\.?\s*|"
    r"you are offline and only viewing locally cached content\.?\s*|"
    r"本站(?:首页|导航)\.?\s*|"
    r"登录\s*注册\s*)",
    re.I,
)


def strip_boilerplate(text: str) -> str:
    """反复剥掉开头样板句（常见：Skip to content → You are offline …）。"""
    for _ in range(6):
        new = BOILERPLATE.sub("", text)
        if new == text:
            break
        text = new
    return text.strip()


def extract_main_text(html: str, limit: int = 1200) -> str:
    """Boilerplate-light extraction: drop chrome, keep the densest text block.

    Deliberately simple — it only ever feeds a short excerpt in the report.
    """
    if not html:
        return ""
    body = html
    m = re.search(r"<body[^>]*>(.*?)</body>", html, re.S | re.I)
    if m:
        body = m.group(1)
    text = strip_html(body)
    if not text:
        return ""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    # 去掉导航/按钮这类短行：站点越多，短行越是垃圾
    if len(lines) > 8:
        lines = [
            ln
            for ln in lines
            if ln not in NAV_LINES and (len(ln) >= 10 or re.search(r"[，。！？；,.]", ln))
        ]
    if not lines:
        return squash(text)[:limit]
    # 很多站点同一内容存在桌面/移动两份 DOM，长行只保留第一次出现
    seen: set = set()
    uniq = []
    for ln in lines:
        if len(ln) >= 20:
            if ln in seen:
                continue
            seen.add(ln)
        uniq.append(ln)
    lines = uniq
    filtered = "\n".join(lines)
    filtered = strip_boilerplate(filtered)
    if len(filtered) <= limit:
        return squash(filtered)
    # 取密度最高的一段连续文本
    best, cur = [], []
    for ln in lines:
        cur.append(ln)
        if sum(len(x) for x in cur) >= limit * 2:
            if sum(len(x) for x in cur) > sum(len(x) for x in best):
                best = list(cur)
            cur = []
    if sum(len(x) for x in cur) > sum(len(x) for x in best):
        best = cur
    out = squash(" ".join(best or lines))[:limit]
    return strip_boilerplate(out)


# ------------------------------------------------------------------ tokenising

CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
WORD = re.compile(r"[a-z][a-z0-9+#.\-]{1,23}")
STOP = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with", "by",
    "introduction", "intro", "lecture", "lectures", "notes", "note", "course",
    "courses", "chapter", "part", "vol", "edition", "pdf", "pp", "http", "https",
    "www", "com", "org", "html", "htm",
}
# 中文虚词/泛词：不参与相关性判断，否则任何中文结果都"命中"
# 虚词和站点套话不参与相关度。习题/真题/讲义/期末这类意图词要留下，
# 否则「高等数学 习题」和一本只叫「高等数学」的教材覆盖率一样。
ZH_STOP = {
    "的", "了", "和", "与", "及", "或", "在", "是", "我", "你", "他", "它",
    "课程", "资料", "资源", "学习", "大学", "学生", "老师", "免费", "下载",
    "教学", "基础", "全套", "最新", "完整", "高清", "中文", "百度", "知乎", "文库",
}


def tokens(text: str) -> Set[str]:
    """Latin words (len>=2) + CJK bigrams. Good enough for ranking CJK titles."""
    text = (text or "").lower()
    out: Set[str] = set()
    for w in WORD.findall(text):
        w = w.strip(".-")
        if len(w) >= 2 and w not in STOP:
            out.add(w)
    for run in CJK_RUN.findall(text):
        if len(run) == 1:
            if run not in ZH_STOP:
                out.add(run)
            continue
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg not in ZH_STOP:
                out.add(bg)
    return out


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def norm_title(title: str) -> str:
    """Fingerprint for cross-source dedupe."""
    t = unicodedata.normalize("NFKC", title or "").lower()
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t)
    return t


# ----------------------------------------------------------------------- URLs

_TRACKING = re.compile(
    r"^(utm_|spm|from|ref|referrer|source|share|fr|vd_source|buvid|mid|"
    r"search_query|trackid|sa|ved|usg|opi|fenlei|click|session)",
    re.I,
)


def normalize_url(url: str) -> str:
    """Canonical form for dedupe: drop fragment/tracking, sort query, unify host."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^https?://", url, re.I):
        return url
    sp = urlsplit(url)
    host = sp.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    q = [(k, v) for k, v in parse_qsl(sp.query, keep_blank_values=False) if not _TRACKING.match(k)]
    q.sort()
    path = sp.path.rstrip("/") or "/"
    return urlunsplit((sp.scheme.lower() if sp.scheme else "https", host, path, urlencode(q), ""))


def domain(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return ""


def slugify(text: str, maxlen: int = 60) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", t, flags=re.UNICODE).strip("-")
    t = re.sub(r"-{2,}", "-", t)
    return (t or "query")[:maxlen].strip("-") or "query"


def safe_filename(name: str, maxlen: int = 80) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "")
    name = name.strip(" ._")
    return (name or "file")[:maxlen]
