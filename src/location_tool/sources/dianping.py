"""大众点评数据源（移动端模拟）"""

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
        "Mobile/15E148 MicroMessenger/8.0.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

SEARCH_URL = "https://m.dianping.com/search/keyword"


class DianpingSource(DataSource):
    name = "dianping"

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=15,
            headers=MOBILE_HEADERS,
            follow_redirects=True,
        )
        # 可在此处配置额外 cookie
        self.extra_cookies: dict[str, str] = {}

    async def close(self):
        await self._client.aclose()

    async def search(self, query: SearchQuery) -> list[Restaurant]:
        keyword = query.keyword or query.cuisine or "餐厅"
        city_id = self._city_to_id(query.city)

        params = {
            "cityId": city_id,
            "keyword": keyword,
        }

        try:
            resp = await self._client.get(
                SEARCH_URL,
                params=params,
                cookies=self.extra_cookies,
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            # 大众点评反爬严格，静默失败
            return []

        return self._parse_results(resp.text)

    def _parse_results(self, html: str) -> list[Restaurant]:
        soup = BeautifulSoup(html, "html.parser")
        restaurants: list[Restaurant] = []

        # 尝试解析搜索结果列表
        items = soup.select(".shopItem, .shop-list li, [class*='shop-item']")
        for item in items[:20]:
            try:
                r = self._parse_item(item)
                if r:
                    restaurants.append(r)
            except Exception:
                continue

        return restaurants

    def _parse_item(self, item) -> Restaurant | None:
        # 餐厅名
        name_el = item.select_one(".shopName, .name, h4, [class*='title']")
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if not name:
            return None

        # 评分
        score = 0.0
        score_el = item.select_one(".star, .score, [class*='star'], [class*='score']")
        if score_el:
            text = score_el.get_text(strip=True)
            nums = re.findall(r"[\d.]+", text)
            if nums:
                score = float(nums[0])

        # 人均
        price = 0.0
        price_el = item.select_one(".price, .mean-price, [class*='price']")
        if price_el:
            text = price_el.get_text(strip=True)
            nums = re.findall(r"[\d.]+", text)
            if nums:
                price = float(nums[0])

        # 分类/菜系
        cuisine = ""
        cat_el = item.select_one(".tag, .category, [class*='category']")
        if cat_el:
            cuisine = cat_el.get_text(strip=True)

        # 地址
        addr = ""
        addr_el = item.select_one(".addr, .address, [class*='addr']")
        if addr_el:
            addr = addr_el.get_text(strip=True)

        return Restaurant(
            name=name,
            cuisine=cuisine,
            score=score,
            price_per_person=price,
            address=addr,
            source="dianping",
        )

    @staticmethod
    def _city_to_id(city: str) -> str:
        """常用城市名 → 大众点评城市 ID"""
        mapping = {
            "北京": "2",
            "上海": "1",
            "广州": "4",
            "深圳": "7",
            "杭州": "10",
            "成都": "8",
            "南京": "5",
            "武汉": "6",
            "西安": "17",
            "重庆": "9",
        }
        return mapping.get(city, "2")
