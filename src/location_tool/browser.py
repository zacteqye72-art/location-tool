"""单例浏览器管理器 — Playwright 持久化上下文"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PROFILE_DIR = _DATA_DIR / "browser_profile"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# 注入脚本：移除 webdriver 标记
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
window.chrome = {runtime: {}};
"""


class BrowserManager:
    """Playwright 持久化浏览器单例"""

    _instance: BrowserManager | None = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None

    @classmethod
    async def get(cls) -> BrowserManager:
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    async def _ensure_context(self, *, headless: bool = True) -> BrowserContext:
        """懒初始化持久化上下文"""
        if self._context is not None:
            return self._context

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        self._pw = await async_playwright().start()
        self._context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        # 为所有新 page 注入反检测脚本
        await self._context.add_init_script(_STEALTH_JS)
        return self._context

    async def new_page(self, *, headless: bool = True) -> Page:
        """获取一个新标签页"""
        ctx = await self._ensure_context(headless=headless)
        page = await ctx.new_page()
        return page

    async def open_for_login(self, url: str) -> None:
        """可见模式打开页面，等待用户手动登录"""
        # 登录时需要关闭已有的 headless 上下文，重新以 headed 模式启动
        await self.close()

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=["--disable-blink-features=AutomationControlled"],
        )
        await self._context.add_init_script(_STEALTH_JS)

        page = await self._context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        # 返回 page 让调用方决定何时结束
        return page

    async def close(self) -> None:
        """关闭浏览器和 Playwright"""
        if self._context:
            await self._context.close()
            self._context = None
        if self._pw:
            await self._pw.stop()
            self._pw = None
        BrowserManager._instance = None


async def random_delay(lo: float = 0.5, hi: float = 1.5) -> None:
    """随机延迟，模拟人类操作"""
    await asyncio.sleep(random.uniform(lo, hi))
