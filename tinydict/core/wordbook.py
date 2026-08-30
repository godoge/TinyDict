"""生词本：基于 SQLite 的本地生词管理（分组 / 添加 / 移除 / 列表 / 判断）。

分组采用**标签式多归属**：一个生词可以同时属于多个分组。
- wordbook        ：生词本体（记录首次加入时间），
- wordbook_tags   ：生词 ↔ 分组 的关联。

由此派生出两种「视图」：
- ALL_GROUPS(-1)：全部生词；
- UNGROUPED(0)  ：已加入生词本但不属于任何分组的生词（例如被移出最后一个
                  分组后保留下来的词）。
"""

from typing import List, Optional, Sequence, Tuple

from .database import (
    ALL_GROUPS, DEFAULT_GROUP_ID, UNGROUPED, Database, WordGroup,
)

__all__ = [
    "WordBook", "WordGroup",
    "ALL_GROUPS", "UNGROUPED", "DEFAULT_GROUP_ID",
]


class WordBook:
    def __init__(self, db: Database):
        self._db = db

    # ------------------------------------------------------------------ 分组
    def groups(self) -> List[WordGroup]:
        """全部分组（含生词数），按界面顺序。"""
        return self._db.group_list()

    def group_name(self, group_id: int) -> str:
        for g in self._db.group_list():
            if g.id == group_id:
                return g.name
        return ""

    def add_group(self, name: str) -> Optional[WordGroup]:
        """新建分组，重名返回 None。"""
        name = (name or "").strip()
        if not name:
            return None
        gid = self._db.group_add(name)
        if gid is None:
            return None
        return WordGroup(id=gid, name=name, count=0)

    def rename_group(self, group_id: int, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        return self._db.group_rename(group_id, name)

    def remove_group(self, group_id: int, with_words: bool = False) -> int:
        """删除分组，返回受影响的生词条数。

        with_words=False：生词保留（只属于本分组的词变为「未分组」）；
        with_words=True ：连同这些生词一起从生词本删除。
        """
        return self._db.group_remove(group_id, with_words)

    def reorder_groups(self, ordered_ids: Sequence[int]):
        self._db.group_reorder(ordered_ids)

    @staticmethod
    def default_group_id() -> int:
        return DEFAULT_GROUP_ID

    # ------------------------------------------------------------------ 生词
    def add(self, word: str, group_id: int = None) -> bool:
        """加入生词本并归入 group_id（默认分组）。返回是否新加入了该分组。"""
        word = (word or "").strip()
        if not word:
            return False
        return self._db.wordbook_add(word, group_id)

    def add_words(self, words: Sequence[str], group_id: int) -> int:
        """批量把生词加入分组，返回新增的关联条数。"""
        return self._db.wordbook_add_words(words, group_id)

    def remove(self, word: str) -> bool:
        """从生词本彻底删除（含全部分组关联）。"""
        return self._db.wordbook_remove((word or "").strip())

    def remove_from_group(self, word: str, group_id: int) -> bool:
        """只把生词移出该分组，生词本体保留。"""
        return self._db.wordbook_remove_from_group((word or "").strip(), group_id)

    def remove_words_from_group(self, words: Sequence[str], group_id: int) -> int:
        return self._db.wordbook_remove_words_from_group(words, group_id)

    def clear(self, group_id: int = ALL_GROUPS) -> None:
        """清空整个生词本（默认）或指定分组。"""
        self._db.wordbook_clear(group_id)

    def has(self, word: str, group_id: int = None) -> bool:
        """group_id 为空时判断是否在生词本中，否则判断是否在该分组中。"""
        return self._db.wordbook_has((word or "").strip(), group_id)

    def groups_of(self, word: str) -> List[str]:
        """该生词所属的全部分组名。"""
        return self._db.wordbook_groups_of((word or "").strip())

    def words(self, group_id: int = ALL_GROUPS) -> List[Tuple[str, str]]:
        """返回 [(word, added_at)]，按加入时间倒序。"""
        return self._db.wordbook_list(group_id)

    def stats(self) -> dict:
        """{'all': 全部生词数, 'ungrouped': 未分组数, 'groups': {id: 数}}。"""
        return self._db.wordbook_stats()
