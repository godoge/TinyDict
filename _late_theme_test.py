"""回归测试：词库「延迟套用自己的主题」时，词条页明暗必须能跟上。

这是此前实现的结构性缺陷：复查只到 800ms 为止，而词条容器 1200ms
才揭幕。词库脚本/CSS 若在这之后才生效，sd-invert 就停留在过期结论上
——表现为「第一次看是对的，切到别的词条再切回来就反了」。

三个用例（全部通用，不含任何词库名）：
1) 页面初始浅色，1500ms 后被词库自己改成深色 → 最终不应再套滤镜；
2) 页面初始深色，1500ms 后被词库自己改成浅色 → 最终应补上滤镜；
3) A -> B -> A 来回切换后，A 的结论必须与首次一致（不漂移）。

用法：
    QT_QPA_PLATFORM=offscreen QT_OPENGL=software \
    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
    .venv/Scripts/python _late_theme_test.py
"""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QObject, QTimer, Signal
from PySide6.QtWebEngineCore import QWebEngineUrlSchemeHandler
from PySide6.QtWidgets import QApplication

from tinydict.config import Config
from tinydict.core.query import EntryResult
from tinydict.ui.main_window import MainWindow
from tinydict.ui.theme import ThemeManager

# 页面初始浅色，1.5 秒后词库自己给自己套深色
LATE_DARK = (
    b'<html><head><meta charset="utf-8">'
    b'<style>body{margin:16px;background:#ffffff;color:#222222;}'
    b'body.late-dark{background:#1e1e1e;color:#dddddd;}</style>'
    b'<script>setTimeout(function(){'
    b"document.body.classList.add('late-dark');},1500);</script>"
    b'</head><body><h3>test</h3><p>hello</p></body></html>'
)

# 页面初始深色，1.5 秒后词库自己改回浅色
LATE_LIGHT = (
    b'<html><head><meta charset="utf-8">'
    b'<style>body{margin:16px;background:#1e1e1e;color:#dddddd;}'
    b'body.late-light{background:#ffffff;color:#222222;}</style>'
    b'<script>setTimeout(function(){'
    b"document.body.classList.add('late-light');},1500);</script>"
    b'</head><body><h3>test</h3><p>hello</p></body></html>'
)

# (说明, 词条, 期望最终是否套滤镜, 期望最终背景)
PLAN = [
    ("延迟变深/目标深", LATE_DARK, False, "rgb(30, 30, 30)"),
    ("延迟变浅/目标深", LATE_LIGHT, True, "rgb(255, 255, 255)"),
    ("切换回 A", LATE_DARK, False, "rgb(30, 30, 30)"),
    ("再切一次 A", LATE_DARK, False, "rgb(30, 30, 30)"),
]


class _MdxHandler(QWebEngineUrlSchemeHandler):
    def requestStarted(self, request):
        buf = QBuffer(parent=request)
        request.destroyed.connect(buf.deleteLater)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        buf.write(QByteArray(b"<html><body>unused</body></html>"))
        buf.seek(0)
        buf.close()
        request.reply(b"text/html", buf)


class StubService(QObject):
    mount_progress = Signal(int, int, str)
    dict_mounted = Signal(int)
    dict_mount_failed = Signal(int, str)
    mount_finished = Signal()

    def __init__(self):
        super().__init__()
        self.definition = LATE_DARK

    def enabled_dicts(self):
        return []

    def all_dicts(self):
        return []

    def is_mounted(self, _id):
        return True

    def mount_status(self, _id):
        return "ready"

    def mount_error(self, _id):
        return ""

    def suggest(self, text, limit=30):
        return []

    def lookup(self, word):
        return [EntryResult(word=word, dict_id=7, dict_name="测试词库",
                            encoding="utf-8", definition=self.definition)]


class StubWordbook(QObject):
    def groups(self):
        return []

    def has(self, w, gid):
        return False

    def groups_of(self, w):
        return []

    def group_name(self, gid):
        return "生词本"


app = QApplication(sys.argv)
cfg_path = Path("_late_theme_config.json")
if cfg_path.exists():
    cfg_path.unlink()
cfg = Config(cfg_path)
cfg["theme"] = "dark"          # 应用深色主题
cfg["entry_theme"] = "follow"  # 词条页跟随 → 目标为深色

theme = ThemeManager(cfg, app)
theme.apply_to_qt()

svc = StubService()
win = MainWindow(svc, cfg, StubWordbook(), theme_manager=theme)
win.show()
win._profile.installUrlSchemeHandler(b"mdx", _MdxHandler(win._profile))

step = 0
fails = []

JS_QUERY = (
    "JSON.stringify({"
    "inv:document.documentElement.classList.contains('sd-invert'),"
    "bg:getComputedStyle(document.body).backgroundColor})"
)


def advance():
    if step >= len(PLAN):
        print(f"\n=== 延迟主题：共 {len(PLAN)} 项，失败 {len(fails)} 项 ===",
              flush=True)
        for f in fails:
            print("  失败:", f[0], f[1], flush=True)
        app.quit()
        return
    tag, html, _inv, _bg = PLAN[step]
    svc.definition = html
    win.do_lookup("test", sync_input=False)
    # 等过 1500ms 的词库延迟 + 复查(3000ms) 之后再取值
    QTimer.singleShot(4200, settle_check)


def settle_check():
    win._page.runJavaScript(JS_QUERY, report)


def report(value):
    global step
    tag, _html, exp_inv, exp_bg = PLAN[step]
    try:
        d = json.loads(value or "{}")
    except Exception:
        d = {}
    ok = (d.get("inv") is exp_inv) and (d.get("bg") == exp_bg)
    if not ok:
        fails.append((tag, value))
    print(f"{'OK  ' if ok else 'FAIL'} {tag:<16} 期望[滤镜={exp_inv} "
          f"bg={exp_bg}] 实际 {value}", flush=True)
    step += 1
    QTimer.singleShot(200, advance)


QTimer.singleShot(500, advance)
QTimer.singleShot(180000, app.quit)
app.exec()
