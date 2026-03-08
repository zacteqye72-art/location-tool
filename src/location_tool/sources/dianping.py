"""大众点评数据源 — Playwright 浏览器爬取"""

from __future__ import annotations

import re

from location_tool.config import Config
from location_tool.models import Restaurant, SearchQuery
from location_tool.sources.base import DataSource
from location_tool.browser import BrowserManager, random_delay


class DianpingSource(DataSource):
    name = "dianping"

    def __init__(self, config: Config):
        self.config = config

    async def search(self, query: SearchQuery) -> list[Restaurant]:
        keyword = query.keyword or query.cuisine or "餐厅"
        city = query.city or "北京"

        try:
            bm = await BrowserManager.get()
            page = await bm.new_page()
        except Exception:
            return []

        try:
            # 搜索页 URL
            search_url = (
                f"https://www.dianping.com/search/keyword/0/{keyword}/0_0"
            )
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            await random_delay(1.0, 2.0)

            # 检测登录墙 / 验证码
            if await self._is_blocked(page):
                return []

            # 等待搜索结果加载
            try:
                await page.wait_for_selector(
                    ".shop-list li, #shop-all-list li, .svr-info, .tit",
                    timeout=8000,
                )
            except Exception:
                # 页面结构可能变化，尝试用通用选择器
                pass

            await random_delay(0.5, 1.0)

            # 用 page.evaluate 在 DOM 中提取餐厅数据
            items = await page.evaluate("""() => {
                const results = [];
                // 大众点评搜索结果列表
                const shopItems = document.querySelectorAll(
                    '#shop-all-list li, .shop-list li, .shop-list-ul li'
                );
                shopItems.forEach(item => {
                    try {
                        const nameEl = item.querySelector(
                            '.tit a, .shopname a, h4 a, .shop-name a, .txt .tit a'
                        );
                        const name = nameEl ? nameEl.textContent.trim() : '';
                        if (!name) return;

                        // 评分
                        const scoreEl = item.querySelector(
                            '.comment-list .star_icon, .sml-rank-stars, .star, .score'
                        );
                        let score = 0;
                        if (scoreEl) {
                            // 尝试从 class 提取星级 (star_45 = 4.5)
                            const cls = scoreEl.className || '';
                            const m = cls.match(/star_(\\d+)/);
                            if (m) score = parseInt(m[1]) / 10;
                            // 或直接取文本
                            if (!score) {
                                const txt = scoreEl.textContent.trim();
                                const n = parseFloat(txt);
                                if (!isNaN(n)) score = n;
                            }
                        }

                        // 人均
                        const priceEl = item.querySelector(
                            '.mean-price b, .mean-price, .price b, .avgPrice'
                        );
                        let price = 0;
                        if (priceEl) {
                            const pm = priceEl.textContent.match(/(\\d+)/);
                            if (pm) price = parseInt(pm[1]);
                        }

                        // 评论数
                        const reviewEl = item.querySelector(
                            '.review-num b, .comment-num, .review-num'
                        );
                        let reviewCount = 0;
                        if (reviewEl) {
                            const rm = reviewEl.textContent.match(/(\\d+)/);
                            if (rm) reviewCount = parseInt(rm[1]);
                        }

                        // 地址 / 区域
                        const addrEl = item.querySelector(
                            '.addr, .tag-addr .addr, .region'
                        );
                        const address = addrEl ? addrEl.textContent.trim() : '';

                        // 菜系
                        const cateEl = item.querySelector(
                            '.tag-addr .tag, .cuisine, .cate'
                        );
                        const cuisine = cateEl ? cateEl.textContent.trim() : '';

                        // 标签
                        const tagEls = item.querySelectorAll(
                            '.recommend-tag, .sml-tag, .tag'
                        );
                        const tags = [];
                        tagEls.forEach(t => {
                            const tt = t.textContent.trim();
                            if (tt && tt.length < 15) tags.push(tt);
                        });

                        results.push({
                            name, score, price, reviewCount,
                            address, cuisine, tags
                        });
                    } catch(e) {}
                });
                return results.slice(0, 15);
            }""")

            restaurants = [self._parse(item, city) for item in items if item.get("name")]
            return restaurants

        except Exception:
            return []
        finally:
            await page.close()

    async def _is_blocked(self, page) -> bool:
        """检测是否被登录墙 / 验证码拦截"""
        url = page.url
        if "verify" in url or "login" in url or "passport" in url:
            return True
        # 检查页面是否有验证码元素
        try:
            captcha = await page.query_selector(
                ".captcha, #captcha, .verify-wrap, .reCAPTCHA"
            )
            if captcha:
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _parse(item: dict, city: str) -> Restaurant:
        # 从标签中提取推荐理由
        tags = item.get("tags") or []
        highlights = []
        if tags:
            highlights = [f"大众点评推荐：{', '.join(tags[:3])}"]

        return Restaurant(
            name=item.get("name") or "",
            cuisine=item.get("cuisine") or "",
            score=float(item.get("score") or 0),
            price_per_person=float(item.get("price") or 0),
            address=item.get("address") or "",
            review_count=int(item.get("reviewCount") or 0),
            source="dianping",
            tags=tags,
            highlights=highlights,
        )
