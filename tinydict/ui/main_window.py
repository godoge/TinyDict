"""主窗口：搜索 / 建议列表 / 词条渲染（QWebEngineView）/ 历史导航 / 生词星标 / 置顶。"""

import html as _html
import json
import re as _re
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QSplitter, QStatusBar, QTabBar,
    QToolButton, QVBoxLayout, QWidget,
)
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from urllib.parse import unquote

from ..core.query import DictionaryService, EntryResult
from ..core.wordbook import DEFAULT_GROUP_ID, WordBook
from ..core import dict_config
from .. import __version__
from ..config import Config
from .dict_manager_dialog import DictManagerDialog
from .resource_inliner import inline_resources
from .scheme_handler import MdxSchemeHandler
from .settings_dialog import SettingsDialog
from .wordbook_dialog import WordbookDialog

# ----------------------------------------------------------------------
# 词条 HTML 组装
# ----------------------------------------------------------------------

DEFAULT_CSS = """
body{font-family:'Microsoft YaHei','Segoe UI',Arial,sans-serif;
     font-size:15px;line-height:1.65;color:#24292f;background:#fff;
     margin:18px 28px;}
img{max-width:100%;height:auto;}
table{max-width:100%;border-collapse:collapse;}
a{color:#2563eb;text-decoration:none;}
a:hover{text-decoration:underline;}
.sd-headword{font-size:24px;font-weight:600;color:#111827;
     margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #e5e7eb;}
.sd-plain{white-space:pre-wrap;}
.sd-tip{color:#6b7280;font-size:13px;}
.sd-welcome h1{font-size:30px;color:#1d4ed8;margin-bottom:4px;}
.sd-welcome li{margin:6px 0;}
.sd-notfound p{color:#4b5563;}
code{background:#f3f4f6;border-radius:3px;padding:1px 5px;
     font-family:Consolas,monospace;font-size:13px;}
"""


def _esc(s: str) -> str:
    return _html.escape(s or "")


def _page(inner: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>{DEFAULT_CSS}</style></head><body>{inner}</body></html>"
        + _ENTRY_TAIL_SCRIPT
    )


# 词条内容尾部统一注入的脚本：
#   1) 等待脚本执行完后再显示页面，消除「首帧原始 HTML → 脚本改布局」的闪烁；
#   2) 把未指定 type 的 <button> 强制设为 type="button"，避免默认 submit 行为；
#   3) 拦截 entry:// / mdx:// 词条链接与词条表单的点击/提交，改为设置
#      location.hash（片段变化不会触达主帧导航，从而不会让词条页变空白），
#      Python 端监听 urlChanged 解析片段后查词。这是绕开「注册自定义 scheme 后
#      acceptNavigationRequest 返回 False 仍无法取消主帧导航、导致空白页」的可靠方案。
_ENTRY_TAIL_SCRIPT = (
    "<script>(function(){"
    "function s(){var e=document.getElementById('sd-entry');if(e)e.style.opacity='1';}"
    "if(document.readyState!=='loading')requestAnimationFrame(s);"
    "else document.addEventListener('DOMContentLoaded',function(){"
    "requestAnimationFrame(s);});"
    "setTimeout(s,1200);"
    "function sdWordFromHref(href){"
    "if(!href)return null;"
    "if(href.indexOf('entry://')===0){"
    "var e=href.slice(8).split('#')[0].split('?')[0];return decodeURIComponent(e);}"
    "if(href.indexOf('mdx://')===0){"
    "var p=href.slice(6);var sl=p.indexOf('/');p=sl>=0?p.slice(sl+1):p;"
    "p=p.split('?')[0].split('#')[0];if(p.indexOf('.')>=0)return null;"
    "return decodeURIComponent(p);}return null;}"
    "document.addEventListener('click',function(e){"
    "var b=e.target.closest('button');if(b){var t=b.getAttribute('type');if(t!=='button'&&t!=='reset')b.setAttribute('type','button');}"
    "var a=e.target.closest('a[href]');"
    "if(a){var w=sdWordFromHref(a.getAttribute('href'));"
    "if(w){e.preventDefault();location.hash='sdentry:'+encodeURIComponent(w);}}"
    "},true);"
    "document.addEventListener('submit',function(e){"
    "e.preventDefault();"
    "var f=e.target;var raw=f.getAttribute('action')||f.action||'';"
    "var w=sdWordFromHref(raw);"
    "if(w){location.hash='sdentry:'+encodeURIComponent(w);}"
    "return false;"
    "},true);"
    "})();</script>"
)


