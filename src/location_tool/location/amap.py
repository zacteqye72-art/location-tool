"""高德地图 API 封装：地理编码、POI 搜索、路线规划"""

from __future__ import annotations

import httpx

from location_tool.config import Config
from location_tool.models import Location, Restaurant

BASE_URL = "https://restapi.amap.com/v3"


class AmapClient:
    def __init__(self, config: Config):
        self.key = config.amap_api_key
        self.default_city = config.search.default_city
        self._client = httpx.AsyncClient(timeout=10)

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str, params: dict) -> dict:
        params["key"] = self.key
        resp = await self._client.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            raise RuntimeError(f"高德 API 错误: {data.get('info', 'unknown')}")
        return data

    # ---- 地理编码 ----

    async def geocode(self, address: str, city: str = "") -> Location | None:
        """地址 → 经纬度"""
        data = await self._get("/geocode/geo", {
            "address": address,
            "city": city or self.default_city,
        })
        geocodes = data.get("geocodes", [])
        if not geocodes:
            return None
        g = geocodes[0]
        lng, lat = g["location"].split(",")
        return Location(
            longitude=float(lng),
            latitude=float(lat),
            address=g.get("formatted_address", address),
            city=g.get("city", "") if isinstance(g.get("city"), str) else city,
            district=g.get("district", "") if isinstance(g.get("district"), str) else "",
        )

    async def reverse_geocode(self, lng: float, lat: float) -> Location:
        """经纬度 → 地址"""
        data = await self._get("/geocode/regeo", {
            "location": f"{lng},{lat}",
        })
        comp = data.get("regeocode", {}).get("addressComponent", {})
        return Location(
            longitude=lng,
            latitude=lat,
            address=data.get("regeocode", {}).get("formatted_address", ""),
            city=comp.get("city", "") if isinstance(comp.get("city"), str) else "",
            district=comp.get("district", "") if isinstance(comp.get("district"), str) else "",
        )

    # ---- POI 搜索 ----

    async def search_nearby(
        self,
        location: Location,
        keyword: str = "餐厅",
        radius: int = 3000,
        types: str = "050000",  # 餐饮服务大类
        max_results: int = 20,
    ) -> list[Restaurant]:
        """周边 POI 搜索"""
        data = await self._get("/place/around", {
            "location": location.lnglat,
            "keywords": keyword,
            "types": types,
            "radius": radius,
            "offset": max_results,
            "sortrule": "weight",
        })
        return [self._parse_poi(poi) for poi in data.get("pois", [])]

    async def search_by_keyword(
        self,
        keyword: str,
        city: str = "",
        max_results: int = 20,
    ) -> list[Restaurant]:
        """关键字搜索 POI"""
        data = await self._get("/place/text", {
            "keywords": keyword,
            "city": city or self.default_city,
            "types": "050000",
            "offset": max_results,
            "citylimit": "true",
        })
        return [self._parse_poi(poi) for poi in data.get("pois", [])]

    def _parse_poi(self, poi: dict) -> Restaurant:
        loc = None
        if poi.get("location"):
            lng, lat = poi["location"].split(",")
            loc = Location(longitude=float(lng), latitude=float(lat))

        biz = poi.get("biz_ext", {})
        cost = biz.get("cost") if biz else None

        return Restaurant(
            name=poi.get("name", ""),
            location=loc,
            cuisine=poi.get("type", "").split(";")[-1] if poi.get("type") else "",
            score=float(biz.get("rating", 0)) if biz and biz.get("rating") else 0,
            price_per_person=float(cost) if cost else 0,
            phone=poi.get("tel", ""),
            address=poi.get("address", "") if isinstance(poi.get("address"), str) else "",
            source="amap",
            distance=float(poi.get("distance", 0)),
            tags=poi.get("type", "").split(";") if poi.get("type") else [],
            raw_data=poi,
        )

    # ---- 路线规划（用于计算中间点）----

    async def driving_distance(self, origin: Location, destination: Location) -> dict:
        """驾车路线规划，返回距离（米）和时间（秒）"""
        data = await self._get("/direction/driving", {
            "origin": origin.lnglat,
            "destination": destination.lnglat,
            "strategy": 0,
        })
        route = data.get("route", {})
        paths = route.get("paths", [])
        if not paths:
            return {"distance": 0, "duration": 0}
        path = paths[0]
        return {
            "distance": int(path.get("distance", 0)),
            "duration": int(path.get("duration", 0)),
        }

    async def find_midpoint(self, loc_a: Location, loc_b: Location) -> Location:
        """计算两个位置的地理中心点，返回带地址的 Location"""
        mid_lng = (loc_a.longitude + loc_b.longitude) / 2
        mid_lat = (loc_a.latitude + loc_b.latitude) / 2
        return await self.reverse_geocode(mid_lng, mid_lat)
