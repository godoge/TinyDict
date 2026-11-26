"""词条笔记：SQLite 主存 + 跨设备三路合并。

设计取舍（为什么不把笔记写成 MDX 词库）：
- SQLite 有 WAL + 事务，单条编辑是原子的；MDictWriter 没有增量 update，
  每次保存都要整本重写，中断即损坏全部笔记。
- 笔记挂在「当前词条」上，词库没收录的词也要能写（见候选列表的占位词条），
  混进词库文件会被换词库 / 重装覆盖掉。
- 迁移便利性由**导出格式**决定，不由内部存储决定：本模块负责存储与合并，
  core.note_io 负责 JSON / CSV / MDX 三种交换格式。

跨设备冲突：
每条笔记带 updated_at / device_id / revision / deleted（墓碑）。另外用
note_sync 记「上次两端一致的内容」作为基线，导入时做三路合并：

    base = 上次同步时双方一致的内容
    local / remote = 本次本机 / 导入文件的内容

    local == remote            -> 什么都没变
    local == base              -> 只有远端改了，采用远端
    remote == base             -> 只有本机改了，保留本机
    其它                       -> 两端都改了，判为冲突

真冲突时**保留本地**，把远端内容完整写进 note_conflicts 供人工合并，
并且刻意不推进基线——否则同一个文件再导入一次会被误判成「只有远端改了」，
把用户刚决定保留的内容悄悄覆盖掉。

基线是单份快照，适用于「一台电脑 ↔ 一台手机」这类两方同步；多设备互导
会退化成以最后一次同步为准，这是刻意简化，换来的是行为可预测。
"""

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence

__all__ = [
    "Note", "NoteRecord", "MergeReport", "Conflict", "Notes",
    "normalize_key", "now_iso",
    "STRATEGY_MERGE", "STRATEGY_KEEP_LOCAL", "STRATEGY_OVERWRITE",
]

STRATEGY_MERGE = "merge"            # 三路合并（默认）
STRATEGY_KEEP_LOCAL = "keep_local"  # 只补本地没有的
STRATEGY_OVERWRITE = "overwrite"    # 以导入文件为准


def now_iso() -> str:
    """本地时间 ISO 8601 秒级，与 wordbook_io / Android formatAddedAt 一致。

    刻意不带时区：两端现存的生词本备份都是这个写法，混用时不会出现
    「Android 的 SimpleDateFormat 读不懂」的问题。合并判胜负靠内容基线，
    不靠时间戳比大小，所以手机/电脑差几秒不会影响正确性。
    """
    return datetime.now().isoformat(timespec="seconds")


def normalize_key(word: str) -> str:
    """规范化词键：NFKC（全角→半角）+ casefold + 折叠内部空白。

    生词本的 word 主键是 BINARY，而 has()/groups_of() 用 NOCASE，已经造成
    Apple/apple 分裂的已知缺陷。笔记表从一开始就用规范化键，避免重蹈覆辙；
    显示词形仍单独存在 word 列里，用户看到的还是自己输入的写法。
    """
    return " ".join(
        unicodedata.normalize("NFKC", word or "").casefold().split())


@dataclass
class Note:
    """笔记表中的一行。"""
    word_key: str
    word: str
    body: str
    created_at: str
    updated_at: str
    device_id: str
    revision: int = 1
    deleted: int = 0

    @property
    def is_deleted(self) -> bool:
        return bool(self.deleted)

    @property
    def visible_body(self) -> str:
        return "" if self.deleted else self.body

    def state(self):
        """三路合并比较用的状态：内容与删除标记。"""
        return (self.body, int(bool(self.deleted)))


@dataclass
class NoteRecord:
    """从交换文件解析出的一条笔记（元数据可能缺失，故与 Note 分开）。"""
    word: str
    body: str = ""
    created_at: str = ""
    updated_at: str = ""
    device_id: str = ""
    revision: int = 0
    deleted: int = 0

    def state(self):
        return (self.body, int(bool(self.deleted)))


@dataclass
class MergeReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    conflicts: List[str] = field(default_factory=list)
    actions: Dict[str, str] = field(default_factory=dict)
    peer_id: str = ""

    @property
    def total(self) -> int:
        return self.added + self.updated + self.unchanged + self.deleted + len(self.conflicts)

    def summary(self) -> str:
        return (f"新增 {self.added}、更新 {self.updated}、删除 {self.deleted}、"
                f"未变 {self.unchanged}、冲突 {len(self.conflicts)}")


