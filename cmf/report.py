# -*- coding: utf-8 -*-
"""报告输出：Markdown / JSON / CSV / HTML + 终端摘要。"""
from __future__ import annotations

import csv
import html as html_mod
import json
from pathlib import Path
from typing import List

from .models import Resource, SearchResult

ACCESS_LABEL = {
    "ok": "已抓正文",
    "pdf": "PDF 直链",
    "blocked": "被反爬/需登录",
    "not-found": "页面不存在",
    "not-html": "非网页内容",
    "empty": "页面为空",
    "error": "抓取失败",
    "timeout": "抓取超时",
    "skipped": "未抓取",
    "": "未抓取",
}


def _access(res: Resource) -> str:
    if res.downloaded:
        return "已下载 PDF"
    return ACCESS_LABEL.get(res.crawl_status, res.crawl_status)


def _line_md(res: Resource, idx: int | None = None) -> str:
    head = f"**[{res.title}]({res.url})**" if res.url else f"**{res.title}**"
    if idx is not None:
        head = f"{idx}. {head}"
    bits = [res.source_label or res.source, res.kind_label]
    if res.lang:
        bits.append(res.lang_label)
    if res.year:
        bits.append(f"{res.year}")
    if res.org:
        bits.append(res.org[:40])
    meta = " · ".join(b for b in bits if b)
    out = [head, f"   `{meta}`"]
    summary = res.summary(260)
    if summary:
        out.append(f"   {summary}")
    tails = []
    if res.pdf_url:
        tails.append(f"[PDF]({res.pdf_url})")
    if res.downloaded:
        tails.append(f"本地: `{res.downloaded}`")
    tails.append(f"抓取: {_access(res)}")
    if res.extra.get("stars"):
        tails.append(f"⭐{res.extra['stars']}")
    if res.extra.get("play"):
        tails.append(f"▶{res.extra['play']}")
    tails.append(f"相关度 {res.score:.0f}")
    out.append("   " + " · ".join(tails))
    return "\n".join(out)


def render_markdown(result: SearchResult, stats: dict | None = None) -> str:
    from .rank import group_by_kind

    L: List[str] = []
    L.append(f"# 课程资料检索报告：{result.query}")
    L.append("")
    ok_sources = [s for s in result.statuses if s.ok]
    L.append(
        f"> 生成时间：{result.generated_at} ｜ 用时 {result.elapsed:.1f}s ｜ "
        f"命中 **{len(result.resources)}** 条 ｜ 数据源 {len(ok_sources)}/{len(result.statuses)} 成功"
    )
    L.append(f"> 检索主体：`{result.core}` ｜ 语言：{result.lang}")
    if stats:
        L.append(
            f"> 抓取：正文 {stats.get('crawled', 0)} 条 ｜ 摘要补全 {stats.get('abstracts', 0)} 条 ｜ "
            f"开放全文 {stats.get('oa_pdf', 0)} 个 ｜ 已下载 {stats.get('downloaded', 0)} 个"
        )
        if stats.get("timed_out"):
            L.append(f"> 注意：有 **{stats['timed_out']}** 个数据源超出时间预算被放弃（见文末抓取情况表）")
    L.append("")

    top = result.resources[:5]
    if top:
        L.append("## 一、先看这几条")
        L.append("")
        for i, r in enumerate(top, 1):
            L.append(_line_md(r, i))
            L.append("")

    L.append("## 二、分类清单")
    L.append("")
    for kind, items in group_by_kind(result.resources):
        if kind == "link":
            continue
        L.append(f"### {items[0].kind_label}（{len(items)}）")
        L.append("")
        for r in items:
            L.append(_line_md(r))
            L.append("")
        L.append("")

    if result.link_portals:
        L.append("## 三、仅链接：这些平台抓不到，只能给你入口")
        L.append("")
        L.append("| 平台 | 说明 | 检索链接 |")
        L.append("| --- | --- | --- |")
        for r in result.link_portals:
            note = (r.description or "").replace("（本工具不抓取其内容，仅提供检索入口）", "")
            L.append(f"| {r.org or r.title} | {note} | [打开检索]({r.url}) |")
        L.append("")

    L.append("## 四、抓取情况（透明账）")
    L.append("")
    L.append("| 数据源 | 状态 | 条数 | 耗时(s) | 说明 |")
    L.append("| --- | --- | --- | --- | --- |")
    for s in result.statuses:
        state = "✅" if s.ok else ("⏭️" if s.skipped else "❌")
        note = s.error or s.skipped or ""
        L.append(f"| {s.label} | {state} | {s.count} | {s.elapsed:.1f} | {note[:80]} |")
    L.append("")

    L.append("## 五、使用说明")
    L.append("")
    L.append("- **已抓正文** = 本工具真的访问了页面并抽取了正文；**PDF 直链/已下载** = 可直接拿走。")
    L.append("- **仅链接** = 平台有反爬/登录墙/付费墙，本工具不绕过，只给可达入口。")
    L.append("- 所有来源均为公开可访问页面或开放接口（OER / 开放获取 / 公开课程），不涉及盗版资源站。")
    L.append("- 引用请遵守各平台版权与授权协议（MIT OCW 为 CC BY-NC-SA，OpenStax 多为 CC BY）。")
    L.append("")
    return "\n".join(L)