def _wrap_with_guard(html: str) -> str:
    """用初始不可见容器包裹词条，并注入尾部脚本（防表单提交/防闪烁）。

    无论词条是否包含 <script>，都必须注入 _ENTRY_TAIL_SCRIPT，
    否则 OALDPEX 等词库的配置按钮会因默认 submit 行为导致词条页变空白。
    """
    has_script = "<script" in html.lower()
    body_open = html.lower().find("<body")
    if body_open < 0:
        html = "<body>" + html + "</body>"
        body_open = 0
    gt = html.find(">", body_open)
    if has_script:
        html = html[:gt + 1] + '<div id="sd-entry" style="opacity:0">' + html[gt + 1:]
    else:
        html = html[:gt + 1] + '<div id="sd-entry">' + html[gt + 1:]
    body_close = html.lower().rfind("</body>")
    if body_close < 0:
        html = html + "</div>" + _ENTRY_TAIL_SCRIPT
    else:
        html = html[:body_close] + "</div>" + _ENTRY_TAIL_SCRIPT + html[body_close:]
    return html


def entry_page(raw_html: str, word: str) -> str:
    """把 MDX 词条内容包装为完整 HTML 文档。

    - 词条本身带样式（<link>/<style>）：原样使用，尊重词库排版；
    - 结构化但无样式：注入默认样式；
    - 纯文本词条：套默认词条模板。
    """
    s = (raw_html or "").strip()
    if not s:
        return _page(f'<div class="sd-headword">{_esc(word)}</div>'
                     f'<p class="sd-tip">（该词条内容为空）</p>')
    lower = s.lower()
    head = lower[:400]
    if s.startswith("<") or "<html" in head or "<div" in head or "<table" in head:
        if "<link" not in lower and "<style" not in lower:
            return _page(s)
        # 已带样式：内容已解码为 str（UTF-8）交给 WebEngine，
        # 清掉词条里原有的非 UTF-8 charset 声明以免乱码
        s = _re.sub(r"<meta[^>]*charset[^>]*>", "", s, flags=_re.I)
        if "<head" in lower:
            s = _re.sub(r"(<head[^>]*>)",
                        r'\1<meta charset="utf-8">',
                        s, count=1, flags=_re.I)
        else:
            s = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head>"
                 f"<body>{s}</body></html>")
        return _wrap_with_guard(s)
    return _page(
        f'<div class="sd-headword">{_esc(word)}</div>'
        f'<div class="sd-plain">{_esc(s)}</div>'
    )


def welcome_page() -> str:
    return _page("""
<div class="sd-welcome">
<h1>TinyDict</h1>
<p class="sd-tip">离线 MDX 词典 &middot; 数据保存在本机；如需在线资源可在「设置」中关闭强制离线</p>
<ul>
<li>点击右上角<b>「词库」</b>添加 <code>.mdx</code> 文件，或直接选择
<b>词库文件夹</b>（自动扫描其中全部词库）—— 即加即用，无需导入</li>
<li>在上方搜索框输入单词，回车查词，左侧列表为实时联想</li>
<li>点 <b>★</b> 把当前词条收藏到右侧选中的<b>生词本分组</b>，
点<b>「生词本」</b>按分组查看与整理（一个词可同时属于多个分组）</li>
<li><b>「置顶」</b>可让窗口常驻最前；关闭窗口默认最小化到系统托盘</li>
<li>默认全局快捷键：<code>Ctrl+Alt+D</code> 显示/隐藏窗口，
<code>Ctrl+Alt+Q</code> 屏幕划词取词（可在设置中修改）</li>
</ul>
</div>""")


def not_found_page(word: str) -> str:
    return _page(
        f'<div class="sd-headword">{_esc(word)}</div>'
        '<div class="sd-notfound">'
        "<p><b>没有找到该词条</b></p>"
        "<p>建议：</p>"
        "<ul><li>检查拼写（可参考左侧候选列表）</li>"
        "<li>在「词库」中确认词库已启用且状态为「就绪」"
        "（新添加的词库后台加载中，稍候即可查询）</li></ul>"
        "</div>"
    )


# ----------------------------------------------------------------------
# WebEngine 页面与离线拦截
# ----------------------------------------------------------------------

