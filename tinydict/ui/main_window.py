"""主窗口：搜索 / 建议列表 / 词条渲染（QWebEngineView）/ 历史导航 / 生词星标 / 置顶。"""

import html as _html
import json
import os
import re as _re
import sys
from pathlib import Path

from PySide6.QtGui import QClipboard, QColor, QDesktopServices, QGuiApplication
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QSplitter,
    QStatusBar, QTabBar, QToolButton, QVBoxLayout, QWidget,
)
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from urllib.parse import unquote

from ..core.query import DictionaryService, EntryResult
from ..core.wordbook import DEFAULT_GROUP_ID, WordBook
from ..core.history import HistoryBook, display_text
from ..core import dict_config
from .. import __version__
from ..config import Config
from . import theme as _theme
from .about_dialog import AboutDialog, RELEASES_URL, REPO_URL
from .dict_manager_dialog import DictManagerDialog
from .history_dialog import HistoryDialog
from .resource_inliner import inline_resources
from .scheme_handler import MdxSchemeHandler
from .settings_dialog import SettingsDialog
from .wordbook_dialog import WordbookDialog


def _esc(s: str) -> str:
    return _html.escape(s or "")


def _copy_text(text: str):
    """把字符串放进系统剪贴板。"""
    QGuiApplication.clipboard().setText(text)


def _open_url(url: str):
    """用系统默认浏览器打开 URL。"""
    QDesktopServices.openUrl(QUrl(url))


# ----------------------------------------------------------------------
# 主题诊断日志（默认关闭）：设置环境变量 TINYDICT_DEBUG_THEME=1 开启。
# 词条页每次校正配色时，把页面明暗状态追加写入日志文件，用于排查
# 「某些词库首次正确、切换词条后主题反了」这类只在真实环境出现的时序
# 问题。日志路径可用 TINYDICT_DEBUG_THEME_LOG 覆盖，默认写在当前目录。
# ----------------------------------------------------------------------

_THEME_DEBUG = os.environ.get("TINYDICT_DEBUG_THEME", "").strip() not in (
    "", "0", "false")
_THEME_DEBUG_LOG = Path(
    os.environ.get("TINYDICT_DEBUG_THEME_LOG")
    or Path.cwd() / "tinydict_theme_debug.log")


