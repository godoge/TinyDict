"""生词本导入导出：txt / csv / json 三种格式的序列化与解析。

只依赖标准库、不碰 Qt，这样格式逻辑可以脱离界面单独测试；
界面层（ui/wordbook_dialog.py）只负责选文件、读写磁盘和结果提示。

三种格式各有分工：
- txt ：每行一个词，最通用，方便和别的工具交换；
- csv ：带「所属分组 / 加入时间」，可以用 Excel 打开查看整理；
- json：完整备份（分组结构 + 每个词的分组归属），用于备份后原样恢复。
"""

import csv
import io
import json
from typing import Dict, List, Sequence, Tuple

__all__ = [
    "BACKUP_TYPE", "BACKUP_VERSION", "GROUP_SEP",
    "dump_txt", "dump_csv", "dump_json",
    "parse_words", "parse_backup", "ext_of",
]

#: JSON 备份里的类型标记，用来判断「这是不是生词本备份」
BACKUP_TYPE = "tinydict-wordbook"
#: 备份格式版本；将来结构变了靠它决定是否兼容
BACKUP_VERSION = 1

#: CSV 里把「一个词所属的多个分组」拼进同一个单元格的分隔符
GROUP_SEP = "; "

# CSV 首行表头的常见写法，导入时跳过
_HEADERS = {"word", "words", "单词", "生词", "vocabulary", "vocab"}


# ---------------------------------------------------------------------- 导出
def dump_txt(rows: Sequence[Tuple[str, str, List[str]]]) -> str:
    """每行一个生词（不含分组与时间）。"""
    return "".join(f"{word}\n" for word, _added, _groups in rows)


def dump_csv(rows: Sequence[Tuple[str, str, List[str]]]) -> str:
    """带表头的 CSV：word,groups,added_at（分组用 GROUP_SEP 拼接）。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["word", "groups", "added_at"])
    for word, added_at, groups in rows:
        writer.writerow([word, GROUP_SEP.join(groups), added_at])
    return buf.getvalue()


def dump_json(rows: Sequence[Tuple[str, str, List[str]]],
              groups: Sequence[str], exported_at: str = "") -> str:
    """完整备份：分组清单 + 每个词的分组归属，导入时可原样恢复。"""
    payload = {
        "app": "TinyDict",
        "type": BACKUP_TYPE,
        "version": BACKUP_VERSION,
        "exported_at": exported_at,
        "groups": list(groups),
        "words": [
            {"word": word, "groups": list(gs), "added_at": added_at}
            for word, added_at, gs in rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------- 导入
def _first_field(line: str) -> str:
    """取一行里的第一个字段：CSV 行按 csv 规则切，纯文本整行返回。"""
    if "," in line or ";" in line or '"' in line:
        try:
            row = next(csv.reader([line]), [])
        except Exception:        # 极端畸形行：退回整行当作一个词
            row = []
        if row:
            return row[0].strip()
    return line.strip()


def parse_words(text: str) -> List[str]:
    """从纯文本 / CSV 提取生词列表。

    忽略空行与 # 开头的注释行；CSV 只取第一列并跳过表头。
    按大小写不敏感去重（与生词本自身的去重规则一致），保留首次出现的写法。
    """
    out: List[str] = []
    seen = set()
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("\ufeff").strip()
        if not line or line.startswith("#"):
            continue
        word = _first_field(line)
        if not word or word.lower() in _HEADERS:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(word)
    return out


def parse_backup(text: str) -> Dict:
    """解析 JSON 备份；格式不符抛 ValueError（界面层转成提示）。

    返回 {'groups': [分组名…], 'words': [{'word','groups','added_at'}…]}。
    """
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError as e:
        raise ValueError(f"不是合法的 JSON 文件：{e}") from e
    if not isinstance(data, dict) or data.get("type") != BACKUP_TYPE:
        raise ValueError("这不是 TinyDict 生词本备份文件（缺少类型标记）。")
    version = data.get("version", 0)
    if not isinstance(version, int) or version > BACKUP_VERSION:
        raise ValueError(
            f"备份文件版本为 {version}，高于当前软件支持的 {BACKUP_VERSION}，"
            "请升级软件后再导入。")

    groups = [str(g).strip() for g in (data.get("groups") or [])]
    groups = [g for g in groups if g]

    words: List[Dict] = []
    for item in (data.get("words") or []):
        if isinstance(item, dict):
            word = str(item.get("word") or "").strip()
            gs = [str(x).strip() for x in (item.get("groups") or [])]
            added = str(item.get("added_at") or "")
        else:                    # 容忍「字符串数组」这种简写
            word, gs, added = str(item).strip(), [], ""
        if word:
            words.append({"word": word,
                          "groups": [g for g in gs if g],
                          "added_at": added})
    return {"groups": groups, "words": words}


def ext_of(path: str) -> str:
    """取小写扩展名（不含点）；没有扩展名时返回空串。"""
    name = (path or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""
