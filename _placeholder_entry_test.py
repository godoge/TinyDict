"""回归测试：候选列表必须始终保留「当前输入的词」这条自建词条。

背景：词库没收录的词不会出现在前缀联想里，用户点不到它，★ 收藏与
后续笔记就没有依附对象。因此 _refresh_suggestions 在联想结果没有同名
词条时，把输入词本身以斜体插到首位；点击 / 回车都要用 UserRole 里的
真词（历史条目的显示文本带时间后缀，不能拿去查词）。

用法：
    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe _placeholder_entry_test.py
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QObject
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QListWidgetItem

from tinydict import i18n
from tinydict.ui.main_window import (
    MainWindow, _VIRTUAL_ENTRY_ROLE, not_found_page,
)

_USER_ROLE = Qt.ItemDataRole.UserRole


class FakeService:
    """只实现候选列表用得到的 suggest（真实 service 需要挂载 MDX）。"""

    def __init__(self, words=()):
        self.words = list(words)

    def suggest(self, query, limit=30):
        q = (query or "").strip().lower()
        return [w for w in self.words if w.lower().startswith(q)][:limit]


class Harness(QObject):
    """把 MainWindow 的几个候选列表方法绑到轻量对象上，避开 WebEngine。"""

    _refresh_suggestions = MainWindow._refresh_suggestions
    _fill_recent_history = MainWindow._fill_recent_history
    _on_suggestion_clicked = MainWindow._on_suggestion_clicked
    _on_return = MainWindow._on_return
    _move_suggestion = MainWindow._move_suggestion

    def __init__(self, words=(), **config):
        super().__init__()
        self._service = FakeService(words)
        self.history = None
        self._config = {
            "history_enabled": False,
            "fill_input_on_select": False,
        }
        self._config.update(config)
        self.search_edit = QLineEdit()
        self.suggest_list = QListWidget()
        self.looked_up = []

    def do_lookup(self, word, push_history=True, sync_input=True,
                  preserve_tab=False):
        self.looked_up.append((word, sync_input))

    def type(self, text):
        self.search_edit.setText(text)
        self._refresh_suggestions()

    def texts(self):
        return [self.suggest_list.item(i).text()
                for i in range(self.suggest_list.count())]

    def virtual_flags(self):
        return [bool(self.suggest_list.item(i).data(_VIRTUAL_ENTRY_ROLE))
                for i in range(self.suggest_list.count())]

    def add_history_item(self, word, display):
        item = QListWidgetItem(display)
        item.setData(_USER_ROLE, word)
        self.suggest_list.addItem(item)
        return item


class PlaceholderEntryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._lang = i18n.get_language()

    @classmethod
    def tearDownClass(cls):
        i18n.set_language(cls._lang)

    def setUp(self):
        i18n.set_language("zh_CN")

    def test_空输入时不插入占位(self):
        h = Harness()
        h.type("")
        self.assertEqual(h.suggest_list.count(), 0)

    def test_词库完全没收录时首位是输入词(self):
        h = Harness()
        h.type("zzzzword")
        self.assertEqual(h.suggest_list.count(), 1)
        item = h.suggest_list.item(0)
        self.assertEqual(item.text(), "zzzzword")
        self.assertEqual(item.data(_USER_ROLE), "zzzzword")
        self.assertTrue(item.data(_VIRTUAL_ENTRY_ROLE))
        self.assertTrue(item.font().italic())
        self.assertIn("zzzzword", item.toolTip())

    def test_联想无精确匹配时占位在首位且联想词保留(self):
        h = Harness(["apple", "application"])
        h.type("app")
        self.assertEqual(h.texts(), ["app", "apple", "application"])
        self.assertEqual(h.virtual_flags(), [True, False, False])

    def test_联想含精确匹配时不重复插入(self):
        h = Harness(["apple", "apple pie"])
        h.type("apple")
        self.assertEqual(h.texts(), ["apple", "apple pie"])
        self.assertEqual(h.virtual_flags(), [False, False])

    def test_大小写不同也视为同名词条(self):
        h = Harness(["Apple"])
        h.type("apple")
        self.assertEqual(h.texts(), ["Apple"])
        self.assertEqual(h.virtual_flags(), [False])

    def test_词组同样会保留为占位词条(self):
        h = Harness(["stay away from"])
        h.type("stay away")
        self.assertEqual(h.texts()[0], "stay away")
        self.assertEqual(h.suggest_list.item(0).data(_USER_ROLE), "stay away")

    def test_点击占位条目会生成当前词条(self):
        h = Harness()
        h.type("newword")
        h._on_suggestion_clicked(h.suggest_list.item(0))
        self.assertEqual(h.looked_up, [("newword", False)])

    def test_回车选中占位条目取UserRole真词(self):
        h = Harness()
        h.type("newword")
        h.suggest_list.setCurrentRow(0)
        h._on_return()
        self.assertEqual(h.looked_up, [("newword", True)])

    def test_点击联想词仍然查联想词(self):
        h = Harness(["application"])
        h.type("app")
        h._on_suggestion_clicked(h.suggest_list.item(1))
        self.assertEqual(h.looked_up, [("application", False)])

    def test_回车选中历史条目不用带时间的显示文本(self):
        h = Harness()
        item = h.add_history_item("Apple", "Apple    （11-11 12:00）")
        h.search_edit.setText("Apple    （11-11 12:00）")
        h.suggest_list.setCurrentItem(item)
        h._on_return()
        self.assertEqual(h.looked_up, [("Apple", True)])

    def test_上下键填入搜索框也用真词(self):
        h = Harness(fill_input_on_select=True)
        h.add_history_item("Apple", "Apple    （11-11 12:00）")
        h._move_suggestion(1)
        self.assertEqual(h.search_edit.text(), "Apple")

    def test_未收录页中文提示可收藏(self):
        page = not_found_page("zzzzword", "light")
        self.assertIn("zzzzword", page)
        self.assertIn("★", page)
        self.assertIn("收藏", page)

    def test_未收录页英文提示可收藏(self):
        i18n.set_language("en_US")
        page = not_found_page("zzzzword", "dark")
        self.assertIn("★", page)
        self.assertIn("wordbook", page)

    def test_占位提示有英文译文(self):
        i18n.set_language("en_US")
        key = "「{}」在词库里没有对应词条，仍可作为当前词条收藏到生词本。"
        value = i18n._(key)
        self.assertNotEqual(value, key)
        self.assertIn("{}", value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
