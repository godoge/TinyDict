"""SQLite 存储层（挂载式架构）。

数据库只保存轻量数据：
- dicts          : 词库注册信息（路径 / 名称 / 启用状态 / 优先级 / 挂载后的统计数）
- wordbook       : 生词本（生词本体，记录首次加入时间）
- wordbook_groups: 生词本分组
- wordbook_tags  : 生词 ↔ 分组 关联（标签式多归属：一个词可属于多个分组）

词条正文与 MDD 资源**不再入库**：查询与资源渲染直接从挂载的
.mdx/.mdd 原文件按需读取（详见 core.mdx_access）。
旧的 entries / resources 表在启动时自动删除（旧版全量导入数据）。

连接管理：SQLite 连接不能跨线程复用，这里按线程维护局部连接
（threading.local），并开启 WAL 模式以支持读写并发。
"""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import List, Sequence


@dataclass
class DictInfo:
    """词库元数据。"""
    id: int
    name: str
    filename: str
    encoding: str
    entry_count: int
    resource_count: int
    enabled: bool
    sort_order: int


@dataclass
class WordGroup:
    """生词本分组。"""
    id: int
    name: str
    count: int = 0


# 生词本分组相关的哨兵值（group_id 列只使用正整数，故用 0 / -1 表达虚拟分组）
DEFAULT_GROUP_ID = 1   # 默认分组：随库创建，可重命名、不可删除
ALL_GROUPS = -1        # 虚拟分组：全部生词
UNGROUPED = 0          # 虚拟分组：未归入任何分组的生词

_DEFAULT_GROUP_NAME = "默认分组"


_SCHEMA = """
DROP TABLE IF EXISTS entries;
DROP TABLE IF EXISTS resources;
CREATE TABLE IF NOT EXISTS dicts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    encoding TEXT DEFAULT 'utf-8',
    entry_count INTEGER DEFAULT 0,
    resource_count INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    imported_at TEXT
);
CREATE TABLE IF NOT EXISTS wordbook(
    word TEXT PRIMARY KEY,
    added_at TEXT
);
CREATE TABLE IF NOT EXISTS wordbook_groups(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS wordbook_tags(
    word TEXT NOT NULL,
    group_id INTEGER NOT NULL,
    added_at TEXT,
    PRIMARY KEY(word, group_id)
);
CREATE INDEX IF NOT EXISTS idx_wordbook_tags_group ON wordbook_tags(group_id);
"""


