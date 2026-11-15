# -*- coding: utf-8 -*-
"""「不能爬就给你链接」层。

这些平台实测无法稳定抓取：
  * 中国大学MOOC / 学堂在线 / 智慧树 / 超星 —— 纯 JS 渲染或大数据服务报错；
  * 百度文库 / 豆丁 / 知网 / 万方 —— 登录墙 + 付费墙；
  * CSDN / 知乎 —— 反爬 + 需登录；
  * Google Scholar / YouTube —— 验证码 / API key。
所以这一层不做抓取，只生成**带关键词的直达检索链接**，并在报告里明确标注
「仅链接 · 平台限制」，不冒充「已获取内容」。
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote_plus

from ..models import Resource
from ..query import Query
from .base import Context, Source, SourceMeta

# (展示名, 检索 URL 模板, 备注)
PORTALS = [
    ("中国大学MOOC", "https://www.icourse163.org/search.htm?search={q}", "国内高校慕课，需登录学习"),
    ("学堂在线", "https://www.xuetangx.com/search?query={q}", "清华发起，含名校课程"),
    ("智慧树", "https://www.zhihuishu.com/search.html?key={q}", "高校学分课平台"),
    ("超星/学习通", "https://www.chaoxing.com/search?keyword={q}", "高校常用，需机构账号"),
    ("国家高等教育智慧教育平台", "https://higher.smartedu.cn/search?keyword={q}", "教育部官方，2 万+ 课程"),
    ("百度文库", "https://wenku.baidu.com/search?word={q}", "课件/试卷极多，下载需付费"),
    ("道客巴巴", "https://www.doc88.com/search?q={q}", "文档分享站"),
    ("豆丁网", "https://www.docin.com/search.do?searchcat=2&searchType=1&nkey={q}", "文档分享站"),
    ("知网 CNKI", "https://kns.cnki.net/kns8s/defaultresult/index?kw={q}", "中文学术权威库，需机构权限"),
    ("万方数据", "https://www.wanfangdata.com.cn/search/searchList.do?searchType=all&searchWord={q}", "中文学位论文/期刊"),
    ("CSDN", "https://so.csdn.net/so/search?q={q}", "中文技术博客/课程笔记"),
    ("知乎", "https://www.zhihu.com/search?type=content&q={q}", "经验贴/学习方法"),
    ("Google Scholar", "https://scholar.google.com/scholar?q={q}", "英文学术，被引数据最全"),
    ("YouTube", "https://www.youtube.com/results?search_query={q}", "英文视频课最全"),
    ("中国慕课·爱课程", "https://www.icourses.cn/search?keyword={q}", "精品资源共享课"),
]


class LinkPortalSource(Source):
    meta = SourceMeta(
        id="portals",
        label="平台检索入口（仅链接）",
        kind="link",
        lang="zh",
        tier="link",
        note="这些平台实测无法稳定抓取：JS 渲染 / 登录墙 / 反爬，只提供直达检索链接",
    )

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        out: List[Resource] = []
        term = quote_plus(q.core)
        for name, template, note in PORTALS:
            out.append(
                self.make(
                    title=f"在「{name}」检索：{q.core}",
                    url=template.format(q=term),
                    kind="link",
                    lang="zh",
                    org=name,
                    description=f"{note}（本工具不抓取其内容，仅提供检索入口）",
                    extra={"portal": name, "access": "link-only"},
                )
            )
        return out
