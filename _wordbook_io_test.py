"""生词本导入导出回归测试（桌面版 ↔ Android 版一致性）。

用标准库 unittest，``.venv/Scripts/python.exe -m unittest -v _wordbook_io_test`` 即可运行，
不需要 Qt / 不需要真机。分三层：

1. FormatTests —— 把 Android 单测 ``WordbookBackupTest`` 里的基准串搬过来，
   要求桌面版 ``dump_txt / dump_csv / dump_json`` 逐字节一致；
2. ParseTests  —— Android 导出的文件、旧版文件、各种边界输入都能正确解析；
3. RoundTripTests —— 用临时 SQLite 真库做「导出 → 导入到空库 → 再导出」，
   核对分组归属与**每个分组各自的收藏时间**没有丢失。

基准串来源：app/src/test/java/com/godoge/tinydict/data/WordbookBackupTest.kt
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tinydict.core import wordbook_io as io
from tinydict.core.database import Database
from tinydict.core.wordbook import ALL_GROUPS, WordBook

# Android WordbookBackupTest.kt 里的 rows，两本、含逗号 / 引号 / 空格词条
GROUPS = ["默认生词本", "重点难点"]
ROWS = [
    ("apple", "2026-09-20T10:00:00", ["默认生词本"],
     ["2026-09-20T10:00:00"]),
    ("banana", "2026-09-21T11:30:00", ["默认生词本", "重点难点"],
     ["2026-09-20T09:00:00", "2026-09-21T11:30:00"]),
    ("co,ma", "2026-09-22T09:05:00", ["重点难点"],
     ["2026-09-22T09:05:00"]),
    ('quote"word', "2026-09-23T08:00:00", [], []),
    ("行 政", "2026-09-19T08:00:00", ["默认生词本", "重点难点"],
     ["2026-09-18T07:00:00", "2026-09-19T08:00:00"]),
]

TXT = "apple\nbanana\nco,ma\nquote\"word\n行 政\n"

CSV = ("word,groups,added_at,group_added_at\r\n"
       "apple,默认生词本,2026-09-20T10:00:00,2026-09-20T10:00:00\r\n"
       "banana,默认生词本; 重点难点,2026-09-21T11:30:00,"
       "2026-09-20T09:00:00; 2026-09-21T11:30:00\r\n"
       "\"co,ma\",重点难点,2026-09-22T09:05:00,2026-09-22T09:05:00\r\n"
       "\"quote\"\"word\",,2026-09-23T08:00:00,\r\n"
       "行 政,默认生词本; 重点难点,2026-09-19T08:00:00,"
       "2026-09-18T07:00:00; 2026-09-19T08:00:00\r\n")

JSON = """{
  "app": "TinyDict",
  "type": "tinydict-wordbook",
  "version": 1,
  "exported_at": "2026-09-23T08:00:00",
  "groups": [
    "默认生词本",
    "重点难点"
  ],
  "words": [
    {
      "word": "apple",
      "groups": [
        "默认生词本"
      ],
      "added_at": "2026-09-20T10:00:00",
      "group_added_at": [
        "2026-09-20T10:00:00"
      ]
    },
    {
      "word": "banana",
      "groups": [
        "默认生词本",
        "重点难点"
      ],
      "added_at": "2026-09-21T11:30:00",
      "group_added_at": [
        "2026-09-20T09:00:00",
        "2026-09-21T11:30:00"
      ]
    },
    {
      "word": "co,ma",
      "groups": [
        "重点难点"
      ],
      "added_at": "2026-09-22T09:05:00",
      "group_added_at": [
        "2026-09-22T09:05:00"
      ]
    },
    {
      "word": "quote\\"word",
      "groups": [],
      "added_at": "2026-09-23T08:00:00",
      "group_added_at": []
    },
    {
      "word": "行 政",
      "groups": [
        "默认生词本",
        "重点难点"
      ],
      "added_at": "2026-09-19T08:00:00",
      "group_added_at": [
        "2026-09-18T07:00:00",
        "2026-09-19T08:00:00"
      ]
    }
  ]
}"""


class FormatTests(unittest.TestCase):
    """导出文本必须和 Android 版逐字节一致。"""

    def test_dump_txt(self):
        self.assertEqual(TXT, io.dump_txt(ROWS))

    def test_dump_csv(self):
        self.assertEqual(CSV, io.dump_csv(ROWS))

    def test_dump_json(self):
        self.assertEqual(
            JSON, io.dump_json(ROWS, GROUPS, "2026-09-23T08:00:00"))

    def test_写出版本保持1(self):
        payload = json.loads(io.dump_json(ROWS, GROUPS))
        self.assertEqual(1, payload["version"])
        self.assertEqual("tinydict-wordbook", payload["type"])
        self.assertEqual(5, len(payload["words"]))
        self.assertEqual(4, len(io.dump_csv(ROWS).splitlines()[0].split(",")))

    def test_空表导出(self):
        self.assertEqual("", io.dump_txt([]))
        self.assertEqual("word,groups,added_at,group_added_at\r\n",
                         io.dump_csv([]))
        self.assertEqual([], json.loads(io.dump_json([], []))["words"])

    def test_导出时间统一成ISO_T格式(self):
        legacy = [("alpha", "2026-09-20 10:00:00", ["默认生词本"],
                   ["2026-09-20 10:00:00"])]
        self.assertIn("alpha,默认生词本,2026-09-20T10:00:00,"
                      "2026-09-20T10:00:00\r\n", io.dump_csv(legacy))
        payload = json.loads(io.dump_json(legacy, GROUPS))
        self.assertEqual("2026-09-20T10:00:00", payload["words"][0]["added_at"])
        self.assertEqual(["2026-09-20T10:00:00"],
                         payload["words"][0]["group_added_at"])

    def test_旧三元组调用仍可用(self):
        legacy = [(r[0], r[1], r[2]) for r in ROWS]
        self.assertEqual(TXT, io.dump_txt(legacy))
        # 三元组没有每分组时间，第四列写空而不是写词级时间
        csv_text = io.dump_csv(legacy)
        self.assertIn("apple,默认生词本,2026-09-20T10:00:00,\r\n", csv_text)


class ParseTests(unittest.TestCase):
    """导入侧：Android 文件、旧文件、边界输入。"""

    def test_parse_android_csv(self):
        parsed = io.parse_rows(CSV)
        self.assertEqual([r[0] for r in ROWS], [r["word"] for r in parsed])
        self.assertEqual(GROUPS, parsed[1]["groups"])
        self.assertEqual(["2026-09-20T09:00:00", "2026-09-21T11:30:00"],
                         parsed[1]["group_added_at"])
        self.assertEqual(["重点难点"], parsed[2]["groups"])
        self.assertEqual([], parsed[3]["groups"])
        self.assertEqual([], parsed[3]["group_added_at"])
        self.assertEqual(GROUPS, parsed[4]["groups"])

    def test_csv_roundtrip(self):
        parsed = io.parse_rows(io.dump_csv(ROWS))
        self.assertEqual(5, len(parsed))
        self.assertEqual(
            [list(r[2]) for r in ROWS], [r["groups"] for r in parsed])
        self.assertEqual(
            [list(r[3]) for r in ROWS], [r["group_added_at"] for r in parsed])

    def test_旧三列_csv_回退(self):
        old = ("word,groups,added_at\r\n"
               "alpha,重点难点,2026-09-20T10:00:00\r\n"
               "beta,默认生词本; 重点难点,2026-09-21T11:30:00\r\n")
        parsed = io.parse_rows(old)
        self.assertEqual(["alpha", "beta"], [r["word"] for r in parsed])
        self.assertEqual([], parsed[0]["group_added_at"])
        self.assertEqual(
            ["2026-09-21T11:30:00", "2026-09-21T11:30:00"],
            io.align_group_times(parsed[1]["groups"],
                                 parsed[1]["group_added_at"],
                                 parsed[1]["added_at"]))

    def test_表头乱序与中文表头(self):
        text = ("分组,单词,时间,分组时间\r\n"
                "重点难点; 默认生词本,beta,2026-09-21T11:30:00,"
                "2026-09-20T09:00:00; 2026-09-21T11:30:00\r\n")
        parsed = io.parse_rows(text)
        self.assertEqual(["beta"], [r["word"] for r in parsed])
        self.assertEqual(["重点难点", "默认生词本"], parsed[0]["groups"])
        self.assertEqual(["2026-09-20T09:00:00", "2026-09-21T11:30:00"],
                         parsed[0]["group_added_at"])

    def test_bom_crlf_注释与去重(self):
        parsed = io.parse_rows("\ufeff# 注释\r\n" + CSV + "APPLE,,\r\n")
        self.assertEqual(5, len(parsed))
        self.assertEqual("apple", parsed[0]["word"])

    def test_引号内换行不被拆行(self):
        text = ("word,groups,added_at,group_added_at\r\n"
                "\"line\nbreak\",重点难点,2026-09-22T09:05:00,"
                "2026-09-22T09:05:00\r\n")
        parsed = io.parse_rows(text)
        self.assertEqual(1, len(parsed))
        self.assertEqual("line\nbreak", parsed[0]["word"])
        self.assertEqual(["重点难点"], parsed[0]["groups"])

    def test_时间列空占位不去重(self):
        text = ("word,groups,added_at,group_added_at\r\n"
                "alpha,一; 二,2026-01-01T00:00:00,"
                "2026-01-01T00:00:00; 2026-01-01T00:00:00\r\n"
                "beta,一; 二,2026-01-01T00:00:00,; 2026-02-02T00:00:00\r\n")
        parsed = io.parse_rows(text)
        self.assertEqual(["2026-01-01T00:00:00", "2026-01-01T00:00:00"],
                         parsed[0]["group_added_at"])
        self.assertEqual(["", "2026-02-02T00:00:00"],
                         parsed[1]["group_added_at"])
        self.assertEqual(["2026-01-01T00:00:00", "2026-02-02T00:00:00"],
                         io.align_group_times(parsed[1]["groups"],
                                              parsed[1]["group_added_at"],
                                              parsed[1]["added_at"]))

    def test_txt_不带归属且裸引号不吞行(self):
        parsed = io.parse_rows('word\nquote"word\nword; pierre\nfoo,bar\n')
        self.assertEqual(["quote\"word", "word; pierre", "foo"],
                         [r["word"] for r in parsed])
        self.assertTrue(all(not r["groups"] for r in parsed))

    def test_parse_words_保持旧行为(self):
        self.assertEqual(["quote\"word", "word; pierre", "foo"],
                         io.parse_words('quote"word\nword; pierre\nfoo,bar\n'))
        self.assertEqual(["apple", "banana"], io.parse_words(CSV)[:2])

    def test_parse_backup_读Android的JSON(self):
        payload = io.parse_backup(JSON)
        self.assertEqual(GROUPS, payload["groups"])
        self.assertEqual([r[0] for r in ROWS],
                         [w["word"] for w in payload["words"]])
        self.assertEqual(["2026-09-20T09:00:00", "2026-09-21T11:30:00"],
                         payload["words"][1]["group_added_at"])
        self.assertEqual([], payload["words"][3]["group_added_at"])

    def test_parse_backup_兼容v2与v1旧备份(self):
        v2 = json.loads(JSON)
        v2["version"] = 2
        self.assertEqual(5, len(io.parse_backup(json.dumps(v2))["words"]))
        v1 = json.loads(JSON)
        for word in v1["words"]:
            word.pop("group_added_at")
        parsed = io.parse_backup(json.dumps(v1))
        self.assertEqual([], parsed["words"][1]["group_added_at"])
        self.assertEqual(
            ["2026-09-21T11:30:00", "2026-09-21T11:30:00"],
            io.align_group_times(parsed["words"][1]["groups"], [],
                                 parsed["words"][1]["added_at"]))

    def test_parse_backup_字段类型畸形不产生垃圾词(self):
        weird = ('{"type":"tinydict-wordbook","version":1,'
                 '"groups":"默认生词本","words":"alpha",'
                 '"x":1}')
        parsed = io.parse_backup(weird)
        self.assertEqual([], parsed["groups"])
        self.assertEqual([], parsed["words"])
        bad_lists = ('{"type":"tinydict-wordbook","version":1,'
                     '"words":[{"word":"alpha","groups":"一; 二",'
                     '"added_at":"2026-01-01T00:00:00",'
                     '"group_added_at":"2026-02-02T00:00:00"}]}')
        parsed = io.parse_backup(bad_lists)
        self.assertEqual([], parsed["words"][0]["groups"])
        self.assertEqual([], parsed["words"][0]["group_added_at"])

    def test_parse_backup_拒绝过高版本与非备份(self):
        with self.assertRaises(ValueError):
            io.parse_backup('{"type":"tinydict-wordbook","version":9}')
        with self.assertRaises(ValueError):
            io.parse_backup('{"type":"other","version":1}')
        with self.assertRaises(ValueError):
            io.parse_backup("not json")

    def test_is_backup_按内容嗅探(self):
        self.assertTrue(io.is_backup(JSON, "转发文件.txt"))
        self.assertTrue(io.is_backup(JSON, "备份.json"))
        self.assertFalse(io.is_backup(CSV, "词表.csv"))
        self.assertFalse(io.is_backup(CSV, "备份.json.txt"))

    def test_normalize_added_at(self):
        self.assertEqual("2026-09-20T10:00:00",
                         io.normalize_added_at("2026-09-20T10:00:00"))
        self.assertEqual("2026-09-20T10:00:00",
                         io.normalize_added_at("2026-09-20 10:00:00"))
        self.assertEqual("2026-09-20T00:00:00",
                         io.normalize_added_at("2026-09-20"))
        self.assertEqual("", io.normalize_added_at("随便写的"))
        self.assertEqual("", io.normalize_added_at(""))


class RoundTripTests(unittest.TestCase):
    """真实 SQLite：分组归属与每分组时间必须无损。"""

    # 词 -> [(分组名, 该分组的收藏时间)]
    DATA = {
        "apple": [("默认分组", "2026-09-20T10:00:00")],
        "banana": [("默认分组", "2026-09-20T09:00:00"),
                   ("重点难点", "2026-09-21T11:30:00")],
        "co,ma": [("重点难点", "2026-09-22T09:05:00")],
        'quote"word': [("默认分组", "2026-09-23T08:00:00")],
        "行 政": [("默认分组", "2026-09-18T07:00:00"),
                 ("重点难点", "2026-09-19T08:00:00")],
    }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dbs = []

        def cleanup():
            # Windows 上 SQLite 文件被连接占着时临时目录删不掉，先关连接
            for db in self._dbs:
                try:
                    db.conn().close()
                except Exception:
                    pass
            self._tmp.cleanup()

        self.addCleanup(cleanup)
        self.path = Path(self._tmp.name) / "wordbook.db"

    def _db_at(self, name):
        db = Database(Path(self._tmp.name) / name)
        self._dbs.append(db)
        return db

    def _new_book(self, path=None):
        db = self._db_at(Path(path).name) if path else self._db_at("wordbook.db")
        return WordBook(db)

    def _seed(self, wb):
        wb.add_group("重点难点")
        wb.add_group("还没有词的本")
        name_to_id = {g.name: g.id for g in wb.groups()}
        for word, entries in self.DATA.items():
            for name, stamp in entries:
                wb.add(word, name_to_id[name], added_at=stamp)

    @staticmethod
    def _dump_db(db):
        """从 SQLite 直接读「词 × 分组 → 时间」，绕开导出代码做独立核对。"""
        rows = db.conn().execute(
            "SELECT t.word, g.name, t.added_at FROM wordbook_tags t"
            " JOIN wordbook_groups g ON g.id=t.group_id"
            " ORDER BY t.word, g.id").fetchall()
        out = {}
        for word, name, stamp in rows:
            out.setdefault(word, []).append((name, stamp))
        return out

    def test_导出带各分组时间与空分组(self):
        wb = self._new_book()
        self._seed(wb)
        rows = wb.export_rows(ALL_GROUPS)
        by_word = {r[0]: r for r in rows}
        self.assertEqual(["默认分组", "重点难点"], by_word["banana"][2])
        self.assertEqual(["2026-09-20T09:00:00", "2026-09-21T11:30:00"],
                         by_word["banana"][3])
        json_text = io.dump_json(
            rows, [g.name for g in wb.groups()], "2026-09-23T08:00:00")
        self.assertIn("还没有词的本", json_text)   # 空分组只有 JSON 能保留
        csv_text = io.dump_csv(rows)
        self.assertEqual(6, len(csv_text.splitlines()))  # 表头 + 5 个词

    def test_csv_往返_分组与各分组时间无损(self):
        src = self._new_book()
        self._seed(src)
        expected = self._dump_db(src._db)

        csv_text = io.dump_csv(src.export_rows(ALL_GROUPS))
        dst_db = self._db_at("dst.db")
        dst = WordBook(dst_db)
        stat = dst.restore_rows(io.parse_rows(csv_text))

        self.assertEqual(5, stat["words"])
        self.assertEqual(7, stat["tags"])
        self.assertEqual(1, stat["groups"])   # 默认分组本来就在，只新建「重点难点」
        self.assertEqual(expected, self._dump_db(dst_db))
        # 再导出一遍，信息仍然完整（顺序可能变，按词比对）
        again = {r[0]: (r[2], r[3]) for r in dst.export_rows(ALL_GROUPS)}
        for word, entries in expected.items():
            self.assertEqual([n for n, _ in entries], again[word][0], word)
            self.assertEqual([t for _, t in entries], again[word][1], word)

    def test_json_往返_含顶层空分组(self):
        src = self._new_book()
        self._seed(src)
        expected = self._dump_db(src._db)
        json_text = io.dump_json(
            src.export_rows(ALL_GROUPS),
            [g.name for g in src.groups()], "2026-09-23T08:00:00")

        dst_db = self._db_at("dst.db")
        dst = WordBook(dst_db)
        stat = dst.restore(io.parse_backup(json_text))

        self.assertEqual(5, stat["words"])
        self.assertEqual(7, stat["tags"])
        self.assertEqual(expected, self._dump_db(dst_db))
        self.assertIn("还没有词的本", [g.name for g in dst.groups()])

    def test_导入Android导出的CSV_按原名还原(self):
        dst_db = self._db_at("dst.db")
        dst = WordBook(dst_db)
        rows = io.parse_rows(CSV)
        stat = dst.restore_rows(rows)
        self.assertEqual(5, stat["words"])
        # 顶层没有「默认生词本」，但 CSV 里写了，所以会自动新建
        names = [g.name for g in dst.groups()]
        self.assertIn("默认生词本", names)
        self.assertIn("重点难点", names)
        got = self._dump_db(dst_db)
        self.assertEqual(["默认生词本", "重点难点"],
                         [n for n, _ in got["banana"]])
        self.assertEqual(["2026-09-20T09:00:00", "2026-09-21T11:30:00"],
                         [t for _, t in got["banana"]])
        # 没有归属的词统一落到默认分组（不变量：每个词至少属于一个分组）
        self.assertTrue(got['quote"word'])

    def test_导入Android导出的JSON_每本时间保留(self):
        dst_db = self._db_at("dst.db")
        dst = WordBook(dst_db)
        dst.restore(io.parse_backup(JSON))
        got = self._dump_db(dst_db)
        self.assertEqual(["2026-09-18T07:00:00", "2026-09-19T08:00:00"],
                         [t for _, t in got["行 政"]])
        self.assertEqual(["2026-09-22T09:05:00"],
                         [t for _, t in got["co,ma"]])

    def test_无归属旧CSV_带词级时间导入(self):
        old = ("word,groups,added_at\r\n"
               "alpha,,2026-09-20T10:00:00\r\n"
               "beta,,2026-09-21T11:30:00\r\n")
        rows = io.parse_rows(old)
        wb = self._new_book()
        stat = wb.add_words_with_times(
            [(r["word"], r["added_at"]) for r in rows], 1)
        self.assertEqual(2, stat)
        stamps = dict(wb._db.conn().execute(
            "SELECT word, added_at FROM wordbook_tags").fetchall())
        self.assertEqual("2026-09-20T10:00:00", stamps["alpha"])
        self.assertEqual("2026-09-21T11:30:00", stamps["beta"])

    def test_合并导入不覆盖已有词的时间(self):
        wb = self._new_book()
        wb.add("banana", 1, added_at="2026-01-01T00:00:00")
        wb.restore_rows(io.parse_rows(CSV))
        got = self._dump_db(wb._db)
        # 已存在的「默认分组」关系保持原时间；新关系用文件里的时间
        self.assertIn(("默认分组", "2026-01-01T00:00:00"), got["banana"])
        self.assertIn(("重点难点", "2026-09-21T11:30:00"), got["banana"])


class UiTests(unittest.TestCase):
    """offscreen 冒烟：界面层的导入分流、导出写盘、文案格式化都能跑通。"""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox
        except ImportError as e:                 # pragma: no cover
            raise unittest.SkipTest(f"PySide6 不可用：{e}") from e
        cls.QFileDialog = QFileDialog
        cls.QMenu = QMenu
        cls.QMessageBox = QMessageBox
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tinydict.ui.wordbook_dialog import WordbookDialog
        tmp = tempfile.TemporaryDirectory()
        self._tmp = tmp
        self._db = Database(Path(tmp.name) / "ui.db")

        def cleanup():
            try:
                self._db.conn().close()
            except Exception:
                pass
            tmp.cleanup()

        self.addCleanup(cleanup)
        self.wb = WordBook(self._db)
        self.dlg = WordbookDialog(self.wb)

    @staticmethod
    def _tags(db):
        rows = db.conn().execute(
            "SELECT t.word, g.name, t.added_at FROM wordbook_tags t"
            " JOIN wordbook_groups g ON g.id=t.group_id"
            " ORDER BY t.word, g.id").fetchall()
        out = {}
        for word, name, stamp in rows:
            out.setdefault(word, []).append((name, stamp))
        return out

    def test_导入Android的CSV_走按名还原(self):
        src = Path(self._tmp.name) / "android.csv"
        src.write_text(CSV, encoding="utf-8-sig")
        with patch.object(self.QFileDialog, "getOpenFileName",
                          return_value=(str(src), "")), \
             patch.object(self.QMessageBox, "question",
                          return_value=self.QMessageBox.StandardButton.Yes):
            self.dlg._import_words()
        got = self._tags(self._db)
        self.assertEqual(["默认生词本", "重点难点"],
                         [n for n, _ in got["banana"]])
        self.assertEqual(["2026-09-20T09:00:00", "2026-09-21T11:30:00"],
                         [t for _, t in got["banana"]])

    def test_JSON另存为txt_按内容嗅探成备份(self):
        from tinydict import i18n
        src = Path(self._tmp.name) / "转发丢了后缀.txt"
        src.write_text(JSON, encoding="utf-8")
        i18n.set_language("en_US")              # 顺带验证英文文案的 format 参数
        try:
            with patch.object(self.QFileDialog, "getOpenFileName",
                              return_value=(str(src), "")), \
                 patch.object(self.QMessageBox, "question",
                              return_value=self.QMessageBox.StandardButton.Yes):
                self.dlg._import_words()
        finally:
            i18n.set_language("zh_CN")
        self.assertEqual(["2026-09-18T07:00:00", "2026-09-19T08:00:00"],
                         [t for _, t in self._tags(self._db)["行 政"]])

    def test_导出CSV_四列且能被解析回原状(self):
        self.wb.add_group("重点难点")
        ids = {g.name: g.id for g in self.wb.groups()}
        self.wb.add("banana", ids["默认分组"],
                    added_at="2026-09-20T09:00:00")
        self.wb.add("banana", ids["重点难点"],
                    added_at="2026-09-21T11:30:00")
        out = Path(self._tmp.name) / "out.csv"
        # (None, "csv") = 选项对话框里选「全部生词本 + CSV」
        with patch.object(self.dlg, "_ask_export_options",
                          return_value=(None, "csv")), \
             patch.object(self.QFileDialog, "getSaveFileName",
                          return_value=(str(out), "CSV 表格 (*.csv)")):
            self.dlg._export_words()
        raw = out.read_bytes()
        # 桌面版 CSV 带 BOM（Excel 双击不乱码），行尾是 CRLF；Android 读取时会去掉 BOM
        self.assertTrue(raw.startswith(
            b"\xef\xbb\xbfword,groups,added_at,group_added_at\r\n"))
        parsed = io.parse_rows(raw.decode("utf-8-sig"))
        self.assertEqual(["默认分组", "重点难点"], parsed[0]["groups"])
        self.assertEqual(["2026-09-20T09:00:00", "2026-09-21T11:30:00"],
                         parsed[0]["group_added_at"])

    def test_无归属CSV_仍走选分组分支且带词级时间(self):
        src = Path(self._tmp.name) / "old.csv"
        src.write_text("word,groups,added_at\r\nalpha,,2026-09-20T10:00:00\r\n",
                       encoding="utf-8-sig")

        # QMenu.exec 是 sip 方法，offscreen 下会进事件循环挂住，且 patch 拦不到它；
        # 这里只验证分流到 _import_plain，菜单内的写入逻辑由 RoundTripTests 覆盖。
        with patch.object(self.QFileDialog, "getOpenFileName",
                          return_value=(str(src), "")), \
             patch.object(type(self.dlg), "_import_plain") as plain:
            self.dlg._import_words()
        plain.assert_called_once()
        self.assertEqual(["alpha"], plain.call_args[0][0])
        self.assertEqual(["2026-09-20T10:00:00"], plain.call_args[0][2])

    # ---------------------------------------------------- 导出选项：范围 + 格式
    def test_取消导出选项_不弹保存框也不写盘(self):
        with patch.object(self.dlg, "_ask_export_options",
                          return_value=None), \
             patch.object(self.QFileDialog, "getSaveFileName") as save:
            self.dlg._export_words()
        save.assert_not_called()

    def test_只导出一个分组_CSV不带出其它分组(self):
        self.wb.add_group("重点难点")
        ids = {g.name: g.id for g in self.wb.groups()}
        self.wb.add("shared", ids["默认分组"],
                    added_at="2026-09-20T09:00:00")
        self.wb.add("shared", ids["重点难点"],
                    added_at="2026-09-21T11:30:00")
        self.wb.add("only_default", ids["默认分组"],
                    added_at="2026-09-22T09:00:00")
        out = Path(self._tmp.name) / "part.csv"
        with patch.object(self.dlg, "_ask_export_options",
                          return_value=([ids["重点难点"]], "csv")), \
             patch.object(self.QFileDialog, "getSaveFileName",
                          return_value=(str(out), "")):
            self.dlg._export_words()
        parsed = io.parse_rows(out.read_text(encoding="utf-8-sig"))
        self.assertEqual(["shared"], [r["word"] for r in parsed])
        self.assertEqual([["重点难点"]], [r["groups"] for r in parsed])
        self.assertEqual([["2026-09-21T11:30:00"]],
                         [r["group_added_at"] for r in parsed])

    def test_只导出部分分组_JSON顶层只含所选且保留空分组(self):
        self.wb.add_group("重点难点")
        self.wb.add_group("空的")
        ids = {g.name: g.id for g in self.wb.groups()}
        self.wb.add("alpha", ids["重点难点"],
                    added_at="2026-09-20T09:00:00")
        self.wb.add("beta", ids["默认分组"],
                    added_at="2026-09-21T09:00:00")
        out = Path(self._tmp.name) / "part.json"
        with patch.object(self.dlg, "_ask_export_options",
                          return_value=([ids["重点难点"], ids["空的"]],
                                        "json")), \
             patch.object(self.QFileDialog, "getSaveFileName",
                          return_value=(str(out), "")):
            self.dlg._export_words()
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(["重点难点", "空的"], data["groups"])
        self.assertEqual(["alpha"], [w["word"] for w in data["words"]])
        self.assertEqual(["重点难点"], data["words"][0]["groups"])
        self.assertEqual(["2026-09-20T09:00:00"],
                         data["words"][0]["group_added_at"])

    def test_TXT只写所选分组的词表(self):
        self.wb.add_group("重点难点")
        ids = {g.name: g.id for g in self.wb.groups()}
        self.wb.add("alpha", ids["重点难点"])
        self.wb.add("beta", ids["默认分组"])
        out = Path(self._tmp.name) / "part.txt"
        with patch.object(self.dlg, "_ask_export_options",
                          return_value=([ids["重点难点"]], "txt")), \
             patch.object(self.QFileDialog, "getSaveFileName",
                          return_value=(str(out), "")):
            self.dlg._export_words()
        self.assertEqual("alpha\n", out.read_text(encoding="utf-8"))

    def test_保存时手输的其它后缀按所选格式纠正(self):
        ids = {g.name: g.id for g in self.wb.groups()}
        self.wb.add("alpha", ids["默认分组"])
        typed = Path(self._tmp.name) / "chosen.json"
        expected = Path(self._tmp.name) / "chosen.csv"
        with patch.object(self.dlg, "_ask_export_options",
                          return_value=(None, "csv")), \
             patch.object(self.QFileDialog, "getSaveFileName",
                          return_value=(str(typed), "")):
            self.dlg._export_words()
        self.assertFalse(typed.exists())
        self.assertTrue(expected.read_bytes().startswith(
            b"\xef\xbb\xbfword,groups,added_at,group_added_at\r\n"))

    def test_部分分组CSV_导入空库不会带出没选的分组(self):
        self.wb.add_group("重点难点")
        ids = {g.name: g.id for g in self.wb.groups()}
        self.wb.add("shared", ids["默认分组"],
                    added_at="2026-09-20T09:00:00")
        self.wb.add("shared", ids["重点难点"],
                    added_at="2026-09-21T11:30:00")
        out = Path(self._tmp.name) / "part.csv"
        with patch.object(self.dlg, "_ask_export_options",
                          return_value=([ids["重点难点"]], "csv")), \
             patch.object(self.QFileDialog, "getSaveFileName",
                          return_value=(str(out), "")):
            self.dlg._export_words()
        dst_db = Database(Path(self._tmp.name) / "dst.db")
        self.addCleanup(lambda: dst_db.conn().close())
        WordBook(dst_db).restore_rows(
            io.parse_rows(out.read_text(encoding="utf-8-sig")))
        tags = self._tags(dst_db)
        self.assertEqual(["重点难点"], [n for n, _ in tags["shared"]])
        self.assertEqual(["2026-09-21T11:30:00"],
                         [t for _, t in tags["shared"]])

    def test_所选分组没有词时不弹保存框(self):
        self.wb.add_group("空的")
        ids = {g.name: g.id for g in self.wb.groups()}
        with patch.object(self.dlg, "_ask_export_options",
                          return_value=([ids["空的"]], "csv")), \
             patch.object(self.QFileDialog, "getSaveFileName") as save, \
             patch.object(self.QMessageBox, "information") as info:
            self.dlg._export_words()
        info.assert_called_once()
        save.assert_not_called()


class ExportDialogTests(unittest.TestCase):
    """导出选项对话框本身的状态机（不进 exec 事件循环）。"""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:                 # pragma: no cover
            raise unittest.SkipTest(f"PySide6 不可用：{e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def _dlg(self, **kw):
        from tinydict.ui.export_dialog import ExportOptionsDialog
        return ExportOptionsDialog(
            [(1, "默认分组", 3), (2, "重点难点", 1), (3, "空的", 0)], **kw)

    def test_默认全部生词本_CSV_确定可用(self):
        d = self._dlg()
        self.assertTrue(d._chk_all.isChecked())
        self.assertTrue(d._list.isEnabled())      # 全选时列表仍可编辑（可取消单项）
        self.assertEqual("csv", d.format)
        self.assertTrue(d._ok_button.isEnabled())
        d.accept()
        self.assertIsNone(d.selected_group_ids)

    def test_选部分分组与JSON_accept后能读出结果(self):
        d = self._dlg()
        d.set_selection([2], "json")
        self.assertFalse(d._chk_all.isChecked())
        self.assertTrue(d._list.isEnabled())
        self.assertEqual("json", d.format)
        d.accept()
        self.assertEqual([2], d.selected_group_ids)

    def test_构造时直接指定选择与格式(self):
        d = self._dlg(group_ids=[1, 3], fmt="txt")
        self.assertEqual("txt", d.format)
        d.accept()
        self.assertEqual([1, 3], d.selected_group_ids)

    def test_没选任何分组时确定禁用(self):
        d = self._dlg()
        d.set_selection([], "txt")
        self.assertFalse(d._ok_button.isEnabled())
        d._check_all(True)
        self.assertTrue(d._ok_button.isEnabled())
        # 全选后「全部生词本」应自动勾上，导出即视为全部（None）
        self.assertTrue(d._chk_all.isChecked())
        d.accept()
        self.assertIsNone(d.selected_group_ids)

    def test_取消全部时保留列表现状_勾回全部时全勾(self):
        from PySide6.QtCore import Qt
        d = self._dlg()
        # 默认全部勾选、列表全勾且可编辑
        self.assertTrue(d._list.isEnabled())
        self.assertTrue(all(
            d._list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(d._list.count())))
        # 主动取消「全部」：保留列表现状（仍全勾），不再强制清空
        d._chk_all.setChecked(False)
        self.assertTrue(d._list.isEnabled())
        self.assertTrue(all(
            d._list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(d._list.count())))
        # 勾回「全部」：列表全勾
        d._chk_all.setChecked(True)
        self.assertTrue(all(
            d._list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(d._list.count())))

    def test_全部模式下取消单项_自动退出全部模式且单项生效(self):
        from PySide6.QtCore import Qt
        d = self._dlg()
        self.assertTrue(d._chk_all.isChecked())
        # 模拟用户在「全部」模式下取消「重点难点」(gid=2, index=1)
        target = d._list.item(1)
        self.assertEqual(2, target.data(Qt.ItemDataRole.UserRole))
        target.setCheckState(Qt.CheckState.Unchecked)   # 触发 itemChanged
        # 「全部」应自动取消，列表保留其它勾选
        self.assertFalse(d._chk_all.isChecked())
        self.assertEqual(Qt.CheckState.Unchecked, d._list.item(1).checkState())
        self.assertEqual(Qt.CheckState.Checked, d._list.item(0).checkState())
        self.assertEqual(Qt.CheckState.Checked, d._list.item(2).checkState())
        self.assertTrue(d._ok_button.isEnabled())
        # accept 后只导出选中的分组（不含被取消的 gid=2）
        d.accept()
        self.assertEqual([1, 3], d.selected_group_ids)

    def test_格式说明随选择变化(self):
        d = self._dlg()
        csv_hint = d._hint.text()
        d._radios["json"].setChecked(True)
        self.assertEqual("json", d.format)
        self.assertNotEqual(csv_hint, d._hint.text())

    def test_手动逐项勾满_自动勾上全部生词本(self):
        from PySide6.QtCore import Qt
        d = self._dlg()
        # 先取消「全部」，让列表进入可微调的显式选择状态（保留全勾）
        d._chk_all.setChecked(False)
        self.assertFalse(d._chk_all.isChecked())
        # 逐个取消后再逐个勾回，模拟用户手动操作
        for i in range(d._list.count()):
            d._list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(d._chk_all.isChecked())
        for i in range(d._list.count()):
            d._list.item(i).setCheckState(Qt.CheckState.Checked)
        # 全部单项勾满后，「全部生词本」应自动勾上
        self.assertTrue(d._chk_all.isChecked())
        self.assertTrue(all(
            d._list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(d._list.count())))
        # 取消其中一个后，「全部」自动退出
        d._list.item(0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(d._chk_all.isChecked())
        d.accept()
        self.assertEqual([2, 3], d.selected_group_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
