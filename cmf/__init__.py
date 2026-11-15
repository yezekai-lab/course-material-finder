# -*- coding: utf-8 -*-
"""Course Material Finder — 大学课程资料获取助手.

Layered retrieval:
  1. structured APIs      (openalex / crossref / zenodo / chinaooc / ...)
  2. result-page scraping (bing / baidu / bilibili)
  3. local site indexes   (MIT OCW sitemap, OpenStax catalogue)
  4. deep-link fallbacks  (platforms that block crawling -> give the link)

Crawl what is crawlable, link what is not, and say which is which.
"""
from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
