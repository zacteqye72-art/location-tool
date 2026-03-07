"""配置加载：dotenv + YAML"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _load_yaml() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@dataclass
class SearchConfig:
    radius: int = 3000
    max_results: int = 20
    default_city: str = "北京"


@dataclass
class RankingConfig:
    score_weight: float = 0.35
    distance_weight: float = 0.25
    price_weight: float = 0.15
    review_weight: float = 0.15
    preference_weight: float = 0.10


@dataclass
class SourcesConfig:
    amap: bool = True
    dianping: bool = True
    xiaohongshu: bool = True


@dataclass
class LLMConfig:
    model: str = "gpt-5.4"
    max_tokens: int = 2048


@dataclass
class Config:
    amap_api_key: str = ""
    openai_api_key: str = ""
    search: SearchConfig = field(default_factory=SearchConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)


def load_config() -> Config:
    """加载所有配置"""
    _load_env()
    raw = _load_yaml()

    search_raw = raw.get("search", {})
    ranking_raw = raw.get("ranking", {})
    sources_raw = raw.get("sources", {})
    llm_raw = raw.get("llm", {})

    return Config(
        amap_api_key=os.getenv("AMAP_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        search=SearchConfig(**{k: v for k, v in search_raw.items() if k in SearchConfig.__dataclass_fields__}),
        ranking=RankingConfig(**{k: v for k, v in ranking_raw.items() if k in RankingConfig.__dataclass_fields__}),
        sources=SourcesConfig(**{k: v for k, v in sources_raw.items() if k in SourcesConfig.__dataclass_fields__}),
        llm=LLMConfig(**{k: v for k, v in llm_raw.items() if k in LLMConfig.__dataclass_fields__}),
    )
