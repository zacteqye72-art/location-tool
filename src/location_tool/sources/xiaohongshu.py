"""小红书数据源（搜索笔记提取餐厅推荐）"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from location_tool.models import Restaurant, SearchQuery
from location_tool.sources.base import DataSource

MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

SEARCH_URL = "https://www.xiaohongshu.com/search_result"


class XiaohongshuSource(DataSource):
    name = "xiaohongshu"

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=15,
            headers=MOBILE_HEADERS,
            follow_redirects=True,
        )
        self.extra_cookies: dict[str, str] = {}

    async def close(self):
        await self._client.aclose()

    async def search(self, query: SearchQuery) -> list[Restaurant]:
        keyword = query.keyword or query.cuisine or "餐厅"
        search_term = f"{query.city}{keyword}推荐" if query.city else f"{keyword}推荐"

        try:
            resp = await self._client.get(
                SEARCH_URL,
                params={"keyword": search_term, "source": "web_search_result_notes"},
                cookies=self.extra_cookies,
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return []

        return self._parse_results(resp.text)

    def _parse_results(self, html: str) -> list[Restaurant]:
        soup = BeautifulSoup(html, "html.parser")
        restaurants: list[Restaurant] = []

        # 小红书搜索结果以笔记卡片展示
        cards = soup.select(".note-item, [class*='note-card'], [class*='search-item']")
        for card in cards[:15]:
            try:
                items = self._extract_restaurants_from_card(card)
                restaurants.extend(items)
            except Exception:
                continue

        return restaurants

    def _extract_restaurants_from_card(self, card) -> list[Restaurant]:
        """从笔记卡片中提取餐厅信息"""
        results: list[Restaurant] = []

        title_el = card.select_one(".title, h3, [class*='title']")
        desc_el = card.select_one(".desc, .content, [class*='desc']")

        title = title_el.get_text(strip=True) if title_el else ""
        desc = desc_el.get_text(strip=True) if desc_el else ""
        full_text = f"{title} {desc}"

        if not full_text.strip():
            return results

        # 从文本中提取可能的餐厅名（常见模式：「店名」、【店名】、《店名》）
        bracket_names = re.findall(r"[「【《](.+?)[」】》]", full_text)

        # 提取人均价格
        price_match = re.search(r"人均[：:]?\s*(\d+)", full_text)
        price = float(price_match.group(1)) if price_match else 0

        # 提取评分
        score_match = re.search(r"(\d+\.?\d*)\s*分", full_text)
        score = float(score_match.group(1)) if score_match else 0
        if score > 5:
            score = score / 2  # 归一化到 5 分制

        if bracket_names:
            for name in bracket_names[:3]:
                results.append(Restaurant(
                    name=name,
                    score=score,
                    price_per_person=price,
                    source="xiaohongshu",
                    highlights=[title] if title else [],
                ))
        elif title:
            # 标题本身可能就是餐厅推荐
            results.append(Restaurant(
                name=title,
                score=score,
                price_per_person=price,
                source="xiaohongshu",
                highlights=[desc[:100]] if desc else [],
            ))

        return results
