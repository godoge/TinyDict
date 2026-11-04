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
from .wordbook_io import align_group_times, normalize_added_at

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
    def add(self, word: str, group_id: int = None,
            added_at: str = None) -> bool:
        """加入生词本并归入 group_id（默认分组）。返回是否新加入了该分组。

        added_at 供导入备份 / CSV 时还原原收藏时间，None 表示「就是现在」。
        """
        word = (word or "").strip()
        if not word:
            return False
        return self._db.wordbook_add(word, group_id, added_at)

    def add_words(self, words: Sequence[str], group_id: int) -> int:
        """批量把生词加入分组，返回新增的关联条数。"""
        return self._db.wordbook_add_words(words, group_id)

    def add_words_with_times(self, rows: Sequence[Tuple[str, str]],
                             group_id: int) -> int:
        """批量加入分组并保留文件里记录的时间；``rows`` 是 ``(词, 时间)`` 列表。

        用于「CSV 里写了 added_at、但没写 groups」的旧文件：仍然按用户选的
        分组导入，但收藏时间不再是导入那一刻。
        """
        clean = [(word, normalize_added_at(stamp))
                 for word, stamp in rows]
        return self._db.wordbook_add_rows(clean, group_id)

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
            group_id: int = ALL_GROUPS,
            group_ids: Optional[Sequence[int]] = None,
    ) -> List[Tuple[str, str, List[str], List[str]]]:
        """导出用：``[(word, added_at, [分组名…], [各分组时间…])]``。

        后两个列表一一对应，格式与 Android ``ExportRow`` 完全一致。

        ``group_ids`` 传了具体分组时按「只导出这些生词本」处理：以全部生词
        为基准，丢掉不属于任何所选分组的词，并把每行剩下的归属与时间收敛到
        所选分组。这样文件导入回任意一端都只会建出所选分组，不会把没选的
        分组一起带回来。``None`` 时完全走旧路径（逐字节兼容 Android）。
        """
        if group_ids is None:
            return self._db.wordbook_export(group_id)
        wanted_ids = set(group_ids)
        names = {g.name for g in self.groups() if g.id in wanted_ids}
        out: List[Tuple[str, str, List[str], List[str]]] = []
        for word, added, gs, times in self._db.wordbook_export(ALL_GROUPS):
            aligned = align_group_times(gs, times, added)
            pairs = [(n, t) for n, t in zip(gs, aligned) if n in names]
            if not pairs:
                continue
            out.append((word, added,
                        [n for n, _ in pairs], [t for _, t in pairs]))
        return out

    def restore(self, payload: dict) -> dict:
        """从 JSON 备份合并恢复（不覆盖、不删除现有数据）。

        payload 为 ``wordbook_io.parse_backup()`` 的结果。缺少的分组自动新建
        （顶层清单里没有词的空分组也会保留），已存在的词只补它还没有的归属，
        **每个分组各自的收藏时间**都会还原。
        """
        return self._restore(payload.get("groups") or [],
                             payload.get("words") or [])

    def restore_rows(self, rows: Sequence[dict]) -> dict:
        """从带归属的 CSV 行合并恢复，走与 JSON 备份完全相同的还原逻辑。

        ``rows`` 为 ``wordbook_io.parse_rows()`` 的结果。CSV 是扁平表，没有
        顶层分组清单，所以从各行里按顺序收集出分组名（含空归属行的兜底）。
        """
        groups: List[str] = []
        for row in rows:
            for name in row.get("groups") or []:
                if name and name not in groups:
                    groups.append(name)
        return self._restore(groups, rows)

    def _restore(self, group_names: Sequence[str],
                 items: Sequence[dict]) -> dict:
        """CSV / JSON 共用的恢复实现：建分组、按名还原、按分组写时间。

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

        for name in group_names:
            if name:
                _group_id(name)

        default_name = self.group_name(DEFAULT_GROUP_ID) or "默认分组"
        new_words = 0
        new_tags = 0
        for item in items:
            word = (item.get("word") or "").strip()
            if not word:
                continue
            existed = self._db.wordbook_has(word)
            names = [n for n in (item.get("groups") or []) if n]
            added_at = normalize_added_at(item.get("added_at") or "")
            times = align_group_times(
                names, item.get("group_added_at") or [], added_at)
            if not names:
                # 文件里没写分组（老备份 / 手写的 CSV）：归入默认分组，
                # 不允许出现无归属的词（数据层不变量）。
                names = [default_name]
                times = [added_at]
            seen = set()
            for i, name in enumerate(names):
                if name in seen:                # 同名分组只插一次，保留首次的时间
                    continue
                seen.add(name)
                gid = _group_id(name)
                if gid is None:
                    continue
                stamp = normalize_added_at(times[i]) or added_at
                if self._db.wordbook_add(word, gid, stamp or None):
                    new_tags += 1
            if not existed:
                new_words += 1
        return {"words": new_words, "tags": new_tags, "groups": new_groups}

    def stats(self) -> dict:
        """{'all': 全部生词数, 'groups': {id: 数}}。"""
        return self._db.wordbook_stats()
