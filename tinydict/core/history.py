"""查询历史：本地记录查过的词（按词去重，保留最近时间与累计次数）。

与生词本不同，查询历史是**被动记录**的：每次成功查词自动写入，
不占用用户的收藏列表。典型用途：

- 忘了刚才查过的词，回头翻一下；
- 搜索框为空时直接展示最近查过的词（点一下就能再看）；
- 「历史」窗口里集中查看、搜索、删除、清空。

存储上限默认 2000 条，超出后自动淘汰最久未查询的记录，
避免长期使用后数据库无限膨胀。
"""

from datetime import datetime
from typing import List, Optional, Tuple

from .database import Database

DEFAULT_LIMIT = 2000


class HistoryBook:
    """查询历史的门面：记录 / 列表 / 搜索 / 删除 / 清空。"""

    def __init__(self, db: Database, limit: int = DEFAULT_LIMIT):
        self._db = db
        self._limit = limit if limit and limit > 0 else DEFAULT_LIMIT

    # ------------------------------------------------------------------ 记录
    def record(self, word: str) -> bool:
        """记录一次查询（同一个词只刷新时间与次数）。"""
        return self._db.history_record(word, self._limit)

    # ------------------------------------------------------------------ 读取
    def recent(self, limit: int = 200, keyword: str = ""
               ) -> List[Tuple[str, str, int]]:
        """最近查询的词：[(word, queried_at, times)]，时间倒序。"""
        return self._db.history_recent(limit, keyword)

    def search(self, keyword: str, limit: int = 200
               ) -> List[Tuple[str, str, int]]:
        """在历史里按片段过滤（不区分大小写）。"""
        return self._db.history_recent(limit, keyword)

    def words(self, limit: int = 200, keyword: str = "") -> List[str]:
        """只要词本身（给搜索框联想用）。"""
        return [w for w, _t, _n in self.recent(limit, keyword)]

    def count(self) -> int:
        return self._db.history_count()

    # ------------------------------------------------------------------ 维护
    def remove(self, word: str) -> bool:
        """删除单条历史记录。"""
        return self._db.history_remove(word)

    def clear(self) -> None:
        """清空全部查询历史。"""
        self._db.history_clear()


def format_time(iso: str) -> str:
    """把 ISO 时间转成界面上更友好的短格式。

    今天 → "今天 18:04"；昨天 → "昨天 09:12"；
    今年内 → "09-08 14:30"；更早 → "2025-12-31"。
    解析失败时原样返回，保证界面永远有东西可显示。
    """
    raw = (iso or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("T", " ").split(".")[0])
    except ValueError:
        return raw
    now = datetime.now()
    if dt.date() == now.date():
        return f"今天 {dt:%H:%M}"
    if (now.date() - dt.date()).days == 1:
        return f"昨天 {dt:%H:%M}"
    if dt.year == now.year:
        return f"{dt:%m-%d %H:%M}"
    return f"{dt:%Y-%m-%d}"


def display_text(word: str, iso: str, times: int = 1) -> str:
    """列表项显示文本：`word    今天 18:04（3 次）`。"""
    text = f"{word}    （{format_time(iso)}"
    if times and times > 1:
        text += f" · {times} 次"
    return text + "）"


__all__ = ["HistoryBook", "DEFAULT_LIMIT", "format_time", "display_text"]
