"""搜索协调器：并发调用多个数据源"""

from __future__ import annotations

import asyncio

from location_tool.config import Config
from location_tool.location.amap import AmapClient
from location_tool.models import Restaurant, SearchQuery
from location_tool.sources.base import DataSource
from location_tool.sources.dianping import DianpingSource
from location_tool.sources.xiaohongshu import XiaohongshuSource


class SearchEngine:
    def __init__(self, config: Config):
        self.config = config
        self.amap = AmapClient(config)
        self._sources: list[DataSource] = []

        if config.sources.dianping:
            self._sources.append(DianpingSource(config))
        if config.sources.xiaohongshu:
            self._sources.append(XiaohongshuSource(config))

    async def close(self):
        await self.amap.close()
        for src in self._sources:
            await src.close()
        # 清理浏览器资源
        if self._sources:
            from location_tool.browser import BrowserManager
            bm = await BrowserManager.get()
            await bm.close()

    async def search(self, query: SearchQuery) -> list[Restaurant]:
        """并发搜索所有数据源，合并去重"""
        tasks: list = []

        # 高德 POI 搜索
        if self.config.sources.amap:
            if query.location:
                tasks.append(self.amap.search_nearby(
                    location=query.location,
                    keyword=query.keyword or query.cuisine or "餐厅",
                    radius=query.radius,
                    max_results=self.config.search.max_results,
                ))
            else:
                tasks.append(self.amap.search_by_keyword(
                    keyword=query.keyword or query.cuisine or "餐厅",
                    city=query.city,
                    max_results=self.config.search.max_results,
                ))

        # 其他数据源
        for src in self._sources:
            tasks.append(src.search(query))

        results_groups = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[Restaurant] = []
        for group in results_groups:
            if isinstance(group, Exception):
                continue
            all_results.extend(group)

        return self._deduplicate(all_results)

    @staticmethod
    def _deduplicate(restaurants: list[Restaurant]) -> list[Restaurant]:
        """根据餐厅名去重，优先保留信息更丰富的条目"""
        seen: dict[str, Restaurant] = {}
        for r in restaurants:
            key = r.name.strip()
            if not key:
                continue
            if key in seen:
                existing = seen[key]
                # 合并：保留评分更高、信息更多的
                if r.score > existing.score:
                    existing.score = r.score
                if r.price_per_person and not existing.price_per_person:
                    existing.price_per_person = r.price_per_person
                if r.location and not existing.location:
                    existing.location = r.location
                if r.review_count > existing.review_count:
                    existing.review_count = r.review_count
                existing.highlights.extend(r.highlights)
                existing.tags = list(set(existing.tags + r.tags))
            else:
                seen[key] = r
        return list(seen.values())