class OfflineBlocker(QWebEngineUrlRequestInterceptor):
    """按需拦截远程请求。

    offline_mode 为 True 时，拦截一切 http/https/ftp/ws/wss 请求，保证纯离线运行
    （仅可用词库自带离线资源）；为 False 时放行，允许词库按需在线获取资源。
    """

    REMOTE_SCHEMES = {"http", "https", "ftp", "ws", "wss"}

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config

    def interceptRequest(self, info):
        # 允许在线（默认）：不拦截任何请求
        if not self._config["offline_mode"]:
            return
        if info.requestUrl().scheme() not in self.REMOTE_SCHEMES:
            return
        # 必须调用 block(True) 才能真正中止请求。PySide6 该接口签名是
        # block(self, bool)，不带参会抛 TypeError；而旧版可能是无参 block()。
        # 这里两种写法都试，确保万无一失地拦下所有外网请求。
        for _call in (lambda: info.block(True), lambda: info.block()):
            try:
                _call()
                return
            except (TypeError, AttributeError):
                continue


# mdx:// 协议下需要拦截的资源文件扩展名（这些是子资源而非词条导航）
_MDX_RESOURCE_EXTS = {
    ".html", ".htm", ".css", ".js", ".json", ".xml",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".mp3", ".ogg", ".wav", ".spx", ".mp4",
    ".pdf", ".zip",
}


class DictPage(QWebEnginePage):
    """词条页面：接管 entry:// 与 mdx:// 导航（词库词条互链 / 相对链接）。

    发音链接不再走 sound:// 导航，而是由 resource_inliner 改写为
    href="#" + data-snd="mdx://<dict_id>/<file>" + onclick（原生 <audio> 播放）。
    """

    entryLink = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 注入全局 applyTheme：部分词库（如欧陆系）的词条 HTML 自带脚本，会调用
        # applyTheme() 套用明暗主题；本应用使用固定 CSS、并未提供该函数，直接调用
        # 会抛 ReferenceError。这里在文档创建时注入一个空实现，使其调用安全无害。
        script = QWebEngineScript()
        script.setName("tinydict-globals")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(
            "window.applyTheme=window.applyTheme||function(mode){"
            "try{document.documentElement.setAttribute('data-theme',"
            "(mode==='dark'?'dark':'light'));}catch(e){}};"
        )
        self.scripts().insert(script)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # 仅打印 Error 级别，屏蔽词库自身的 console.log / console.info 调试噪音。
        # 旧默认实现会把所有 JS 控制台消息（含普通调试）打到 stderr，前缀 "js:"。
        if level != QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            return
        src = f" ({sourceID}:{lineNumber})" if sourceID else ""
        print(f"[JS错误]{src} {message}", file=sys.stderr)

    def acceptNavigationRequest(self, url, nav_type, is_main):
        scheme = url.scheme()
        if scheme == "entry":
            target = url.toString()[len("entry://"):]
            self.entryLink.emit(unquote(target))
            return False
        if scheme == "sound":
            return False
        if scheme == "mdx":
            # mdx:// 协议的导航处理：
            # 1) 资源路径（带文件扩展名）→ 阻止导航，避免空白页；
            # 2) 词条路径（无扩展名）→ 转为词条查询，如 OALDPEX 的
            #    Configuration 按钮点击后浏览器解析为 mdx://{id}/oaldpexconfig，
            #    应触发 do_lookup("oaldpexconfig") 而非替换页面。
            raw_path = url.path().strip("/")
            if not raw_path:
                return False
            # 去掉 query / fragment（浏览器可能附加参数）
            raw_path = raw_path.split("?")[0].split("#")[0]
            decoded = unquote(raw_path)
            # 检查是否为资源文件（带扩展名）
            low = decoded.lower()
            dot = low.rfind(".")
            ext = low[dot:] if dot >= 0 else ""
            if ext in _MDX_RESOURCE_EXTS:
                return False
            self.entryLink.emit(decoded)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main)


# ----------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------

APP_QSS = """
QLineEdit#search_edit{
    border:1px solid #d1d5db;border-radius:15px;padding:5px 14px;
    font-size:15px;background:#fff;selection-background-color:#dbeafe;
}
QLineEdit#search_edit:focus{border-color:#2563eb;}
QListWidget#suggest_list{
    border:none;border-right:1px solid #e5e7eb;background:#fafafa;
    font-size:14px;outline:0;
}
QListWidget#suggest_list::item{padding:5px 10px;}
QListWidget#suggest_list::item:selected{background:#dbeafe;color:#111827;}
QTabBar::tab{padding:5px 14px;background:#f3f4f6;color:#4b5563;}
QTabBar::tab:selected{background:#fff;color:#1d4ed8;
    border:1px solid #e5e7eb;border-bottom:1px solid #fff;}
QStatusBar{color:#6b7280;}
QStatusBar QLabel{padding:0 10px;}
QComboBox#group_combo{
    border:1px solid #d1d5db;border-radius:13px;padding:3px 10px;
    font-size:13px;background:#fff;color:#374151;
}
QComboBox#group_combo:hover{border-color:#2563eb;}
QComboBox#group_combo::drop-down{border:none;width:16px;}
"""


