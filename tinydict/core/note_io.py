"""笔记导入导出：JSON / CSV / MDX 三种交换格式的序列化与解析。

只依赖标准库（MDX 用到 mdict-utils 时延迟导入）、不碰 Qt，格式逻辑可以
脱离界面单独测试。与 core.wordbook_io 的分层方式一致。

三种格式的分工：
- json ：``type = "tinydict-notes"``，带 device_id / updated_at / revision /
         deleted 全套同步元数据，用于电脑 ↔ 手机（及电脑 ↔ 电脑）双向同步；
- csv  ：通用表格，正文里带换行也由 csv.writer 正确加引号；
- mdx  ：只读快照，任何 MDX 词典软件（含手机版）都能当词库查，不参与编辑。

另外提供 ``dump_wordbook_json`` / ``dump_wordbook_csv``：在手机版现有的
``tinydict-wordbook`` v1 生词本备份上加**可选** note 字段。按该版本的既定
约定，version 必须保持 1、新增字段一律可选，老版本读到会原样忽略，
所以不会破坏现有互通。手机端合入配套补丁后即可读出笔记。

解析侧刻意宽容：容器名 / 字段名都接受多种别名，缺元数据能回退，
这样手机端以后改字段名或导出简写格式，也不必同步升级电脑版。
"""

import csv
import html
import io
import json
import os
from typing import Dict, List, Sequence, Tuple

from .notes import NoteRecord
from .wordbook_io import (BACKUP_TYPE as WORDBOOK_TYPE,
                          GROUP_SEP, GROUP_TIME_COLUMN,
                          normalize_added_at)

__all__ = [
    "BACKUP_TYPE", "BACKUP_VERSION", "MAX_IMPORT_VERSION",
    "NOTE_COLUMN", "dump_json", "dump_csv", "dump_wordbook_json",
    "dump_wordbook_csv", "dump_mdx", "parse_notes", "is_notes_file",
    "ext_of",
]

#: 笔记备份的类型标记（与生词本备份区分，避免被当成词表逐行导入）
BACKUP_TYPE = "tinydict-notes"
#: 写出的版本；新增字段一律可选，永远保持 1
BACKUP_VERSION = 1
MAX_IMPORT_VERSION = 2

#: CSV 里笔记正文的列名（同时是手机版生词本备份的扩展列）
NOTE_COLUMN = "note"
NOTE_META_COLUMNS = [
    "note_updated_at", "note_device_id", "note_revision", "note_deleted",
]

_WORD_KEYS = {"word", "headword", "key", "词条", "单词"}
_BODY_KEYS = {"note", "content", "body", "text", "html", "笔记", "正文", "内容"}
_UPDATED_KEYS = {"updated_at", "note_updated_at", "modified_at", "updated",
                 "mtime", "time", "更新时间", "修改时间"}
_CREATED_KEYS = {"created_at", "note_created_at", "created", "创建时间"}
_DEVICE_KEYS = {"device_id", "note_device_id", "device", "origin", "设备"}
_REVISION_KEYS = {"revision", "note_revision", "rev", "版本"}
_DELETED_KEYS = {"deleted", "note_deleted", "is_deleted", "已删除"}
_CONTAINER_KEYS = ("notes", "words", "items", "entries", "records", "笔记")


