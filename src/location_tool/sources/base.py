"""数据源抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod

from location_tool.models import Restaurant, SearchQuery


class DataSource(ABC):
    """数据源统一接口"""

    name: str = "base"

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[Restaurant]:
        """搜索餐厅，返回结果列表"""
        ...

    async def close(self):
        """清理资源"""
        pass
