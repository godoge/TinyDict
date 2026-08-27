"""SQLite 存储层（挂载式架构）。

数据库只保存轻量数据：
- dicts   : 词库注册信息（路径 / 名称 / 启用状态 / 优先级 / 挂载后的统计数）
- wordbook: 生词本

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

    # ------------------------------------------------------------------ 生词本
    def wordbook_add(self, word: str) -> bool:
        try:
            self.conn().execute(
                "INSERT INTO wordbook(word, added_at) VALUES(?,?)",
                (word, datetime.now().isoformat(timespec="seconds")),
            )
            self.conn().commit()
            return True
        except sqlite3.IntegrityError:
            return False  # 已存在

    def wordbook_remove(self, word: str) -> bool:
        cur = self.conn().execute("DELETE FROM wordbook WHERE word=?", (word,))
        self.conn().commit()
        return cur.rowcount > 0

    def wordbook_clear(self):
        self.conn().execute("DELETE FROM wordbook")
        self.conn().commit()

    def wordbook_has(self, word: str) -> bool:
        row = self.conn().execute(
            "SELECT 1 FROM wordbook WHERE word=? COLLATE NOCASE", (word,)
        ).fetchone()
        return row is not None

    def wordbook_list(self) -> List[tuple]:
        rows = self.conn().execute(
            "SELECT word, added_at FROM wordbook ORDER BY added_at DESC"
        ).fetchall()
        return [(r[0], r[1] or "") for r in rows]
