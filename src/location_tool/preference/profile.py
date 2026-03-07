"""偏好画像管理：读写偏好 JSON，记录搜索历史"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from location_tool.config import DATA_DIR
from location_tool.models import SearchRecord


PREFERENCES_FILE = DATA_DIR / "preferences.json"
HISTORY_FILE = DATA_DIR / "history.json"


class PreferenceProfile:
    def __init__(self):
        self._prefs_path = PREFERENCES_FILE
        self._history_path = HISTORY_FILE

    # ---- 偏好 ----

    def load_preferences(self) -> dict:
        if self._prefs_path.exists():
            with open(self._prefs_path, encoding="utf-8") as f:
                return json.load(f)
        return self._default_prefs()

    def save_preferences(self, prefs: dict) -> None:
        prefs["updated_at"] = datetime.now().isoformat()
        self._prefs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._prefs_path, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)

    def get_preference_tags(self) -> list[str]:
        """返回用于排序的偏好标签"""
        prefs = self.load_preferences()
        tags = list(prefs.get("cuisines", []))
        tags.extend(prefs.get("taste_notes", []))
        return tags

    @staticmethod
    def _default_prefs() -> dict:
        return {
            "cuisines": [],
            "price_range": None,
            "taste_notes": [],
            "avoid": [],
            "llm_summary": None,
            "updated_at": None,
        }

    # ---- 历史记录 ----

    def load_history(self) -> list[dict]:
        if self._history_path.exists():
            with open(self._history_path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def add_history(self, record: SearchRecord) -> None:
        history = self.load_history()
        history.append({
            "query": record.query,
            "timestamp": record.timestamp,
            "results_count": record.results_count,
            "selected": record.selected,
        })
        # 只保留最近 200 条
        history = history[-200:]
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def record_selection(self, restaurant_name: str) -> None:
        """记录用户选择的餐厅到最近一条历史"""
        history = self.load_history()
        if history:
            history[-1]["selected"] = restaurant_name
            with open(self._history_path, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
