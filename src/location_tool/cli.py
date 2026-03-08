"""CLI 入口：Typer 命令定义"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from location_tool.config import load_config
from location_tool.engine.ranker import Ranker
from location_tool.engine.search import SearchEngine
from location_tool.models import Location, Restaurant, SearchQuery, SearchRecord
from location_tool.preference.llm import LLMAssistant
from location_tool.preference.profile import PreferenceProfile

app = typer.Typer(
    name="lt",
    help="餐厅智能搜索 CLI - 整合大众点评、小红书和高德地图数据",
    invoke_without_command=True,
)
console = Console()


@app.callback()
def main(ctx: typer.Context):
    """餐厅智能搜索 CLI - 默认进入对话模式"""
    if ctx.invoked_subcommand is None:
        chat()

# 存储当前会话位置
_current_location: Location | None = None


def _run(coro):
    """同步运行异步函数"""
    return asyncio.run(coro)


def _display_results(restaurants: list[Restaurant], title: str = "搜索结果"):
    """用 Rich 表格展示餐厅列表"""
    if not restaurants:
        console.print("[yellow]未找到相关餐厅[/yellow]")
        return

    table = Table(title=title, show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("餐厅名", style="bold cyan", max_width=20)
    table.add_column("菜系", max_width=10)
    table.add_column("评分", justify="right", width=5)
    table.add_column("人均", justify="right", width=8)
    table.add_column("距离", justify="right", width=8)
    table.add_column("地址", max_width=25)
    table.add_column("来源", width=6)

    for i, r in enumerate(restaurants[:15], 1):
        score_str = f"{r.score:.1f}" if r.score else "-"
        price_str = f"¥{r.price_per_person:.0f}" if r.price_per_person else "-"
        dist_str = f"{r.distance:.0f}m" if r.distance else "-"
        table.add_row(
            str(i), r.name, r.cuisine, score_str,
            price_str, dist_str, r.address[:25] if r.address else "-", r.source,
        )

    console.print(table)

    if restaurants[0].highlights:
        console.print(f"\n[dim]💡 {restaurants[0].highlights[0]}[/dim]")


# ---- 命令 ----


@app.command()
def locate(address: str = typer.Argument(..., help="位置描述，如 '北京国贸'")):
    """设置当前位置"""
    global _current_location

    async def _do():
        global _current_location
        config = load_config()
        from location_tool.location.amap import AmapClient
        client = AmapClient(config)
        try:
            loc = await client.geocode(address)
            if loc:
                _current_location = loc
                # 保存到临时文件以便跨命令共享
                _save_location(loc)
                console.print(f"[green]📍 位置已设置[/green]")
                console.print(f"   地址: {loc.address}")
                console.print(f"   坐标: {loc.longitude}, {loc.latitude}")
                if loc.district:
                    console.print(f"   区域: {loc.city} {loc.district}")
            else:
                console.print(f"[red]无法解析地址: {address}[/red]")
        finally:
            await client.close()

    _run(_do())


@app.command()
def search(
    query: str = typer.Argument(..., help="搜索描述，如 '想吃火锅，人均150左右'"),
    radius: int = typer.Option(None, "--radius", "-r", help="搜索半径（米）"),
    city: str = typer.Option(None, "--city", "-c", help="城市"),
    no_llm: bool = typer.Option(False, "--no-llm", help="不使用 LLM 解析查询"),
):
    """搜索餐厅"""

    async def _do():
        config = load_config()
        profile = PreferenceProfile()

        # 构建搜索查询
        if no_llm or not config.openai_api_key:
            sq = SearchQuery(
                keyword=query,
                city=city or config.search.default_city,
                radius=radius or config.search.radius,
                raw_text=query,
            )
        else:
            llm = LLMAssistant(config)
            with console.status("🤔 理解搜索意图..."):
                sq = llm.parse_search_query(query, city or "")

        sq.radius = radius or sq.radius or config.search.radius
        sq.city = sq.city or city or config.search.default_city

        # 加载位置
        loc = _load_location()
        if loc:
            sq.location = loc

        console.print(f"[dim]搜索: {sq.keyword or sq.cuisine} | 城市: {sq.city} | 半径: {sq.radius}m[/dim]")

        # 执行搜索
        engine = SearchEngine(config)
        try:
            with console.status("🔍 搜索中..."):
                results = await engine.search(sq)
        finally:
            await engine.close()

        # 排序
        ranker = Ranker(config.ranking)
        pref_tags = profile.get_preference_tags()
        results = ranker.rank(results, sq, pref_tags)

        _display_results(results)

        # LLM 推荐说明
        if results and config.openai_api_key and not no_llm:
            llm = LLMAssistant(config)
            top_results = [
                {"name": r.name, "cuisine": r.cuisine, "score": r.score,
                 "price": r.price_per_person, "distance": r.distance}
                for r in results[:5]
            ]
            with console.status("💡 生成推荐..."):
                rec = llm.recommend(top_results, query)
            console.print(Panel(rec, title="推荐", border_style="green"))

        # 记录历史
        record = SearchRecord(query=query, results_count=len(results))
        profile.add_history(record)

    _run(_do())


@app.command()
def meet(
    location_a: str = typer.Argument(..., help="你的位置，如 '国贸'"),
    other: str = typer.Option(..., "--other", "-o", help="对方的位置"),
    cuisine: str = typer.Option("", "--cuisine", "-k", help="菜系偏好"),
    radius: int = typer.Option(3000, "--radius", "-r", help="中间点搜索半径"),
):
    """约饭模式：找两人中间点附近的餐厅"""

    async def _do():
        config = load_config()
        from location_tool.location.amap import AmapClient
        client = AmapClient(config)

        try:
            with console.status("📍 解析位置..."):
                loc_a = await client.geocode(location_a)
                loc_b = await client.geocode(other)

            if not loc_a:
                console.print(f"[red]无法解析位置: {location_a}[/red]")
                return
            if not loc_b:
                console.print(f"[red]无法解析位置: {other}[/red]")
                return

            console.print(f"[dim]你的位置: {loc_a.address}[/dim]")
            console.print(f"[dim]对方位置: {loc_b.address}[/dim]")

            with console.status("🧭 计算中间点..."):
                midpoint = await client.find_midpoint(loc_a, loc_b)

            console.print(f"[green]📍 推荐会合区域: {midpoint.address}[/green]")

            # 在中间点搜索餐厅
            sq = SearchQuery(
                keyword=cuisine or "餐厅",
                cuisine=cuisine,
                location=midpoint,
                radius=radius,
                city=config.search.default_city,
            )

            engine = SearchEngine(config)
            try:
                with console.status("🔍 搜索中间点附近餐厅..."):
                    results = await engine.search(sq)
            finally:
                await engine.close()

            ranker = Ranker(config.ranking)
            profile = PreferenceProfile()
            results = ranker.rank(results, sq, profile.get_preference_tags())

            _display_results(results, title=f"会合点附近 - {midpoint.address}")
        finally:
            await client.close()

    _run(_do())


@app.command()
def prefer():
    """查看/分析偏好画像"""
    config = load_config()
    profile = PreferenceProfile()
    prefs = profile.load_preferences()

    if prefs.get("llm_summary"):
        console.print(Panel(prefs["llm_summary"], title="当前偏好画像", border_style="blue"))
        console.print(f"  菜系偏好: {', '.join(prefs.get('cuisines', [])) or '无'}")
        console.print(f"  口味标签: {', '.join(prefs.get('taste_notes', [])) or '无'}")
        console.print(f"  避免: {', '.join(prefs.get('avoid', [])) or '无'}")
        price = prefs.get("price_range")
        if price:
            console.print(f"  价格区间: ¥{price.get('min', '?')}-{price.get('max', '?')}")
    else:
        console.print("[dim]暂无偏好画像[/dim]")

    # 自动分析
    if config.openai_api_key:
        history = profile.load_history()
        if len(history) >= 3:
            if typer.confirm("是否用 AI 分析历史记录更新偏好？"):
                llm = LLMAssistant(config)
                with console.status("🧠 分析偏好中..."):
                    summary = llm.analyze_preferences()
                console.print(Panel(summary, title="偏好分析结果", border_style="green"))
        elif not history:
            console.print("[dim]多搜索几次后，AI 可以帮你分析口味偏好[/dim]")


@app.command()
def history(
    limit: int = typer.Option(10, "--limit", "-n", help="显示条数"),
):
    """查看搜索历史"""
    profile = PreferenceProfile()
    records = profile.load_history()

    if not records:
        console.print("[dim]暂无搜索历史[/dim]")
        return

    table = Table(title="搜索历史")
    table.add_column("时间", style="dim", width=19)
    table.add_column("搜索内容", style="cyan")
    table.add_column("结果数", justify="right", width=6)
    table.add_column("选择", style="green")

    for r in records[-limit:]:
        table.add_row(
            r.get("timestamp", "")[:19],
            r.get("query", ""),
            str(r.get("results_count", 0)),
            r.get("selected", "-") or "-",
        )

    console.print(table)


@app.command()
def login(
    platform: str = typer.Argument(
        ..., help="平台名称：dianping 或 xiaohongshu"
    ),
):
    """打开浏览器手动登录平台，保存 cookie"""
    urls = {
        "dianping": "https://www.dianping.com",
        "xiaohongshu": "https://www.xiaohongshu.com",
    }
    if platform not in urls:
        console.print(f"[red]不支持的平台: {platform}，可选: dianping, xiaohongshu[/red]")
        raise typer.Exit(1)

    async def _do():
        from location_tool.browser import BrowserManager
        bm = await BrowserManager.get()
        page = await bm.open_for_login(urls[platform])
        console.print(f"[green]浏览器已打开 {platform}，请手动登录。[/green]")
        console.print("[dim]登录完成后按 Enter 键关闭浏览器并保存 cookie...[/dim]")

        try:
            input()  # 阻塞等待用户按回车
        except (KeyboardInterrupt, EOFError):
            pass

        await bm.close()
        console.print(f"[green]cookie 已保存，后续搜索将自动使用登录态。[/green]")

    _run(_do())


@app.command()
def chat():
    """进入对话模式，自然语言交互"""
    config = load_config()
    if not config.openai_api_key:
        console.print("[red]对话模式需要配置 OPENAI_API_KEY[/red]")
        raise typer.Exit(1)

    llm = LLMAssistant(config)
    conversation: list[dict] = []

    console.print("[bold]🍽️  美食助手对话模式[/bold]")
    console.print("[dim]输入你想吃什么，或聊聊美食。输入 quit 退出。[/dim]\n")

    while True:
        try:
            user_input = console.input("[bold cyan]你> [/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]再见！[/dim]")
            break

        if not user_input.strip():
            continue

        with console.status("思考中..."):
            reply = llm.chat(user_input, conversation)

        conversation.append({"role": "user", "content": user_input})
        conversation.append({"role": "assistant", "content": reply})

        # 检查是否有搜索意图 [SEARCH:关键词|城市|人均最低|人均最高]
        search_match = re.search(r"\[SEARCH:(.+?)\]", reply)
        if search_match:
            search_tag = search_match.group(1)
            clean_reply = reply.replace(search_match.group(0), "").strip()
            console.print(f"[bold]助手>[/bold] {clean_reply}\n")

            # 解析搜索参数
            parts = [p.strip() for p in search_tag.split("|")]
            keyword = parts[0] if len(parts) > 0 else "餐厅"
            city = parts[1] if len(parts) > 1 and parts[1] else config.search.default_city
            price_min = float(parts[2]) if len(parts) > 2 and parts[2] and parts[2] != "0" else 0
            price_max = float(parts[3]) if len(parts) > 3 and parts[3] and parts[3] != "0" else 0

            console.print(f"[dim]🔍 搜索: {keyword} | 城市: {city} | 人均: {f'¥{price_min:.0f}-{price_max:.0f}' if price_max else '不限'}[/dim]")

            async def _auto_search():
                sq = SearchQuery(
                    keyword=keyword,
                    cuisine=keyword,
                    city=city,
                    radius=config.search.radius,
                    price_min=price_min,
                    price_max=price_max,
                )
                loc = _load_location()
                if loc:
                    sq.location = loc

                engine = SearchEngine(config)
                try:
                    results = await engine.search(sq)
                finally:
                    await engine.close()

                ranker = Ranker(config.ranking)
                profile = PreferenceProfile()
                results = ranker.rank(results, sq, profile.get_preference_tags())
                _display_results(results)

                # LLM 推荐
                if results and config.openai_api_key:
                    top = [
                        {"name": r.name, "cuisine": r.cuisine, "score": r.score,
                         "price": r.price_per_person, "distance": r.distance}
                        for r in results[:5]
                    ]
                    with console.status("💡 生成推荐..."):
                        rec = llm.recommend(top, f"{keyword} {city}")
                    console.print(Panel(rec, title="推荐", border_style="green"))

                record = SearchRecord(query=f"{keyword}({city})", results_count=len(results))
                profile.add_history(record)

            _run(_auto_search())
        else:
            console.print(f"[bold]助手>[/bold] {reply}\n")


# ---- 位置持久化（跨命令共享）----

def _location_file():
    from location_tool.config import DATA_DIR
    return DATA_DIR / ".current_location.json"


def _save_location(loc: Location):
    path = _location_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(loc), f, ensure_ascii=False)


def _load_location() -> Location | None:
    path = _location_file()
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Location(**data)


if __name__ == "__main__":
    app()
