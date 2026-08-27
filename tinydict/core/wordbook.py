"""生词本：基于 SQLite 的本地生词管理（添加 / 删除 / 列表 / 判断）。"""

from typing import List, Tuple

from .database import Database


class WordBook:
    def __init__(self, db: Database):
        self._db = db

    def add(self, word: str) -> bool:
        """添加生词；已存在返回 False。"""
        word = word.strip()
        if not word:
            return False
        return self._db.wordbook_add(word)

    def remove(self, word: str) -> bool:
        return self._db.wordbook_remove(word.strip())

    def clear(self) -> None:
        self._db.wordbook_clear()

    def has(self, word: str) -> bool:
        return self._db.wordbook_has(word.strip())

    def words(self) -> List[Tuple[str, str]]:
        """返回 [(word, added_at)]，按添加时间倒序。"""
        return self._db.wordbook_list()