def write_markdown(result: SearchResult, path: Path, stats: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(result, stats), "utf-8")
    return path


def write_json(result: SearchResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), "utf-8")
    return path


CSV_FIELDS = [
    "title", "url", "source", "source_label", "kind", "lang", "year", "org",
    "authors", "score", "relevance", "quality", "crawl_status", "pdf_url", "summary",
]


def write_csv(result: SearchResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in result.resources:
            w.writerow(
                {
                    "title": r.title,
                    "url": r.url,
                    "source": r.source,
                    "source_label": r.source_label,
                    "kind": r.kind_label,
                    "lang": r.lang_label,
                    "year": r.year or "",
                    "org": r.org,
                    "authors": "; ".join(r.authors[:4]),
                    "score": f"{r.score:.1f}",
                    "relevance": f"{r.relevance:.2f}",
                    "quality": f"{r.quality:.2f}",
                    "crawl_status": _access(r),
                    "pdf_url": r.pdf_url,
                    "summary": r.summary(300),
                }
            )
    return path


_CSS = """
:root{--bg:#0f1115;--card:#171a21;--fg:#e8eaf0;--muted:#9aa4b2;--acc:#4f9cf9;--ok:#3fb950;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 6px}h2{margin:34px 0 12px;font-size:19px;border-left:4px solid var(--acc);padding-left:10px}
.meta{color:var(--muted);font-size:13px;margin-bottom:8px}
.card{background:var(--card);border:1px solid #232833;border-radius:10px;padding:14px 16px;margin:10px 0}
.card h3{margin:0 0 6px;font-size:16px}.card a{color:var(--acc);text-decoration:none}.card a:hover{text-decoration:underline}
.tags span{display:inline-block;font-size:12px;color:var(--muted);border:1px solid #2c323d;border-radius:99px;padding:1px 8px;margin:0 6px 6px 0}
.p{color:#c7cdd8;font-size:14px}.bar{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:8px}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #232833}th{color:var(--muted);font-weight:500}
input,button{font:inherit}input{background:#0b0d11;border:1px solid #2c323d;color:var(--fg);border-radius:8px;padding:10px 12px;width:100%}
button{background:var(--acc);color:#06121f;border:0;border-radius:8px;padding:10px 18px;font-weight:600;cursor:pointer}
"""


def render_html(result: SearchResult, stats: dict | None = None) -> str:
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>课程资料：{html_mod.escape(result.query)}</title><style>{_CSS}</style></head>"
        f"<body>{render_html_body(result, stats)}</body></html>"
    )


