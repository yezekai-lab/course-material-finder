# -*- coding: utf-8 -*-
"""学习向排序、查询词、类型重标、导出与结果页约定。全部离线。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cmf import rank  # noqa: E402
from cmf.classify import apply_kinds, classify_kind  # noqa: E402
from cmf.engine import CRAWL_BONUS  # noqa: E402
from cmf.models import (  # noqa: E402
    KIND_FAMILY,
    KIND_LABELS,
    Resource,
    SearchResult,
    SourceStatus,
    family_count_line,
    present_kinds,
)
from cmf.query import parse  # noqa: E402
from cmf.report import render_csv, render_html, render_markdown  # noqa: E402
from cmf.sources import LINK_IDS, Context  # noqa: E402
from cmf.sources.links import PORTALS  # noqa: E402
from cmf.sources.misc import GitHubSource  # noqa: E402
from cmf.sources.websearch import BaiduSource, BingSource  # noqa: E402


def R(title, kind="web", source="baidu", lang="zh", url=None, description="", **kw):
    return Resource(
        title=title,
        url=url or f"https://example.com/{abs(hash(title)) % 10**8}",
        source=source,
        kind=kind,
        lang=lang,
        description=description,
        **kw,
    )


class TestUtilityAndIntent(unittest.TestCase):
    def test_study_kinds_outrank_textbooks_by_default(self):
        floor = rank.KIND_UTILITY["textbook"]
        for kind in ("exercise", "exam", "solution", "review", "note", "slides", "explanation", "video", "qa"):
            self.assertGreaterEqual(rank.KIND_UTILITY[kind], floor, kind)
        self.assertLess(rank.KIND_UTILITY["paper"], rank.KIND_UTILITY["reference"])
        self.assertLess(rank.KIND_UTILITY["course"], floor)
        self.assertNotIn("textbook", rank.WANT_BOOST["exercise"])
        self.assertNotIn("textbook", rank.WANT_BOOST["exam"])
        self.assertNotIn("textbook", rank.WANT_BOOST["notes"])
        self.assertNotIn("textbook", rank.WANT_BOOST["slides"])

    def test_default_course_query_puts_study_materials_first(self):
        """只输课名时，公开真题/习题/复习提纲要排在官方课和教材前面，抓到正文的 +3 也翻不回来。"""
        q = parse("高等数学")
        items = [
            R("高等数学", kind="course", source="chinaooc", url="https://higher.smartedu.cn/course/1", extra={"national": True}),
            R("高等数学", kind="textbook", source="wikibooks", url="https://zh.wikibooks.org/wiki/gaoshu"),
            R("Calculus Volume 1", kind="textbook", source="openstax", lang="en", url="https://openstax.org/books/calculus-volume-1"),
            R("高等数学", kind="paper", source="openalex", url="https://openalex.org/W1"),
            R("高等数学", kind="reference", source="wikipedia", url="https://zh.wikipedia.org/wiki/gaoshu"),
            R("高等数学期末复习提纲", kind="web", source="baidu", url="https://notes.example/review"),
            R("高等数学期末真题", kind="web", source="baidu", url="https://notes.example/exam"),
            R("高等数学习题详解", kind="web", source="bing", url="https://notes.example/sol"),
        ]
        ranked = rank.rank_resources(items, q)
        top = [r for r in ranked if r.kind_family == "study"][:3]
        self.assertEqual(len(top), 3)
        self.assertLess(ranked.index(top[-1]), min(i for i, r in enumerate(ranked) if r.kind in {"course", "textbook", "paper"}))
        # 官方页更容易抓到正文。加成之后学习向仍然在前。
        for r in ranked:
            if r.kind_family == "canonical":
                r.score += CRAWL_BONUS
        ranked.sort(key=lambda r: -r.score)
        self.assertEqual(ranked[0].kind_family, "study")
        first_canonical = next(r for r in ranked if r.kind_family == "canonical")
        self.assertGreater(ranked[0].score, first_canonical.score)

    def test_exercise_intent_does_not_promote_textbooks(self):
        q = parse("高等数学 习题")
        items = [
            R("高等数学教材", kind="textbook", source="wikibooks", url="https://zh.wikibooks.org/wiki/book"),
            R("高等数学", kind="course", source="chinaooc", url="https://higher.smartedu.cn/course/2"),
            R("高等数学习题全解", kind="web", source="baidu", url="https://notes.example/ex"),
            R("高等数学课程改革论文", kind="paper", source="crossref", url="https://doi.org/10.1/x"),
        ]
        ranked = rank.rank_resources(items, q)
        self.assertEqual(ranked[0].kind, "solution")
        self.assertIn(ranked[0].kind_family, {"study"})
        book = next(r for r in ranked if r.kind == "textbook")
        self.assertGreater(ranked[0].score, book.score)
        paper = next(r for r in ranked if r.kind == "paper")
        self.assertGreater(book.score, paper.score)

    def test_review_intent_keeps_the_words_and_study_rank(self):
        q = parse("高等数学 期末复习")
        self.assertEqual(q.core, "高等数学")
        self.assertIn("exam", q.modifiers)
        self.assertIn("review", q.modifiers)
        items = [
            R("高等数学", kind="course", source="ocw", lang="en", url="https://ocw.mit.edu/courses/18-01/"),
            R("高等数学", kind="textbook", source="openstax", lang="en", url="https://openstax.org/books/calc"),
            R("高等数学期末复习", kind="video", source="bilibili", url="https://www.bilibili.com/video/BV1"),
            R("高等数学", kind="paper", source="arxiv", url="https://arxiv.org/abs/1"),
        ]
        ranked = rank.rank_resources(items, q)
        self.assertEqual(ranked[0].kind_family, "study")
        self.assertGreater(ranked[0].score, next(r.score for r in ranked if r.kind == "paper"))

    def test_paper_intent_lifts_papers(self):
        q = parse("高等数学 论文")
        plain = rank.rank_resources(
            [
                R("高等数学", kind="paper", source="openalex", url="https://openalex.org/W2"),
                R("高等数学期末真题", kind="web", source="baidu", url="https://notes.example/p"),
            ],
            parse("高等数学"),
        )
        self.assertEqual(plain[0].kind, "exam")
        focused = rank.rank_resources(
            [
                R("高等数学", kind="paper", source="openalex", url="https://openalex.org/W3"),
                R("高等数学期末真题", kind="web", source="baidu", url="https://notes.example/p2"),
            ],
            q,
        )
        self.assertEqual(focused[0].kind, "paper")


class TestDiversify(unittest.TestCase):
    def test_type_cap_keeps_textbooks_from_filling_the_list(self):
        q = parse("高等数学")
        books = [
            R(f"高等数学教材{i}", kind="textbook", source=f"press{i}", url=f"https://books.example/{i}")
            for i in range(8)
        ]
        study = [
            R(f"高等数学习题{i}", kind="exercise", source="baidu", url=f"https://ex.example/{i}")
            for i in range(6)
        ]
        # 教材分故意设得更高，类型封顶仍不能让它们占满前 10。
        for b in books:
            b.score = 90
        for s in study:
            s.score = 70
        ordered = sorted(books + study, key=lambda r: -r.score)
        out = rank.diversify(ordered, limit=10, max_per_source=3, q=q)
        self.assertEqual(len(out), 10)
        self.assertLessEqual(sum(1 for r in out if r.kind == "textbook"), 4)
        self.assertEqual(sum(1 for r in out if r.kind == "exercise"), 6)

    def test_type_cap_relaxes_when_the_corpus_is_only_textbooks(self):
        q = parse("高等数学")
        books = [
            R(f"高等数学{i}", kind="textbook", source=f"press{i}", url=f"https://only-books.example/{i}")
            for i in range(8)
        ]
        for i, b in enumerate(books):
            b.score = 80 - i
        out = rank.diversify(books, limit=6, max_per_source=3, q=q)
        self.assertEqual(len(out), 6)
        self.assertTrue(all(r.kind == "textbook" for r in out))

    def test_paper_cap_on_a_course_query(self):
        q = parse("线性代数")
        papers = [
            R(f"线性代数论文{i}", kind="paper", source=f"journal{i}", url=f"https://papers.example/{i}")
            for i in range(6)
        ]
        notes = [
            R(f"线性代数讲义{i}", kind="note", source=f"note{i}", url=f"https://notes.example/{i}")
            for i in range(5)
        ]
        for p in papers:
            p.score = 95
        for n in notes:
            n.score = 60
        ordered = sorted(papers + notes, key=lambda r: -r.score)
        out = rank.diversify(ordered, limit=7, max_per_source=3, q=q)
        self.assertLessEqual(sum(1 for r in out if r.kind == "paper"), 2)
        self.assertEqual(sum(1 for r in out if r.kind == "note"), 5)


class TestQueryStrings(unittest.TestCase):
    def test_intent_is_kept(self):
        q = parse("高等数学 期末复习")
        self.assertEqual(q.search_string(), "高等数学 期末复习")
        self.assertEqual(q.with_intent(), "高等数学 期末复习")
        self.assertEqual(q.engine_queries(), ["高等数学 期末复习"])
        self.assertIn("期末复习", q.github_query())
        self.assertEqual(q.portal_query(), "高等数学 期末复习")
        self.assertNotIn("高等数学 期末复习", q.core)

    def test_bare_course_name_expands_for_study_sources(self):
        q = parse("高等数学")
        self.assertEqual(q.core, "高等数学")
        self.assertFalse(q.modifiers)
        queries = q.engine_queries()
        self.assertEqual(queries[0], "高等数学")
        blob = " ".join(queries)
        for term in ("习题", "真题", "讲义", "题解"):
            self.assertIn(term, blob)
        gh = q.github_query()
        for term in ("习题", "题解", "讲义", "notes", "solutions"):
            self.assertIn(term, gh)
        portal = q.portal_query()
        for term in ("习题", "真题", "讲义", "题解"):
            self.assertIn(term, portal)

    def test_english_expansion(self):
        q = parse("calculus")
        blob = " ".join(q.engine_queries())
        for term in ("exercises", "past papers", "lecture notes", "solutions"):
            self.assertIn(term, blob)
        self.assertIn("exercises OR solutions OR notes", q.github_query())

    def test_noise_words_dropped_but_intent_kept(self):
        q = parse("高等数学 习题 免费下载")
        self.assertEqual(q.with_intent(), "高等数学 习题")
        self.assertIn("exercise", q.modifiers)
        self.assertEqual(q.engine_queries(), ["高等数学 习题"])

    def test_sources_send_those_strings(self):
        class Rec:
            def __init__(self):
                self.params = []

            def get_text(self, url, **kw):
                self.params.append(kw.get("params") or {})
                return ""

            def get_json(self, url, **kw):
                self.params.append(kw.get("params") or {})
                return {"items": []}

        bare = parse("高等数学")
        http = Rec()
        BaiduSource().fetch(bare, Context(http=http, per_source=4))
        sent = [p.get("wd") for p in http.params]
        self.assertIn("高等数学", sent)
        self.assertTrue(any(s and "习题" in s for s in sent))
        self.assertTrue(any(s and "真题" in s for s in sent))
        self.assertTrue(any(s and "讲义" in s for s in sent))
        self.assertTrue(any(s and "题解" in s for s in sent))

        intent = parse("高等数学 期末复习")
        http = Rec()
        BingSource().fetch(intent, Context(http=http, per_source=4))
        self.assertEqual([p.get("q") for p in http.params], ["高等数学 期末复习"])

        http = Rec()
        GitHubSource().fetch(bare, Context(http=http, per_source=5))
        gh = http.params[0]["q"]
        self.assertIn("高等数学", gh)
        self.assertIn("题解", gh)
        self.assertIn("讲义", gh)

        from cmf.sources.cn_courses import BilibiliSource

        http = Rec()
        # 接口在空 data 上会报 code；这里只核对查询词被放进参数。
        try:
            BilibiliSource().fetch(intent, Context(http=http, per_source=5))
        except Exception:
            pass
        self.assertTrue(http.params)
        self.assertEqual(http.params[0].get("keyword"), "高等数学 期末复习")


class TestClassify(unittest.TestCase):
    def test_retag_matrix(self):
        cases = [
            ("高等数学", "textbook", "textbook"),
            ("高等数学", "web", "web"),
            ("高等数学教材", "web", "textbook"),
            ("高等数学教材习题", "textbook", "exercise"),
            ("高等数学教材习题解答", "textbook", "solution"),
            ("高等数学期末真题", "web", "exam"),
            ("高等数学期末复习提纲", "web", "review"),
            ("高等数学课件", "web", "slides"),
            ("高等数学讲义", "note", "note"),
            ("高等数学精讲", "video", "explanation"),
            ("calculus-notes", "repo", "note"),
            ("user/calculus-solutions", "repo", "solution"),
            ("Problem Set 1", "course", "exercise"),
            ("Calculus Volume 1", "textbook", "textbook"),
            ("高等数学教学大纲", "course", "official"),
            ("高等数学习题教学改革", "paper", "paper"),
            ("在「知乎」检索：高等数学 期末真题", "link", "link"),
            ("随机介绍页面", "web", "web"),
            ("高等数学答案", "web", "solution"),
            ("高等数学全解", "web", "solution"),
            ("问题完全解决", "web", "web"),
            ("Single Variable Calculus", "course", "course"),
            ("高等数学（中国大学MOOC）", "web", "course"),
            ("高等数学慕课期末真题", "web", "exam"),
        ]
        for title, default, expect in cases:
            got = classify_kind(R(title, kind=default))
            self.assertEqual(got, expect, title)

    def test_description_retags_web_not_textbooks(self):
        web = R("高等数学第一章", kind="web", description="内含期末真题与评分标准")
        self.assertEqual(classify_kind(web), "exam")
        book = R(
            "Calculus Volume 1",
            kind="textbook",
            source="openstax",
            description="开放获取大学教材，可在线看、可下 PDF，附习题与教师资源。",
        )
        self.assertEqual(classify_kind(book), "textbook")

    def test_uncertain_does_not_follow_the_query(self):
        q = parse("高等数学 习题")
        page = R("高等数学", kind="web")
        self.assertEqual(classify_kind(page, q), "web")
        self.assertEqual(apply_kinds([page], q)[0].kind, "web")

    def test_query_breaks_exam_review_tie_when_the_user_only_asked_for_one(self):
        title = "高等数学期末复习"
        self.assertEqual(classify_kind(R(title), parse("高等数学 复习")), "review")
        self.assertEqual(classify_kind(R(title), parse("高等数学 期末")), "exam")

    def test_access_state_stays_separate_from_kind(self):
        page = R("高等数学期末真题", kind="web", crawl_status="blocked")
        self.assertEqual(classify_kind(page), "exam")
        apply_kinds([page], parse("高等数学"))
        self.assertEqual(page.kind, "exam")
        self.assertEqual(page.crawl_status, "blocked")
        self.assertNotIn("blocked", page.kind)


class TestKindFamilyAndExport(unittest.TestCase):
    def test_family_ids_and_labels(self):
        expected = {
            "exercise": "study", "exam": "study", "solution": "study", "review": "study",
            "explanation": "study", "note": "study", "slides": "study", "video": "study", "qa": "study",
            "textbook": "canonical", "official": "canonical", "course": "canonical",
            "paper": "other", "reference": "other", "repo": "other", "dataset": "other",
            "web": "other", "link": "other",
        }
        self.assertEqual(KIND_FAMILY, expected)
        self.assertEqual(KIND_LABELS["exercise"], "习题/作业")
        self.assertEqual(KIND_LABELS["exam"], "真题/试卷")
        self.assertEqual(KIND_LABELS["solution"], "题解/答案")
        self.assertEqual(KIND_LABELS["qa"], "问答")
        self.assertEqual(KIND_LABELS["textbook"], "教材")
        self.assertEqual(KIND_LABELS["official"], "官方文档")
        sample = R("高等数学习题", kind="exercise")
        self.assertEqual(sample.kind_family, "study")
        self.assertEqual(sample.kind_family_label, "学习向")
        self.assertEqual(sample.to_dict()["kind_family"], "study")
        self.assertEqual(sample.to_dict()["kind_family_label"], "学习向")

    def test_filter_order_and_counts(self):
        resources = [
            R("a", kind="paper", url="https://e/a"),
            R("b", kind="exercise", url="https://e/b"),
            R("c", kind="textbook", url="https://e/c"),
            R("d", kind="exam", url="https://e/d"),
            R("e", kind="web", url="https://e/e"),
        ]
        self.assertEqual([k for k, _ in present_kinds(resources)], ["exercise", "exam", "textbook", "paper", "web"])
        self.assertEqual(family_count_line(resources), "学习向 2 · 教材/官方 1 · 其他 2")

    def test_markdown_html_csv_json(self):
        q = parse("高等数学 习题")
        resources = rank.rank_resources(
            [
                R("高等数学习题解答", kind="web", source="baidu", url="https://notes.example/a"),
                R("高等数学", kind="textbook", source="wikibooks", url="https://zh.wikibooks.org/wiki/x"),
                R("高等数学教学研究", kind="paper", source="crossref", url="https://doi.org/10.1/y"),
            ],
            q,
        )
        res = SearchResult(
            query="高等数学 习题",
            core=q.core,
            lang="zh",
            resources=resources,
            statuses=[SourceStatus(id="baidu", label="百度", ok=True, count=1, elapsed=0.2)],
            link_portals=[R("在「知乎」检索", kind="link", source="portals", url="https://www.zhihu.com/search?q=1")],
            generated_at="2026-01-01 00:00:00",
            elapsed=1.0,
        )
        md = render_markdown(res, {"crawled": 0})
        self.assertIn("类型图例：", md)
        self.assertIn("学习向", md)
        self.assertIn("教材/官方", md)
        self.assertIn("【题解/答案】", md)
        self.assertLess(md.index("### 学习向资料"), md.index("### 教材与官方文档"))
        self.assertLess(md.index("### 教材与官方文档"), md.index("### 其他"))
        self.assertIn("先看这几条", md)
        # 标题前的类型标签，不是只出现在元信息里
        self.assertIn("【题解/答案】 **[", md)

        html = render_html(res, {"crawled": 0})
        self.assertIn('class="kbadge study"', html)
        self.assertIn("题解/答案", html)
        self.assertIn("学习向资料", html)
        self.assertLess(html.index(">学习向资料"), html.index(">教材与官方文档"))
        self.assertLess(html.index(">教材与官方文档"), html.index(">其他"))

        row = json.loads(json.dumps(res.to_dict(), ensure_ascii=False))
        item = next(r for r in row["resources"] if r["kind"] == "solution")
        self.assertEqual(item["kind_label"], "题解/答案")
        self.assertEqual(item["kind_family"], "study")
        self.assertEqual(item["kind_family_label"], "学习向")

        csv_text = render_csv(res)
        header = csv_text.splitlines()[0]
        for col in ("kind", "kind_id", "kind_family", "kind_family_label"):
            self.assertIn(col, header)
        self.assertIn("题解/答案", csv_text)
        self.assertIn("solution", csv_text)
        self.assertIn("study", csv_text)
        self.assertIn("学习向", csv_text)


class TestPortalsStayLinkOnly(unittest.TestCase):
    def test_paywalled_portals_are_not_ranked_sources(self):
        blob = "\n".join(f"{name} {url} {note}" for name, url, note in PORTALS)
        for banned in ("组卷网", "学科网", "zujuan", "zxxk.com"):
            self.assertNotIn(banned, blob)
        for name in ("百度文库", "豆丁网", "知乎", "CSDN"):
            self.assertIn(name, blob)
        self.assertIn("portals", LINK_IDS)
        from cmf.sources.links import LinkPortalSource

        items = LinkPortalSource().fetch(parse("高等数学 期末真题"), Context(http=None, per_source=5))
        self.assertTrue(items)
        self.assertTrue(all(r.kind == "link" for r in items))
        self.assertTrue(all(r.extra.get("access") == "link-only" for r in items))
        self.assertTrue(all(classify_kind(r) == "link" for r in items))
        self.assertTrue(all(quote_plus("期末真题") in r.url for r in items))
        self.assertTrue(all("wenku.baidu.com" not in r.url or quote_plus("高等数学 期末真题") in r.url for r in items))


class TestResultsPageContract(unittest.TestCase):
    def test_ui_badge_filter_and_counts(self):
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
        # 类型徽标独立于灰字元信息行
        self.assertIn('class="kbadge', js)
        self.assertNotIn("r.kind_label, r.lang_label", js)
        meta = js.split("const meta = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("kind_label", meta)
        self.assertIn(".kbadge.study", css)
        self.assertIn(".kbadge.canonical", css)
        order = js.split("const KIND_ORDER = [", 1)[1].split("]", 1)[0]
        self.assertLess(order.index("exercise"), order.index("textbook"))
        self.assertLess(order.index("qa"), order.index("textbook"))
        self.assertLess(order.index("textbook"), order.index("paper"))
        self.assertIn("学习向", js)
        self.assertIn("教材/官方", js)
        self.assertIn("其他", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
