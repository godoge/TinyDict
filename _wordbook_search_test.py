"""生词本搜索回归测试。

``.venv/Scripts/python.exe _wordbook_search_test.py`` 即可运行（不需要真词库）。

分两层：
1. SearchDataTests  —— SQL 层：片段匹配 / 大小写 / 分组范围 / 字面通配符；
2. SearchUiTests    —— offscreen Qt：输入即时过滤、计数文案、回车查词、
   切换分组保留关键词、再次打开清空残留关键词、批量操作作用于筛选结果。

关键字是「字面片段」，% / _ / \\ 不能当 SQL 通配符用（否则搜 "%" 会列出全部词）。
"""

import os
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from tinydict.core.database import Database, DEFAULT_GROUP_ID
from tinydict.core.wordbook import ALL_GROUPS, WordBook

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WORDS = ["Apple", "apple pie", "pineapple", "Banana", "a_b", "100%", "back\\slash"]
IN_GROUP = ["Apple", "pineapple", "Banana"]


def _seed(wb: WordBook):
    g = wb.add_group("考研")
    for w in WORDS:
        wb.add(w)                       # 全部进默认分组
    for w in IN_GROUP:
        wb.add(w, g.id)                 # 其中几个也进「考研」
    return g


class _DbCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self._tmp = tmp
        self._db = Database(Path(tmp.name) / "wb.db")

        def cleanup():
            try:
                self._db.conn().close()
            except Exception:
                pass
            tmp.cleanup()

        self.addCleanup(cleanup)
        self.wb = WordBook(self._db)
        self.group = _seed(self.wb)

    def _words(self, gid=ALL_GROUPS, kw=""):
        return [w for w, _ in self.wb.words(gid, keyword=kw)]


class SearchDataTests(_DbCase):
    def test_空关键字返回全部且顺序不变(self):
        self.assertEqual(self._words(), self._words(kw="   "))
        self.assertEqual(len(self._words()), len(WORDS))

    def test_片段匹配且不区分大小写(self):
        self.assertEqual(set(self._words(kw="app")),
                         {"Apple", "apple pie", "pineapple"})
        self.assertEqual(set(self._words(kw="APP")),
                         {"Apple", "apple pie", "pineapple"})

    def test_首尾空格被忽略(self):
        self.assertEqual(self._words(kw="  Banana  "), ["Banana"])

    def test_搜不到时返回空(self):
        self.assertEqual(self._words(kw="zzzz"), [])

    def test_范围限定在当前分组(self):
        self.assertEqual(set(self._words(self.group.id, kw="app")),
                         {"Apple", "pineapple"})
        self.assertEqual(set(self._words(DEFAULT_GROUP_ID, kw="app")),
                         {"Apple", "apple pie", "pineapple"})
        # 「全部」与「默认分组」在当前数据下集合相同，但计数走的是不同表
        self.assertEqual(set(self._words(ALL_GROUPS, kw="app")),
                         {"Apple", "apple pie", "pineapple"})

    def test_百分号下划线反斜杠按字面匹配(self):
        # 若没转义，'%' 会匹配所有词、'_' 会匹配任意单字符，这里都会炸
        self.assertEqual(self._words(kw="%"), ["100%"])
        self.assertEqual(self._words(kw="_"), ["a_b"])
        self.assertEqual(self._words(kw="\\"), ["back\\slash"])
        self.assertEqual(self._words(kw="a_b"), ["a_b"])
        # 前缀片段 + 通配符混合
        self.assertEqual(self._words(kw="100%"), ["100%"])

    def test_中文片段也能匹配(self):
        self.wb.add("行政 管理")
        self.assertEqual(self._words(kw="行政"), ["行政 管理"])


class SearchUiTests(_DbCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:                       # pragma: no cover
            raise unittest.SkipTest(f"PySide6 不可用：{e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from tinydict.ui.wordbook_dialog import WordbookDialog
        self.dlg = WordbookDialog(self.wb)
        self.addCleanup(self.dlg.close)

    def _shown(self):
        return [self.dlg._word_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.dlg._word_list.count())]

    def test_默认无搜索词时列出全部(self):
        self.assertEqual(self.dlg._search.text(), "")
        self.assertEqual(len(self._shown()), len(WORDS))

    def test_输入即时过滤(self):
        self.dlg._search.setText("app")
        self.assertEqual(set(self._shown()),
                         {"Apple", "apple pie", "pineapple"})
        self.dlg._search.clear()
        self.assertEqual(len(self._shown()), len(WORDS))

    def test_计数行显示匹配数与总数(self):
        self.dlg._search.setText("app")
        label = self.dlg._count_label.text()
        self.assertIn("3", label)
        self.assertIn(str(len(WORDS)), label)
        self.assertIn("匹配", label)

    def test_无匹配时禁用加入分组按钮(self):
        self.dlg._search.setText("zzzz")
        self.assertEqual(self._shown(), [])
        self.assertFalse(self.dlg._btn_add_to.isEnabled())
        self.assertFalse(self.dlg._btn_delete.isEnabled())

    def test_回车查第一条匹配(self):
        seen = []
        self.dlg.lookupRequested.connect(seen.append)
        self.dlg._search.setText("banana")
        self.dlg._lookup_first()
        self.assertEqual(seen, ["Banana"])

    def test_清空按钮的提示说明范围不受搜索影响(self):
        self.dlg._search.setText("app")
        self.assertIn("不受上方搜索影响", self.dlg._btn_clear.toolTip())
        self.dlg._search.clear()
        self.assertEqual(self.dlg._btn_clear.toolTip(), "")

    def test_左栏切换分组保留关键词并按新分组过滤(self):
        self.dlg._search.setText("app")
        row = self.dlg._row_of_group(self.group.id)
        self.dlg._group_list.setCurrentRow(row)
        self.assertEqual(self.dlg._search.text(), "app")
        self.assertEqual(set(self._shown()), {"Apple", "pineapple"})

    def test_重新打开窗口会清掉上次的关键词(self):
        self.dlg._search.setText("app")
        self.dlg.select_group(ALL_GROUPS)      # 主窗口每次打开都走这个入口
        self.assertEqual(self.dlg._search.text(), "")
        self.assertEqual(len(self._shown()), len(WORDS))

    def test_搜索结果上做批量操作只影响选中的词(self):
        self.dlg._search.setText("app")
        for i in range(self.dlg._word_list.count()):
            item = self.dlg._word_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == "pineapple":
                item.setSelected(True)
        self.assertEqual(self.dlg._selected_words(), ["pineapple"])
        # 直接调底层删除路径（不弹确认框），验证作用范围就是筛选后的选中项
        self.wb.remove("pineapple")
        self.dlg.refresh()
        self.assertEqual(set(self._shown()), {"Apple", "apple pie"})
        self.assertNotIn("pineapple", self._words())


if __name__ == "__main__":
    unittest.main(verbosity=2)
