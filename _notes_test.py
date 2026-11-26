"""词条笔记回归测试：数据层 / 交换格式 / 三路合并 / 双端冲突。

跑法：.venv/Scripts/python.exe _notes_test.py
（单独进程跑，避免和其它 QApplication 测试脚本抢单例。）
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tinydict.core import note_io
from tinydict.core.database import Database
from tinydict.core.notes import (
    Notes, NoteRecord, STRATEGY_KEEP_LOCAL, STRATEGY_MERGE,
    STRATEGY_OVERWRITE, normalize_key, now_iso,
)
from tinydict.core.wordbook_io import parse_backup as parse_wordbook_backup


def rec(word, body, **kw):
    return NoteRecord(word=word, body=body, **kw)


class NormalizeTest(unittest.TestCase):
    def test_大小写全角与空白折叠(self):
        self.assertEqual(normalize_key("Apple"), "apple")
        self.assertEqual(normalize_key("  APPLE  "), "apple")
        self.assertEqual(normalize_key("Ａｐｐｌｅ"), "apple")
        self.assertEqual(normalize_key("stay   away"), "stay away")
        self.assertEqual(normalize_key(""), "")

    def test_时间戳是秒级无时区(self):
        stamp = now_iso()
        self.assertEqual(len(stamp), 19)
        self.assertIn("T", stamp)
        self.assertNotIn("+", stamp)


class NotesCrudTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.notes = Notes(self.db, "pc-test")

    def tearDown(self):
        try:
            self.db.conn().close()
        except Exception:
            pass

    def test_写入读取与大小写不敏感(self):
        self.notes.set("Apple", "一条笔记")
        self.assertEqual(self.notes.body("apple"), "一条笔记")
        self.assertEqual(self.notes.body("Ａｐｐｌｅ"), "一条笔记")
        self.assertEqual(self.notes.get("Apple").revision, 1)
        self.assertEqual(self.notes.get("Apple").device_id, "pc-test")

    def test_同内容重写不增加版本(self):
        self.notes.set("Apple", "内容")
        self.notes.set("apple", "内容")
        self.assertEqual(self.notes.get("Apple").revision, 1)
        self.notes.set("apple", "改了")
        self.assertEqual(self.notes.get("Apple").revision, 2)
        self.assertEqual(self.notes.get("Apple").word, "apple")

    def test_清空内容写成墓碑(self):
        self.notes.set("Apple", "内容")
        self.notes.set("apple", "")
        note = self.notes.get("Apple")
        self.assertEqual(note.deleted, 1)
        self.assertEqual(note.body, "")
        self.assertEqual(self.notes.body("Apple"), "")
        self.assertEqual(self.notes.stats()["tombstones"], 1)

    def test_删除后重新写入可复活(self):
        self.notes.set("Apple", "旧内容")
        self.notes.delete("apple")
        self.notes.set("Apple", "新内容")
        note = self.notes.get("Apple")
        self.assertEqual(note.body, "新内容")
        self.assertEqual(note.deleted, 0)
        self.assertEqual(note.revision, 3)

    def test_搜索按字面匹配且通配符转义(self):
        self.notes.set("100%", "百分比")
        self.notes.set("a_b", "下划线")
        self.notes.set("normal", "普通")
        self.assertEqual([n.word for n in self.notes.search("%")], ["100%"])
        self.assertEqual([n.word for n in self.notes.search("_")], ["a_b"])
        self.assertEqual(len(self.notes.search("普通")), 1)

    def test_统计包含墓碑与冲突(self):
        self.notes.set("a", "x")
        self.notes.set("b", "y")
        self.notes.delete("b")
        st = self.notes.stats()
        self.assertEqual(st["notes"], 1)
        self.assertEqual(st["tombstones"], 1)
        self.assertEqual(st["conflicts"], 0)


class NoteIoTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.notes = Notes(self.db, "pc-aaa")
        self.notes.set("Apple", "第一行\n第二行")
        self.notes.set("quantumxyz", "词库没收录")
        self.notes.set("gone", "删掉的", )
        self.notes.delete("gone")
        self.rows = self.notes.all(include_deleted=True)

    def tearDown(self):
        try:
            self.db.conn().close()
        except Exception:
            pass

    def _words(self, records):
        return sorted((r.word, r.body, r.deleted) for r in records)

    def test_json_往返保留墓碑与元数据(self):
        text = note_io.dump_json(self.rows, "pc-aaa", "2026-11-26T16:00:00")
        records, device, exported = note_io.parse_notes(text, "n.json")
        self.assertEqual(device, "pc-aaa")
        self.assertEqual(exported, "2026-11-26T16:00:00")
        self.assertEqual(self._words(records), self._words(
            [rec(n.word, n.body, deleted=n.deleted) for n in self.rows]))
        self.assertTrue(all(r.device_id == "pc-aaa" for r in records))

    def test_csv_往返正文换行不错位(self):
        text = note_io.dump_csv(self.rows)
        records, _, _ = note_io.parse_notes(text, "n.csv")
        by_word = {r.word: r.body for r in records}
        self.assertEqual(by_word["Apple"], "第一行\n第二行")
        self.assertTrue(next(r for r in records if r.word == "gone").deleted)

    def test_手机版备份_version_恒为1且旧解析器能读(self):
        text = note_io.dump_wordbook_json(
            self.rows, "2026-11-26T16:00:00", added_at="2026-11-26T16:00:00")
        data = json.loads(text)
        self.assertEqual(data["type"], "tinydict-wordbook")
        self.assertEqual(data["version"], 1)
        self.assertIn("note", data["words"][0])
        # 旧版 Android/PC 的解析器只认四个字段，未知字段必须能安全忽略
        payload = parse_wordbook_backup(text)
        self.assertEqual(len(payload["words"]), 3)
        records, _, _ = note_io.parse_notes(text, "wb.json")
        self.assertEqual(len(records), 3)

    def test_手机版CSV_前三列顺序不变(self):
        text = note_io.dump_wordbook_csv(self.rows, added_at="2026-11-26T16:00:00")
        header = text.splitlines()[0]
        self.assertTrue(header.startswith("word,groups,added_at,group_added_at,"))
        records, _, _ = note_io.parse_notes(text, "wb.csv")
        self.assertEqual(len(records), 3)

    def test_生词本备份里没有笔记的词被跳过(self):
        payload = {
            "app": "TinyDict", "type": "tinydict-wordbook", "version": 1,
            "groups": ["默认分组"],
            "words": [
                {"word": "a", "groups": ["默认分组"], "added_at": ""},
                {"word": "b", "groups": [], "added_at": "", "note": "有笔记"},
            ],
        }
        records, _, _ = note_io.parse_notes(json.dumps(payload), "w.json")
        self.assertEqual([r.word for r in records], ["b"])

    def test_宽容解析_字段别名与简写(self):
        payload = {"notes": [
            {"headword": "X", "content": "内容", "modified_at": "2026-11-26 16:00:00",
             "device": "phone-1", "rev": 4},
            "Y",
        ]}
        records, _, _ = note_io.parse_notes(json.dumps(payload), "x.json")
        self.assertEqual(records[0].word, "X")
        self.assertEqual(records[0].body, "内容")
        self.assertEqual(records[0].updated_at, "2026-11-26T16:00:00")
        self.assertEqual(records[0].device_id, "phone-1")
        self.assertEqual(records[0].revision, 4)
        # "Y" 是词表简写、没有笔记正文：必须跳过，不能凭空造一条空笔记
        self.assertEqual(len(records), 1)

    def test_纯数组与字符串数组简写(self):
        records, _, _ = note_io.parse_notes(
            json.dumps([{"word": "A", "note": "内容"}]), "x.json")
        self.assertEqual(records[0].word, "A")

    def test_缺时间戳用导出时间兜底(self):
        payload = {"type": "tinydict-notes", "version": 1,
                   "device_id": "phone-9", "exported_at": "2026-11-26T10:00:00",
                   "notes": [{"word": "A", "note": "内容"}]}
        records, dev, _ = note_io.parse_notes(json.dumps(payload), "x.json")
        self.assertEqual(records[0].updated_at, "2026-11-26T10:00:00")
        self.assertEqual(records[0].device_id, "phone-9")

    def test_坏输入全部抛ValueError(self):
        cases = [
            ("", "e.json"), ("not json", "e.json"),
            (json.dumps({"type": "tinydict-notes", "version": 99, "notes": []}), "e.json"),
            (json.dumps({"type": "tinydict-notes", "version": "1", "notes": []}), "e.json"),
            (json.dumps({"type": "tinydict-notes", "version": 1}), "e.json"),
            (json.dumps({"type": "别的类型", "version": 1, "notes": []}), "e.json"),
            ("word,groups\nA,B\n", "e.csv"),
            ("随便一行文本", "e.txt"),
        ]
        for text, path in cases:
            with self.subTest(path=path, text=text[:24]):
                with self.assertRaises(ValueError):
                    note_io.parse_notes(text, path)

    def test_is_notes_file_分流(self):
        self.assertTrue(note_io.is_notes_file(note_io.dump_json(self.rows, "d")))
        self.assertFalse(note_io.is_notes_file("apple\nbanana\n"))

    def test_mdx_导出并能被本项目读回(self):
        from tinydict.core.mdx_access import LazyMDX
        work = Path(tempfile.mkdtemp(prefix="td_notes_mdx_"))
        path = work / "notes.mdx"
        note_io.dump_mdx(
            [n for n in self.rows if not n.deleted and n.body], str(path))
        self.assertTrue(path.exists() and path.stat().st_size > 0)
        mdx = LazyMDX(str(path), cache_dir=str(work / "cache"))
        hit = mdx.lookup("quantumxyz")
        self.assertTrue(hit and b"\xe8\xaf\x8d\xe5\xba\x93" in hit[1])

    def test_mdx_没有可导出笔记时抛错(self):
        with self.assertRaises(ValueError):
            note_io.dump_mdx([], str(Path(tempfile.gettempdir()) / "x.mdx"))


class ThreeWayMergeTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.notes = Notes(self.db, "pc-local")

    def tearDown(self):
        try:
            self.db.conn().close()
        except Exception:
            pass

    def test_只有对端改过_自动采用(self):
        self.notes.set("Apple", "基线")
        self.notes.mark_synced("phone-1")
        report = self.notes.merge(
            [rec("Apple", "手机改的", updated_at="2026-11-26T17:00:00",
                 device_id="phone-1", revision=2)], peer_id="phone-1")
        self.assertEqual(report.updated, 1)
        self.assertEqual(self.notes.body("Apple"), "手机改的")
        self.assertEqual(self.notes.stats()["conflicts"], 0)

    def test_只有本机改过_保留本机(self):
        self.notes.set("Apple", "基线")
        self.notes.mark_synced("phone-1")
        self.notes.set("Apple", "电脑改的")
        report = self.notes.merge(
            [rec("Apple", "基线", updated_at="2026-11-26T16:00:00",
                 device_id="phone-1")], peer_id="phone-1")
        self.assertEqual(report.unchanged, 1)
        self.assertEqual(self.notes.body("Apple"), "电脑改的")

    def test_两端都改_保留本机并留痕(self):
        self.notes.set("Apple", "基线")
        self.notes.mark_synced("phone-1")
        self.notes.set("Apple", "电脑改的")
        report = self.notes.merge(
            [rec("Apple", "手机也改了", updated_at="2026-11-26T17:00:00",
                 device_id="phone-1", revision=2)], peer_id="phone-1")
        self.assertEqual(len(report.conflicts), 1)
        self.assertEqual(self.notes.body("Apple"), "电脑改的")
        conflict = self.notes.conflicts()[0]
        self.assertEqual(conflict.local_body, "电脑改的")
        self.assertEqual(conflict.remote_body, "手机也改了")
        self.assertEqual(conflict.peer_id, "phone-1")

    def test_重复导入同一文件不误覆盖且冲突不重复(self):
        self.notes.set("Apple", "基线")
        self.notes.mark_synced("phone-1")
        self.notes.set("Apple", "电脑改的")
        incoming = [rec("Apple", "手机也改了", device_id="phone-1", revision=2)]
        self.notes.merge(incoming, peer_id="phone-1")
        second = self.notes.merge(incoming, peer_id="phone-1")
        self.assertEqual(len(second.conflicts), 1)
        self.assertEqual(len(self.notes.conflicts()), 1)
        self.assertEqual(self.notes.body("Apple"), "电脑改的")

    def test_冲突解决_三种选择(self):
        for choice, expected in (
                ("keep_local", "电脑改的"),
                ("take_remote", "手机也改了"),
                ("merged", "合并结果")):
            with self.subTest(choice=choice):
                db = Database(":memory:")
                n = Notes(db, "pc-local")
                n.set("Apple", "基线")
                n.mark_synced("phone-1")
                n.set("Apple", "电脑改的")
                n.merge([rec("Apple", "手机也改了", device_id="phone-1")],
                        peer_id="phone-1")
                cid = n.conflicts()[0].id
                self.assertTrue(n.resolve_conflict(cid, choice, "合并结果"))
                self.assertEqual(n.body("Apple"), expected)
                self.assertEqual(len(n.conflicts()), 0)
                # 处理完基线必须推进，否则同一文件再导入还会报冲突
                again = n.merge([rec("Apple", "手机也改了",
                                     device_id="phone-1")], peer_id="phone-1")
                self.assertEqual(again.conflicts, [])
                db.conn().close()

    def test_删除同步_墓碑不会被旧备份复活(self):
        self.notes.set("Apple", "基线")
        self.notes.mark_synced("phone-1")
        report = self.notes.merge(
            [rec("Apple", "", deleted=1, device_id="phone-1",
                 updated_at="2026-11-26T17:00:00")], peer_id="phone-1")
        self.assertEqual(report.deleted, 1)
        self.assertTrue(self.notes.get("Apple").deleted)
        # 再导入一份更早的、还带着内容的备份：本地已删除，应判为冲突而不是复活
        report2 = self.notes.merge(
            [rec("Apple", "基线", device_id="phone-1")], peer_id="phone-1")
        self.assertEqual(report2.conflicts, ["Apple"])

    def test_keep_local_只补本地没有的(self):
        self.notes.set("Apple", "本机内容")
        report = self.notes.merge(
            [rec("Apple", "文件内容"), rec("Banana", "新增")],
            strategy=STRATEGY_KEEP_LOCAL)
        self.assertEqual(self.notes.body("Apple"), "本机内容")
        self.assertEqual(self.notes.body("Banana"), "新增")
        self.assertEqual(report.added, 1)

    def test_overwrite_无条件覆盖(self):
        self.notes.set("Apple", "本机内容")
        self.notes.mark_synced("phone-1")
        self.notes.set("Apple", "本机又改了")
        report = self.notes.merge([rec("Apple", "文件内容")],
                                  strategy=STRATEGY_OVERWRITE)
        self.assertEqual(self.notes.body("Apple"), "文件内容")
        self.assertEqual(report.conflicts, [])

    def test_同文件重复词取较新的一条(self):
        report = self.notes.merge([
            rec("Apple", "旧", updated_at="2026-11-26T10:00:00", revision=1),
            rec("Apple", "新", updated_at="2026-11-26T12:00:00", revision=2),
        ])
        self.assertEqual(self.notes.body("Apple"), "新")
        self.assertEqual(report.added, 1)

    def test_导入保留对端时间与设备不被改写(self):
        self.notes.merge([rec("Apple", "手机写的",
                              updated_at="2026-11-26T09:00:00",
                              device_id="phone-7", revision=5)])
        note = self.notes.get("Apple")
        self.assertEqual(note.updated_at, "2026-11-26T09:00:00")
        self.assertEqual(note.device_id, "phone-7")
        self.assertEqual(note.revision, 5)

    def test_未收录词也能笔记并参与同步(self):
        self.notes.set("quantumxyz", "自己写的")
        text = note_io.dump_json(self.notes.all(), "pc-local")
        db2 = Database(":memory:")
        other = Notes(db2, "phone-1")
        report = other.merge(note_io.parse_notes(text)[0], peer_id="pc-local")
        self.assertEqual(report.added, 1)
        self.assertEqual(other.body("quantumxyz"), "自己写的")
        db2.conn().close()

    def test_导出推进基线后本机再改会被正确判定(self):
        """完整双端链路：导出 → 两端各自修改 → 回传，必须判为冲突。"""
        self.notes.set("Apple", "共识内容")
        text = note_io.dump_json(self.notes.all(), "pc-local",
                                 "2026-11-26T10:00:00")
        self.notes.mark_synced("phone-1")

        # 手机端基于这份导出独立修改
        db2 = Database(":memory:")
        phone = Notes(db2, "phone-1")
        phone.merge(note_io.parse_notes(text)[0], peer_id="pc-local")
        phone.set("Apple", "手机改的")
        phone_text = note_io.dump_json(phone.all(), "phone-1",
                                       "2026-11-26T11:00:00")

        # 电脑端在同一份基线上也改了
        self.notes.set("Apple", "电脑改的")
        report = self.notes.merge(note_io.parse_notes(phone_text)[0],
                                  peer_id="phone-1")
        self.assertEqual(report.conflicts, ["Apple"])
        self.assertEqual(self.notes.body("Apple"), "电脑改的")
        self.assertEqual(self.notes.conflicts()[0].remote_body, "手机改的")
        db2.conn().close()

    def test_手机没改只做回传时采用电脑的修改(self):
        self.notes.set("Apple", "共识内容")
        text = note_io.dump_json(self.notes.all(), "pc-local")
        self.notes.mark_synced("phone-1")
        self.notes.set("Apple", "电脑改的")
        report = self.notes.merge(note_io.parse_notes(text)[0],
                                  peer_id="phone-1")
        self.assertEqual(report.conflicts, [])
        self.assertEqual(self.notes.body("Apple"), "电脑改的")


if __name__ == "__main__":
    unittest.main(verbosity=2)
