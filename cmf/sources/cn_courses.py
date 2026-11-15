# -*- coding: utf-8 -*-
"""中文课程/视频：国家高等教育智慧教育平台（chinaooc 后端）+ B站。

两个源都是实测可抓的：
  * chinaooc /api/v1/courses 是平台前端自己在调的接口，返回结构化 JSON；
  * B站搜索需要先访问首页拿 buvid3 cookie，之后 /x/web-interface/search/type 返回 JSON。
"""
from __future__ import annotations

import re
from typing import List

from ..models import Resource
from ..query import Query
from ..textutil import strip_html
from .base import Context, Source, SourceMeta

CHINAOOC_API = "https://api.chinaooc.com.cn/api/v1/courses"
SMARTEDU_COURSE = "https://higher.smartedu.cn/course/{cid}"


class ChinaoocSource(Source):
    meta = SourceMeta(
        id="chinaooc",
        label="国家高等教育智慧教育平台",
        kind="course",
        lang="zh",
        tier="api",
        note="教育部官方课程库，含 985/211 及地方高校慕课",
        ttl=3600,
    )

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        out: List[Resource] = []
        pages = 2 if ctx.per_source > 20 else 1
        for page in range(1, pages + 1):
            try:
                data = ctx.http.get_json(
                    CHINAOOC_API,
                    params={"keyword": q.core, "page": page},
                    timeout=self.meta.timeout,
                    ttl=self.meta.ttl,
                )
            except Exception:  # noqa: BLE001
                if page == 1:
                    raise
                break
            courses = (data or {}).get("courses") or []
            for c in courses:
                cid = c.get("courseID") or ""
                name = strip_html(c.get("name") or "")
                school = strip_html(c.get("school") or "")
                teachers = [t.get("teacherName", "") for t in (c.get("teachers") or [])][:3]
                tags = [strip_html(t) for t in (c.get("tags") or [])][:6]
                url = SMARTEDU_COURSE.format(cid=cid) if cid else "https://higher.smartedu.cn/"
                out.append(
                    self.make(
                        title=name,
                        url=url,
                        kind="course",
                        lang="zh",
                        year=self.year_of(c.get("start") or c.get("updateDate")),
                        org=school or (c.get("platform") or ""),
                        authors=[t for t in teachers if t],
                        description=strip_html(c.get("describe") or ""),
                        extra={
                            "platform": c.get("platform", ""),
                            "national": bool(c.get("national")),
                            "enroll": c.get("totalEnroll", ""),
                            "tags": tags,
                            "duration_weeks": c.get("duration"),
                            "course_id": cid,
                        },
                    )
                )
            if len(out) >= ctx.per_source:
                break
        return out[: ctx.per_source]


class BilibiliSource(Source):
    meta = SourceMeta(
        id="bilibili",
        label="哔哩哔哩 视频课",
        kind="video",
        lang="zh",
        tier="engine",
        note="国内高校课程录像/考研名师课的主要集散地",
        ttl=1800,
    )
    API = "https://api.bilibili.com/x/web-interface/search/type"

    def fetch(self, q: Query, ctx: Context) -> List[Resource]:
        data = ctx.http.get_json(
            self.API,
            params={
                "search_type": "video",
                "keyword": q.core,
                "page": 1,
                "page_size": min(max(ctx.per_source, 10), 50),
            },
            headers={"Referer": "https://www.bilibili.com/"},
            warmup="https://www.bilibili.com/",
            timeout=self.meta.timeout,
            ttl=self.meta.ttl,
        )
        if not isinstance(data, dict) or data.get("code") not in (0, None):
            raise RuntimeError(f"B站接口返回 code={data.get('code')}: {data.get('message')}")
        items = ((data.get("data") or {}).get("result")) or []
        out: List[Resource] = []
        for it in items:
            bvid = it.get("bvid") or ""
            if not bvid:
                continue  # 广告位/直播位没有 bvid
            title = strip_html(it.get("title") or "").replace("\n", " ")
            pub = it.get("pubdate")
            year = None
            if isinstance(pub, (int, float)) and pub > 0:
                import datetime

                year = datetime.datetime.fromtimestamp(pub).year
            out.append(
                self.make(
                    title=title,
                    url=f"https://www.bilibili.com/video/{bvid}",
                    kind="video",
                    lang="zh",
                    year=year,
                    org=it.get("author", ""),
                    authors=[it.get("author", "")] if it.get("author") else [],
                    description=strip_html(it.get("description") or ""),
                    extra={
                        "bvid": bvid,
                        "play": it.get("play"),
                        "danmaku": it.get("video_review"),
                        "duration": it.get("duration"),
                        "favorites": it.get("favorites"),
                    },
                )
            )
        return out[: ctx.per_source]
