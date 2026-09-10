"""查询历史回归测试（离屏运行）。

覆盖：记录 / 去重与次数累加 / 大小写不敏感 / 上限裁剪 / 关键字过滤 /
删除 / 清空 / 搜索框空态填充 / 历史对话框列表与信号。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QListWidgetItem,
)
from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402

from tinydict.core.database import Database  # noqa: E402
from tinydict.core.history import (  # noqa: E402
    HistoryBook, display_text, format_time,
)
from tinydict.config import Config  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {extra}" if extra else ""))


def main():
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    tmp = tempfile.mkdtemp(prefix="tdhist_")
    db = Database(os.path.join(tmp, "t.db"))
    hb = HistoryBook(db, limit=5)
    cfg = Config(os.path.join(tmp, "cfg.json"))

    print("== 存储层 ==")
    check("初始为空", hb.count() == 0)
    hb.record("hello")
    check("记录后 count=1", hb.count() == 1, f"count={hb.count()}")
    hb.record("hello")
    check("同词去重（仍 1 条）", hb.count() == 1)
    rows = hb.recent()
    check("次数累加为 2", rows[0][2] == 2, f"times={rows[0][2]}")
    hb.record("Hello")
    check("大小写不敏感去重", hb.count() == 1, f"count={hb.count()}")
    hb.record("world")
    check("不同词新增", hb.count() == 2)

    for w in ("alpha", "beta", "gamma", "delta"):
        hb.record(w)
    check("超出上限自动裁剪到 5", hb.count() == 5, f"count={hb.count()}")
    words = [w for w, _t, _n in hb.recent()]
    check("裁剪淘汰最久未查的 hello", "hello" not in words, f"words={words}")

    hb.record("zebra")
    top = hb.recent()[0][0]
    check("最近查询排在最前", top == "zebra", f"top={top}")
    check("关键字过滤命中", [w for w, _t, _n in hb.recent(keyword="zeb")] == ["zebra"])
    check("关键字过滤无结果", hb.recent(keyword="qqqq") == [])

    print("== 时间格式 ==")
    from datetime import datetime, timedelta
    now = datetime.now()
    check("今天", format_time(now.isoformat(timespec="seconds")).startswith("今天"),
          format_time(now.isoformat(timespec="seconds")))
    y = (now - timedelta(days=1)).isoformat(timespec="seconds")
    check("昨天", format_time(y).startswith("昨天"), format_time(y))
    check("非法时间原样返回", format_time("not-a-time") == "not-a-time")
    check("显示文本含词与时间", display_text("hello", now.isoformat(timespec="seconds"),
                                             3).startswith("hello"))

    print("== 删除 / 清空 ==")
    check("删除命中返回 True", hb.remove("zebra"))
    check("删除后不在列表", "zebra" not in [w for w, _t, _n in hb.recent()])
    hb.clear()
    check("清空后 count=0", hb.count() == 0)

    print("== 主窗口接线 ==")
    from tinydict.ui.main_window import MainWindow

    class StubService(QObject):
        mount_progress = Signal(int, int, str)
        dict_mounted = Signal(int)
        dict_mount_failed = Signal(int, str)
        mount_finished = Signal()

        def __init__(self):
            super().__init__()
            self.calls = []
            self.hits = []        # 测试里直接指定 lookup 的返回值

        def suggest(self, q, limit=25):
            self.calls.append(q)
            return ["suggest_" + q]

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

        def remove_from_group(self, w, g):
            return False

    svc = StubService()
    win = MainWindow(svc, cfg, StubWordbook(), history=hb)
    check("窗口拿到 history", win.history is hb)

    # 无结果时不记录（lookup 返回 [] 且无 pending）
    win.do_lookup("nothing-here")
    check("未命中不记历史", hb.count() == 0, f"count={hb.count()}")

    # 有结果时记录
    from tinydict.core.query import EntryResult
    svc.hits = [EntryResult(word="ok", dict_id=1, dict_name="D",
                            encoding="utf-8", definition=b"<b>ok</b>")]
    win.do_lookup("ok")
    check("命中时记入历史", hb.count() == 1, f"count={hb.count()}")

    # 搜索框为空 → 候选列表展示历史
    win.search_edit.setText("")
    win._refresh_suggestions()
    check("空输入时显示历史", win.suggest_list.count() == 1,
          f"count={win.suggest_list.count()}")
    item = win.suggest_list.item(0)
    check("历史项 UserRole 存真词",
          item.data(Qt.ItemDataRole.UserRole) == "ok",
          f"data={item.data(Qt.ItemDataRole.UserRole)!r} text={item.text()!r}")

    # 点击历史项 → 用真词查词（不能把带时间的显示文本当词）
    got = []
    orig_lookup = win.do_lookup
    win.do_lookup = lambda w, **kw: got.append(w)
    win._on_suggestion_clicked(item)
    win.do_lookup = orig_lookup
    check("点击历史项取到真词", got == ["ok"], f"got={got}")

    # 有输入时走词库建议，不显示历史
    win.search_edit.setText("ze")
    win._refresh_suggestions()
    check("有输入时走词库建议", win.suggest_list.count() == 1
          and win.suggest_list.item(0).text() == "suggest_ze")

    print("== 历史对话框 ==")
    from tinydict.ui.history_dialog import HistoryDialog
    win._results = [EntryResult(word="ok", dict_id=1, dict_name="D",
                                encoding="utf-8", definition=b"<b>ok</b>")]
    win.do_lookup("ok")
    win.do_lookup("word")
    dlg = HistoryDialog(hb, config=cfg)
    check("对话框列出 2 条", dlg._list.count() == 2, f"count={dlg._list.count()}")
    dlg._filter.setText("wor")
    check("过滤后 1 条", dlg._list.count() == 1, f"count={dlg._list.count()}")
    dlg._filter.setText("")
    fired = []
    dlg.lookupRequested.connect(fired.append)
    dlg._on_double_clicked(dlg._list.item(0))
    check("双击发出查词信号", len(fired) == 1, f"fired={fired}")

    print()
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
