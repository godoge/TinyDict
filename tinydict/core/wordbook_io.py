"""生词本导入导出：txt / csv / json 三种格式的序列化与解析。

只依赖标准库、不碰 Qt，这样格式逻辑可以脱离界面单独测试；
界面层（ui/wordbook_dialog.py）只负责选文件、读写磁盘和结果提示。

三种格式各有分工：
- txt ：每行一个词，最通用，方便和别的工具交换；
- csv ：带「所属分组 / 加入时间 / 各分组各自的加入时间」；
- json：完整备份（分组清单 + 每个词的分组归属），用于备份后原样恢复。

**与 Android 版 TinyDict 互通**：字段、列顺序、表头、分组分隔符、时间格式、
JSON 结构都和 ``WordbookBackup.kt`` 完全一致，导出的文件可以双向直接导入。
「每个分组各自的收藏时间」是可选扩展字段（CSV 第四列 ``group_added_at``、
JSON 每个词的 ``group_added_at`` 数组）：版本号保持 1，因为 Android 早期
构建写出过 2，而更老的版本遇到 ``version > 1`` 会拒绝；旧的三列 CSV /
只带 ``added_at`` 的 JSON 照样能导入，缺字段时回退到词级时间。
"""

import csv
import io
import json
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

__all__ = [
    "BACKUP_TYPE", "BACKUP_VERSION", "MAX_IMPORT_VERSION", "GROUP_SEP",
    "GROUP_TIME_COLUMN", "ExportRow",
    "dump_txt", "dump_csv", "dump_json",
    "parse_words", "parse_rows", "parse_backup", "is_backup",
    "align_group_times", "normalize_added_at", "ext_of",
]

#: JSON 备份里的类型标记，用来判断「这是不是生词本备份」
BACKUP_TYPE = "tinydict-wordbook"
#: 写出的备份版本；与 Android 一致，**必须保持 1**（见模块说明）
BACKUP_VERSION = 1
#: 导入可识别的最高版本：2 是 Android 早期构建曾写出的扩展版，仍要能读回来
MAX_IMPORT_VERSION = 2

#: CSV 里把「一个词所属的多个分组」拼进同一个单元格的分隔符
GROUP_SEP = "; "
#: CSV 里记录每个分组各自收藏时间的列名
GROUP_TIME_COLUMN = "group_added_at"

# 导出用的一行：(word, added_at, [所属分组名…], [各分组各自的时间…])
# 后两个列表一一对应；三元组（旧调用）也接受，视为「没有每分组时间」。
ExportRow = Tuple[str, str, List[str], List[str]]

# CSV 首列 / 表头的常见写法，导入时跳过
_HEADERS = {"word", "words", "单词", "生词", "vocabulary", "vocab"}
# CSV 表头里「所属分组」这一列的常见写法（与 Android 一致）
_GROUP_HEADERS = {
    "groups", "group", "wordbooks", "wordbook", "books", "book",
    "生词本", "单词本", "分组", "分组名",
}
# CSV 表头里「收藏时间」这一列的常见写法
_TIME_HEADERS = {
    "added_at", "addedat", "added", "time", "date", "timestamp",
    "时间", "收藏时间", "加入时间", "添加时间",
}
# CSV 表头里「按分组分别记录的时间」这一列的常见写法
_GROUP_TIME_HEADERS = {
    "group_added_at", "groupaddedat", "book_added_at", "分组时间",
}


# ---------------------------------------------------------------------- 导出
def _row_of(row) -> ExportRow:
    """把一行导出数据规整成四元组；兼容旧的三元组调用。

    时间统一走 [normalize_added_at]：老数据里可能有 SQLite ``CURRENT_TIMESTAMP``
    的 ``yyyy-MM-dd HH:mm:ss`` 写法，写进导出文件前转成两端都认的 ISO ``T`` 格式。
    """
    word = str(row[0] or "")
    added_at = normalize_added_at(str(row[1] or ""))
    groups = list(row[2] or [])
    times = [normalize_added_at(str(t or ""))
             for t in (row[3] if len(row) > 3 and row[3] else [])]
    return word, added_at, groups, times


def dump_txt(rows: Sequence) -> str:
    """每行一个生词（不含分组与时间）。"""
    return "".join(f"{_row_of(row)[0]}\n" for row in rows)


