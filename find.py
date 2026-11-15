#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""课程资料获取助手 —— 命令行入口。

    python find.py "高等数学 期末复习 课件"
    python find.py "数据结构" --limit 20 --download ./dl
    python find.py "linear algebra" --sources openalex,arxiv,ocw --no-crawl
    python find.py --list-sources

能爬的直接抓正文，抓不到的平台给检索链接——报告里会明确标出每一条是哪一种。
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            # 已经是 GBK/UTF-8 的控制台不动它，只在纯 ASCII（管道）时兜底
            if (getattr(stream, "encoding", "") or "").lower() in ("", "ascii", "ansi_x3.4-1968"):
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="find.py",
        description="大学课程资料获取助手：从全网检索课程/教材/视频/论文/题解，能爬的抓正文，不能爬的给链接。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python find.py "高等数学 期末复习"
  python find.py "数据结构 实验" --limit 25 --download ./dl
  python find.py "计算流体力学" --sources openalex,arxiv,ocw
  python find.py "大学物理" --no-crawl --format md,json
  python find.py --list-sources
""",
    )
    p.add_argument("query", nargs="*", help="课程名/关键词，可带「期末 课件 习题」等意图词")
    p.add_argument("-n", "--limit", type=int, default=30, help="最终结果条数（默认 30）")
    p.add_argument("-s", "--per-source", type=int, default=10, help="每个数据源最多取几条（默认 10）")
    p.add_argument("--sources", nargs="*", help="只查指定源，如 openalex arxiv bilibili；all=全部")
    p.add_argument("--exclude", nargs="*", default=[], help="排除指定源")
    p.add_argument("--no-crawl", action="store_true", help="不抓正文，只出链接（更快）")
    p.add_argument("--crawl-limit", type=int, default=12, help="抓正文的条数上限（默认 12）")
    p.add_argument("--download", metavar="DIR", help="把找到的开放 PDF 下载到该目录")
    p.add_argument("--no-oa", action="store_true", help="不查 Unpaywall 开放全文")
    p.add_argument("--min-score", type=float, default=10.0, help="最低相关度分（0-100，默认 10）")
    p.add_argument("--format", default="md,json", help="输出格式，逗号分隔：md,json,csv,html（默认 md,json）")
    p.add_argument("--out", default=str(ROOT / "out"), help="报告输出目录")
    p.add_argument("--budget", type=float, default=100.0, help="检索总预算秒数（默认 100，到点放弃慢源直接出报告）")
    p.add_argument("--crawl-budget", type=float, default=60.0, help="抓正文预算秒数（默认 60）")
    p.add_argument("--no-cache", action="store_true", help="禁用磁盘缓存（默认缓存，重复查询更快）")
    p.add_argument("--list-sources", action="store_true", help="列出所有数据源后退出")
    p.add_argument("--open", action="store_true", help="生成 HTML 后自动打开")
    p.add_argument("-v", "--verbose", action="store_true", help="打印详细日志")
    return p


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8()
    args = build_parser().parse_args(argv)

    from cmf.engine import Options, list_sources, search
    from cmf.report import render_console, write_csv, write_html, write_json, write_markdown
    from cmf.textutil import slugify

    if args.list_sources:
        print(list_sources())
        return 0

    query = " ".join(args.query).strip()
    if not query:
        build_parser().print_help()
        return 2

    if args.verbose:
        import logging

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    sources = args.sources or None
    if sources and args.exclude:
        excl = {e.lower() for e in args.exclude}
        sources = [s for s in sources if s.lower() not in excl]

    opts = Options(
        limit=args.limit,
        per_source=args.per_source,
        crawl=not args.no_crawl,
        crawl_limit=args.crawl_limit,
        sources=sources,
        min_score=args.min_score,
        download_dir=Path(args.download) if args.download else None,
        cache=not args.no_cache,
        verbose=args.verbose,
        resolve_oa=not args.no_oa,
        budget=args.budget,
        crawl_budget=args.crawl_budget,
    )

    print(f"\n正在检索：{query}")
    print("  分层抓取中：结构化 API → 搜索结果页 → 站点索引 → 链接兜底 …")
    result, stats = search(query, opts)

    print(render_console(result, stats))

    out_dir = Path(args.out)
    stamp = result.generated_at.replace(":", "").replace(" ", "-")[:15]
    base = f"{stamp}-{slugify(result.core, 40)}"
    formats = {f.strip().lower() for f in args.format.split(",") if f.strip()}
    written = []
    if "md" in formats:
        written.append(write_markdown(result, out_dir / f"{base}.md", stats))
    if "json" in formats:
        written.append(write_json(result, out_dir / f"{base}.json"))
    if "csv" in formats:
        written.append(write_csv(result, out_dir / f"{base}.csv"))
    if "html" in formats:
        html_path = write_html(result, out_dir / f"{base}.html", stats)
        written.append(html_path)
        if args.open:
            webbrowser.open(html_path.as_uri())

    print("\n报告已生成：")
    for w in written:
        print(f"  {w}")

    if not result.resources:
        print("\n没找到可用结果。可以试试：--sources all --limit 50 --min-score 5，或换个更通用的课程名。")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        raise SystemExit(130)
