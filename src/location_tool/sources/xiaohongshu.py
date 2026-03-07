"""小红书数据源 — 通过 OpenAI web_search 获取笔记推荐"""

from __future__ import annotations

import json
import re

from openai import OpenAI

from location_tool.config import Config
from location_tool.models import Restaurant, SearchQuery
from location_tool.sources.base import DataSource


def _extract_json_array(text: str) -> list[dict]:
    """从 LLM 返回的文本中提取 JSON 数组"""
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    start = text.find("[")
    if start == -1:
        return []
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return []
    return []


class XiaohongshuSource(DataSource):
    name = "xiaohongshu"

    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)

    async def search(self, query: SearchQuery) -> list[Restaurant]:
        keyword = query.keyword or query.cuisine or "餐厅"
        city = query.city or "北京"
        price_hint = ""
        if query.price_min or query.price_max:
            price_hint = f"，人均{query.price_min or '?'}-{query.price_max or '?'}元"

        prompt = f"""搜索小红书上关于 {city}「{keyword}」餐厅的推荐笔记{price_hint}，提取被推荐最多的 10 家餐厅。

返回 JSON 数组，每个元素包含：
- name: 餐厅名
- cuisine: 菜系
- score: 推荐程度（1-5，根据笔记数量和评价估算）
- price_per_person: 人均消费（数字，没有则 0）
- address: 地址（如有）
- tags: 标签数组（如 ["网红店", "拍照好看", "氛围感"]）
- highlights: 小红书博主的推荐理由数组（1-2条）

只返回 JSON 数组，不要其他内容。"""

        try:
            resp = self.client.responses.create(
                model=self.config.llm.model,
                tools=[{"type": "web_search_preview"}],
                input=prompt,
            )

            text = ""
            for item in resp.output:
                if item.type == "message":
                    for block in item.content:
                        if block.type == "output_text":
                            text = block.text
                            break

            if not text:
                return []

            data = _extract_json_array(text)
            return [self._parse(item) for item in data if isinstance(item, dict)]
        except Exception:
            return []

    @staticmethod
    def _parse(item: dict) -> Restaurant:
        return Restaurant(
            name=item.get("name") or "",
            cuisine=item.get("cuisine") or "",
            score=float(item.get("score") or 0),
            price_per_person=float(item.get("price_per_person") or 0),
            address=item.get("address") or "",
            source="xiaohongshu",
            tags=item.get("tags") or [],
            highlights=item.get("highlights") or [],
        )
