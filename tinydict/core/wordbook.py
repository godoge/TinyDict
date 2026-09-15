"""生词本：基于 SQLite 的本地生词管理（分组 / 添加 / 移除 / 列表 / 判断）。

分组采用**标签式多归属**：一个生词可以同时属于多个分组。
- wordbook        ：生词本体（记录首次加入时间），
- wordbook_tags   ：生词 ↔ 分组 的关联。

视图：ALL_GROUPS(-1) 表示全部生词；正整数表示某个分组。

**不变量：每个生词必须至少属于一个分组**，没有「未分组」这种状态。
把词移出最后一个分组、删除分组、清空分组之后，它会自动归入默认分组
（DEFAULT_GROUP_ID）；只有「从默认分组移出 / 清空默认分组」例外，此时
视为从生词本中移除。数据层负责兜底（database._ensure_has_group）。
"""

from typing import List, Optional, Sequence, Tuple

from .database import (
    ALL_GROUPS, DEFAULT_GROUP_ID, Database, WordGroup,
)

__all__ = [
    "WordBook", "WordGroup",
    "ALL_GROUPS", "DEFAULT_GROUP_ID",
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

        with_words=False：生词保留（只属于本分组的词归入默认分组）；
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

    def export_rows(
            self,
            group_id: int = ALL_GROUPS) -> List[Tuple[str, str, List[str]]]:
        """导出用：[(word, added_at, [所属分组名…])]。"""
        return self._db.wordbook_export(group_id)

    def restore(self, payload: dict) -> dict:
        """从 JSON 备份合并恢复（不覆盖、不删除现有数据）。

        payload 为 wordbook_io.parse_backup 的结果。缺少的分组自动新建，
        已存在的词跳过（只补它还没有的分组归属）。

        返回 {'words': 新增生词数, 'tags': 新增分组归属数, 'groups': 新建分组数}
        """
        name_to_id = {g.name: g.id for g in self.groups()}
        new_groups = 0

        def _group_id(name: str):
            nonlocal new_groups
            gid = name_to_id.get(name)
            if gid is not None:
                return gid
            g = self.add_group(name)
            if g is None:                       # 理论上不会发生（刚查过清单）
                return None
            name_to_id[name] = g.id
            new_groups += 1
            return g.id

        for name in (payload.get("groups") or []):
            if name:
                _group_id(name)

        new_words = 0
        new_tags = 0
        for item in (payload.get("words") or []):
            word = (item.get("word") or "").strip()
            if not word:
                continue
            existed = self._db.wordbook_has(word)
            names = [n for n in (item.get("groups") or []) if n]
            if not names:
                # 备份里没写分组（老备份）：归入默认分组，不允许无归属
                names = [self.group_name(DEFAULT_GROUP_ID) or "默认分组"]
            for name in names:
                gid = _group_id(name)
                if gid is None:
                    continue
                if self._db.wordbook_add(word, gid):
                    new_tags += 1
            if not existed:
                new_words += 1
        return {"words": new_words, "tags": new_tags, "groups": new_groups}

    def stats(self) -> dict:
        """{'all': 全部生词数, 'groups': {id: 数}}。"""
        return self._db.wordbook_stats()
