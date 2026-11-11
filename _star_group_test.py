"""★ 收藏下拉的分组勾选回归测试。

``.venv/Scripts/python.exe _star_group_test.py`` 即可运行（offscreen Qt，不需真词库）。

背景：数据层有个不变量「每个生词至少属于一个分组」，移出最后一个非默认
分组时会自动归入默认分组。这对生词本窗口的「从本分组移除」是对的，但对
★ 下拉的「取消收藏」是错的——用户取消自建分组里的收藏后，词会莫名其妙
出现在默认分组里。修复方式是给移出操作加 rehome 开关：★ 下拉用
rehome=False（彻底删除），生词本窗口保持默认的 rehome=True。
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QLabel, QToolButton
from tinydict.core.database import Database, DEFAULT_GROUP_ID
from tinydict.core.wordbook import WordBook
from tinydict.ui.main_window import MainWindow, _StayOpenMenu


class _DbCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self._tmp = tmp
        self._db = Database(Path(tmp.name) / "star.db")

        def cleanup():
            try:
                self._db.conn().close()
            except Exception:
                pass
            tmp.cleanup()

        self.addCleanup(cleanup)
        self.wb = WordBook(self._db)
        self.group = self.wb.add_group("考研")

    def _groups(self, word):
        return self.wb.groups_of(word)

    def _in_default(self, word):
        return self.wb.has(word, DEFAULT_GROUP_ID)

    def _rows(self):
        return [r[0] for r in self._db.conn().execute(
            "SELECT word FROM wordbook")]


class RehomeSwitchTests(_DbCase):
    """数据层：rehome 开关的行为。"""

    def test_默认_rehomeTrue_移出最后一个非默认分组会归入默认分组(self):
        self.wb.add("Apple", self.group.id)
        self.wb.remove_from_group("Apple", self.group.id)   # 生词本窗口语义
        self.assertEqual(self._groups("Apple"), ["默认分组"])
        self.assertTrue(self._in_default("Apple"))

    def test_rehomeFalse_移出最后一个非默认分组会彻底删除(self):
        self.wb.add("Apple", self.group.id)
        self.wb.remove_from_group("Apple", self.group.id, rehome=False)
        self.assertEqual(self._groups("Apple"), [])
        self.assertFalse(self._in_default("Apple"))
        self.assertFalse(self.wb.has("Apple"))
        self.assertEqual(self._rows(), [])

    def test_rehomeFalse_移出默认分组也彻底删除(self):
        self.wb.add("Apple", DEFAULT_GROUP_ID)
        self.wb.remove_from_group("Apple", DEFAULT_GROUP_ID, rehome=False)
        self.assertFalse(self.wb.has("Apple"))

    def test_rehomeFalse_还有其它分组时只解除该分组(self):
        self.wb.add("Apple", DEFAULT_GROUP_ID)
        self.wb.add("Apple", self.group.id)
        self.wb.remove_from_group("Apple", self.group.id, rehome=False)
        self.assertEqual(self._groups("Apple"), ["默认分组"])
        # 再取消剩下的最后一个分组 → 彻底删除，不再兜底归回默认分组
        self.wb.remove_from_group("Apple", DEFAULT_GROUP_ID, rehome=False)
        self.assertEqual(self._groups("Apple"), [])
        self.assertFalse(self.wb.has("Apple"))
        self.assertEqual(self._rows(), [])

    def test_依次取消全部分组后不会出现在默认分组(self):
        g2 = self.wb.add_group("雅思")
        self.wb.add("Apple", DEFAULT_GROUP_ID)
        self.wb.add("Apple", self.group.id)
        self.wb.add("Apple", g2.id)
        for gid in (DEFAULT_GROUP_ID, self.group.id, g2.id):
            self.wb.remove_from_group("Apple", gid, rehome=False)
        self.assertFalse(self.wb.has("Apple"))
        self.assertEqual(self._rows(), [])


class StarMenuTests(_DbCase):
    """UI 层：把 MainWindow 的真实方法绑到轻量 harness 上跑完整点击序列。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()

        class Harness(QObject):
            wordbook_changed = Signal()
            _build_star_menu = MainWindow._build_star_menu
            _on_star_group = MainWindow._on_star_group
            _update_star = MainWindow._update_star
            _reload_groups = MainWindow._reload_groups

            def __init__(self, wb, word):
                super().__init__()
                self.wordbook, self._current_word = wb, word
                self._status_info = QLabel()
                self._btn_star = QToolButton(text="star")
                self._star_menu = _StayOpenMenu(self._btn_star)
                self._btn_star.setMenu(self._star_menu)
                self._star_menu.aboutToShow.connect(self._build_star_menu)
                self.wordbook_changed.connect(self._reload_groups)

            def _create_group(self):
                pass

        self.h = Harness(self.wb, "Apple")
        self.addCleanup(self.h._star_menu.hide)
        self._open_menu()

    def _open_menu(self):
        self.h._star_menu.popup(
            self.h._btn_star.mapToGlobal(self.h._btn_star.rect().bottomLeft()))
        self.app.processEvents()

    def _actions(self):
        return [a for a in self.h._star_menu.actions() if a.isCheckable()]

    def _click_group(self, gid):
        """模拟 _StayOpenMenu.mouseReleaseEvent 里的 action.trigger()（真实点击已验证等价）。"""
        for act, g in zip(self._actions(), self.wb.groups()):
            if g.id == gid:
                act.trigger()
                self.app.processEvents()
                return
        self.fail(f"菜单里找不到分组 id={gid}")

    def _checked_after_reopen(self):
        self.h._star_menu.hide()
        self.app.processEvents()
        self._open_menu()
        return [(g.name, a.isChecked(), self.wb.has("Apple", g.id))
                for a, g in zip(self._actions(), self.wb.groups())]

    def test_加入自建分组再取消_重新打开不会出现在默认分组(self):
        """用户报的场景：从自建分组取消收藏，词跑到默认分组。"""
        self._click_group(self.group.id)          # 勾「考研」（唯一分组）
        self.assertEqual(self._groups("Apple"), ["考研"])
        self._click_group(self.group.id)          # 取消「考研」
        self.assertFalse(self.wb.has("Apple"))
        state = self._checked_after_reopen()
        self.assertEqual(state, [("默认分组", False, False),
                                 ("考研", False, False)])
        self.assertEqual(self.h._btn_star.text(), "☆")

    def test_先默认再自建_取消默认分组后只剩自建分组(self):
        self.wb.add("Apple", DEFAULT_GROUP_ID)
        self._open_menu()                        # 重建，带上默认分组的勾选
        self._click_group(self.group.id)
        self._click_group(DEFAULT_GROUP_ID)
        self.assertEqual(self._groups("Apple"), ["考研"])
        self.assertFalse(self._in_default("Apple"))

    def test_多分组时取消一个_其余分组不受影响(self):
        g2 = self.wb.add_group("雅思")
        self.wb.add("Apple", DEFAULT_GROUP_ID)
        self._open_menu()
        self._click_group(self.group.id)
        self._click_group(g2.id)
        self._click_group(DEFAULT_GROUP_ID)
        self.assertEqual(self._groups("Apple"), ["考研", "雅思"])
        self.assertIn("已从", self.h._status_info.text())

    def test_取消最后一个分组时状态栏提示彻底取消收藏(self):
        self._click_group(self.group.id)
        self._click_group(self.group.id)
        self.assertIn("已取消收藏", self.h._status_info.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