def render_html_body(result: SearchResult, stats: dict | None = None) -> str:
    """结果正文（不含 <html> 外壳），本地 Web 界面直接复用。"""
    from .rank import group_by_kind

    def esc(s: str) -> str:
        return html_mod.escape(s or "")

    def card(r: Resource) -> str:
        tags = [r.source_label or r.source, r.kind_label, r.lang_label]
        if r.year:
            tags.append(str(r.year))
        if r.org:
            tags.append(r.org[:40])
        if r.extra.get("stars"):
            tags.append(f"⭐{r.extra['stars']}")
        if r.extra.get("play"):
            tags.append(f"▶{r.extra['play']}")
        summary = esc(r.summary(320))
        links = [f'<a href="{esc(r.url)}" target="_blank" rel="noreferrer">打开原文</a>']
        if r.pdf_url:
            links.append(f'<a href="{esc(r.pdf_url)}" target="_blank" rel="noreferrer">PDF</a>')
        status = _access(r)
        cls = "ok" if r.crawl_status in ("ok", "pdf") else ("warn" if r.crawl_status in ("blocked", "not-found") else "bad")
        return (
            '<div class="card">'
            f'<h3><a href="{esc(r.url)}" target="_blank" rel="noreferrer">{esc(r.title)}</a></h3>'
            f'<div class="tags">{"".join(f"<span>{esc(t)}</span>" for t in tags)}</div>'
            f'<div class="p">{summary}</div>'
            f'<div class="bar"><span class="{cls}">{esc(status)}</span>'
            f"<span>相关度 {r.score:.0f}</span>" + "".join(f"<span>{x}</span>" for x in links) + "</div>"
            "</div>"
        )

    body = [
        f'<div class="wrap"><h1>课程资料检索报告：{esc(result.query)}</h1>',
        f'<div class="meta">生成 {esc(result.generated_at)} ｜ 用时 {result.elapsed:.1f}s ｜ '
        f'命中 {len(result.resources)} 条 ｜ 检索主体 <code>{esc(result.core)}</code></div>',
    ]
    if stats:
        body.append(
            f'<div class="meta">正文抓取 {stats.get("crawled", 0)} 条 ｜ 摘要补全 {stats.get("abstracts", 0)} 条 ｜ '
            f'开放全文 {stats.get("oa_pdf", 0)} ｜ 已下载 {stats.get("downloaded", 0)}</div>'
        )
        if stats.get("timed_out"):
            body.append(
                f'<div class="meta warn">有 {stats["timed_out"]} 个数据源超出时间预算被放弃，详见下方抓取情况</div>'
            )
    body.append("<h2>先看这几条</h2>")
    body.extend(card(r) for r in result.resources[:5])
    for kind, items in group_by_kind(result.resources):
        if kind == "link":
            continue
        body.append(f"<h2>{esc(items[0].kind_label)}（{len(items)}）</h2>")
        body.extend(card(r) for r in items)
    if result.link_portals:
        body.append("<h2>仅链接：抓不到的平台，给你入口</h2><table><tr><th>平台</th><th>说明</th><th>链接</th></tr>")
        for r in result.link_portals:
            body.append(
                f"<tr><td>{esc(r.org)}</td><td>{esc((r.description or '')[:90])}</td>"
                f'<td><a href="{esc(r.url)}" target="_blank" rel="noreferrer">检索</a></td></tr>'
            )
        body.append("</table>")
    body.append("<h2>抓取情况</h2><table><tr><th>数据源</th><th>状态</th><th>条数</th><th>耗时</th><th>说明</th></tr>")
    for s in result.statuses:
        state = '<span class="ok">成功</span>' if s.ok else (f'<span class="warn">跳过</span>' if s.skipped else '<span class="bad">失败</span>')
        body.append(
            f"<tr><td>{esc(s.label)}</td><td>{state}</td><td>{s.count}</td><td>{s.elapsed:.1f}s</td>"
            f"<td>{esc((s.error or s.skipped or '')[:90])}</td></tr>"
        )
    body.append("</table>")
    body.append("<h2>说明</h2><p class='p'>「已抓正文」为本工具真实访问页面后抽取的正文；「仅链接」为平台反爬/登录墙/付费墙，"
                "本工具不绕过，只提供入口。全部来源为公开可访问页面或开放接口。</p></div>")
    return "".join(body)


def write_html(result: SearchResult, path: Path, stats: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(result, stats), "utf-8")
    return path


def render_console(result: SearchResult, stats: dict | None = None) -> str:
    ok = [s for s in result.statuses if s.ok]
    lines = [
        "",
        f"查询：{result.query}   主体：{result.core}",
        f"命中 {len(result.resources)} 条 ｜ 用时 {result.elapsed:.1f}s ｜ 源 {len(ok)}/{len(result.statuses)} 成功",
    ]
    if stats:
        lines.append(
            f"抓取：正文 {stats.get('crawled', 0)} ｜ 摘要 {stats.get('abstracts', 0)} ｜ "
            f"OA 全文 {stats.get('oa_pdf', 0)} ｜ 下载 {stats.get('downloaded', 0)}"
        )
    lines.append("-" * 72)
    for i, r in enumerate(result.resources[:10], 1):
        tag = f"{r.kind_label}/{r.source_label}"
        lines.append(f"{i:>2}. [{r.score:>5.1f}] {r.title[:56]}")
        lines.append(f"    {tag} · {_access(r)} · {r.url[:88]}")
    if len(result.resources) > 10:
        lines.append(f"    … 其余 {len(result.resources) - 10} 条见报告")
    failed = [s for s in result.statuses if not s.ok and not s.skipped]
    if failed:
        lines.append("-" * 72)
        lines.append("失败源：" + "；".join(f"{s.label}({s.error[:36]})" for s in failed))
    return "\n".join(lines)


HTML_CSS = _CSS  # 供本地 Web 界面复用