def dump_csv(rows: Sequence) -> str:
    """带表头的四列 CSV：``word,groups,added_at,group_added_at``。

    ``groups`` 与 ``group_added_at`` 都用 [GROUP_SEP] 拼接且位置一一对应，
    所以一个词属于三个分组、三个分组收藏时间各不同时也不会错位。
    用 ``csv.writer``（CRLF、QUOTE_MINIMAL）而非手工拼串，和 Android 的
    ``dumpCsv`` 产出的文本逐字节一致。
    """
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["word", "groups", "added_at", GROUP_TIME_COLUMN])
    for row in rows:
        word, added_at, groups, times = _row_of(row)
        writer.writerow([word, GROUP_SEP.join(groups), added_at,
                         GROUP_SEP.join(times)])
    return buf.getvalue()


def dump_json(rows: Sequence, groups: Sequence[str],
              exported_at: str = "") -> str:
    """完整备份：分组清单 + 每个词的分组归属与各自的时间。

    字段顺序与 Android ``dumpJson`` 一致，便于两边导出文件做逐字节比对；
    ``group_added_at`` 是可选扩展字段，老软件读不懂时直接忽略。
    """
    words: List[Dict] = []
    for row in rows:
        word, added_at, gs, times = _row_of(row)
        words.append({"word": word, "groups": list(gs),
                      "added_at": added_at,
                      "group_added_at": list(times)})
    payload = {
        "app": "TinyDict",
        "type": BACKUP_TYPE,
        "version": BACKUP_VERSION,
        "exported_at": exported_at,
        "groups": list(groups),
        "words": words,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------- 导入
def _column_of(header: Sequence[str], names: set) -> int:
    """按列名找列号；列顺序被打乱、或用了中文表头也能读。"""
    for i, cell in enumerate(header):
        if cell.strip().lower() in names:
            return i
    return -1


def _split_groups(cell: str) -> List[str]:
    """分组单元格：按 ``;`` 切、去空、去重（兼容只写 ``;`` 不带空格的旧文件）。"""
    out: List[str] = []
    for part in (cell or "").split(";"):
        name = part.strip()
        if name and name not in out:
            out.append(name)
    return out


def _split_times(cell: str) -> List[str]:
    """时间单元格：**保留空串占位、不能去重**，否则与 groups 的一一对应会错位。"""
    if not (cell or "").strip():
        return []
    return [part.strip() for part in cell.split(";")]


def parse_rows(text: str) -> List[Dict]:
    """从 txt / csv 解析带归属的生词行。

    返回 ``[{'word','groups','added_at','group_added_at'}, …]``，字段与
    Android ``parseRows`` 的 ``ImportRow`` 一一对应。

    只有认出带表头的 CSV（至少两列、含 word 列、且还有其它信息列）才解析
    第二列以后：无表头的纯文本里 ``word; pierre`` 这种带分号的词条必须整行
    保留，不能凭空切出归属；同理第一行恰好是单词 ``word`` 也不能误当表头。
    旧的三列 / 两列 CSV 照样能读，缺哪一列就退化成「没有归属 / 没有每分组时间」。

    用 ``csv.reader`` 读整个文本而不是先 ``splitlines()``：词头里带换行时
    导出端会给它加引号，硬按换行切会把一行拆成两行、后面所有列错位。
    """
    body = (text or "").lstrip("\ufeff")
    try:
        lines = list(csv.reader(io.StringIO(body, newline="")))
    except csv.Error:                     # 极端畸形文件：退回按行读
        lines = [[line] for line in body.splitlines()]

    def _clean(row: List[str]) -> str:
        return (row[0] if row else "").strip()

    # 第一个非空、非注释行是表头候选
    first = next((i for i, row in enumerate(lines)
                  if _clean(row) and not _clean(row).startswith("#")), -1)
    header = [cell.strip().lower() for cell in lines[first]] if first >= 0 else []
    word_col = _column_of(header, _HEADERS)
    has_header = (
        len(header) >= 2 and word_col >= 0 and
        any(_column_of(header, names) >= 0 for names in
            (_GROUP_HEADERS, _TIME_HEADERS, _GROUP_TIME_HEADERS))
    )
    if has_header:
        groups_col = _column_of(header, _GROUP_HEADERS)
        time_col = _column_of(header, _TIME_HEADERS)
        group_time_col = _column_of(header, _GROUP_TIME_HEADERS)
    else:
        word_col, groups_col, time_col, group_time_col = 0, -1, -1, -1

    def _cell(row: List[str], col: int) -> str:
        return row[col] if 0 <= col < len(row) else ""

    out: List[Dict] = []
    seen = set()
    for index, row in enumerate(lines):
        line = _clean(row)
        if not line or line.startswith("#"):
            continue
        if has_header and index == first:
            continue
        word = (_cell(row, word_col) if has_header
                else (row[0] if row else "")).strip()
        if not word or word.lower() in _HEADERS:
            continue
        key = word.lower()
        if key in seen:                  # 大小写不敏感去重，保留首次出现的写法
            continue
        seen.add(key)
        out.append({
            "word": word,
            "groups": _split_groups(_cell(row, groups_col)) if groups_col >= 0 else [],
            "added_at": _cell(row, time_col).strip() if time_col >= 0 else "",
            "group_added_at": _split_times(_cell(row, group_time_col))
            if group_time_col >= 0 else [],
        })
    return out


def parse_words(text: str) -> List[str]:
    """从纯文本 / CSV 提取生词列表（只要词，不要其它列）。

    忽略空行与 # 开头的注释行；按大小写不敏感去重，保留首次出现的写法。
    """
    return [row["word"] for row in parse_rows(text)]


def align_group_times(groups: Sequence[str], group_times: Sequence[str],
                      fallback: str) -> List[str]:
    """把「按分组记录的时间」补齐/截短到与 groups 等长；缺的位置用词级时间兜底。"""
    return [
        group_times[i].strip() if i < len(group_times) and group_times[i].strip()
        else fallback
        for i in range(len(groups))
    ]


def normalize_added_at(value: str) -> str:
    """把导入文件里的时间统一成桌面版 / Android 共用的 ISO 8601 秒级写法。

    覆盖 Android ``formatAddedAt`` 的 ``yyyy-MM-dd'T'HH:mm:ss``、桌面版
    ``datetime.isoformat()``，以及旧数据里 SQLite ``CURRENT_TIMESTAMP`` 的
    ``yyyy-MM-dd HH:mm:ss``。认不出来返回空串（调用方回退到当前时间）；
    带时区的写法会去掉时区，避免写出 Android ``parseAddedAt`` 读不懂的字符串。
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return ""
    return parsed.replace(tzinfo=None).isoformat(timespec="seconds")


def is_backup(text: str, path: str = "") -> bool:
    """判断读到的文件是不是 JSON 备份。

    只认扩展名不够：用户另存为 .txt、或转发后丢了后缀时，JSON 会被当词表
    逐行导入成一堆垃圾词；内容里有类型标记就一律按备份处理（与 Android 同）。
    """
    body = (text or "").lstrip("\ufeff \t\r\n")
    return ext_of(path) == "json" or (
        body.startswith("{") and BACKUP_TYPE in body)


def parse_backup(text: str) -> Dict:
    """解析 JSON 备份；格式不符抛 ValueError（界面层转成提示）。

    返回 ``{'groups': [分组名…], 'words': [{'word','groups','added_at',
    'group_added_at'}…]}``。v1 / v2 都能读，v1 没有 ``group_added_at`` 时
    由 [align_group_times] 统一回退到词级 ``added_at``。
    """
    try:
        data = json.loads((text or "").lstrip("\ufeff"))
    except json.JSONDecodeError as e:
        raise ValueError(f"不是合法的 JSON 文件：{e}") from e
    if not isinstance(data, dict) or data.get("type") != BACKUP_TYPE:
        raise ValueError("这不是 TinyDict 生词本备份文件（缺少类型标记）。")
    version = data.get("version", 0)
    if (not isinstance(version, int) or isinstance(version, bool)
            or version < 0 or version > MAX_IMPORT_VERSION):
        raise ValueError(
            f"备份文件版本为 {version}，高于当前软件支持的 {MAX_IMPORT_VERSION}，"
            "请升级软件后再导入。")

    raw_groups = data.get("groups")
    groups = [str(g).strip() for g in raw_groups] if isinstance(raw_groups, list) else []
    groups = [g for g in groups if g]

    raw_words = data.get("words")
    words: List[Dict] = []
    for item in (raw_words if isinstance(raw_words, list) else []):
        if isinstance(item, dict):
            word = str(item.get("word") or "").strip()
            raw_gs = item.get("groups")
            gs = [str(x).strip() for x in raw_gs] if isinstance(raw_gs, list) else []
            added = str(item.get("added_at") or "")
            # 时间数组要保留空串占位：两个分组同一秒、或某个分组没写时间时，
            # 按 index 对齐才不会错位，所以不能像 gs 那样过滤空值。
            raw_times = item.get("group_added_at")
            times = [str(x).strip() if x is not None else ""
                     for x in raw_times] if isinstance(raw_times, list) else []
        else:                            # 容忍「字符串数组」这种简写
            word, gs, added, times = str(item).strip(), [], "", []
        if word:
            words.append({"word": word,
                          "groups": [g for g in gs if g],
                          "added_at": added,
                          "group_added_at": times})
    return {"groups": groups, "words": words}


def ext_of(path: str) -> str:
    """取小写扩展名（不含点）；没有扩展名时返回空串。"""
    name = (path or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""
