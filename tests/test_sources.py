# -*- coding: utf-8 -*-
"""数据源解析测试：用真实响应夹具离线跑，验证「换个网络环境也能解析出来」。

夹具来自 dev/probe_sources*.py 的真实抓取，不是手写样例——所以能真正
拦住「上游改字段了」这类回归。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cmf.http import Response  # noqa: E402
from cmf.query import parse  # noqa: E402
from cmf.sources import ALL_SOURCES, Context  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


class FakeHttp:
    """把 URL 片段映射到夹具文件：一个 source 只关心自己的接口。"""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def _body(self, url: str) -> str:
        for key, name in self.mapping.items():
            if key in url:
                path = FIX / name
                raw = path.read_bytes()
                return raw.decode("utf-8", "replace")
        raise AssertionError(f"未预期的请求: {url}")

    def get_text(self, url, **kw):
        self.calls.append(url)
        return self._body(url)

    def get_json(self, url, **kw):
        self.calls.append(url)
        return json.loads(self._body(url))

    def request(self, url, **kw):
        self.calls.append(url)
        text = self._body(url)
        return Response(
            url=url,
            status=200,
            content=text.encode("utf-8"),
            text=text,
            headers={"content-type": "application/atom+xml; charset=utf-8"},
        )


def run_source(sid: str, mapping, q: str = "高等数学", per_source: int = 10):
    src = ALL_SOURCES[sid]
    ctx = Context(http=FakeHttp(mapping), per_source=per_source)
    return src.fetch(parse(q), ctx)


class TestChineseSources(unittest.TestCase):
    def test_chinaooc(self):
        items = run_source("chinaooc", {"api.chinaooc.com.cn": "chinaooc_courses.json"})
        self.assertGreater(len(items), 5)
        first = items[0]
        self.assertTrue(first.title.startswith("高等数学"))
        self.assertTrue(first.url.startswith("https://higher.smartedu.cn/course/"))
        self.assertEqual(first.kind, "course")
        self.assertIn("重庆", first.org + "".join(first.authors) + first.description + str(first.extra))
        self.assertNotIn("<span", first.title)  # 高亮标签必须被剥掉

    def test_bilibili(self):
        items = run_source("bilibili", {"api.bilibili.com": "bilibili_api.json"})
        self.assertGreater(len(items), 5)
        self.assertTrue(all("bilibili.com/video/BV" in r.url for r in items))
        self.assertTrue(all("<em" not in r.title for r in items))
        self.assertGreaterEqual(items[0].year or 0, 2010)


class TestTextbookSources(unittest.TestCase):
    def test_openstax_catalogue_match(self):
        items = run_source("openstax", {"openstax.org": "openstax_books.json"}, q="calculus")
        self.assertGreater(len(items), 0)
        self.assertTrue(all(r.url.startswith("http") for r in items))
        self.assertEqual(items[0].kind, "textbook")

    def test_open_textbook_library_atom(self):
        items = run_source("otl", {"open.umn.edu": "umn_otl.xml"}, q="calculus")
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(items[0].url.startswith("https://open.umn.edu/opentextbooks/textbooks/"))
        self.assertGreater(len(items[0].title), 5)


class TestPaperSources(unittest.TestCase):
    def test_arxiv(self):
        items = run_source("arxiv", {"export.arxiv.org": "arxiv.xml"}, q="fractional calculus")
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(items[0].pdf_url.startswith("http"))
        self.assertEqual(items[0].kind, "paper")
        self.assertTrue(items[0].description)

    def test_crossref(self):
        items = run_source("crossref", {"api.crossref.org": "crossref.json"}, q="linear algebra")
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(any(r.extra.get("doi") for r in items))

    def test_openalex(self):
        items = run_source("openalex", {"api.openalex.org": "openalex.json"}, q="linear algebra")
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(all(r.url.startswith("http") for r in items))
        # 夹具里的记录没有摘要，单独验摘要还原逻辑（真实接口常带 inverted index）
        from cmf.sources.papers import _openalex_abstract

        self.assertEqual(_openalex_abstract({"Hello": [0], "world": [1], "again": [2]}), "Hello world again")
        self.assertEqual(_openalex_abstract(None), "")

    def test_doaj(self):
        items = run_source("doaj", {"doaj.org": "doaj.json"}, q="linear algebra")
        self.assertGreater(len(items), 0)
        self.assertTrue(all(r.kind == "paper" for r in items))

    def test_zenodo(self):
        items = run_source("zenodo", {"zenodo.org": "zenodo.json"}, q="linear algebra")
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(all(r.url.startswith("http") for r in items))

    def test_europepmc(self):
        items = run_source("europepmc", {"www.ebi.ac.uk": "europepmc.json"}, q="calculus")
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(all(r.title for r in items))


class TestWebAndMiscSources(unittest.TestCase):
    def test_bing_parse(self):
        items = run_source("bing", {"www.bing.com": "bing_search.html"}, q="calculus lecture notes")
        self.assertGreaterEqual(len(items), 5)
        self.assertTrue(all(r.url.startswith("http") for r in items))
        self.assertTrue(all("bing.com" not in r.url for r in items))
        self.assertTrue(any(r.description for r in items))

    def test_baidu_parse_and_ad_filter(self):
        items = run_source("baidu", {"www.baidu.com/s": "baidu_a.html"}, q="高等数学 课件")
        self.assertGreaterEqual(len(items), 5)
        self.assertTrue(all(r.title for r in items))
        # 豆包/广告文案不能进结果
        self.assertFalse(any("豆包" in r.title for r in items))
        self.assertTrue(any("高等数学" in r.title for r in items))

    def test_wikipedia(self):
        items = run_source("wikipedia", {"zh.wikipedia.org": "wikipedia.json"}, q="线性代数")
        self.assertGreater(len(items), 0)
        self.assertIn("wikipedia.org/wiki/", items[0].url)

    def test_stackexchange(self):
        items = run_source("stackexchange", {"api.stackexchange.com": "stackexchange.json"}, q="python linked list")
        self.assertGreater(len(items), 0)
        self.assertTrue(items[0].url.startswith("https://stackoverflow.com/questions/"))

    def test_github(self):
        items = run_source("github", {"api.github.com": "github_repos.json"}, q="course notes")
        self.assertGreater(len(items), 0)
        self.assertTrue(any(r.extra.get("stars") for r in items))
        self.assertTrue(items[0].url.startswith("https://github.com/"))


class TestLinkPortals(unittest.TestCase):
    def test_portals_always_return_links(self):
        items = run_source("portals", {}, q="高等数学 期末复习")
        self.assertGreaterEqual(len(items), 10)
        self.assertTrue(all(r.kind == "link" for r in items))
        self.assertTrue(all(r.url.startswith("http") for r in items))
        # 中文关键词必须已编码进链接
        self.assertTrue(any("%E9%AB%98%E7%AD%89" in r.url for r in items))
        self.assertTrue(any("icourse163" in r.url for r in items))


class TestRegistry(unittest.TestCase):
    def test_resolve_all_and_aliases(self):
        from cmf.sources import resolve

        self.assertIn("openalex", resolve(["openalex"]))
        self.assertIn("ocw", resolve(["mit"]))
        self.assertIn("portals", resolve(["zhihu"]))
        self.assertEqual(len(resolve(["all"])), len(ALL_SOURCES))
        with self.assertRaises(KeyError):
            resolve(["nope-source"])

    def test_every_source_has_meta(self):
        for sid, src in ALL_SOURCES.items():
            self.assertEqual(src.meta.id, sid)
            self.assertTrue(src.meta.label)
            self.assertIn(src.meta.tier, {"api", "engine", "index", "link"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