def _theme_debug_log(line: str):
    """追加一行主题诊断日志；写失败静默忽略（诊断不能影响主功能）。"""
    try:
        with open(_THEME_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# 主题诊断探针：词条渲染后由 Python 侧定时执行，取页面明暗全貌。
# 关注四组信号：html 上的滤镜类、body/卡片的背景与文字色、词库主题类
# （通用地取 .dict-section-all 这类内容容器，仅作观测样本，不参与决策）、
# 词库主题环境（dark_mode 变量 / applyTheme / matchMedia 结果）。
_THEME_PROBE_JS = (
    "JSON.stringify({"
    "dt:(window.__sdT0?Date.now()-window.__sdT0:-1),"
    "href:location.href.slice(0,60),"
    "tgt:String(window.__sdEntryTarget),"
    "inv:document.documentElement.classList.contains('sd-invert'),"
    "htmlCls:document.documentElement.className.slice(0,80),"
    "bodyBg:getComputedStyle(document.body).backgroundColor,"
    "bodyColor:getComputedStyle(document.body).color,"
    "tldDark:document.body?document.body.classList.contains('tld-dark'):null,"
    "card:(function(){var e=document.querySelector('.dict-section-all');"
    "return e?{bg:getComputedStyle(e).backgroundColor,"
    "color:getComputedStyle(e).color,"
    "tld:e.classList.contains('tld-dark')}:null;})(),"
    "darkMode:('dark_mode' in window)?String(window.dark_mode):'x',"
    "applyFn:typeof window.applyTheme,"
    "applyCur:typeof window.applyCurrentDarkTheme,"
    "mq:(window.matchMedia?String("
    "window.matchMedia('(prefers-color-scheme: dark)').matches):null)"
    "})"
)


def _esc_js(s: str) -> str:
    """把任意字符串转成 JS 可直接嵌入的字符串字面量（含引号）。

    用 JSON 编码自动处理反斜杠、引号、换行、制表符等所有转义，
    返回的结果可以直接写进 JS 代码里当作一个完整字符串。
    """
    import json as _json
    return _json.dumps(s)   # 带引号，例如 "body{color:#d4d4d4;}"


def _theme_seed(theme_mode: str, entry_target: str = "native") -> str:
    """把本次渲染使用的主题模式与词条页目标明暗写进页面。

    主题必须随 HTML 一起传递，不能写死在注入脚本的源码里：
    注入脚本只在 DictPage 构造时安装一次，若把模式烘焙进脚本源码，
    切换主题后每个新文档仍会按旧模式执行（表现为窗口变浅了、词条页
    却还是深色）；而脚本集合的改动是异步同步到渲染进程的，运行时
    反复增删脚本还会出现"新文档根本没拿到脚本"的竞态。

    这里只种下两个变量，不调用任何词库函数——词库自己的 applyTheme 在其
    脚本里才定义，<head> 处的种子时机它尚未就绪，提前调用无意义。真正
    应用主题由 DictPage 注入脚本在文档就绪后统一处理。

    entry_target 为 "native" 时表示不干预词条页（应用自生成的页面用，
    它们本来就带完整深浅 CSS）。
    """
    mode = _esc_js(theme_mode)
    target = _esc_js(entry_target)
    return (f"<script>window.__sdThemeMode={mode};"
            f"window.__sdEntryTarget={target};</script>")


def matchmedia_shim_js() -> str:
    """matchMedia 垫片：让词库脚本探测到的配色方案跟随本应用主题。

    Qt WebEngine 的 prefers-color-scheme 只认操作系统深浅色（meta
    color-scheme / QStyleHints.setColorScheme 均覆盖不了），而多数现代词库
    是用 matchMedia('(prefers-color-scheme: dark)') 决定是否套深色皮肤的。
    这里在 <head> 最早处重写 window.matchMedia：对包含 prefers-color-scheme
    的查询按 window.__sdThemeMode 求值，其它查询原样交给原生实现。
    不针对具体词库，对所有词库通用。
    """
    return (
        "(function(){"
        "if(!window.matchMedia)return;"
        "var orig=window.matchMedia.bind(window);"
        "function fake(q,matches){return{matches:matches,media:q,onchange:null,"
        "addListener:function(){},removeListener:function(){},"
        "addEventListener:function(){},removeEventListener:function(){},"
        "dispatchEvent:function(){return false;}};}"
        "window.matchMedia=function(q){"
        "var s=String(q||'');"
        "var m=s.match(/prefers-color-scheme\\s*:\\s*(dark|light)/i);"
        "if(!m)return orig(s);"
        "var want=m[1].toLowerCase();"
        "var mode=window.__sdThemeMode||'light';"
        "if(want!==mode)return fake(s,false);"
        # 与主题一致：仅含 prefers-color-scheme 一个条件时恒真，
        # 还与其它条件组合（如 max-width）时交原生求值
        "var rest=s.replace(/prefers-color-scheme\\s*:\\s*(dark|light)/i,'');"
        "if(/[\\w-]\\s*:/.test(rest))return orig(s);"
        "return fake(s,true);"
        "};"
        "})();"
    )


def entry_theme_js() -> str:
    """生成「通用」词条页配色脚本——对所有词库执行完全相同的逻辑。

    设计原则：不出现任何词库名，不注入高特异性 !important 覆盖（那会
    压平词库自带的配色/背景/排版，表现为词条页「变样」）。流程只有三步：

    1) 目标为 native → 直接收工，词条页保持词库原样，一个字节都不改；
    2) 若词库自己暴露了 window.applyTheme，就用它的原生实现切到目标
       明暗（这是保真度最高的路径，外观完全是词库自己的设计）；
    3) 实测页面整体明暗，若与目标不一致，才给 <html> 加上 sd-invert
       类启用通用反色滤镜——明暗对调但保留配色关系与排版。这一步对
       所有词库一视同仁，是静态词库（无主题系统）的兜底。

    目标不写死进脚本源码：真正的目标来自每次渲染都重新携带的 HTML 种子
    window.__sdEntryTarget，切换主题后新文档会自动按新目标执行。

    本脚本随 HTML 内联，而不是用 QWebEngineScript 注入：实测注入脚本在
    反复 setHtml 的页面上存在"新文档拿不到脚本"的竞态（表现为同一词条
    第一次配色正确、切回来就变浅），内联脚本随文档解析执行，必然生效。
    """
    return (
        "(function(){"
        "window.__sdT0=Date.now();"
        # 解析一个 CSS 颜色的明暗；透明（alpha<0.5）返回 null 表示"看不出来"
        "function sdIsDark(c){"
        "var m=/rgba?\\(([^)]+)\\)/i.exec(String(c||''));"
        "if(!m)return null;"
        "var p=m[1].split(',');"
        "var a=p.length>3?(parseFloat(p[3])||0):1;"
        "if(a<0.5)return null;"
        "var r=parseFloat(p[0])||0,g=parseFloat(p[1])||0,b=parseFloat(p[2])||0;"
        "return (0.299*r+0.587*g+0.114*b)<128;"
        "}"
        "function sdPageIsDark(){"
        "try{"
        "var d=sdIsDark(getComputedStyle("
        "document.body||document.documentElement).backgroundColor);"
        "if(d!==null)return d;"
        "d=sdIsDark(getComputedStyle(document.documentElement).backgroundColor);"
        "if(d!==null)return d;"
        "}catch(e){}"
        # 整页背景都透明 → 按浅色处理：此时画布色由 Qt 提供（已是目标明暗），
        # 正文通常是黑色，翻转后正好变成白字压在深色画布上。
        "return false;"
        "}"
        "var last=null;var applied=false;"
        "function sdApplyEntryTheme(force){"
        "var r=document.documentElement;"
        "if(!r)return;"
        "var t=window.__sdEntryTarget||'native';"
        "if(t==='native'){"
        "if(last!=='native'){last='native';r.classList.remove('sd-invert');}"
        "return;}"
        # 词库自带主题函数：每个文档只调用一次（force 除外）。
        # 老实现每次复查都调用，遇到 toggle 型实现会被反复翻转，
        # 最终明暗取决于调用次数的奇偶——这正是「切回某个词条后主题
        # 反过来」的一类成因。
        "if((!applied||force)&&typeof window.applyTheme==='function'){"
        "applied=true;"
        "try{window.applyTheme(t);}catch(e){}"
        "}"
        "var want=(t==='dark');"
        "var need=(sdPageIsDark()!==want);"
        # 结论没变就一个字节都不动：既避免与词库自身的 MutationObserver
        # 互相触发，也保证本函数幂等（重复执行结果完全一致）。
        "if(need===last)return;"
        "last=need;"
        "if(need){r.classList.add('sd-invert');}"
        "else{r.classList.remove('sd-invert');}"
        "}"
        "window.__sdApplyEntryTheme=function(force){"
        "last=null;sdApplyEntryTheme(!!force);};"
        "function sdSchedule(){"
        "sdApplyEntryTheme();"
        # 词库脚本与样式表常常是异步就绪的（外链 CSS/JS、延迟注入的
        # 主题类），而词条容器要到 1200ms 才揭幕；复查点必须覆盖到
        # 揭幕之后，否则用户看到的是过期结论。
        "[0,80,300,800,1500,3000].forEach(function(ms){"
        "setTimeout(function(){sdApplyEntryTheme();},ms);});"
        # 所有资源加载完毕后再校正一次：此时词库自己的脚本一定已执行
        "window.addEventListener('load',function(){"
        "sdApplyEntryTheme();"
        "setTimeout(function(){sdApplyEntryTheme();},200);"
        "setTimeout(function(){sdApplyEntryTheme();},800);});"
        # 长期观察：无论词库在什么时候改动 DOM/class（延迟注入暗色样式、
        # 点开折叠区后重排等），都重新校正一次。debounce 合并，且结论
        # 不变时不碰 DOM，因此不会自激震荡。
        "if(typeof MutationObserver!=='undefined'){"
        "var pending=false;"
        "var mo=new MutationObserver(function(){"
        "if(pending)return;pending=true;"
        "setTimeout(function(){pending=false;sdApplyEntryTheme();},80);});"
        "try{mo.observe(document.documentElement,{childList:true,"
        "subtree:true,attributes:true,"
        "attributeFilter:['class','style']});}catch(e){}"
        "}"
        "}"
        "if(document.readyState!=='loading'){sdSchedule();}"
        "else{document.addEventListener('DOMContentLoaded',sdSchedule);}"
        "})();"
    )


def _page(inner: str, theme_mode: str = "light") -> str:
    """组装完整 HTML 页面：注入默认 CSS + 主题种子 + 尾部脚本。

    这里的默认 CSS 仅用于应用「自己生成」的页面（欢迎页 / 未找到 /
    加载中 / 纯文本词条模板）——它们已有完整的深浅两套样式，因此词条页
    目标恒为 "native"（不干预）。真实词库词条的明暗由通用方案处理
    （见 entry_page / DictPage 注入脚本）。
    """
    css = _theme.entry_css(theme_mode)
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>{css}</style>{_theme_seed(theme_mode, 'native')}</head>"
        f"<body>{inner}</body></html>"
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


def entry_page(raw_html: str, word: str, theme_mode: str = "light",
               entry_target: str = "native") -> str:
    """把 MDX 词条内容包装为完整 HTML 文档。

    - 词条本身带样式（<link>/<style>）：原样使用，尊重词库排版；
    - 结构化但无样式：注入默认样式；
    - 纯文本词条：套默认词条模板。

    entry_target 是词条页的目标明暗（"light" / "dark" / "native"），
    由 theme.resolve_entry_theme() 从「词条页配色」设置解析而来。只有真实
    词库词条（自带样式的那种）才需要它；应用自生成的页面走 _page()，
    目标恒为 "native"。
    """
    s = (raw_html or "").strip()
    if not s:
        return _page(f'<div class="sd-headword">{_esc(word)}</div>'
                     f'<p class="sd-tip">（该词条内容为空）</p>',
                     theme_mode)
    lower = s.lower()
    head = lower[:400]
    if s.startswith("<") or "<html" in head or "<div" in head or "<table" in head:
        if "<link" not in lower and "<style" not in lower:
            # 无样式的结构化词条：用应用自带 CSS（已有深浅两套），不干预
            return _page(s, theme_mode)
        # 已带样式：内容已解码为 str（UTF-8）交给 WebEngine，
        # 清掉词条里原有的非 UTF-8 charset 声明以免乱码
        s = _re.sub(r"<meta[^>]*charset[^>]*>", "", s, flags=_re.I)
        # 通用滤镜：所有词库共用同一份 CSS，不含任何词库名或词库专有选择器。
        # 滤镜本身不生效，只有注入脚本实测到「页面明暗与目标不一致」时，
        # 才会给 <html> 加上 sd-invert 类启用它。
        filter_css = (
            f'<style id="sd-entry-filter">{_theme.entry_filter_css()}</style>')
        # 垫片必须早于词库自己的脚本：很多词库在加载时就用 matchMedia
        # 决定明暗，晚一步它们就按系统（而非本应用）的配色套皮肤了。
        shim = f"<script>{matchmedia_shim_js()}</script>"
        if "<head" in lower:
            # 用函数做替换，避免反向引用 \1 在 f-string 里被误解析
            s = _re.sub(
                r"(<head[^>]*>)",
                lambda m: (m.group(1) + '<meta charset="utf-8">'
                           + shim
                           + _theme_seed(theme_mode, entry_target)
                           + filter_css),
                s, count=1, flags=_re.I,
            )
        else:
            s = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                 + shim
                 + _theme_seed(theme_mode, entry_target)
                 + filter_css + "</head>"
                 f"<body>{s}</body></html>")
        # 配色脚本内联在文档尾部：随解析执行，不依赖注入脚本的时序
        s = _wrap_with_guard(s)
        tail = f"<script>{entry_theme_js()}</script>"
        end = s.lower().rfind("</body>")
        return s[:end] + tail + s[end:] if end > 0 else s + tail
    return _page(
        f'<div class="sd-headword">{_esc(word)}</div>'
        f'<div class="sd-plain">{_esc(s)}</div>',
        theme_mode,
    )