class MainWindow(QMainWindow):
    settings_saved = Signal()      # 设置已保存（app 层据此重绑快捷键）
    wordbook_changed = Signal()    # 生词本内容变化
    dicts_changed = Signal()       # 词库增删/顺序变化（由管理对话框发出）

    def __init__(self, service: DictionaryService, config: Config,
                 wordbook: WordBook, parent=None):
        super().__init__(parent)
        self._service = service
        self._config = config
        self.wordbook = wordbook
        self._results: list[EntryResult] = []
        self._current_word = ""
        self._history: list[str] = []
        self._hist_pos = -1
        self._tray = None               # 由 app 层注入
        self._tray_message_shown = False
        self._wordbook_dialog = None
        self._dict_dialog = None

        self.setWindowTitle(f"TinyDict 离线词典 v{__version__}")
        self.resize(980, 680)
        self.setStyleSheet(APP_QSS)

        self._build_ui()
        # 顶栏分组下拉框（★ 的归属分组）；生词变化时同步刷新计数
        self._reload_groups()
        self.wordbook_changed.connect(self._reload_groups)
        self._view.setHtml(welcome_page(), QUrl("mdx://0/"))
        self._suggest_timer = QTimer(self, singleShot=True, interval=250)
        self._suggest_timer.timeout.connect(self._refresh_suggestions)

        # 词库挂载进度 / 完成（挂载式架构：后台加载 key 索引）
        self._mount_done = 0
        self._mount_total = 0
        self._service.mount_progress.connect(self._on_mount_progress)
        self._service.dict_mounted.connect(self._on_dict_mounted)
        self._service.dict_mount_failed.connect(
            lambda _id, _msg: self._refresh_dict_status())
        self._service.mount_finished.connect(self._refresh_dict_status)

        # 词库后台挂载进度/完成（挂载式架构）
        self._mount_total = 0
        self._mount_done = 0
        self._service.mount_progress.connect(self._on_mount_progress)
        self._service.dict_mounted.connect(self._on_dict_mounted)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 6)
        root.setSpacing(6)

        # ---- 顶栏
        top = QHBoxLayout()
        top.setSpacing(4)

        self._btn_back = QToolButton(text="←", enabled=False)
        self._btn_back.setToolTip("后退")
        self._btn_back.clicked.connect(self._go_back)
        self._btn_fwd = QToolButton(text="→", enabled=False)
        self._btn_fwd.setToolTip("前进")
        self._btn_fwd.clicked.connect(self._go_forward)
        top.addWidget(self._btn_back)
        top.addWidget(self._btn_fwd)

        self.search_edit = QLineEdit(objectName="search_edit")
        self.search_edit.setPlaceholderText(
            "输入单词查询，回车查词（Ctrl+Alt+D 显示/隐藏窗口）"
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._on_return)
        self.search_edit.textChanged.connect(self._on_text_changed)
        top.addWidget(self.search_edit, stretch=1)

        self._btn_star = QToolButton(text="☆", checkable=True)
        self._btn_star.setToolTip("加入/移出当前分组")
        self._btn_star.clicked.connect(self._on_star)
        top.addWidget(self._btn_star)

        # 生词本分组选择：★ 收录的词进入这里选中的分组
        self.group_combo = QComboBox(objectName="group_combo")
        self.group_combo.setToolTip("点 ★ 时把当前词条加入的分组")
        self.group_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.group_combo.setMaximumWidth(180)
        self.group_combo.currentIndexChanged.connect(self._on_group_combo_changed)
        top.addWidget(self.group_combo)

        self._btn_pin = QToolButton(text="置顶", checkable=True)
        self._btn_pin.setToolTip("窗口常驻最前")
        self._btn_pin.clicked.connect(self._on_pin)
        top.addWidget(self._btn_pin)

        for text, tip, slot in (
            ("词库", "管理 MDX 词库（导入 / 删除 / 优先级）", self.open_dict_manager),
            ("生词本", "查看生词本", self.open_wordbook),
            ("设置", "快捷键等设置", self.open_settings),
        ):
            b = QToolButton(text=text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            top.addWidget(b)
        root.addLayout(top)

        # ---- 词典切换（多部词库命中时显示在词条页上方）
        self._tabs = QTabBar()
        self._tabs.setExpanding(False)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.currentChanged.connect(self._render_current)
        self._tabs.hide()

        # ---- 左建议列表 + 右词条渲染
        self.suggest_list = QListWidget(objectName="suggest_list")
        self.suggest_list.itemClicked.connect(self._on_suggestion_clicked)

        self._handler = MdxSchemeHandler(self._service)
        self._profile = QWebEngineProfile(self)  # 离线 profile（无磁盘缓存）
        self._profile.installUrlSchemeHandler(b"mdx", self._handler)
        # 必须保留拦截器实例引用：否则 Python 对象被 GC 后，C++ 侧回调丢失，
        # 外网请求会悄悄放行（表现为仍能看到 SSL handshake 错误）。
        self._offline_blocker = OfflineBlocker(self._config)
        try:
            self._profile.setUrlRequestInterceptor(self._offline_blocker)
        except AttributeError:
            pass  # 新版本 Qt 移除该 API 时跳过（mdx 本身也无远程内容）
        self._page = DictPage(self._profile, self)
        self._page.entryLink.connect(self.do_lookup)
        # 词条内的 entry:// / mdx:// 链接经前端改写为 location.hash 片段通信，
        # 在此监听 urlChanged 解析片段后发起查词（绕开自定义 scheme 导航变空白）。
        self._page.urlChanged.connect(self._on_url_fragment)
        settings = self._page.settings()
        settings.setFontFamily(
            QWebEngineSettings.FontFamily.StandardFont, "Microsoft YaHei")
        settings.setFontFamily(
            QWebEngineSettings.FontFamily.SansSerifFont, "Microsoft YaHei")
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        self._view = QWebEngineView()
        self._view.setPage(self._page)

        # 词条页容器：顶部词典切换标签 + 下方词条内容，使切换标签成为
        # 词条页的页头（只压在词条内容上方，不再横跨左侧联想列表）
        entry_page = QWidget()
        entry_vbox = QVBoxLayout(entry_page)
        entry_vbox.setContentsMargins(0, 0, 0, 0)
        entry_vbox.setSpacing(0)
        entry_vbox.addWidget(self._tabs)
        entry_vbox.addWidget(self._view)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.suggest_list)
        splitter.addWidget(entry_page)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 750])
        root.addWidget(splitter, stretch=1)

        self.setCentralWidget(central)

        # ---- 状态栏
        status = QStatusBar()
        self._status_dict = QLabel("未加载词库")
        self._status_dict.setTextFormat(Qt.TextFormat.RichText)
        self._status_dict.setOpenExternalLinks(False)
        self._status_dict.linkActivated.connect(self.open_dict_manager)
        self._status_info = QLabel("")
        status.addWidget(self._status_dict)
        status.addPermanentWidget(self._status_info)
        self.setStatusBar(status)
        self._refresh_dict_status()

    # ------------------------------------------------------------ 搜索建议
    def _on_text_changed(self, text: str):
        self._suggest_timer.start()

    def _refresh_suggestions(self):
        text = self.search_edit.text().strip()
        self.suggest_list.clear()
        if not text:
            return
        for word in self._service.suggest(text, limit=30):
            item = QListWidgetItem(word)
            item.setToolTip(word)
            self.suggest_list.addItem(item)

    def _on_suggestion_clicked(self, item: QListWidgetItem):
        # 是否把点击的词条同步写入搜索框，由设置 fill_input_on_select 控制
        # （默认关闭：只显示释义，不改变搜索框内容，便于在候选列表里连续浏览）。
        self.do_lookup(
            item.text(),
            sync_input=bool(self._config["fill_input_on_select"]),
        )

    def _on_return(self):
        text = self.search_edit.text().strip()
        if text:
            self.do_lookup(text)

    # ---------------------------------------------------------------- 查词
    # ---------------------------------------------------- entry:// 链接通信通道
    def _on_url_fragment(self, url: QUrl):
        """监听 urlChanged：词组内的 entry:// / mdx:// 链接经前端改写为
        location.hash 片段以避免主帧导航变空白，这里解析后处理。

        - #sdentry:<word>  ：词条互链 / 候选导航，解析后查词；
        - #sdconfig:<id>:<json> ：localStorage 桥回写，把该词典的配置快照
          整体持久化到 data_dir()/dict_config/<id>.json。
        """
        frag = url.fragment()
        if not frag:
            return
        if frag.startswith("sdentry:"):
            word = unquote(frag[len("sdentry:"):])
            # 清除 hash（仅修正 URL，不触发导航），避免历史污染与重复触发
            self._page.runJavaScript(
                "try{history.replaceState(null,'',location.pathname+"
                "location.search);}catch(e){}"
            )
            self.do_lookup(word)
            return
        if frag.startswith("sdconfig:"):
            rest = frag[len("sdconfig:"):]
            dict_part, _, json_str = rest.partition(":")
            try:
                did = int(dict_part)
                data = json.loads(unquote(json_str))
                if isinstance(data, dict):
                    dict_config.replace_dict_config(did, data)
            except (ValueError, json.JSONDecodeError, OSError):
                pass
            self._page.runJavaScript(
                "try{history.replaceState(null,'',location.pathname+"
                "location.search);}catch(e){}"
            )
            return

    def do_lookup(self, word: str, push_history: bool = True,
                  sync_input: bool = True):
        """查词并渲染。

        sync_input=True 时把词条写入上方搜索框，并刷新左侧候选列表
        （历史/回车/词条内互链等默认路径保持 True）；
        左侧候选点击受设置 fill_input_on_select 控制，关闭时为 False，
        此时只显示释义、不改变搜索框，也避免候选列表被无谓刷新。
        """
        word = (word or "").strip()
        if not word:
            return
        self._current_word = word

        if sync_input and self.search_edit.text() != word:
            self.search_edit.blockSignals(True)
            self.search_edit.setText(word)
            self.search_edit.blockSignals(False)

        self._results = self._service.lookup(word)
        if self._results:
            self._setup_tabs()
            self._render_current()
        else:
            self._tabs.blockSignals(True)
            self._tabs.hide()
            self._tabs.blockSignals(False)
            self._view.setHtml(not_found_page(word), QUrl("mdx://0/"))
            self._status_info.setText("未找到词条")

        if push_history:
            self._push_history(word)

        self._update_star()
        # 仅当搜索框内容被本次查词改变时，才刷新候选列表
        if sync_input:
            self._suggest_timer.start()

    def _setup_tabs(self):
        self._tabs.blockSignals(True)
        while self._tabs.count() > 0:
            self._tabs.removeTab(0)
        for r in self._results:
            self._tabs.addTab(r.dict_name)
        self._tabs.setVisible(len(self._results) > 1)
        self._tabs.setCurrentIndex(0)
        self._tabs.blockSignals(False)

    def _render_current(self):
        if not self._results:
            return
        idx = max(self._tabs.currentIndex(), 0)
        r = self._results[idx]
        # 先把 MDD 资源（图标/CSS）内联为 data URI，绕开 mdx:// 子资源加载；
        # 同时注入 localStorage 桥，用该词典已持久化的配置作种子（重启不丢配置）
        raw = inline_resources(
            r.html(), r.dict_id, self._service,
            dict_config.get_dict_config(r.dict_id),
        )
        self._view.setHtml(entry_page(raw, r.word),
                           QUrl(f"mdx://{r.dict_id}/"))
        others = len(self._results) - 1
        self._status_info.setText(
            f"词典：{r.dict_name}"
            + (f" · 另有 {others} 部词库命中" if others > 0 else "")
        )
        # 调试：把当前词条处理前后的 HTML 与资源诊断保存到项目目录
        if r.word.lower() in ("obvious",):
            from .resource_inliner import _MISS_LOG
            debug_dir = Path(__file__).resolve().parent.parent.parent / ".tmpwheels"
            debug_dir.mkdir(exist_ok=True)
            (debug_dir / "debug_obvious_before.html").write_text(
                r.html() or "", encoding="utf-8", errors="ignore")
            (debug_dir / "debug_obvious_after.html").write_text(
                raw or "", encoding="utf-8", errors="ignore")
            # 资源诊断：未命中的引用 + MDD 实际 key 列表
            mount = self._service._mounts.get(r.dict_id)
            mdd_keys = []
            if mount:
                for mdd in mount.mdds:
                    mdd_keys.extend(mdd._res_map.keys())
            miss_text = "\n".join(
                f"  REF={u!r}\n    tried={c}" for u, c in _MISS_LOG) or "  (无)"
            diag = (
                f"== 未命中资源（HTML 引用但 find_resource 返回 None）==\n"
                f"{miss_text}\n\n"
                f"== 当前词库 MDD 实际资源 key 数：{len(mdd_keys)} ==\n"
                f"{chr(10).join(sorted(mdd_keys)[:300])}\n"
            )
            (debug_dir / "debug_diag.txt").write_text(
                diag, encoding="utf-8", errors="ignore")

    # ---------------------------------------------------------------- 历史
    def _push_history(self, word: str):
        if self._hist_pos >= 0 and self._history[self._hist_pos] == word:
            return
        self._history = self._history[: self._hist_pos + 1]
        self._history.append(word)
        self._hist_pos = len(self._history) - 1
        self._update_nav_buttons()

    def _go_back(self):
        if self._hist_pos > 0:
            self._hist_pos -= 1
            self.do_lookup(self._history[self._hist_pos], push_history=False)
            self._update_nav_buttons()

    def _go_forward(self):
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            self.do_lookup(self._history[self._hist_pos], push_history=False)
            self._update_nav_buttons()

    def _update_nav_buttons(self):
        self._btn_back.setEnabled(self._hist_pos > 0)
        self._btn_fwd.setEnabled(
            self._hist_pos < len(self._history) - 1)

    # ------------------------------------------------------------ 生词本分组
    def _reload_groups(self):
        """重建顶栏分组下拉框（保持当前选中的分组）。"""
        gid = self._selected_group_id()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        index = 0
        for i, g in enumerate(self.wordbook.groups()):
            self.group_combo.addItem(f"{g.name}（{g.count}）", g.id)
            # 分组名单独存一份，避免从带计数的显示文本里反解
            self.group_combo.setItemData(i, g.name, Qt.ItemDataRole.ToolTipRole)
            if g.id == gid:
                index = i
        self.group_combo.addItem("＋ 新建分组…", -1)
        self.group_combo.setCurrentIndex(index)
        self.group_combo.blockSignals(False)
        self._update_star()

    def _selected_group_id(self) -> int:
        """当前选中的分组 id；未选中（如停在「新建分组…」）时回退到配置值。"""
        gid = self.group_combo.currentData()
        if isinstance(gid, int) and gid > 0:
            return gid
        try:
            saved = int(self._config["wordbook_group_id"])
        except (TypeError, ValueError):
            saved = DEFAULT_GROUP_ID
        return saved if saved > 0 else DEFAULT_GROUP_ID

    def _selected_group_name(self) -> str:
        idx = self.group_combo.currentIndex()
        name = self.group_combo.itemData(idx, Qt.ItemDataRole.ToolTipRole)
        if name:
            return str(name)
        # 停在「＋ 新建分组…」等非常规项时，按实际选中的分组 id 反查名字
        return self.wordbook.group_name(self._selected_group_id()) or "生词本"

    def _on_group_combo_changed(self, index: int):
        gid = self.group_combo.itemData(index)
        if gid == -1:                     # 「＋ 新建分组…」
            self._create_group()
            return
        if isinstance(gid, int) and gid > 0:
            self._config["wordbook_group_id"] = gid
            self._config.save()
        self._update_star()

    def _create_group(self):
        name, ok = QInputDialog.getText(self, "新建分组", "分组名称：")
        if not ok or not (name or "").strip():
            self._reload_groups()          # 取消：回到之前选中的分组
            return
        name = name.strip()
        group = self.wordbook.add_group(name)
        if group is None:
            QMessageBox.warning(self, "新建分组", f"分组「{name}」已存在。")
            self._reload_groups()
            return
        self._config["wordbook_group_id"] = group.id
        self._config.save()
        self._reload_groups()
        self._status_info.setText(f"已新建分组：{name}")
        self.wordbook_changed.emit()       # 已打开的生词本窗口同步刷新

    # ---------------------------------------------------------------- 生词
    def _update_star(self):
        gid = self._selected_group_id()
        gname = self._selected_group_name()
        self._btn_star.blockSignals(True)
        in_group = bool(self._current_word) and self.wordbook.has(
            self._current_word, gid)
        self._btn_star.setChecked(in_group)
        self._btn_star.setText("★" if in_group else "☆")
        self._btn_star.blockSignals(False)

        action = f"点 ★ 加入 / 移出分组「{gname}」"
        if self._current_word:
            names = self.wordbook.groups_of(self._current_word)
            self._btn_star.setToolTip(
                (f"所属分组：{'、'.join(names)}\n" if names else "")
                + action
            )
        else:
            self._btn_star.setToolTip(action)

    def _on_star(self, checked: bool):
        if not self._current_word:
            return
        word = self._current_word
        gid = self._selected_group_id()
        gname = self._selected_group_name()
        if checked:
            if self.wordbook.add(word, gid):
                self._status_info.setText(f"已加入「{gname}」：{word}")
            else:
                self._status_info.setText(f"{word} 已在「{gname}」中")
        else:
            self.wordbook.remove_from_group(word, gid)
            self._status_info.setText(f"已从「{gname}」移除：{word}")
        self._update_star()
        self.wordbook_changed.emit()

    # ---------------------------------------------------------------- 置顶
    def _on_pin(self, checked: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    # ---------------------------------------------------------------- 对话框
    def open_dict_manager(self):
        if self._dict_dialog is None:
            self._dict_dialog = DictManagerDialog(
                self._service, self)
            self._dict_dialog.dicts_changed.connect(self._on_dicts_changed)
        self._dict_dialog.refresh()
        self._dict_dialog.show()
        self._dict_dialog.raise_()
        self._dict_dialog.activateWindow()

    def _on_dicts_changed(self):
        self._refresh_dict_status()
        if self._current_word:
            self.do_lookup(self._current_word, push_history=False)

    def _refresh_dict_status(self):
        dicts = self._service.enabled_dicts()
        if not dicts:
            self._status_dict.setText(
                "未启用任何词库，点击「词库」添加 .mdx 文件或词库文件夹")
            self._status_dict.setToolTip("")
            return
        mounted = sum(1 for d in dicts if self._service.is_mounted(d.id))
        missing = [d for d in dicts
                   if self._service.mount_status(d.id) == "missing"]
        total_entries = sum(d.entry_count for d in dicts
                            if self._service.is_mounted(d.id))
        if missing:
            names = "、".join(d.name for d in missing)
            self._status_dict.setText(
                f"⚠ {len(missing)} 部词库文件缺失或无法加载，"
                f"<a href='manage'>点击「词库管理」查看并修复</a>")
            self._status_dict.setToolTip(
                "缺失词库：" + names + "\n"
                "（通常是文件夹被改名 / 移动后路径失效）\n"
                "打开「词库管理」选中后点「修复路径…」重新指定 .mdx 文件")
        elif mounted < len(dicts):
            loading = len(dicts) - mounted
            self._status_dict.setText(
                f"词库加载中 {mounted}/{len(dicts)} 部"
                f"（{loading} 部加载中） · 已就绪 {total_entries:,} 词条")
            self._status_dict.setToolTip("")
        else:
            self._status_dict.setText(
                f"已启用 {len(dicts)} 部词库 · {total_entries:,} 词条")
            self._status_dict.setToolTip("")

    def _on_mount_progress(self, done: int, total: int, name: str):
        self._mount_done, self._mount_total = done, total
        self._status_dict.setText(
            f"词库加载中 {done}/{total}：{name}")
        if not self._results and not self._current_word:
            pass  # 无当前查询时仅更新状态栏

    def _on_dict_mounted(self, dict_id: int):
        self._refresh_dict_status()
        # 挂载完成前发起的查询（结果为空）自动重查
        if self._current_word and not self._results:
            self.do_lookup(self._current_word, push_history=False)

    def open_wordbook(self):
        if self._wordbook_dialog is None:
            self._wordbook_dialog = WordbookDialog(self.wordbook, self)
            self._wordbook_dialog.lookupRequested.connect(
                self.bring_up_and_lookup)
            self.wordbook_changed.connect(
                self._wordbook_dialog.refresh_if_visible)
            # 生词本窗口里改了分组 / 增删了生词 → 同步顶栏下拉框与 ★
            self._wordbook_dialog.groupsChanged.connect(self._reload_groups)
            self._wordbook_dialog.wordsChanged.connect(self._update_star)
        # 打开时定位到顶栏当前选中的分组
        self._wordbook_dialog.select_group(self._selected_group_id())
        self._wordbook_dialog.show()
        self._wordbook_dialog.raise_()
        self._wordbook_dialog.activateWindow()

    def open_settings(self):
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._config.save()
            self.settings_saved.emit()
            if self._tray is not None:
                self._tray.apply_config()

    # ---------------------------------------------------------------- 对外接口
    def bring_up_and_lookup(self, word: str):
        """划词取词后：唤起窗口并查询。"""
        self.show()
        self.raise_()
        self.activateWindow()
        self.do_lookup(word)

    def set_tray(self, tray):
        self._tray = tray

    def notify(self, text: str):
        """在状态栏显示一条提示信息（全局快捷键/取词反馈等）。"""
        self._status_info.setText(text)

    # ---------------------------------------------------------------- 发音播放
    # ---------------------------------------------------------------- 关闭行为
    def closeEvent(self, event):
        if (self._config["minimize_to_tray"] and self._tray is not None
                and self._tray.is_available()):
            event.ignore()
            self.hide()
            if not self._tray_message_shown:
                self._tray_message_shown = True
                self._tray.notify_minimized()
        else:
            event.accept()
