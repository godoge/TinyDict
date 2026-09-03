"""端到端验证：走 MainWindow 真实信号链，检查词条页的通用配色方案。

链路：Config -> ThemeManager.reapply() -> theme_changed
      -> MainWindow._reapply_theme() -> DictPage.set_theme_mode + 重渲染
      -> setHtml(entry_page(raw, word, mode, target), QUrl("mdx://7/"))

验证目标（通用方案，全程不含任何词库名）：
1) 静态词库（无主题系统、白底）：应用深色时套通用反色滤镜，浅色时不套；
2) 自带 applyTheme 的词库：走它自己的原生实现切换，不需要滤镜，且原生
   强调色 h3 红不被任何覆盖改写（即「没变样」）；
3) 词条页配色设为「保持词库原样」时，无论应用什么主题都完全不干预；
4) 绝不注入高特异性覆盖样式（sd-theme 必须始终不存在）。
"""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEngineUrlSchemeHandler
from PySide6.QtWidgets import QApplication

from tinydict.config import Config
from tinydict.core.query import EntryResult
from tinydict.ui.main_window import MainWindow
from tinydict.ui.theme import ThemeManager

# ---- 词条原型 1：静态词库（自带样式，没有任何主题系统，白底）
STATIC = (
    b'<html><head><meta charset="utf-8">'
    b'<style>'
    b'  body{margin:16px;background:#ffffff;color:#222222;}'
    b'  h3{color:#c0392b;}'                      # 词库原生强调色
    b'</style></head>'
    b'<body><h3>test</h3><p>hello</p></body></html>'
)

# ---- 词条原型 2：自带主题系统的词库（暴露 applyTheme，默认先套深色）
THEMED = (
    b'<html><head><meta charset="utf-8">'
    b'<style>'
    b'  body{margin:16px;}'
    b'  h3{color:#c0392b;}'                      # 词库原生强调色
    b'</style>'
    b'<script>'
    b'  window.applyTheme=function(m){'
    b"    var d=m==='dark';"
    b"    if(document.body){"
    b"      document.body.style.background=d?'#1e1e1e':'#ffffff';"
    b"      document.body.style.color=d?'#dddddd':'#222222';"
    b"    }"
    b"    document.documentElement.setAttribute('data-theme',m);"
    b"  };"
    b"  window.applyTheme('dark');"
    b'</script>'
    b'</head><body><h3>test</h3><p>hello</p></body></html>'
)

EXPECT_H3 = "rgb(192, 57, 43)"   # #c0392b 原生强调色，任何情况下都不得被改写

# (说明, 词条原型, 外观主题, 词条页配色, 期望是否套滤镜, 期望目标, 期望body背景)
PLAN = [
    ("静态词库/跟随/深色", STATIC, "dark", "follow", True, "dark", None),
    ("静态词库/跟随/浅色", STATIC, "light", "follow", False, "light", None),
    ("静态词库/原样/深色", STATIC, "dark", "native", False, "native", None),
    ("主题词库/跟随/浅色", THEMED, "light", "follow", False, "light",
     "rgb(255, 255, 255)"),
    ("主题词库/跟随/深色", THEMED, "dark", "follow", False, "dark",
     "rgb(30, 30, 30)"),
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
        self.definition = STATIC

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

cfg_path = Path("_e2e_config.json")
if cfg_path.exists():
    cfg_path.unlink()
cfg = Config(cfg_path)
cfg["theme"] = "dark"
cfg["entry_theme"] = "follow"

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
    "bg:getComputedStyle(document.body).backgroundColor,"
    "h3:getComputedStyle(document.querySelector('h3')).color,"
    "ov:!!document.getElementById('sd-theme'),"
    "flt:!!document.getElementById('sd-entry-filter'),"
    "target:String(window.__sdEntryTarget)})"
)


def advance():
    if step >= len(PLAN):
        print(f"\n=== 端到端：共 {len(PLAN)} 项，异常 {len(fails)} 项 ===",
              flush=True)
        app.quit()
        return
    _, html, mode, etheme, _inv, _target, _bg = PLAN[step]
    cfg["theme"] = mode
    cfg["entry_theme"] = etheme
    svc.definition = html
    theme.reapply()                      # 同步刷新 mode / 触发信号链
    win.do_lookup("test", sync_input=False)
    # 等页面加载 + 注入脚本的几次复查(0/80/300/800ms)全部跑完再取值
    QTimer.singleShot(1200, settle_check)


def settle_check():
    tag, _html, _mode, _etheme, inv, target, bg = PLAN[step]
    win._page.runJavaScript(JS_QUERY, lambda v: report(tag, inv, target, bg, v))


def report(tag, exp_inv, exp_target, exp_bg, value):
    global step
    try:
        d = json.loads(value or "{}")
    except Exception:
        d = {}
    ok = (d.get("inv") is exp_inv
          and d.get("target") == exp_target
          and d.get("h3") == EXPECT_H3      # 原生强调色未被改写 = 外观没变样
          and d.get("ov") is False          # 未注入高特异性覆盖样式
          and d.get("flt") is True)         # 通用滤镜样式已就位（按需启用）
    if exp_bg is not None:
        ok = ok and d.get("bg") == exp_bg
    if not ok:
        fails.append((tag, value))
    print(f"{'OK ' if ok else 'FAIL'} {tag:<20} 期望[滤镜={exp_inv} "
          f"目标={exp_target}] 实际 {value}", flush=True)
    step += 1
    QTimer.singleShot(150, advance)


QTimer.singleShot(500, advance)
QTimer.singleShot(120000, app.quit)
app.exec()
