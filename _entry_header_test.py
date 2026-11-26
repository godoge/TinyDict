"""固定词条标题条回归测试（离屏运行）。

覆盖：启动隐藏 / 欢迎页不显示笔记面板 / 收录与未收录页共用标题 /
词汇工具栏收进词形右侧的圆角胶囊 / ★ 中性灰与金色、空心描边粗细 /
「显示笔记」勾选框与左侧圆点 / 面板开合与配置同步 / 标题条高度恒定 /
浅深主题 QSS / 自生成页面隐藏重复 HTML 标题 / 中英文文案。
"""
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFontMetrics, QIcon  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QSizePolicy, QToolButton, QHBoxLayout,
)

from tinydict import i18n  # noqa: E402
from tinydict.config import Config  # noqa: E402
from tinydict.core.database import Database  # noqa: E402
from tinydict.core.notes import Notes  # noqa: E402
from tinydict.core.query import EntryResult  # noqa: E402
from tinydict.ui import theme  # noqa: E402
from tinydict.ui import icons as iconmod  # noqa: E402
from tinydict.ui.icons import star_icon  # noqa: E402
from tinydict.ui.main_window import (  # noqa: E402
    MainWindow, _ENTRY_HEADER_HEIGHT, entry_page, not_found_page, welcome_page,
)


def ink_rgb(icon, size=20):
    """取图标里第一个满不透明像素的 RGB；全透明图标返回 None。"""
    img = icon.pixmap(size, size).toImage()
    for y in range(size):
        for x in range(size):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                return (c.red(), c.green(), c.blue())
    return None


def near(a, b, tol=10):
    return (a is not None and b is not None
            and all(abs(x - y) <= tol for x, y in zip(a, b)))


def hex_rgb(value):
    c = QColor(value)
    return (c.red(), c.green(), c.blue())


def dot_ink(win):
    """取勾选框左侧圆点控件的墨色；透明占位图返回 None。"""
    return ink_rgb(QIcon(win._note_dot.pixmap()), 10)


class StubService(QObject):
    mount_progress = Signal(int, int, str)
    dict_mounted = Signal(int)
    dict_mount_failed = Signal(int, str)
    mount_finished = Signal()

    def __init__(self):
        super().__init__()
        self.hits = []

    def suggest(self, q, limit=25):
        return []

    def lookup(self, word):
        return self.hits

    def find_resource(self, dict_id, path):
        return None

    def enabled_dicts(self):
        return []

    def is_mounted(self, _i):
        return True

    def mount_status(self, _i):
        return "ready"

    def mount_error(self, _i):
        return ""

    def all_dicts(self):
        return []

    def mount_count(self):
        return 0


class StubWordbook:
    def groups(self):
        return []

    def group_name(self, gid):
        return "默认分组"

    def has(self, w, g=None):
        return False

    def groups_of(self, w):
        return []

    def add(self, w, g=None):
        return False

    def remove_from_group(self, w, g, rehome=True):
        return False


class EntryHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        i18n.set_language("zh_CN")
        self.tmp = tempfile.mkdtemp(prefix="tdheader_")
        self.cfg = Config(os.path.join(self.tmp, "cfg.json"))
        self.notes = Notes(Database(":memory:"), "test-pc")
        self.svc = StubService()
        self.win = MainWindow(
            self.svc, self.cfg, StubWordbook(), notes=self.notes)
        self.win.show()
        self.app.processEvents()

    def tearDown(self):
        i18n.set_language("zh_CN")
        self.win.close()
        self.app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_启动时不显示标题条(self):
        self.assertFalse(self.win._entry_header.isVisible())
        self.assertEqual(self.win._entry_headword.text(), "")
        self.assertFalse(self.win._btn_star.isVisible())
        self.assertFalse(self.win._note_indicator_on)

    def test_启动欢迎页不显示笔记面板(self):
        """笔记挂在词条上：没进入词条时底部不该有空的笔记框。

        旧逻辑在 _build_ui 里直接按 notes_visible（默认 True）setVisible，
        欢迎页下就多出一个面板。现在配置值不动，进入词条后按它恢复。
        """
        panel = self.win._notes_panel
        splitter = self.win._notes_splitter
        self.assertEqual(self.win._current_word, "")
        self.assertTrue(bool(self.cfg["notes_visible"]))
        self.assertTrue(self.win._chk_notes.isChecked())
        self.assertFalse(panel.isVisibleTo(splitter))
        self.assertFalse(self.win._entry_header.isVisibleTo(self.win))

        self.win.do_lookup("Apple")
        self.app.processEvents()
        self.assertTrue(panel.isVisibleTo(splitter))
        self.assertGreater(panel.height(), 0)     # 不是只有几像素的残条
        self.assertTrue(bool(self.cfg["notes_visible"]))

        # 用户收起后切词不该又自动弹出来，配置仍然保留
        self.win._chk_notes.setChecked(False)
        self.app.processEvents()
        self.assertFalse(panel.isVisibleTo(splitter))
        self.win.do_lookup("Banana")
        self.app.processEvents()
        self.assertFalse(panel.isVisibleTo(splitter))
        self.assertFalse(bool(self.cfg["notes_visible"]))

        # 回到欢迎页（换肤/清空）时，即使配置为真也不挂空面板
        self.cfg["notes_visible"] = True
        self.win._chk_notes.setChecked(True)
        self.win._current_word = ""
        self.win._update_entry_header()
        self.app.processEvents()
        self.assertFalse(panel.isVisibleTo(splitter))
        self.assertTrue(bool(self.cfg["notes_visible"]))

    def test_词汇工具栏收进词形右侧的圆角胶囊(self):
        """标题条单行：词形在左，★ | 分隔线 | ● + 显示笔记收在右侧胶囊里。"""
        outer = self.win._entry_header.layout()
        self.assertIsInstance(outer, QHBoxLayout)
        tools = self.win._entry_tools_layout
        hw = self.win._entry_headword
        star = self.win._btn_star
        sep = self.win._entry_tool_sep
        grp = self.win._notes_group
        # 胶囊内顺序：★ → 分隔线 → 笔记组；三个控件一组，不留 spacer
        self.assertEqual(tools.indexOf(star), 0)
        self.assertEqual(tools.indexOf(sep), 1)
        self.assertEqual(tools.indexOf(grp), 2)
        self.assertEqual(tools.count(), 3)

        self.win.do_lookup("Apple")
        self.app.processEvents()
        h = self.win._entry_header
        host = self.win._entry_tools_host

        def in_header(widget):
            return widget.mapTo(h, widget.pos())

        # 胶囊与词形同一行、紧跟词形右侧（不是顶到最右端）
        self.assertLess(abs(host.y() - hw.y()), hw.height())
        self.assertGreaterEqual(in_header(star).x(), hw.x() + hw.width())
        self.assertGreater(h.width() - (host.x() + host.width()), 100)
        # 分隔线夹在收藏星与笔记组之间
        self.assertLess(in_header(star).x() + star.width(), in_header(sep).x())
        self.assertLess(in_header(sep).x() + sep.width(),
                        in_header(grp).x())
        self.assertGreaterEqual(
            hw.width(), QFontMetrics(hw.font()).horizontalAdvance("Apple"))

        # 长词封顶 + 右端省略，胶囊仍不被挤出标题条
        self.win.do_lookup("internationalization")
        self.app.processEvents()
        self.assertLessEqual(hw.width(), hw.MAX_WIDTH + 4)
        self.assertLessEqual(host.x() + host.width(), h.width())
        self.assertLess(abs(host.y() - hw.y()), hw.height())

        # 窗口收窄时优先压词形，工具栏保持完整可见
        self.win.resize(420, 620)
        self.app.processEvents()
        self.assertGreater(hw.width(), 0)
        self.assertLessEqual(host.x() + host.width(), h.width())
        self.assertGreaterEqual(star.height(), star.minimumSizeHint().height())

    def test_未收录页也有固定单词标题(self):
        self.win.do_lookup("zzzzword")
        self.app.processEvents()
        self.assertTrue(self.win._entry_header.isVisible())
        self.assertEqual(self.win._entry_headword.text(), "zzzzword")
        self.assertEqual(self.win._entry_headword.toolTip(), "zzzzword")
        self.assertTrue(self.win._btn_star.isVisible())
        self.assertIs(self.win._btn_star.menu(), self.win._star_menu)
        self.assertGreaterEqual(
            self.win._entry_tools_layout.indexOf(self.win._btn_star), 0)
        self.assertGreaterEqual(
            self.win._entry_tools_layout.indexOf(
                self.win._notes_group), 0)
        self.assertFalse(self.win._note_indicator_on)

    def test_收录页与多词典标签共用同一标题(self):
        self.svc.hits = [
            EntryResult(word="Apple", dict_id=1, dict_name="D1",
                        encoding="utf-8", definition=b"<b>apple</b>"),
            EntryResult(word="Apple", dict_id=2, dict_name="D2",
                        encoding="utf-8", definition=b"<b>apple2</b>"),
        ]
        self.win.do_lookup("Apple")
        self.app.processEvents()
        self.assertTrue(self.win._entry_header.isVisible())
        self.assertEqual(self.win._entry_headword.text(), "Apple")
        self.assertTrue(self.win._tabs.isVisible())
        self.assertTrue(self.win._btn_star.isVisible())

    def test_有笔记圆点跟随词条_草稿即时显示且不动checked(self):
        """圆点只做标识：checked 仍完全由用户控制面板显隐。"""
        btn = self.win._chk_notes
        checked = btn.isChecked()
        self.assertFalse(self.win._note_indicator_on)
        self.assertIsNone(dot_ink(self.win))          # 无笔记：圆点隐藏
        self.assertFalse(self.win._note_dot.isVisible())

        self.win.do_lookup("Apple")
        self.app.processEvents()
        # 无笔记时勾选框左对齐到组首，不留圆点空位
        grp = self.win._notes_group
        x_no_note = btn.x()
        self.assertFalse(self.win._note_dot.isVisible())
        self.assertLessEqual(abs(btn.x()), 4)   # 组内 x≈0（内容左边距 0）
        self.win._notes_editor.setPlainText("词根记忆")
        self.app.processEvents()
        self.assertTrue(self.win._note_indicator_on)
        self.assertTrue(self.win._note_dot.isVisible())
        self.assertIsNotNone(dot_ink(self.win))
        self.assertIn("已有笔记", btn.toolTip())
        self.assertIn("已有笔记", self.win._note_dot.toolTip())
        self.assertEqual(btn.isChecked(), checked)   # 有笔记不自动按下
        # 圆点出现后把勾选框右推，整组变宽
        self.assertGreater(btn.x(), x_no_note)
        self.assertGreater(self.win._notes_group.width(),
                           self.win._note_dot.width() + 4 + btn.width() - 1)

        self.win._flush_note()
        self.assertTrue(self.win._note_indicator_on)
        # 面板收起也保留圆点，checked 只跟着用户走
        btn.setChecked(not checked)
        self.app.processEvents()
        self.assertTrue(self.win._note_indicator_on)
        btn.setChecked(checked)
        self.app.processEvents()

        self.win.do_lookup("Banana")
        self.assertFalse(self.win._note_indicator_on)
        self.assertIsNone(dot_ink(self.win))
        self.notes.set("Banana", "例句")
        self.win._load_note("Banana")
        self.assertTrue(self.win._note_indicator_on)

        self.win._notes_editor.setPlainText("")
        self.win._flush_note()
        self.assertFalse(self.win._note_indicator_on)

    def test_笔记开关同步面板与配置(self):
        self.win.do_lookup("Apple")
        initial = bool(self.cfg["notes_visible"])
        self.assertEqual(self.win._chk_notes.isChecked(), initial)
        self.win._chk_notes.setChecked(not initial)
        self.app.processEvents()
        self.assertEqual(bool(self.cfg["notes_visible"]), not initial)
        self.assertEqual(
            self.win._notes_panel.isVisibleTo(self.win._notes_splitter),
            not initial)
        self.win._toggle_notes_panel(initial)
        self.assertEqual(self.win._chk_notes.isChecked(), initial)
        self.assertEqual(bool(self.cfg["notes_visible"]), initial)

    def test_自生成页面隐藏重复标题但保留词形(self):
        page = not_found_page("zzzzword", "light")
        self.assertIn("zzzzword", page)
        self.assertIn(".sd-headword{display:none;}", page)
        self.assertIn("标题右侧", page)
        self.assertIn("★", page)
        self.assertIn(".sd-headword{display:none;}",
                      entry_page("plain text", "Apple", "light"))
        self.assertNotIn(".sd-headword{display:none;}",
                         welcome_page("light"))

    def test_浅深主题都有标题条样式(self):
        for mode in ("light", "dark"):
            css = theme.app_qss(mode)
            for selector in (
                "QFrame#entry_header",
                "QLabel#entry_headword",
                "QFrame#entry_tools",
                "QFrame#entry_tool_sep",
                "QToolButton#entry_star_btn",
                "QLabel#entry_note_dot",
                "QCheckBox#entry_notes_cb",
                "QCheckBox#entry_notes_cb::indicator{width:15px;height:15px;}",
                "QCheckBox#entry_notes_cb:checked",
            ):
                self.assertIn(selector, css)
            # 笔记开关已是勾选框，旧的按钮样式与独立的有笔记标签都不该残留
            self.assertNotIn("QToolButton#entry_notes_btn", css)
            self.assertNotIn("QLabel#entry_note_badge", css)
            # indicator 规则只给尺寸；一旦覆盖 border/background，
            # QStyleSheetStyle 会把勾一起抹掉（离屏实测 V2~V5）。
            rule = css.split("QCheckBox#entry_notes_cb::indicator", 1)[1]
            rule = rule.split("}", 1)[0]
            self.assertNotIn("border", rule)
            self.assertNotIn("background", rule)
            # 控件背景必须与工具胶囊同色：写 transparent 会让 Qt 连方框
            # 边框一起透明化，勾选框只剩一个孤零零的勾（真实窗口实测）。
            block = css.split("QCheckBox#entry_notes_cb{", 1)[1]
            block = block.split("}", 1)[0]
            self.assertNotIn("transparent", block)
            self.assertIn("background:#f3f4f6" if mode == "light"
                          else "background:#2d2d30", block)
            capsule = css.split("QFrame#entry_tools{", 1)[1].split("}", 1)[0]
            self.assertIn("border-radius:16px", capsule)
            # 深色原生边框太暗，只补 unchecked 态；浅色不需要，
            # 两态都写 border 会把勾抹掉。
            if mode == "dark":
                self.assertIn(
                    "QCheckBox#entry_notes_cb::indicator:unchecked{", css)
            else:
                self.assertNotIn("::indicator:unchecked", css)

    def test_收藏星是矢量图标_空心透明且颜色随主题(self):
        """★/☆ 字体字形在 18px 下空心描边全是半透明像素，看着像锯齿；
        改用 QPainter 矢量路径后，空心内部保持透明，颜色按主题给出。"""
        self.win.do_lookup("Apple")
        self.app.processEvents()
        btn = self.win._btn_star
        self.assertFalse(self.win._star_filled)
        self.assertEqual(btn.text(), "")
        self.assertEqual(btn.toolButtonStyle(),
                         Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.assertFalse(btn.icon().isNull())

        light = QColor(theme.star_color("light"))
        dark = QColor(theme.star_color("dark"))
        self.assertNotEqual(light.name(), dark.name())
        self.assertNotEqual(light.name().lower(), "#ffffff")
        self.assertNotEqual(dark.name().lower(), "#ffffff")

        # 空心星中心透明 → 透出标题条背景（浅色白 / 深色深灰），不写死白底
        outline = star_icon(False, light).pixmap(20, 20).toImage()
        filled = star_icon(True, dark).pixmap(20, 20).toImage()
        self.assertEqual(outline.pixelColor(10, 10).alpha(), 0)
        self.assertGreater(filled.pixelColor(10, 10).alpha(), 0)

        ink_light = ink_rgb(star_icon(False, light))
        ink_dark = ink_rgb(star_icon(False, dark))
        self.assertIsNotNone(ink_light)
        self.assertNotEqual(ink_light, (255, 255, 255))
        self.assertNotEqual(ink_light, ink_dark)

        # 换主题时窗口会重画图标，而不是留着上一套主题的颜色。
        # 先把主题钉成 light（默认可能是跟随系统，本机解析为 dark）。
        self.cfg["theme"] = "light"
        self.win._refresh_nav_icons()
        before = ink_rgb(btn.icon())
        self.cfg["theme"] = "dark"
        self.win._refresh_nav_icons()
        after = ink_rgb(btn.icon())
        self.assertNotEqual(before, after)

    def test_未收藏星用中性黑白灰_收藏后仍是金色(self):
        """用户要求：未收藏改成黑白样式，收藏时保持原来的金色不变。"""
        light_gray = hex_rgb(theme.star_neutral_color("light"))
        dark_gray = hex_rgb(theme.star_neutral_color("dark"))
        gold_light = hex_rgb(theme.star_color("light"))
        gold_dark = hex_rgb(theme.star_color("dark"))
        self.assertNotEqual(light_gray, gold_light)
        self.assertNotEqual(dark_gray, gold_dark)
        self.assertNotEqual(light_gray, dark_gray)
        self.assertNotEqual(light_gray, (255, 255, 255))   # 不写死白色
        self.assertNotEqual(dark_gray, (255, 255, 255))

        self.cfg["theme"] = "light"
        self.win.do_lookup("Apple")
        self.app.processEvents()
        self.assertTrue(near(ink_rgb(self.win._btn_star.icon()), light_gray))
        self.assertFalse(near(ink_rgb(self.win._btn_star.icon()), gold_light))

        # 收藏后回到金色（同一个 star_icon 路径，只换颜色）
        self.win._star_filled = True
        self.win._apply_star_icon()
        self.assertTrue(near(ink_rgb(self.win._btn_star.icon()), gold_light))

        # 深色主题下未收藏换成近白灰，仍不是白色
        self.win._star_filled = False
        self.cfg["theme"] = "dark"
        self.win._refresh_nav_icons()
        self.assertTrue(near(ink_rgb(self.win._btn_star.icon()), dark_gray))

    def test_未收藏描边更细_已收藏线宽不变(self):
        """反馈：空心星 stroke 偏粗。只调空心，实心仍用 0.105 不动。"""
        self.assertLess(iconmod._STAR_STROKE_HOLLOW,
                        iconmod._STAR_STROKE_FILLED)
        self.assertEqual(iconmod._STAR_STROKE_FILLED, 0.105)

        def solid_pixels(img):
            return sum(
                1 for y in range(20) for x in range(20)
                if img.pixelColor(x, y).alpha() == 255)

        light = QColor(theme.star_neutral_color("light"))
        thin = star_icon(False, light).pixmap(20, 20).toImage()
        self.assertEqual(thin.pixelColor(10, 10).alpha(), 0)   # 仍是空心
        thin_solid = solid_pixels(thin)
        self.assertGreater(thin_solid, 0)   # 轮廓仍连续，没有全变半透明

        old = iconmod._STAR_STROKE_HOLLOW
        try:
            iconmod._STAR_STROKE_HOLLOW = iconmod._STAR_STROKE_FILLED
            thick_solid = solid_pixels(
                star_icon(False, light).pixmap(20, 20).toImage())
        finally:
            iconmod._STAR_STROKE_HOLLOW = old
        self.assertLess(thin_solid, thick_solid)

        # 实心星走另一条常量，改空心线宽不会连带改掉「已收藏」的观感
        gold = QColor(theme.star_color("light"))
        before = star_icon(True, gold).pixmap(20, 20).toImage()
        iconmod._STAR_STROKE_HOLLOW = 0.05
        try:
            after = star_icon(True, gold).pixmap(20, 20).toImage()
        finally:
            iconmod._STAR_STROKE_HOLLOW = old
        self.assertEqual(before, after)

    def test_笔记开关是勾选框且标签为显示笔记(self):
        cb = self.win._chk_notes
        self.assertIsInstance(cb, QCheckBox)
        self.assertNotIsInstance(cb, QToolButton)
        self.assertEqual(cb.text(), i18n._("显示笔记"))
        self.assertTrue(cb.isCheckable())
        # 圆点不再挂在 QCheckBox 的 icon 上，而是独立控件排在方框左边
        self.assertTrue(cb.icon().isNull())
        dot = self.win._note_dot
        self.assertEqual(dot.width(), 10)
        self.assertEqual(dot.height(), 10)
        group = self.win._notes_group
        glay = group.layout()
        self.assertEqual(glay.indexOf(dot), 0)
        self.assertEqual(glay.indexOf(cb), 1)
        # 整组在收藏星与分隔线之后，圆点在方框左侧（同组内 index 更小）
        lay = self.win._entry_tools_layout
        self.assertEqual(lay.indexOf(group),
                         lay.indexOf(self.win._btn_star) + 2)

    def test_笔记圆点颜色随主题且checked不受影响(self):
        self.cfg["theme"] = "light"
        self.win.do_lookup("Apple")
        self.win._notes_editor.setPlainText("词根记忆")
        self.app.processEvents()
        checked = self.win._chk_notes.isChecked()
        self.assertTrue(near(dot_ink(self.win),
                            hex_rgb(theme.note_dot_color("light"))))
        self.cfg["theme"] = "dark"
        self.win._refresh_nav_icons()
        self.assertTrue(near(dot_ink(self.win),
                            hex_rgb(theme.note_dot_color("dark"))))
        self.assertEqual(self.win._chk_notes.isChecked(), checked)

    def test_标题条高度恒定且按钮不被裁切(self):
        """收录 / 未收录 / 多词典标签 / 笔记开合 / 窗口缩放都不该撑高标题条。"""
        self.assertEqual(self.win._view.sizePolicy().verticalPolicy(),
                         QSizePolicy.Policy.Expanding)
        heights = []

        def record(tag):
            self.app.processEvents()
            heights.append((tag, self.win._entry_header.height()))

        self.win.do_lookup("zzzzword")
        record("未收录")
        self.svc.hits = [
            EntryResult(word="Apple", dict_id=1, dict_name="D1",
                        encoding="utf-8", definition=b"<b>apple</b>"),
        ]
        self.win.do_lookup("Apple")
        record("收录单词典")
        self.svc.hits = [
            EntryResult(word="Apple", dict_id=1, dict_name="D1",
                        encoding="utf-8", definition=b"<b>apple</b>"),
            EntryResult(word="Apple", dict_id=2, dict_name="D2",
                        encoding="utf-8", definition=b"<b>apple2</b>"),
        ]
        self.win.do_lookup("Apple")
        record("收录多词典带标签")
        self.win._chk_notes.setChecked(False)
        record("收起笔记面板")
        self.win._chk_notes.setChecked(True)
        record("展开笔记面板")
        self.win.resize(980, 400)
        record("缩窗口")
        self.assertEqual({h for _, h in heights}, {_ENTRY_HEADER_HEIGHT},
                         f"标题条高度出现跳变: {heights}")
        self.assertGreaterEqual(
            self.win._btn_star.height(),
            self.win._btn_star.minimumSizeHint().height())

    def test_中英文文案齐全(self):
        i18n.set_language("zh_CN")
        page = not_found_page("zzzzword", "light")
        self.assertIn("收藏", page)
        self.assertIn("标题右侧", page)
        i18n.set_language("en_US")
        self.assertEqual(i18n._("显示笔记"), "Show notes")
        self.assertNotEqual(
            i18n._("这个词条已有笔记；勾选「显示笔记」可展开查看"),
            "这个词条已有笔记；勾选「显示笔记」可展开查看")
        self.assertNotEqual(
            i18n._("显示 / 隐藏词条下方的笔记面板（笔记会自动保存）"),
            "显示 / 隐藏词条下方的笔记面板（笔记会自动保存）")
        page = not_found_page("zzzzword", "dark")
        self.assertIn("fixed title", page)
        self.assertIn("wordbook", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
