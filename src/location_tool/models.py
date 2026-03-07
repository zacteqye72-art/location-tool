"""数据模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Location:
    """地理位置"""
    longitude: float
    latitude: float
    address: str = ""
    city: str = ""
    district: str = ""

    @property
    def lnglat(self) -> str:
        """高德格式：经度,纬度"""
        return f"{self.longitude},{self.latitude}"


@dataclass
class Restaurant:
    """餐厅信息"""
    name: str
    location: Location | None = None
    cuisine: str = ""            # 菜系
    score: float = 0.0           # 评分 (0-5 或 0-10，归一化到 0-5)
    price_per_person: float = 0  # 人均消费
    review_count: int = 0        # 评论数
    phone: str = ""
    address: str = ""
    source: str = ""             # 数据来源 (amap/dianping/xiaohongshu)
    distance: float = 0          # 距搜索点距离（米）
    tags: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)  # 推荐理由/亮点
    raw_data: dict = field(default_factory=dict)

    # 排序用的归一化分数
    rank_score: float = 0.0


@dataclass
class SearchQuery:
    """搜索请求"""
    keyword: str = ""
    cuisine: str = ""
    location: Location | None = None
    radius: int = 3000
    price_min: float = 0
    price_max: float = 0
    city: str = "北京"
    raw_text: str = ""  # 用户原始输入


@dataclass
class SearchRecord:
    """搜索历史记录"""
    query: str
    timestamp: str = ""
    results_count: int = 0
    selected: str | None = None  # 用户最终选择的餐厅名

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