class Database:
    def __init__(self, path):
        self._path = str(path)
        self._local = threading.local()
        self._init_schema()

    # ------------------------------------------------------------------ 连接
    def conn(self) -> sqlite3.Connection:
        """返回当前线程的数据库连接（惰性创建）。"""
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, timeout=30, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    def _init_schema(self):
        with self.conn():
            self.conn().executescript(_SCHEMA)
        self._migrate_wordbook_groups()

    def _migrate_wordbook_groups(self):
        """生词本分组迁移。

        - 确保默认分组存在（id=1，旧库升级时补建）；
        - 旧版升级：把「没有任何分组关联」的生词归入默认分组，避免升级后
          生词全部掉进「未分组」而看起来像丢数据。

        注意：旧数据迁移**只能执行一次**（用 PRAGMA user_version 记录）。
        若每次启动都跑，已经从默认分组移出的词会被重新塞回去，
        「移出默认分组」这个操作就永远失效。
        """
        c = self.conn()
        now = datetime.now().isoformat(timespec="seconds")
        exists = c.execute(
            "SELECT 1 FROM wordbook_groups WHERE id=?", (DEFAULT_GROUP_ID,)
        ).fetchone()
        if exists is None:
            c.execute(
                "INSERT INTO wordbook_groups(id, name, sort_order, created_at)"
                " VALUES(?,?,?,?)",
                (DEFAULT_GROUP_ID, _DEFAULT_GROUP_NAME, 0, now),
            )
        version = c.execute("PRAGMA user_version").fetchone()[0] or 0
        if version < 1:
            c.execute(
                "INSERT OR IGNORE INTO wordbook_tags(word, group_id, added_at)"
                " SELECT w.word, ?, COALESCE(w.added_at, ?) FROM wordbook w"
                " WHERE NOT EXISTS("
                "SELECT 1 FROM wordbook_tags t WHERE t.word=w.word)",
                (DEFAULT_GROUP_ID, now),
            )
            c.execute("PRAGMA user_version=1")
        c.commit()

    # ------------------------------------------------------------------ 词库
    def list_dicts(self) -> List[DictInfo]:
        rows = self.conn().execute(
            "SELECT id, name, filename, encoding, entry_count, resource_count,"
            " enabled, sort_order FROM dicts ORDER BY sort_order, id"
        ).fetchall()
        return [
            DictInfo(
                id=r["id"], name=r["name"], filename=r["filename"],
                encoding=r["encoding"] or "utf-8",
                entry_count=r["entry_count"] or 0,
                resource_count=r["resource_count"] or 0,
                enabled=bool(r["enabled"]), sort_order=r["sort_order"] or 0,
            )
            for r in rows
        ]

    def next_sort_order(self) -> int:
        row = self.conn().execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM dicts"
        ).fetchone()
        return (row[0] or 0) + 1

    def add_dict(self, name: str, filename: str, encoding: str) -> int:
        cur = self.conn().execute(
            "INSERT INTO dicts(name, filename, encoding, sort_order, imported_at)"
            " VALUES(?,?,?,?,?)",
            (name, filename, encoding, self.next_sort_order(),
             datetime.now().isoformat(timespec="seconds")),
        )
        self.conn().commit()
        return cur.lastrowid

    def update_dict_counts(self, dict_id: int, entry_count: int, resource_count: int):
        """挂载完成后回填统计数（词条数 / 资源数，来自原文件）。"""
        self.conn().execute(
            "UPDATE dicts SET entry_count=?, resource_count=? WHERE id=?",
            (entry_count, resource_count, dict_id),
        )
        self.conn().commit()

    def remove_dict(self, dict_id: int):
        """取消注册词库（词条本就在原文件中，无需清理数据）。"""
        self.conn().execute(
            "DELETE FROM dicts WHERE id=?", (dict_id,))
        self.conn().commit()

    def set_enabled(self, dict_id: int, enabled: bool):
        self.conn().execute(
            "UPDATE dicts SET enabled=? WHERE id=?", (1 if enabled else 0, dict_id)
        )
        self.conn().commit()

    def set_filename(self, dict_id: int, filename: str):
        """修复路径：更新词库注册的文件位置（文件改名 / 移动后）。"""
        self.conn().execute(
            "UPDATE dicts SET filename=? WHERE id=?", (filename, dict_id)
        )
        self.conn().commit()

    def set_name(self, dict_id: int, name: str):
        """更新词库显示名（占位符修复 / 用户重命名场景）。"""
        self.conn().execute(
            "UPDATE dicts SET name=? WHERE id=?", (name, dict_id)
        )
        self.conn().commit()

    def reorder(self, ordered_ids: Sequence[int]):
        """按给定顺序重写 sort_order（ordered_ids 即优先级从高到低）。"""
        c = self.conn()
        for pos, dict_id in enumerate(ordered_ids, start=1):
            c.execute("UPDATE dicts SET sort_order=? WHERE id=?", (pos, dict_id))
        c.commit()

    def find_dict_by_filename(self, filename: str) -> List[DictInfo]:
        return [d for d in self.list_dicts() if d.filename == filename]

    def unique_dict_name(self, name: str) -> str:
        """同名词库自动追加序号，保证界面展示可区分。"""
        existing = {d.name for d in self.list_dicts()}
        if name not in existing:
            return name
        n = 2
        while f"{name} ({n})" in existing:
            n += 1
        return f"{name} ({n})"

    # ------------------------------------------------------------ 生词本分组
    def group_list(self) -> List[WordGroup]:
        """返回全部分组（含每个分组的生词数），按界面顺序排序。"""
        rows = self.conn().execute(
            "SELECT g.id, g.name,"
            " (SELECT COUNT(*) FROM wordbook_tags t WHERE t.group_id=g.id) AS cnt"
            " FROM wordbook_groups g ORDER BY g.sort_order, g.id"
        ).fetchall()
        return [WordGroup(id=r["id"], name=r["name"], count=r["cnt"] or 0)
                for r in rows]

    def _group_next_sort_order(self) -> int:
        row = self.conn().execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM wordbook_groups"
        ).fetchone()
        return (row[0] or 0) + 1

    def group_add(self, name: str):
        """新建分组，成功返回新 id，重名返回 None。"""
        try:
            cur = self.conn().execute(
                "INSERT INTO wordbook_groups(name, sort_order, created_at)"
                " VALUES(?,?,?)",
                (name, self._group_next_sort_order(),
                 datetime.now().isoformat(timespec="seconds")),
            )
            self.conn().commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None  # 重名

    def group_rename(self, group_id: int, name: str) -> bool:
        try:
            self.conn().execute(
                "UPDATE wordbook_groups SET name=? WHERE id=?", (name, group_id))
            self.conn().commit()
            return True
        except sqlite3.IntegrityError:
            return False  # 重名

    def group_remove(self, group_id: int, with_words: bool = False) -> int:
        """删除分组，返回受影响的生词条数。

        with_words=False：仅解除分组关联，生词保留（只属于本分组的词变为「未分组」）；
        with_words=True ：同时把这些生词从生词本彻底删除（含其在其它分组的关联）。
        """
        c = self.conn()
        words = [r[0] for r in c.execute(
            "SELECT word FROM wordbook_tags WHERE group_id=?", (group_id,)
        ).fetchall()]
        if with_words:
            for w in words:
                c.execute("DELETE FROM wordbook_tags WHERE word=?", (w,))
                c.execute("DELETE FROM wordbook WHERE word=?", (w,))
        else:
            c.execute("DELETE FROM wordbook_tags WHERE group_id=?", (group_id,))
        c.execute("DELETE FROM wordbook_groups WHERE id=?", (group_id,))
        c.commit()
        return len(words)

    def group_reorder(self, ordered_ids: Sequence[int]):
        c = self.conn()
        for pos, group_id in enumerate(ordered_ids, start=1):
            c.execute("UPDATE wordbook_groups SET sort_order=? WHERE id=?",
                      (pos, group_id))
        c.commit()

    # ------------------------------------------------------------------ 生词本
    def wordbook_add(self, word: str, group_id: int = None) -> bool:
        """把生词加入生词本并归入 group_id（默认分组）。

        返回 True 表示「新加入了该分组」；词已在生词本中但不在该分组时同样
        返回 True（多分组模型下，加入新分组是有意义的操作）。
        """
        gid = group_id if group_id else DEFAULT_GROUP_ID
        now = datetime.now().isoformat(timespec="seconds")
        c = self.conn()
        c.execute(
            "INSERT OR IGNORE INTO wordbook(word, added_at) VALUES(?,?)",
            (word, now))
        cur = c.execute(
            "INSERT OR IGNORE INTO wordbook_tags(word, group_id, added_at)"
            " VALUES(?,?,?)", (word, gid, now))
        c.commit()
        return cur.rowcount > 0

    def wordbook_add_words(self, words: Sequence[str], group_id: int) -> int:
        """批量加入分组，返回新增的关联条数（已在该分组的跳过）。"""
        gid = group_id if group_id else DEFAULT_GROUP_ID
        now = datetime.now().isoformat(timespec="seconds")
        c = self.conn()
        added = 0
        for raw in words:
            word = (raw or "").strip()
            if not word:
                continue
            c.execute(
                "INSERT OR IGNORE INTO wordbook(word, added_at) VALUES(?,?)",
                (word, now))
            cur = c.execute(
                "INSERT OR IGNORE INTO wordbook_tags(word, group_id, added_at)"
                " VALUES(?,?,?)", (word, gid, now))
            added += cur.rowcount
        c.commit()
        return added

    def wordbook_remove(self, word: str) -> bool:
        """从生词本彻底删除（含全部分组关联）。"""
        c = self.conn()
        c.execute("DELETE FROM wordbook_tags WHERE word=?", (word,))
        cur = c.execute("DELETE FROM wordbook WHERE word=?", (word,))
        c.commit()
        return cur.rowcount > 0

    def wordbook_remove_from_group(self, word: str, group_id: int) -> bool:
        """只把生词移出指定分组；生词本体保留（无分组后归入「未分组」）。"""
        cur = self.conn().execute(
            "DELETE FROM wordbook_tags WHERE word=? AND group_id=?",
            (word, group_id))
        self.conn().commit()
        return cur.rowcount > 0

    def wordbook_remove_words_from_group(self, words: Sequence[str],
                                         group_id: int) -> int:
        c = self.conn()
        removed = 0
        for raw in words:
            word = (raw or "").strip()
            if not word:
                continue
            cur = c.execute(
                "DELETE FROM wordbook_tags WHERE word=? AND group_id=?",
                (word, group_id))
            removed += cur.rowcount
        c.commit()
        return removed

    def wordbook_clear(self, group_id: int = ALL_GROUPS):
        """清空：默认清空整个生词本；指定分组时只清空该分组。"""
        c = self.conn()
        if group_id == ALL_GROUPS:
            c.execute("DELETE FROM wordbook_tags")
            c.execute("DELETE FROM wordbook")
        elif group_id == UNGROUPED:
            c.execute("DELETE FROM wordbook WHERE NOT EXISTS("
                      "SELECT 1 FROM wordbook_tags t WHERE t.word=wordbook.word)")
        else:
            c.execute("DELETE FROM wordbook_tags WHERE group_id=?", (group_id,))
        c.commit()

    def wordbook_has(self, word: str, group_id: int = None) -> bool:
        """group_id 为空时判断是否在生词本中，否则判断是否在该分组中。"""
        c = self.conn()
        if group_id is None:
            row = c.execute(
                "SELECT 1 FROM wordbook WHERE word=? COLLATE NOCASE", (word,)
            ).fetchone()
        else:
            row = c.execute(
                "SELECT 1 FROM wordbook_tags WHERE word=? COLLATE NOCASE"
                " AND group_id=?", (word, group_id)
            ).fetchone()
        return row is not None

    def wordbook_groups_of(self, word: str) -> List[str]:
        """返回该生词所属的全部分组名（按分组顺序）。"""
        rows = self.conn().execute(
            "SELECT g.name FROM wordbook_tags t"
            " JOIN wordbook_groups g ON g.id=t.group_id"
            " WHERE t.word=? COLLATE NOCASE"
            " ORDER BY g.sort_order, g.id", (word,)
        ).fetchall()
        return [r[0] for r in rows]

    def wordbook_list(self, group_id: int = ALL_GROUPS) -> List[tuple]:
        """返回 [(word, added_at)]，按加入时间倒序。

        group_id: ALL_GROUPS(-1) 全部 / UNGROUPED(0) 未分组 / 正整数 指定分组。
        """
        # added_at 只精确到秒，同一秒内加入的词用 rowid 兜底，
        # 保证「最新加入排最前」稳定成立（否则同秒词的顺序由存储布局决定）。
        c = self.conn()
        if group_id == ALL_GROUPS:
            rows = c.execute(
                "SELECT word, added_at FROM wordbook"
                " ORDER BY added_at DESC, rowid DESC"
            ).fetchall()
        elif group_id == UNGROUPED:
            rows = c.execute(
                "SELECT word, added_at FROM wordbook w WHERE NOT EXISTS("
                "SELECT 1 FROM wordbook_tags t WHERE t.word=w.word)"
                " ORDER BY w.added_at DESC, w.rowid DESC"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT word, added_at FROM wordbook_tags WHERE group_id=?"
                " ORDER BY added_at DESC, rowid DESC", (group_id,)
            ).fetchall()
        return [(r[0], r[1] or "") for r in rows]

    def wordbook_stats(self) -> dict:
        """一次性取回界面需要的计数：{'all':n, 'ungrouped':n, 'groups':{id:n}}。"""
        c = self.conn()
        total = c.execute("SELECT COUNT(*) FROM wordbook").fetchone()[0] or 0
        ungrouped = c.execute(
            "SELECT COUNT(*) FROM wordbook w WHERE NOT EXISTS("
            "SELECT 1 FROM wordbook_tags t WHERE t.word=w.word)"
        ).fetchone()[0] or 0
        rows = c.execute(
            "SELECT group_id, COUNT(*) FROM wordbook_tags GROUP BY group_id"
        ).fetchall()
        return {"all": total, "ungrouped": ungrouped,
                "groups": {r[0]: r[1] for r in rows}}