@dataclass
class Conflict:
    id: int
    word_key: str
    word: str
    local_body: str
    remote_body: str
    local_updated_at: str
    remote_updated_at: str
    peer_id: str
    created_at: str
    resolved: int = 0


class Notes:
    """笔记读写门面。持有 Database，SQL 集中在本文件，便于脱离 UI 单测。"""

    def __init__(self, db, device_id: str = ""):
        self._db = db
        self.device_id = device_id or "unknown"

    # ---------------------------------------------------------------- 基础读写
    def _c(self):
        return self._db.conn()

    @staticmethod
    def _row(row) -> Note:
        return Note(
            word_key=row[0], word=row[1], body=row[2] or "",
            created_at=row[3] or "", updated_at=row[4] or "",
            device_id=row[5] or "", revision=row[6] or 1,
            deleted=row[7] or 0)

    def get(self, word: str) -> Optional[Note]:
        key = normalize_key(word)
        if not key:
            return None
        row = self._c().execute(
            "SELECT word_key,word,body,created_at,updated_at,device_id,"
            "revision,deleted FROM notes WHERE word_key=?", (key,)).fetchone()
        return self._row(row) if row else None

    def body(self, word: str) -> str:
        note = self.get(word)
        return note.visible_body if note else ""

    def set(self, word: str, body: str, device_id: str = "") -> Optional[Note]:
        """写入 / 更新一条笔记；body 为空视为删除（写墓碑）。

        内容与删除状态都没变时不写库，避免防抖保存把 revision 无谓地 +
        1（那样会让对端误以为本机改过，制造假冲突）。
        """
        key = normalize_key(word)
        if not key:
            return None
        text = body or ""
        dev = device_id or self.device_id
        stamp = now_iso()
        c = self._c()
        old = self.get(word)
        if text == "":
            return self.delete(word, device_id=dev)

        if old is not None and old.body == text and not old.deleted:
            return old
        created = old.created_at if old and old.created_at else stamp
        revision = (old.revision + 1) if old else 1
        c.execute(
            "INSERT INTO notes(word_key,word,body,created_at,updated_at,"
            "device_id,revision,deleted) VALUES(?,?,?,?,?,?,?,0) "
            "ON CONFLICT(word_key) DO UPDATE SET "
            " word=excluded.word, body=excluded.body,"
            " updated_at=excluded.updated_at, device_id=excluded.device_id,"
            " revision=excluded.revision, deleted=0",
            (key, (word or "").strip(), text, created, stamp, dev, revision))
        c.commit()
        return self.get(word)

    def delete(self, word: str, device_id: str = "") -> Optional[Note]:
        """软删除：只置墓碑、保留元数据，让「删除」也能同步给另一端。"""
        key = normalize_key(word)
        if not key:
            return None
        old = self.get(word)
        if old is None or old.deleted:
            return old
        c = self._c()
        c.execute(
            "UPDATE notes SET body='', deleted=1, updated_at=?, device_id=?,"
            " revision=revision+1 WHERE word_key=?",
            (now_iso(), device_id or self.device_id, key))
        c.commit()
        return self.get(word)

    def all(self, include_deleted: bool = True) -> List[Note]:
        sql = ("SELECT word_key,word,body,created_at,updated_at,device_id,"
               "revision,deleted FROM notes")
        if not include_deleted:
            sql += " WHERE deleted=0"
        sql += " ORDER BY updated_at DESC, word_key"
        return [self._row(r) for r in self._c().execute(sql).fetchall()]

    def search(self, keyword: str, limit: int = 200) -> List[Note]:
        """按词或笔记正文搜（字面片段，通配符转义）。"""
        kw = (keyword or "").strip()
        if not kw:
            return [n for n in self.all(include_deleted=False) if n.body][:limit]
        escaped = (kw.replace("\\", "\\\\").replace("%", "\\%")
                     .replace("_", "\\_"))
        rows = self._c().execute(
            "SELECT word_key,word,body,created_at,updated_at,device_id,"
            "revision,deleted FROM notes WHERE deleted=0 AND "
            "(word LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')"
            " ORDER BY updated_at DESC LIMIT ?",
            (f"%{escaped}%", f"%{escaped}%", limit)).fetchall()
        return [self._row(r) for r in rows]

    def stats(self) -> dict:
        c = self._c()
        active = c.execute(
            "SELECT COUNT(*) FROM notes WHERE deleted=0 AND body<>''").fetchone()[0]
        tombstones = c.execute(
            "SELECT COUNT(*) FROM notes WHERE deleted=1").fetchone()[0]
        conflicts = c.execute(
            "SELECT COUNT(*) FROM note_conflicts WHERE resolved=0").fetchone()[0]
        return {"notes": active, "tombstones": tombstones,
                "conflicts": conflicts}

    # ---------------------------------------------------------------- 同步基线
    def _baseline(self, key: str):
        row = self._c().execute(
            "SELECT base_body,base_deleted FROM note_sync WHERE word_key=?",
            (key,)).fetchone()
        return (row[0] or "", row[1] or 0) if row else ("", 0)

    def _set_baseline(self, key: str, state, peer_id: str = ""):
        self._c().execute(
            "INSERT INTO note_sync(word_key,base_body,base_deleted,peer_id,synced_at)"
            " VALUES(?,?,?,?,?) ON CONFLICT(word_key) DO UPDATE SET "
            " base_body=excluded.base_body, base_deleted=excluded.base_deleted,"
            " peer_id=excluded.peer_id, synced_at=excluded.synced_at",
            (key, state[0], int(state[1]), peer_id, now_iso()))

    def mark_synced(self, peer_id: str = "") -> int:
        """导出成功 / 一次干净合并后，把当前全库状态刷成新的同步基线。

        必须在**写文件成功之后**调用：失败了却推进基线，会让对端的修改
        下次被误判成「只有本机改过」而永远合并不进来。
        """
        c = self._c()
        rows = self.all(include_deleted=True)
        for note in rows:
            self._set_baseline(note.word_key, note.state(), peer_id)
        c.commit()
        return len(rows)

    # ---------------------------------------------------------------- 冲突留痕
    def conflicts(self, unresolved_only: bool = True) -> List[Conflict]:
        sql = ("SELECT id,word_key,word,local_body,remote_body,"
               "local_updated_at,remote_updated_at,peer_id,created_at,resolved "
               "FROM note_conflicts")
        if unresolved_only:
            sql += " WHERE resolved=0"
        sql += " ORDER BY created_at DESC, id DESC"
        return [Conflict(*r) for r in self._c().execute(sql).fetchall()]

    def _add_conflict(self, key: str, remote: NoteRecord,
                      word: str, local: Optional[Note], peer_id: str):
        remote_body = remote.body if not remote.deleted else ""
        local_body = local.body if local else ""
        c = self._c()
        # 同一份文件被反复导入是常见操作（用户忘了导过、或换设备时重试）。
        # 不推进基线是为了防止误覆盖，但会重复走到这里，所以按「同词 + 同远端
        # 内容 + 未解决」去重，否则冲突列表会被刷出一堆一模一样的条目。
        exists = c.execute(
            "SELECT 1 FROM note_conflicts WHERE word_key=? AND resolved=0"
            " AND remote_body=? AND local_body=? LIMIT 1",
            (key, remote_body, local_body)).fetchone()
        if exists:
            return
        c.execute(
            "INSERT INTO note_conflicts(word_key,word,local_body,remote_body,"
            "local_updated_at,remote_updated_at,peer_id,created_at,resolved)"
            " VALUES(?,?,?,?,?,?,?,?,0)",
            (key, word, local_body, remote_body,
             local.updated_at if local else "", remote.updated_at or "",
             peer_id, now_iso()))

    def resolve_conflict(self, conflict_id: int, choice: str,
                         merged_body: str = "") -> bool:
        """处理一条冲突。

        choice: keep_local / take_remote / merged。
        处理完必须推进基线，否则同一份文件再导入一次还会报冲突。
        """
        c = self._c()
        row = c.execute(
            "SELECT word_key,word,local_body,remote_body FROM note_conflicts"
            " WHERE id=? AND resolved=0", (conflict_id,)).fetchone()
        if row is None:
            return False
        key, word, local_body, remote_body = row
        if choice == "take_remote":
            final = remote_body
        elif choice == "merged":
            final = merged_body
        else:
            final = local_body
        note = self.set(word, final) if final else self.delete(word)
        state = note.state() if note else ("", 0)
        self._set_baseline(key, state, "resolved")
        c.execute("UPDATE note_conflicts SET resolved=1 WHERE id=?",
                  (conflict_id,))
        c.commit()
        return True

    # ---------------------------------------------------------------- 三路合并
    @staticmethod
    def _dedup(records: Iterable[NoteRecord]) -> Dict[str, NoteRecord]:
        """同一个文件里出现重复词时，保留 updated_at / revision 较新的一条。"""
        out: Dict[str, NoteRecord] = {}
        for rec in records:
            key = normalize_key(rec.word)
            if not key:
                continue
            old = out.get(key)
            if old is None or (rec.updated_at, rec.revision) >= (
                    old.updated_at, old.revision):
                out[key] = rec
        return out

    def _write_remote(self, key: str, rec: NoteRecord, old: Optional[Note]):
        """把导入的一条写成本地状态，保留对端的时间 / 设备 / 版本。

        绝不能改成本机当前时间：那样导回去时，对端会以为「本机刚改过」，
        制造一次本不存在的冲突。
        """
        c = self._c()
        stamp = rec.updated_at or now_iso()
        created = rec.created_at or (old.created_at if old else "") or stamp
        revision = rec.revision or ((old.revision + 1) if old else 1)
        dev = rec.device_id or "imported"
        c.execute(
            "INSERT INTO notes(word_key,word,body,created_at,updated_at,"
            "device_id,revision,deleted) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(word_key) DO UPDATE SET "
            " word=excluded.word, body=excluded.body,"
            " created_at=excluded.created_at, updated_at=excluded.updated_at,"
            " device_id=excluded.device_id, revision=excluded.revision,"
            " deleted=excluded.deleted",
            (key, (rec.word or "").strip(), rec.body, created, stamp,
             dev, revision, int(bool(rec.deleted))))

    def merge(self, records: Sequence[NoteRecord], peer_id: str = "",
              strategy: str = STRATEGY_MERGE) -> MergeReport:
        """把一份导入文件合并进本地笔记库。

        strategy:
          merge      —— 三路合并，真冲突保留本地并留痕（默认，不丢数据）
          keep_local —— 只补本地完全没有的词，已有笔记一律不动
          overwrite  —— 以文件为准覆盖同名笔记（用户显式要求时才用）
        """
        report = MergeReport(peer_id=peer_id)
        c = self._c()
        local = {n.word_key: n for n in self.all(include_deleted=True)}
        incoming = self._dedup(records)

        for key, rec in incoming.items():
            old = local.get(key)
            cur = old.state() if old else ("", 0)
            remote = rec.state()
            base = self._baseline(key)
            shown_word = old.word if old else (rec.word or "").strip()

            if remote == cur:
                report.unchanged += 1
                report.actions[key] = "unchanged"
                self._set_baseline(key, cur, peer_id)
                continue

            if strategy == STRATEGY_KEEP_LOCAL and old is not None:
                # 已有记录（含墓碑）一律不动，避免「仅补充」把删掉的笔记复活
                report.unchanged += 1
                report.actions[key] = "kept_local"
                continue

            if strategy == STRATEGY_OVERWRITE:
                action = "take_remote"
            elif cur == base:
                action = "take_remote"      # 只有对端改了
            elif remote == base:
                action = "keep_local"       # 只有本机改了
            else:
                action = "conflict"         # 两端都改了

            # 本机已是删除墓碑、文件里却还有内容：无法区分这是「删除之后
            # 重新写的笔记」还是「一份更早的旧备份」。三路合并只看内容，
            # 而删除同步已把基线推进成空，旧备份看起来恰好像一次新修改，
            # 会把删掉的笔记悄悄复活。这里一律留冲突，由用户明确决定是否
            # 恢复（冲突窗口里点「采用导入」即可），不依赖两端时钟对齐。
            # 用户显式选了「以导入文件为准」时尊重其选择，不拦截。
            if (strategy != STRATEGY_OVERWRITE and action == "take_remote"
                    and old is not None and old.deleted and not rec.deleted):
                action = "conflict"

            if action == "keep_local":
                report.unchanged += 1
                report.actions[key] = "kept_local"
                continue

            if action == "conflict":
                self._add_conflict(key, rec, shown_word, old, peer_id)
                report.conflicts.append(shown_word)
                report.actions[key] = "conflict"
                # 刻意不推进基线：见模块说明
                continue

            self._write_remote(key, rec, old)
            self._set_baseline(key, remote, peer_id)
            if rec.deleted:
                report.deleted += 1
                report.actions[key] = "deleted"
            elif old is None:
                report.added += 1
                report.actions[key] = "added"
            else:
                report.updated += 1
                report.actions[key] = "updated"

        c.commit()
        return report
