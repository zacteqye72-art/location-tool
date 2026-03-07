"""LLM 偏好分析与自然语言理解（OpenAI ChatGPT）"""

from __future__ import annotations

import json

from openai import OpenAI

from location_tool.config import Config
from location_tool.models import SearchQuery
from location_tool.preference.profile import PreferenceProfile


class LLMAssistant:
    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)
        self.profile = PreferenceProfile()

    def _chat(self, messages: list[dict], max_tokens: int | None = None) -> str:
        resp = self.client.chat.completions.create(
            model=self.config.llm.model,
            max_completion_tokens=max_tokens or self.config.llm.max_tokens,
            messages=messages,
        )
        return resp.choices[0].message.content.strip()

    def parse_search_query(self, text: str, city: str = "") -> SearchQuery:
        """用 LLM 从自然语言中提取搜索参数"""
        prompt = f"""从以下用户输入中提取餐厅搜索参数，返回 JSON：
- keyword: 搜索关键词
- cuisine: 菜系（如川菜、日料、火锅等）
- price_min: 最低人均（数字，没有则 0）
- price_max: 最高人均（数字，没有则 0）
- city: 城市（没有则空字符串）

用户输入："{text}"

只返回 JSON，不要其他内容。"""

        raw = self._chat([{"role": "user", "content": prompt}], max_tokens=256)

        try:
            # 处理可能的 markdown 代码块
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            return SearchQuery(keyword=text, city=city or self.config.search.default_city, raw_text=text)

        return SearchQuery(
            keyword=data.get("keyword", text),
            cuisine=data.get("cuisine", ""),
            price_min=float(data.get("price_min", 0)),
            price_max=float(data.get("price_max", 0)),
            city=data.get("city", "") or city or self.config.search.default_city,
            raw_text=text,
        )

    def analyze_preferences(self) -> str:
        """分析搜索历史，生成/更新偏好画像"""
        history = self.profile.load_history()
        if not history:
            return "暂无搜索历史，无法分析偏好。"

        current_prefs = self.profile.load_preferences()

        prompt = f"""分析以下用户的餐厅搜索和选择历史，生成偏好画像。

搜索历史（最近记录）：
{json.dumps(history[-30:], ensure_ascii=False, indent=2)}

当前偏好（可能为空）：
{json.dumps(current_prefs, ensure_ascii=False, indent=2)}

请返回 JSON 格式的偏好画像：
{{
  "cuisines": ["偏好的菜系列表"],
  "price_range": {{"min": 数字, "max": 数字}},
  "taste_notes": ["口味偏好标签"],
  "avoid": ["不喜欢的标签"],
  "llm_summary": "一段自然语言的偏好总结"
}}

只返回 JSON。"""

        raw = self._chat([{"role": "user", "content": prompt}])

        try:
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            new_prefs = json.loads(raw)
            self.profile.save_preferences(new_prefs)
            return new_prefs.get("llm_summary", "偏好已更新。")
        except (json.JSONDecodeError, IndexError):
            return "偏好分析失败，请稍后重试。"

    def recommend(self, restaurants: list[dict], query_text: str) -> str:
        """对搜索结果做个性化推荐说明"""
        prefs = self.profile.load_preferences()

        prompt = f"""你是一个美食推荐助手。用户搜索了 "{query_text}"。

用户偏好：
{json.dumps(prefs, ensure_ascii=False, indent=2) if prefs.get("llm_summary") else "暂无偏好记录"}

搜索结果（前 5 个）：
{json.dumps(restaurants[:5], ensure_ascii=False, indent=2)}

请用简洁友好的中文，给出 2-3 句推荐说明，告诉用户哪个最适合他，为什么。"""

        return self._chat([{"role": "user", "content": prompt}], max_tokens=512)

    def chat(self, user_message: str, conversation: list[dict]) -> str:
        """对话模式：自然语言交互"""
        system = """你是 Location Tool 的美食助手。你可以帮用户：
1. 搜索餐厅（当用户表达想吃什么时，提取搜索意图）
2. 推荐餐厅
3. 聊美食相关话题
4. 分析用户的口味偏好

当用户表达搜索意图时，在回复末尾添加搜索标记，格式严格如下：
[SEARCH:关键词|城市|人均最低|人均最高]

规则：
- 关键词必须简短，只写菜系或餐厅类型（如"西餐""火锅""日料"），不要加地点、价格、风格等修饰词
- 城市只写城市名（如"上海""北京"），从对话中推断，默认"北京"
- 人均最低和最高写数字，没有则写0
- 例如用户说"想在上海吃火锅，人均150左右"，标记为 [SEARCH:火锅|上海|100|200]
- 例如用户说"附近有什么好吃的日料"，标记为 [SEARCH:日料|北京|0|0]
- 每条回复最多一个 SEARCH 标记，放在回复最末尾"""

        messages = [{"role": "system", "content": system}] + conversation + [{"role": "user", "content": user_message}]

        return self._chat(messages)