def ext_of(path: str) -> str:
    name = (path or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _txt(value) -> str:
    """把任意 JSON 值安全转成字符串；None / 容器一律当空。"""
    if value is None or isinstance(value, (dict, list, tuple)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _txt(value).strip().lower() in {"1", "true", "yes", "y", "是", "删除"}


def _int_of(value, default: int = 0) -> int:
    try:
        return int(_txt(value).strip() or default)
    except ValueError:
        return default


# ---------------------------------------------------------------------- 导出
def _record(note) -> Dict:
    """Note / NoteRecord / 任意带同名属性的对象 → 导出行。"""
    return {
        "word": _txt(getattr(note, "word", "")),
        "note": _txt(getattr(note, "body", "")),
        "created_at": normalize_added_at(_txt(getattr(note, "created_at", ""))),
        "updated_at": normalize_added_at(_txt(getattr(note, "updated_at", ""))),
        "device_id": _txt(getattr(note, "device_id", "")),
        "revision": _int_of(getattr(note, "revision", 0)),
        "deleted": bool(getattr(note, "deleted", 0)),
    }


def dump_json(notes: Sequence, device_id: str = "",
              exported_at: str = "", platform: str = "desktop") -> str:
    """完整同步备份：含每条笔记的来源设备、修改时间、版本与删除墓碑。

    墓碑也要导出，否则「一端删了笔记」在另一端导入旧备份时会被当成新增而复活。
    """
    payload = {
        "app": "TinyDict",
        "type": BACKUP_TYPE,
        "version": BACKUP_VERSION,
        "exported_at": exported_at,
        "device_id": device_id,
        "platform": platform,
        "notes": [_record(n) for n in notes],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def dump_csv(notes: Sequence) -> str:
    """通用表格：``word,note,created_at,updated_at,device_id,revision,deleted``。"""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["word", NOTE_COLUMN, "created_at", "updated_at",
                     "device_id", "revision", "deleted"])
    for rec in (_record(n) for n in notes):
        writer.writerow([rec["word"], rec["note"], rec["created_at"],
                         rec["updated_at"], rec["device_id"],
                         rec["revision"], "1" if rec["deleted"] else "0"])
    return buf.getvalue()


def _wordbook_row(rec: Dict, groups: Sequence[str], added_at: str):
    """手机版 ``tinydict-wordbook`` v1 的一行，笔记字段全部是可选扩展。"""
    row = {
        "word": rec["word"],
        "groups": list(groups),
        "added_at": added_at,
        "group_added_at": [added_at for _ in groups],
        NOTE_COLUMN: rec["note"],
        "note_updated_at": rec["updated_at"],
        "note_device_id": rec["device_id"],
        "note_revision": rec["revision"],
        "note_deleted": rec["deleted"],
    }
    return row


def dump_wordbook_json(notes: Sequence, exported_at: str = "",
                       groups_by_word: Dict[str, List[str]] = None,
                       default_group: str = "默认分组",
                       added_at: str = "") -> str:
    """导出成手机版现有生词本备份（type/version/列顺序都保持 v1 不变）。

    笔记相关字段是**附加**的：手机端未合入补丁时 ``parseBackup`` 只读它认识的
    四个字段，其余原样忽略，文件仍可正常导入生词本，只是笔记暂不生效。
    """
    groups_by_word = groups_by_word or {}
    stamp = normalize_added_at(added_at)
    words = []
    for rec in (_record(n) for n in notes):
        key = rec["word"].strip().casefold()
        gs = groups_by_word.get(key) or [default_group]
        words.append(_wordbook_row(rec, gs, stamp))
    payload = {
        "app": "TinyDict",
        "type": WORDBOOK_TYPE,
        "version": 1,               # 绝不升版本：Android 老构建遇到 >2 会拒绝
        "exported_at": exported_at,
        "groups": sorted({g for w in words for g in w["groups"]}),
        "words": words,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def dump_wordbook_csv(notes: Sequence,
                      groups_by_word: Dict[str, List[str]] = None,
                      default_group: str = "默认分组",
                      added_at: str = "") -> str:
    """同上，CSV 版：前三列与手机版一致，后面追加笔记列。"""
    groups_by_word = groups_by_word or {}
    stamp = normalize_added_at(added_at)
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["word", "groups", "added_at", GROUP_TIME_COLUMN,
                     NOTE_COLUMN] + NOTE_META_COLUMNS)
    for rec in (_record(n) for n in notes):
        key = rec["word"].strip().casefold()
        gs = groups_by_word.get(key) or [default_group]
        writer.writerow([
            rec["word"], GROUP_SEP.join(gs), stamp,
            GROUP_SEP.join([stamp for _ in gs]), rec["note"],
            rec["updated_at"], rec["device_id"], rec["revision"],
            "1" if rec["deleted"] else "0",
        ])
    return buf.getvalue()


def dump_mdx(notes: Sequence, path: str, title: str = "TinyDict 笔记") -> str:
    """把笔记写成只读 MDX 词库快照，返回实际写出的路径。

    MDictWriter 是一次性写 header + key 索引 + record 块，没有增量 update
    接口，所以它只适合做导出快照、绝不能当主存储（详见 core.notes 模块说明）。
    key 必须按字典序给出，故这里先排序。
    """
    from mdict_utils.writer import MDictWriter, pack_mdx_txt

    items = [n for n in notes
             if not getattr(n, "deleted", 0) and _txt(getattr(n, "body", ""))]
    if not items:
        raise ValueError("没有可导出的笔记。")
    items = sorted(items, key=lambda n: _txt(getattr(n, "word", "")).casefold())

    lines: List[str] = []
    for note in items:
        word = _txt(getattr(note, "word", "")).strip()
        body = _txt(getattr(note, "body", ""))
        # 正文按纯文本渲染：转义 HTML，换行转 <br>，保留用户原来的排版
        rendered = html.escape(body).replace("\r\n", "\n").replace("\r", "\n")
        lines.append(word)
        lines.append("<div class=\"td-note\">" + rendered.replace("\n", "<br>")
                     + "</div>")
        lines.append("</>")

    tmp = path + ".src.txt"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        data = pack_mdx_txt(tmp, encoding="UTF-8")
        writer = MDictWriter(data, title=title,
                             description="TinyDict notes export (read-only snapshot)",
                             encoding="UTF-8")
        with open(path, "wb") as out:
            writer.write(out)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return path


# ---------------------------------------------------------------------- 导入
def _pick(item: Dict, names: set) -> str:
    """按别名集合取字段；JSON 的 key 大小写不敏感。"""
    for key, value in item.items():
        if str(key).strip().lower() in names:
            return _txt(value)
    return ""


def _from_item(item) -> NoteRecord:
    if isinstance(item, str):
        return NoteRecord(word=item.strip())
    if not isinstance(item, dict):
        return NoteRecord(word="")
    deleted = _truthy(_pick(item, _DELETED_KEYS))
    body = _pick(item, _BODY_KEYS)
    return NoteRecord(
        word=_pick(item, _WORD_KEYS).strip(),
        body=body,
        created_at=normalize_added_at(_pick(item, _CREATED_KEYS)),
        updated_at=normalize_added_at(_pick(item, _UPDATED_KEYS)),
        device_id=_pick(item, _DEVICE_KEYS),
        revision=_int_of(_pick(item, _REVISION_KEYS)),
        deleted=int(deleted),
    )


def _parse_json(text: str) -> Tuple[List[NoteRecord], str, str]:
    try:
        data = json.loads((text or "").lstrip("\ufeff"))
    except json.JSONDecodeError as e:
        raise ValueError(f"不是合法的 JSON 文件：{e}") from e

    if isinstance(data, list):
        raw_items, kind = data, BACKUP_TYPE
        device_id = exported_at = ""
    elif isinstance(data, dict):
        kind = _txt(data.get("type")) or BACKUP_TYPE
        device_id = _txt(data.get("device_id"))
        exported_at = normalize_added_at(_txt(data.get("exported_at")))
        version = data.get("version", BACKUP_VERSION)
        if isinstance(version, bool) or not isinstance(version, (int, float)):
            raise ValueError("备份文件里的 version 不是数字。")
        if version > MAX_IMPORT_VERSION:
            raise ValueError(
                f"备份文件版本为 {version}，高于当前软件支持的 "
                f"{MAX_IMPORT_VERSION}，请升级软件后再导入。")
        raw_items = next((data[k] for k in _CONTAINER_KEYS
                          if isinstance(data.get(k), list)), None)
        if raw_items is None:
            raise ValueError("备份文件里找不到笔记列表（notes / words）。")
        if kind not in {BACKUP_TYPE, WORDBOOK_TYPE, "notes", "note", ""}:
            raise ValueError(f"不认识的备份类型：{kind}")
    else:
        raise ValueError("JSON 根节点必须是对象或数组。")

    records: List[NoteRecord] = []
    for item in raw_items:
        rec = _from_item(item)
        if not rec.word:
            continue
        # 生词本备份里绝大多数词没有笔记：body 为空且不是明确的删除墓碑时
        # 直接跳过，否则导入一次备份会凭空造出成百上千条空笔记。
        if not rec.body and not rec.deleted:
            continue
        # 手机端可能只给一个统一时间戳；用它兜底每条笔记的修改时间
        if not rec.updated_at and exported_at:
            rec.updated_at = exported_at
        if not rec.device_id and device_id:
            rec.device_id = device_id
        records.append(rec)
    return records, device_id, exported_at


def _parse_csv(text: str) -> Tuple[List[NoteRecord], str, str]:
    body = (text or "").lstrip("\ufeff")
    rows = list(csv.reader(io.StringIO(body, newline="")))
    if not rows:
        return [], "", ""
    header = [c.strip().lower() for c in rows[0]]

    def col(names: set) -> int:
        for i, cell in enumerate(header):
            if cell in names:
                return i
        return -1

    word_col = col(_WORD_KEYS)
    note_col = col(_BODY_KEYS)
    if word_col < 0 or note_col < 0:
        raise ValueError("CSV 缺少 word 或 note 列，无法识别为笔记文件。")
    cols = {
        "created_at": col(_CREATED_KEYS),
        "updated_at": col(_UPDATED_KEYS),
        "device_id": col(_DEVICE_KEYS),
        "revision": col(_REVISION_KEYS),
        "deleted": col(_DELETED_KEYS),
    }

    def cell(row, idx) -> str:
        return row[idx].strip() if 0 <= idx < len(row) else ""

    records: List[NoteRecord] = []
    for row in rows[1:]:
        word = cell(row, word_col)
        if not word or word.lower() in {"word", "单词", "词条"}:
            continue
        deleted = _truthy(cell(row, cols["deleted"]))
        text_value = cell(row, note_col)
        if not text_value and not deleted:
            continue
        records.append(NoteRecord(
            word=word, body=text_value,
            created_at=normalize_added_at(cell(row, cols["created_at"])),
            updated_at=normalize_added_at(cell(row, cols["updated_at"])),
            device_id=cell(row, cols["device_id"]),
            revision=_int_of(cell(row, cols["revision"])),
            deleted=int(deleted),
        ))
    return records, "", ""


def parse_notes(text: str, path: str = "") -> Tuple[List[NoteRecord], str, str]:
    """解析笔记文件，返回 ``(记录列表, 来源设备, 导出时间)``。

    兼容三类输入：完整 ``tinydict-notes`` 备份、手机版 ``tinydict-wordbook``
    备份（取其中的可选 note 字段）、以及带 ``word``/``note`` 表头的 CSV。
    格式不符抛 ValueError，由界面层转成提示。
    """
    stripped = (text or "").lstrip("\ufeff \t\r\n")
    if not stripped:
        raise ValueError("文件是空的。")
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json(text)
    if ext_of(path) == "json":
        return _parse_json(text)
    if ext_of(path) == "csv" or ("," in stripped.splitlines()[0]
                                 and "note" in stripped.splitlines()[0].lower()):
        return _parse_csv(text)
    raise ValueError("无法识别的笔记文件：需要 JSON 备份或带 word/note 表头的 CSV。")


def is_notes_file(text: str, path: str = "") -> bool:
    """分流用：判断一份文件是不是笔记备份（而不是生词本词表）。"""
    body = (text or "").lstrip("\ufeff \t\r\n")
    if not body.startswith("{"):
        return False
    return BACKUP_TYPE in body[:400] or (
        WORDBOOK_TYPE in body[:400] and NOTE_COLUMN in body[:2000])
