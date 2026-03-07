"""结果排序：基于距离、评分、价格、偏好的加权排序"""

from __future__ import annotations

from location_tool.config import RankingConfig
from location_tool.models import Restaurant, SearchQuery


class Ranker:
    def __init__(self, config: RankingConfig):
        self.config = config

    def rank(
        self,
        restaurants: list[Restaurant],
        query: SearchQuery,
        preference_tags: list[str] | None = None,
    ) -> list[Restaurant]:
        """对餐厅列表打分排序"""
        if not restaurants:
            return []

        # 收集归一化所需的范围
        scores = [r.score for r in restaurants if r.score > 0]
        max_score = max(scores) if scores else 5.0
        min_score = min(scores) if scores else 0.0

        distances = [r.distance for r in restaurants if r.distance > 0]
        max_dist = max(distances) if distances else 1.0

        reviews = [r.review_count for r in restaurants if r.review_count > 0]
        max_reviews = max(reviews) if reviews else 1

        for r in restaurants:
            r.rank_score = self._compute_score(
                r, query, max_score, min_score, max_dist, max_reviews,
                preference_tags or [],
            )

        restaurants.sort(key=lambda r: r.rank_score, reverse=True)
        return restaurants

    def _compute_score(
        self,
        r: Restaurant,
        query: SearchQuery,
        max_score: float,
        min_score: float,
        max_dist: float,
        max_reviews: int,
        preference_tags: list[str],
    ) -> float:
        c = self.config

        # 评分归一化 (0-1)
        score_range = max_score - min_score if max_score > min_score else 1.0
        norm_score = (r.score - min_score) / score_range if r.score > 0 else 0.3

        # 距离：越近越好 (0-1)
        norm_dist = 1 - (r.distance / max_dist) if r.distance > 0 and max_dist > 0 else 0.5

        # 价格匹配度 (0-1)
        norm_price = self._price_match(r, query)

        # 评论数归一化 (0-1)
        norm_reviews = (r.review_count / max_reviews) if r.review_count > 0 and max_reviews > 0 else 0.3

        # 偏好匹配 (0-1)
        norm_pref = self._preference_match(r, preference_tags)

        return (
            c.score_weight * norm_score
            + c.distance_weight * norm_dist
            + c.price_weight * norm_price
            + c.review_weight * norm_reviews
            + c.preference_weight * norm_pref
        )

    @staticmethod
    def _price_match(r: Restaurant, query: SearchQuery) -> float:
        """价格匹配度"""
        if not query.price_max and not query.price_min:
            return 0.5  # 无价格要求
        if not r.price_per_person:
            return 0.3  # 无价格信息

        price = r.price_per_person
        if query.price_min and query.price_max:
            if query.price_min <= price <= query.price_max:
                return 1.0
            # 超出范围，计算偏离程度
            mid = (query.price_min + query.price_max) / 2
            deviation = abs(price - mid) / mid
            return max(0, 1 - deviation)
        elif query.price_max:
            return 1.0 if price <= query.price_max else max(0, 1 - (price - query.price_max) / query.price_max)
        else:
            return 1.0 if price >= query.price_min else max(0, price / query.price_min)

    @staticmethod
    def _preference_match(r: Restaurant, preference_tags: list[str]) -> float:
        """偏好标签匹配度"""
        if not preference_tags:
            return 0.5
        r_tags = set(t.lower() for t in r.tags + [r.cuisine])
        matches = sum(1 for t in preference_tags if t.lower() in r_tags or any(t.lower() in rt for rt in r_tags))
        return min(1.0, matches / max(len(preference_tags), 1))
