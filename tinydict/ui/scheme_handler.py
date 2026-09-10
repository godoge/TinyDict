"""自定义 mdx:// URL Scheme：为 QWebEngineView 提供 MDD 资源。

词条 HTML 通过 view.setHtml(html, QUrl("mdx://<dict_id>/")) 设置 baseUrl，
其中相对引用（<img src="images/a.jpg">、<link href="style.css"> 等）会被
浏览器解析为 mdx://<dict_id>/images/a.jpg，进而走到本 handler，
从各词库的 MDD 原文件按需读取字节流返回。

注意：在 Qt6（Chromium 内核）中，自定义 scheme 必须先用
QWebEngineUrlScheme 注册为「安全 scheme」（并允许 CSP / CORS / 本地访问），
否则 Chromium 会拦截该 scheme 下的所有子资源（图片、CSS），导致图标/样式
全部无法加载。注册必须在 QApplication 创建之前完成。
"""

from urllib.parse import unquote

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWebEngineCore import (
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
    QWebEngineUrlRequestJob,
)

_SCHEME_NAME = b"mdx"
_registered = False


def _register_one_scheme(name: str,
                         syntax=QWebEngineUrlScheme.Syntax.Host):
    """把一个自定义 scheme 注册为本地安全 scheme。

    Qt6（Chromium 内核）会拦截一切未注册的自定义 scheme：
      - 子资源（<img>/<link> 引用的图片/CSS）加载失败；
      - 链接导航（点击 <a href="sound://..."> / <a href="entry://..."> 跳转）
        被直接丢弃，acceptNavigationRequest 根本不会被调用。
    因此 mdx / sound / entry 都必须在 QApplication 创建前注册，
    否则词条样式、发音播放、词条互链会「点了没反应」。
    """
    scheme = QWebEngineUrlScheme(name.encode("ascii"))
    scheme.setSyntax(syntax)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.CorsEnabled
        | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)


def register_all_schemes():
    """注册全部自定义 scheme（须在 QApplication 创建前调用一次）。

    覆盖 mdx（子资源）、sound（发音）、entry（词条互链）。
    """
    global _registered
    if _registered:
        return
    _register_one_scheme("mdx")    # 词条内子资源（图片/CSS/音频数据）
    _register_one_scheme("sound")  # 发音链接导航（点击喇叭播放）
    _register_one_scheme("entry")  # 词条互链导航（点击查词）
    _registered = True


# 兼容旧调用点
register_mdx_scheme = register_all_schemes

MIME_MAP = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".html": "text/html",
    ".htm": "text/html",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".spx": "audio/speex",
    ".mp4": "video/mp4",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".eot": "application/vnd.ms-fontobject",
}

DEFAULT_MIME = "application/octet-stream"


def guess_mime(path: str) -> str:
    dot = path.rfind(".")
    if dot >= 0:
        return MIME_MAP.get(path[dot:].lower(), DEFAULT_MIME)
    return DEFAULT_MIME


class MdxSchemeHandler(QWebEngineUrlSchemeHandler):
    """mdx:// 资源请求处理器（运行于 Qt WebEngine IO 线程，同步查库）。"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

    def requestStarted(self, job):
        try:
            self._handle(job)
        except Exception:  # noqa: BLE001 任何异常都转为 404，避免渲染进程崩溃
            job.fail(QWebEngineUrlRequestJob.UrlNotFound)

    def _handle(self, job):
        url = job.requestUrl()
        if url.scheme() != "mdx":
            job.fail(QWebEngineUrlRequestJob.UrlNotFound)
            return

        host = url.host()  # 词条所属词库 id（来自 baseUrl）
        # 浏览器会对路径做 URL 编码（如 \ -> %5C、空格 -> %20），
        # 先解码再归一化，才能与 MDD 内资源 key 匹配。
        # 注意：?query 和 #fragment 的切分必须在 unquote 之前做——
        #   部分词典的资源文件名本身含 #（如 _good#_brs_25.mp3），
        #   在 URL 里被编码为 %23；若先 unquote 再 split("#")，
        #   会把文件名里的 # 误判为 fragment 分隔符而截断路径，
        #   导致资源 404、例句音频无法播放。
        raw_path = url.path()
        raw_path = raw_path.split("?")[0].split("#")[0]
        path = unquote(raw_path).replace("\\", "/").lstrip("/").lower()
        if not path:
            job.fail(QWebEngineUrlRequestJob.UrlNotFound)
            return

        preferred = int(host) if host.isdigit() else None
        # 首选所属词库；同一路径也会按优先级在其余词库 MDD 中回退查找
        data = self._service.find_resource(preferred, path)
        if data is None:
            # 兜底：部分词库把资源放在带前导目录（如 data/、img/）下，
            # 若上面未命中，再尝试去掉首级目录后匹配。
            data = self._service.find_resource(
                preferred, path.split("/", 1)[-1])
        if data is None:
            job.fail(QWebEngineUrlRequestJob.UrlNotFound)
            return

        buf = QBuffer()
        buf.setParent(job)  # 生命周期随 job
        buf.setData(data)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(guess_mime(path).encode("ascii"), buf)