def welcome_page(theme_mode: str = "light") -> str:
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
</div>""", theme_mode)


def not_found_page(word: str, theme_mode: str = "light") -> str:
    return _page(
        f'<div class="sd-headword">{_esc(word)}</div>'
        '<div class="sd-notfound">'
        "<p><b>没有找到该词条</b></p>"
        "<p>建议：</p>"
        "<ul><li>检查拼写（可参考左侧候选列表）</li>"
        "<li>在「词库」中确认词库已启用且状态为「就绪」"
        "（新添加的词库后台加载中，稍候即可查询）</li></ul>"
        "</div>",
        theme_mode,
    )


def loading_page(word: str, pending: int, theme_mode: str = "light") -> str:
    """仍有词库在后台加载时的占位页。

    词库挂载是异步的，加载期间直接显示「未找到词条」会误导用户
    （实际是还没查，而不是查不到）。这里明确告知状态，加载完成后
    MainWindow 会自动重新查询并替换本页。
    """
    n = max(1, int(pending))
    return _page(
        f'<div class="sd-headword">{_esc(word)}</div>'
        '<div class="sd-notfound">'
        f"<p><b>还有 {n} 部词库正在加载…</b></p>"
        "<p>已加载完的词库里没有找到该词条，加载完成后会自动重新查询。</p>"
        "</div>",
        theme_mode,
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

    def __init__(self, *args, theme_mode: str = "light", **kwargs):
        super().__init__(*args, **kwargs)
        self._theme_mode = theme_mode

    def set_theme_mode(self, mode: str, entry_target: str = "native"):
        """运行时切换主题模式（由 MainWindow._reapply_theme 调用）。

        更新页面里的两个种子并立即重新执行通用配色逻辑：后续渲染的词条
        HTML 自带新种子会按新目标执行，而"当前已加载"的页面则由这里直接
        触发一次，无需重新渲染。
        """
        self._theme_mode = mode
        # 传 true：允许再调用一次词库自带的主题函数（切换主题时需要它跟着切），
        # 并强制重算结论（last 缓存失效）。
        self.runJavaScript(
            f"try{{window.__sdThemeMode={_esc_js(mode)};"
            f"window.__sdEntryTarget={_esc_js(entry_target)};}}catch(e){{}}"
            f"if(window.__sdApplyEntryTheme)window.__sdApplyEntryTheme(true);")

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # 主题诊断：保留 console.log 上报通道（前缀 SDTHEME），
        # 诊断优先于下面的级别过滤。
        if isinstance(message, str) and message.startswith("SDTHEME "):
            _theme_debug_log(message[len("SDTHEME "):])
            return
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


class EntryView(QWebEngineView):
    """词条视图：接管右键菜单。

    原生菜单只有「复制 / 全选 / 后退」等通用项，这里额外加一条
    「搜索「xxx」」——在释义里选中任意词后右键即可直接查它，
    免去手动复制到搜索框的步骤。

    注意：重写 contextMenuEvent 且不调用基类实现，因此默认菜单不会出现，
    下面把常用项（复制 / 后退 / 重新加载 / 全选）一并保留，功能不减。
    """

    search_requested = Signal(str)

    # 菜单标签的最大显示长度，过长会截断，避免撑爆菜单宽度
    LABEL_MAX = 24

    def contextMenuEvent(self, event):
        page = self.page()
        if page is None:
            return

        # 归一化空白：释义里跨行选中会带换行符，压成单个空格才能正常查词
        sel = " ".join((page.selectedText() or "").split())

        menu = QMenu(self)
        act_search = None
        if sel:
            label = (sel if len(sel) <= self.LABEL_MAX
                     else sel[:self.LABEL_MAX] + "…")
            act_search = menu.addAction(f"搜索「{label}」")
            menu.addAction("复制", lambda: self._copy(sel))
            menu.addSeparator()

        act_back = menu.addAction("后退")
        # setHtml 也会进历史，故以 action 的可用状态为准
        act_back.setEnabled(page.action(QWebEnginePage.WebAction.Back).isEnabled())
        act_reload = menu.addAction("重新加载")
        menu.addSeparator()
        act_all = menu.addAction("全选")

        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen is act_search:
            self.search_requested.emit(sel)
        elif chosen is act_back:
            page.triggerAction(QWebEnginePage.WebAction.Back)
        elif chosen is act_reload:
            page.triggerAction(QWebEnginePage.WebAction.Reload)
        elif chosen is act_all:
            page.triggerAction(QWebEnginePage.WebAction.SelectAll)

    @staticmethod
    def _copy(text: str):
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text, QClipboard.Mode.Clipboard)


# ----------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------


class MainWindow(QMainWindow):
    settings_saved = Signal()      # 设置已保存（app 层据此重绑快捷键）
    wordbook_changed = Signal()    # 生词本内容变化
    dicts_changed = Signal()       # 词库增删/顺序变化（由管理对话框发出）
    quit_requested = Signal()      # 要求彻底退出进程（未启用"最小化到托盘"时点关闭）

    def __init__(self, service: DictionaryService, config: Config,
                 wordbook: WordBook, theme_manager: "_theme.ThemeManager | None" = None,
                 history: "HistoryBook | None" = None, parent=None):
        super().__init__(parent)
        self._service = service
        self._config = config
        self.wordbook = wordbook
        # 查询历史（可选：测试里不传即不记录）
        self.history = history
        self._theme_manager = theme_manager
        self._results: list[EntryResult] = []
        self._current_word = ""
        # 上一次查词时"已挂载完成、实际参与查询"的词库 id 集合。
        # 词库是后台异步挂载的：若查词时某部词库尚未挂载完，它不会出现在结果里；
        # 该词库挂载完成后需要据此判断"本次结果不完整"并自动重查补齐。
        self._queried_dict_ids: set[int] = set()
        self._history: list[str] = []
        self._hist_pos = -1
        self._tray = None               # 由 app 层注入
        self._tray_message_shown = False
        self._wordbook_dialog = None
        self._dict_dialog = None
        self._history_dialog = None

        self.setWindowTitle(f"TinyDict 离线词典 v{__version__}")
        self.resize(980, 680)
        self._apply_qss()

        self._build_ui()
        # 顶栏分组下拉框（★ 的归属分组）；生词变化时同步刷新计数
        self._reload_groups()
        self.wordbook_changed.connect(self._reload_groups)
        self._view.setHtml(welcome_page(self._current_theme_mode()), QUrl("mdx://0/"))
        self._suggest_timer = QTimer(self, singleShot=True, interval=250)
        self._suggest_timer.timeout.connect(self._refresh_suggestions)
        # 启动时搜索框是空的，先把最近查过的词列出来（有历史才显示）
        self._refresh_suggestions()

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

        # 主题变化时自动刷新
        if self._theme_manager is not None:
            self._theme_manager.theme_changed.connect(self._reapply_theme)

    # ------------------------------------------------------------ 主题切换
    def _current_theme_mode(self) -> str:
        """返回当前生效的主题模式（"light" 或 "dark"）。"""
        if self._theme_manager is not None:
            return self._theme_manager.mode
        return _theme.resolve_theme(str(self._config["theme"]))

    def _apply_qss(self):
        """根据当前主题设置主窗口的 QSS。"""
        self.setStyleSheet(_theme.app_qss(self._current_theme_mode()))

    def _entry_target(self) -> str:
        """返回词条页的目标明暗（"light" / "dark" / "native"）。

        由「词条页配色」设置 + 当前应用主题共同决定；解析规则在
        theme.resolve_entry_theme() 里，对任何词库通用。
        """
        return _theme.resolve_entry_theme(
            str(self._config["entry_theme"]), self._current_theme_mode())

    def _apply_page_background(self):
        """设置词条页画布颜色，兜住"无背景色词条/加载瞬间"的显示。

        Qt WebEngine 的 prefers-color-scheme 只认操作系统：系统深色时
        UA 画布默认是黑色，即便应用已切到浅色主题。这里显式指定画布颜色
        来纠正。画布色同时也是通用反色滤镜的底板——滤镜只作用于 DOM 内部，
        透明区域透出的正是这个画布色，因此它天然等于目标明暗。
        """
        if self._page is None:
            return
        self._page.setBackgroundColor(
            QColor(255, 255, 255) if self._current_theme_mode() == "light"
            else QColor(30, 30, 30))

    def _schedule_theme_probe(self):
        """诊断模式：渲染后在几个关键时间点取词条页明暗状态写入日志。

        时间点覆盖「词库脚本/CSS 异步生效」的常见窗口（含 1200ms 揭幕
        之后），足够看清结论是在哪个时刻、被什么改变的。
        """
        if self._page is None:
            return
        for ms in (400, 1000, 2200, 5000):
            QTimer.singleShot(ms, lambda: self._page.runJavaScript(
                _THEME_PROBE_JS,
                lambda v: _theme_debug_log(str(v))))

    def _reapply_theme(self, new_mode: str):
        """主题变化时调用：更新 QSS、通知 DictPage、并重新渲染当前词条。"""
        self._apply_qss()
        self._apply_page_background()
        # 让已加载词条立即按新的目标明暗重算（无需重新渲染也能生效）
        self._page.set_theme_mode(new_mode, self._entry_target())
        if self._results:
            self._render_current()
        elif self._current_word:
            # 有当前查词词但结果被清空（少见），重新查一次即可
            self.do_lookup(self._current_word, push_history=False)
        else:
            # 欢迎页也换肤
            self._view.setHtml(
                welcome_page(new_mode), QUrl("mdx://0/"))

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

        # 搜索框移到左侧候选词列表上方（见下方 left_panel），顶栏不再单独
        # 占一行那么宽的位置；完整提示挪到 tooltip，窄框里只留短占位文。
        self.search_edit = QLineEdit(objectName="search_edit")
        self.search_edit.setPlaceholderText("输入单词，回车查词")
        self.search_edit.setToolTip(
            "输入单词查询，回车查词（Ctrl+Alt+D 显示/隐藏窗口）")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._on_return)
        self.search_edit.textChanged.connect(self._on_text_changed)

        # 顶栏去掉搜索框后，左端放导航、右端放功能按钮，中间弹性撑开
        top.addStretch(1)

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
            ("历史", "查看查询历史", self.open_history),
            ("设置", "快捷键等设置", self.open_settings),
        ):
            b = QToolButton(text=text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            top.addWidget(b)

        # 「关于」按钮：直接弹出关于对话框
        self._btn_about = QToolButton(text="关于")
        self._btn_about.setToolTip("关于本软件")
        self._btn_about.clicked.connect(self.open_about)
        top.addWidget(self._btn_about)
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
        self._page = DictPage(self._profile, self,
                              theme_mode=self._current_theme_mode())
        self._apply_page_background()
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

        self._view = EntryView()
        self._view.setPage(self._page)
        # 右键「搜索「xxx」」：以选中的文本直接查词
        self._view.search_requested.connect(self.do_lookup)

        # 词条页容器：顶部词典切换标签 + 下方词条内容，使切换标签成为
        # 词条页的页头（只压在词条内容上方，不再横跨左侧联想列表）
        entry_page = QWidget()
        entry_vbox = QVBoxLayout(entry_page)
        entry_vbox.setContentsMargins(0, 0, 0, 0)
        entry_vbox.setSpacing(0)
        entry_vbox.addWidget(self._tabs)
        entry_vbox.addWidget(self._view)

        # 左侧面板：搜索框与候选词列表同属一个带边框的卡片（#search_panel），
        # 输入框在上、结果紧贴其下，视觉上是一个整体；搜索框不再单独横跨
        # 整个窗口顶栏。间距设 0，让两者无缝接成一体。
        left_panel = QFrame(objectName="search_panel")
        left_vbox = QVBoxLayout(left_panel)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(0)
        left_vbox.addWidget(self.search_edit)
        left_vbox.addWidget(self.suggest_list, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
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
            # 还没输入时，把最近查过的词直接列出来，点一下就能再看
            self._fill_recent_history()
            return
        for word in self._service.suggest(text, limit=30):
            item = QListWidgetItem(word)
            item.setToolTip(word)
            self.suggest_list.addItem(item)

    def _fill_recent_history(self):
        """搜索框为空时用最近的查询历史填充候选列表。"""
        if self.history is None:
            return
        if not bool(self._config["history_enabled"]):
            return
        for word, queried_at, times in self.history.recent(limit=30):
            item = QListWidgetItem(display_text(word, queried_at, times))
            item.setData(Qt.ItemDataRole.UserRole, word)
            item.setToolTip(f"{word} · 最近查过")
            self.suggest_list.addItem(item)

    def _on_suggestion_clicked(self, item: QListWidgetItem):
        # 是否把点击的词条同步写入搜索框，由设置 fill_input_on_select 控制
        # （默认关闭：只显示释义，不改变搜索框内容，便于在候选列表里连续浏览）。
        # 历史记录项的显示文本带时间后缀，真正的词存在 UserRole 里
        word = item.data(Qt.ItemDataRole.UserRole) or item.text()
        self.do_lookup(
            str(word),
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
                  sync_input: bool = True, preserve_tab: bool = False):
        """查词并渲染。

        sync_input=True 时把词条写入上方搜索框，并刷新左侧候选列表
        （历史/回车/词条内互链等默认路径保持 True）；
        左侧候选点击受设置 fill_input_on_select 控制，关闭时为 False，
        此时只显示释义、不改变搜索框，也避免候选列表被无谓刷新。

        preserve_tab=True 时保留当前选中的词典标签页（用于"词库挂载完成后
        自动重查补齐"，避免把用户正在看的那一页跳回第一个）。
        """
        word = (word or "").strip()
        if not word:
            return
        self._current_word = word

        if sync_input and self.search_edit.text() != word:
            self.search_edit.blockSignals(True)
            self.search_edit.setText(word)
            self.search_edit.blockSignals(False)

        # 记录本次实际参与查询的词库（只有已挂载完成的才参与），
        # 供后续「新词库挂载完成 → 结果是否不完整」的判断使用。
        self._queried_dict_ids = {
            d.id for d in self._service.enabled_dicts()
            if self._service.is_mounted(d.id)
        }

        pending = self._pending_mount_count()
        self._results = self._service.lookup(word)
        mode = self._current_theme_mode()
        if self._results:
            self._setup_tabs(preserve_current=preserve_tab)
            self._render_current()
        else:
            self._tabs.blockSignals(True)
            self._tabs.hide()
            self._tabs.blockSignals(False)
            if pending:
                self._view.setHtml(loading_page(word, pending, mode),
                                   QUrl("mdx://0/"))
                self._status_info.setText(
                    f"还有 {pending} 部词库正在加载，完成后自动重新查询")
            else:
                self._view.setHtml(not_found_page(word, mode), QUrl("mdx://0/"))
                self._status_info.setText("未找到词条")

        if push_history:
            self._push_history(word)

        # 记录查询历史：只在"查到了"或"结果待补齐"时记，
        # 避免把随手打错的词也塞进历史。
        if self.history is not None and bool(self._config["history_enabled"]):
            if self._results or pending:
                self.history.record(word)
                if self._history_dialog is not None:
                    self._history_dialog.refresh_if_visible()

        self._update_star()
        # 仅当搜索框内容被本次查词改变时，才刷新候选列表
        if sync_input:
            self._suggest_timer.start()

    def _setup_tabs(self, preserve_current: bool = False):
        # 重查补齐时保留用户正在看的那一页，避免被跳回第一个词典
        prev = self._tabs.currentIndex() if preserve_current else 0
        self._tabs.blockSignals(True)
        while self._tabs.count() > 0:
            self._tabs.removeTab(0)
        for r in self._results:
            self._tabs.addTab(r.dict_name)
        self._tabs.setVisible(len(self._results) > 1)
        if preserve_current and 0 <= prev < len(self._results):
            self._tabs.setCurrentIndex(prev)
        else:
            self._tabs.setCurrentIndex(0)
        self._tabs.blockSignals(False)

    def _pending_mount_count(self) -> int:
        """尚未挂载完成的启用词库数量（挂载是后台异步进行的）。"""
        return sum(
            1 for d in self._service.enabled_dicts()
            if not self._service.is_mounted(d.id)
        )

    def _current_result(self):
        idx = max(self._tabs.currentIndex(), 0)
        return self._results[min(idx, len(self._results) - 1)]

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
        self._view.setHtml(entry_page(raw, r.word, self._current_theme_mode(),
                                      self._entry_target()),
                           QUrl(f"mdx://{r.dict_id}/"))
        if _THEME_DEBUG:
            _theme_debug_log(
                f"=== render word={r.word!r} dict={r.dict_id} "
                f"target={self._entry_target()} "
                f"mode={self._current_theme_mode()} ===")
            self._schedule_theme_probe()
        others = len(self._results) - 1
        pending = self._pending_mount_count()
        msg = f"词典：{r.dict_name}"
        if others > 0:
            msg += f" · 另有 {others} 部词库命中"
        if pending:
            # 结果尚不完整，必须提示，否则用户会以为"这个词库查不到"。
            # 注意这里不能用 elif：命中多部词库的同时仍可能有词库在加载，
            # 那种情况下结果同样是不完整的。
            msg += f" · 另有 {pending} 部词库仍在加载，完成后自动补齐"
        self._status_info.setText(msg)

        # 调试：把词条处理前后的 HTML 与资源诊断落盘。
        # 由环境变量指定要调试的词（不写死任何词典/单词）：
        #   set TINYDICT_DEBUG_WORD=for
        _dbg_word = os.environ.get("TINYDICT_DEBUG_WORD", "").strip().lower()
        if _dbg_word and r.word.lower() == _dbg_word:
            from .resource_inliner import _MISS_LOG
            debug_dir = Path(__file__).resolve().parent.parent.parent / ".tmpwheels"
            debug_dir.mkdir(exist_ok=True)
            (debug_dir / f"debug_{r.dict_id}_before.html").write_text(
                r.html() or "", encoding="utf-8", errors="ignore")
            (debug_dir / f"debug_{r.dict_id}_after.html").write_text(
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
                self._service, config=self._config,
                theme_manager=self._theme_manager, parent=self)
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
        # 词库是后台异步挂载的，挂载完成顺序不确定。若当前这次查词发生时
        # 该词库还没挂载完，它就不会出现在结果里——此时结果是不完整的，
        # 需要在它挂载完成后自动重查补齐（保留用户正在看的词典页）。
        #
        # 判断依据是「该词库是否参与了上一次查词」，而不是「结果是否为空」：
        # 后者只在所有词库都没命中时才重查，会导致「TLD 先命中、OALDPEX
        # 后挂载完」时 OALDPEX 的标签页永远不出现，只能手动重新搜索。
        if not self._current_word:
            return
        if dict_id in self._queried_dict_ids:
            return  # 已参与过上次查询，结果本就完整
        if not any(d.id == dict_id for d in self._service.enabled_dicts()):
            return  # 该词库已被禁用/移除，无需重查
        self.do_lookup(self._current_word, push_history=False,
                       preserve_tab=True)

    def open_wordbook(self):
        if self._wordbook_dialog is None:
            self._wordbook_dialog = WordbookDialog(
                self.wordbook, config=self._config,
                theme_manager=self._theme_manager, parent=self)
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

    def open_history(self):
        """打开查询历史窗口（没有历史对象时直接提示，不弹空窗）。"""
        if self.history is None:
            QMessageBox.information(self, "查询历史", "当前未启用查询历史。")
            return
        if self._history_dialog is None:
            self._history_dialog = HistoryDialog(
                self.history, config=self._config,
                theme_manager=self._theme_manager, parent=self)
            # 不走 bring_up_and_lookup：那个会强行把主窗口抬到最前，
            # 翻历史时窗口被盖住就没法连续查看了。
            self._history_dialog.lookupRequested.connect(self.do_lookup)
        self._history_dialog.refresh()
        self._history_dialog.show()
        self._history_dialog.raise_()
        self._history_dialog.activateWindow()

    def open_settings(self):
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._config.save()
            self.settings_saved.emit()
            # 没有 ThemeManager 时（少见）信号链不存在，这里直接刷新一次，
            # 保证「词条页配色」改完立即生效，而不是等下次查词。
            if self._theme_manager is None:
                self._reapply_theme(self._current_theme_mode())
            if self._tray is not None:
                self._tray.apply_config()

    def open_about(self):
        dlg = AboutDialog(dict_summary=self._dict_summary(), parent=self)
        dlg.exec()

    def _dict_summary(self) -> str:
        """供「关于」对话框使用的词典数量摘要，失败或为空时返回空串。"""
        try:
            enabled = list(self._service.enabled_dicts())
        except Exception:
            return ""
        if not enabled:
            return ""
        mounted = sum(1 for d in enabled
                      if self._service.is_mounted(d.id))
        return f"{len(enabled)} 部（{mounted} 部已就绪）"

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
            # 未启用"最小化到托盘"：仅 accept 只是关掉窗口本身，而 app 层设了
            # setQuitOnLastWindowClosed(False)，事件循环与托盘图标仍会驻留，
            # 必须由 app 层真正退出进程。
            self.quit_requested.emit()
