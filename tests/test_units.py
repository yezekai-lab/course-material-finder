# -*- coding: utf-8 -*-
"""单元测试：查询解析 / 文本处理 / 排序去重。全部离线。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cmf import query, rank, textutil  # noqa: E402
from cmf.models import Resource  # noqa: E402
from cmf.query import parse  # noqa: E402


class TestQueryParsing(unittest.TestCase):
    def test_split_modifiers(self):
        q = parse("高等数学 期末复习 课件")
        self.assertEqual(q.core, "高等数学")
        self.assertIn("exam", q.modifiers)
        self.assertIn("review", q.modifiers)
        self.assertIn("slides", q.modifiers)
        self.assertEqual(q.lang, "zh")

    def test_suffix_modifiers_without_space(self):
        q = parse("高等数学期末复习")
        self.assertEqual(q.core, "高等数学")
        self.assertIn("exam", q.modifiers)

    def test_do_not_cut_course_name(self):
        # "课程设计" 是课名，不能因为含"课程"就切成"设计"
        q = parse("课程设计")
        self.assertEqual(q.core, "课程设计")

    def test_university_prefix_kept(self):
        q = parse("大学物理 实验")
        self.assertEqual(q.core, "大学物理")
        self.assertIn("lab", q.modifiers)

    def test_english(self):
        q = parse("calculus final exam")
        self.assertEqual(q.core, "calculus")
        self.assertIn("exam", q.modifiers)
        self.assertEqual(q.lang, "en")

    def test_empty_and_short(self):
        q = parse("   ")
        self.assertEqual(q.raw, "")
        q2 = parse("物理")
        self.assertEqual(q2.core, "物理")


class TestTextUtil(unittest.TestCase):
    def test_strip_html_handles_dict_and_list(self):
        self.assertEqual(textutil.strip_html({"tagName": "理学"}), "理学")
        self.assertEqual(textutil.strip_html(["理学", "数学类"]), "理学 数学类")
        self.assertEqual(textutil.strip_html(None), "")
        self.assertEqual(
            textutil.strip_html('<span class="text-blue-500">高等数学</span>Ⅰ'), "高等数学Ⅰ"
        )

    def test_extract_main_text_drops_nav(self):
        html = "<body>" + "".join(f"<div>{x}</div>" for x in textutil.NAV_LINES) + (
            "<p>本课程系统讲解极限、导数、积分与级数，配套习题与实验讲义，"
            "适合工科各专业本科一年级学生使用，期末考试覆盖全部章节。</p>" * 3
        ) + "</body>"
        out = textutil.extract_main_text(html, 200)
        self.assertNotIn("虚仿实验", out)
        self.assertIn("极限", out)

    def test_normalize_url(self):
        self.assertEqual(
            textutil.normalize_url("https://www.Bilibili.com/video/BV1xx/?spm_id_from=333&vd_source=1#t=3"),
            "https://bilibili.com/video/BV1xx",
        )
        self.assertEqual(textutil.normalize_url("//www.baidu.com/s?a=1&utm_source=x"), "https://baidu.com/s?a=1")

    def test_tokens_cjk_bigram_and_stopwords(self):
        t = textutil.tokens("高等数学 期末复习")
        self.assertIn("高等", t)
        self.assertIn("数学", t)
        self.assertNotIn("期末", t)  # 停用词，不参与相关性
        self.assertIn("calculus", textutil.tokens("Calculus Lecture Notes"))


class TestRanking(unittest.TestCase):
    def _res(self, title, kind="web", source="bing", year=None, url=None):
        return Resource(title=title, url=url or f"https://x.com/{abs(hash(title))}", source=source, kind=kind, year=year)

    def test_relevance_prefers_exact_course(self):
        q = parse("高等数学 期末复习")
        good = self._res("高等数学期末复习提纲")
        bad = self._res("高等数学教学法研究综述")
        rs = rank.score_all([good, bad], q)
        self.assertGreater(rs[0].score, rs[1].score)

    def test_exam_intent_demotes_papers(self):
        q = parse("高等数学 期末 真题")
        paper = self._res("高等数学课程改革论文", kind="paper", source="crossref")
        note = self._res("高等数学期末真题答案", kind="note", source="bing")
        rs = {r.title: r for r in rank.score_all([paper, note], q)}
        self.assertGreater(rs[note.title].score, rs[paper.title].score)

    def test_dedupe_same_url_and_near_title(self):
        a = self._res("高等数学讲义", url="https://a.com/x?utm_source=1")
        b = self._res("高等数学讲义", url="https://A.com/x/")
        c = self._res("高等数学 讲义（完整版）", url="https://b.com/y")
        d = self._res("线性代数讲义", url="https://c.com/z")
        out = rank.dedupe([a, b, c, d])
        self.assertEqual(len(out), 2)

    def test_diversify_caps_per_source(self):
        q = parse("高数")
        rs = rank.score_all(
            [self._res(f"高数{i}", source="bilibili") for i in range(6)]
            + [self._res("高数教材", source="openstax", kind="textbook")],
            q,
        )
        self.assertEqual(len(rank.diversify(rs, 5, max_per_source=2)), 5)


class TestEnrichExcerpt(unittest.TestCase):
    def test_prefers_text_matching_title(self):
        from cmf.enrich import _pick_excerpt

        title = "一小时速通《计算机网络》"
        body = "推荐视频 数据结构速通 7.1万 考研数学 3.2万 腾势N8 高空集装箱 40分钟速通 线性代数"
        desc = "一小时速通《计算机网络》课程讲解，覆盖 OSI 七层模型、TCP/IP 协议栈与常见考点。"
        self.assertEqual(_pick_excerpt(body, desc, title), desc)

    def test_keeps_body_when_it_matches(self):
        from cmf.enrich import _pick_excerpt

        title = "高等数学Ⅰ"
        body = "高等数学Ⅰ 由重庆科技大学开设，课程涵盖极限、导数、积分与级数，配套章节习题与期末考试。"
        desc = "课程页面"
        self.assertEqual(_pick_excerpt(body, desc, title), body)

    def test_short_body_falls_back_to_desc(self):
        from cmf.enrich import _pick_excerpt

        self.assertEqual(_pick_excerpt("短", "这是一段足够长的课程简介，描述课程内容与适用对象。", "某课程"),
                         "这是一段足够长的课程简介，描述课程内容与适用对象。")


class TestReport(unittest.TestCase):
    def test_markdown_and_html_render(self):
        from cmf.models import SearchResult, SourceStatus
        from cmf.report import render_html, render_markdown

        q = parse("线性代数")
        rs = rank.score_all(
            [Resource(title="线性代数教材", url="https://x.com/a", source="openstax", kind="textbook")], q
        )
        res = SearchResult(
            query="线性代数",
            core=q.core,
            lang=q.lang,
            resources=rs,
            statuses=[SourceStatus(id="openstax", label="OpenStax", ok=True, count=1, elapsed=0.2)],
            link_portals=[Resource(title="在「知网」检索", url="https://kns.cnki.net/", source="portals", kind="link")],
            generated_at="2026-01-01 00:00:00",
            elapsed=1.2,
        )
        md = render_markdown(res, {"crawled": 1})
        self.assertIn("课程资料检索报告", md)
        self.assertIn("仅链接", md)
        self.assertIn("线性代数教材", md)
        html = render_html(res, {"crawled": 1})
        self.assertIn("<!doctype html>", html.lower())
        self.assertIn("线性代数教材", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
