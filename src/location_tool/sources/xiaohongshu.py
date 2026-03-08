"""小红书数据源 — Playwright 浏览器爬取笔记推荐"""

from __future__ import annotations

import re

from location_tool.config import Config
from location_tool.models import Restaurant, SearchQuery
from location_tool.sources.base import DataSource
from location_tool.browser import BrowserManager, random_delay


# 从笔记标题/正文提取餐厅名的常见模式
_RESTAURANT_PATTERN = re.compile(
    r"[「《【]([^」》】]{2,20})[」》】]"  # 书名号/括号括起来的名称
    r"|(?:推荐|安利|打卡|必吃|探店)[：:]?\s*([^\s,，。！!]{2,15})"  # "推荐xxx"
)


class XiaohongshuSource(DataSource):
    name = "xiaohongshu"

    def __init__(self, config: Config):
        self.config = config

    async def search(self, query: SearchQuery) -> list[Restaurant]:
        keyword = query.keyword or query.cuisine or "餐厅"
        city = query.city or "北京"
        search_term = f"{city} {keyword} 餐厅推荐"

        try:
            bm = await BrowserManager.get()
            page = await bm.new_page()
        except Exception:
            return []

        try:
            search_url = (
                f"https://www.xiaohongshu.com/search_result?"
                f"keyword={search_term}&type=1"
            )
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            await random_delay(1.5, 2.5)

            # 检测登录墙
            if await self._is_blocked(page):
                return []

            # 等待笔记列表加载
            try:
                await page.wait_for_selector(
                    ".note-item, .feeds-page .note-item, section.note-item",
                    timeout=8000,
                )
            except Exception:
                pass

            await random_delay(0.5, 1.0)

            # 提取笔记卡片信息
            notes = await page.evaluate("""() => {
                const results = [];
                const items = document.querySelectorAll(
                    '.note-item, section.note-item, .feeds-page .note-item, [data-v-a264b01a]'
                );
                items.forEach(item => {
                    try {
                        const titleEl = item.querySelector(
                            '.title, .note-title, .desc, a.title span, .footer .title'
                        );
                        const title = titleEl ? titleEl.textContent.trim() : '';

                        const descEl = item.querySelector(
                            '.desc, .note-desc, .content'
                        );
                        const desc = descEl ? descEl.textContent.trim() : '';

                        const likesEl = item.querySelector(
                            '.like-count, .count, .like-wrapper span, [data-v-like]'
                        );
                        let likes = 0;
                        if (likesEl) {
                            const lm = likesEl.textContent.match(/(\\d+)/);
                            if (lm) likes = parseInt(lm[1]);
                        }

                        if (title || desc) {
                            results.push({ title, desc, likes });
                        }
                    } catch(e) {}
                });
                return results.slice(0, 20);
            }""")

            # 从笔记标题/描述中用正则提取餐厅名
            restaurant_counts: dict[str, dict] = {}
            for note in notes:
                text = f"{note.get('title', '')} {note.get('desc', '')}"
                names = self._extract_restaurant_names(text)
                likes = note.get("likes", 0)
                for name in names:
                    if name not in restaurant_counts:
                        restaurant_counts[name] = {
                            "mentions": 0,
                            "total_likes": 0,
                            "highlights": [],
                        }
                    restaurant_counts[name]["mentions"] += 1
                    restaurant_counts[name]["total_likes"] += likes
                    title = note.get("title", "")
                    if title and len(restaurant_counts[name]["highlights"]) < 2:
                        restaurant_counts[name]["highlights"].append(title)

            # 按提及次数排序，转为 Restaurant
            sorted_names = sorted(
                restaurant_counts.items(),
                key=lambda x: (x[1]["mentions"], x[1]["total_likes"]),
                reverse=True,
            )

            restaurants = []
            for name, info in sorted_names[:10]:
                # 根据提及次数估算推荐度 (1-5)
                mentions = info["mentions"]
                score = min(5.0, 1.0 + mentions * 0.8)

                restaurants.append(Restaurant(
                    name=name,
                    cuisine=keyword if keyword != "餐厅" else "",
                    score=score,
                    source="xiaohongshu",
                    tags=["小红书推荐"],
                    highlights=[
                        f"被 {mentions} 篇笔记提及"
                    ] + info["highlights"][:1],
                ))

            return restaurants

        except Exception:
            return []
        finally:
            await page.close()

    async def _is_blocked(self, page) -> bool:
        """检测是否被登录墙拦截"""
        url = page.url
        if "login" in url or "passport" in url:
            return True
        try:
            login_modal = await page.query_selector(
                ".login-container, .captcha-container, #captcha"
            )
            if login_modal:
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _extract_restaurant_names(text: str) -> list[str]:
        """从笔记文本中用正则提取餐厅名"""
        names = []
        for m in _RESTAURANT_PATTERN.finditer(text):
            name = m.group(1) or m.group(2)
            if name:
                name = name.strip()
                # 过滤太短或明显不是餐厅名的
                if len(name) >= 2 and not any(
                    w in name for w in ("小红书", "笔记", "合集", "攻略", "总结", "分享")
                ):
                    names.append(name)
        return names
