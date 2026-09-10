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
from PySide6.QtNetwork import QHttpHeaders
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
        path = unquote(url.path()).replace("\\", "/").lstrip("/").lower()
        path = path.split("?")[0].split("#")[0]
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

        # HTTP Range 请求支持：HTML5 <audio>/<video> 必须能做分段请求
        # （Accept-Ranges + Content-Range + 206 语义），否则媒体引擎
        # 会直接拒绝加载、报 DOMException。这里从请求头里解析 Range，
        # 按字节切片返回，并补全相关响应头。
        total = len(data)
        range_hdr = ""
        try:
            headers = job.requestHeaders()
            raw = None
            if hasattr(headers, "value"):  # Qt6 QHttpHeaders
                raw = headers.value("Range")
            else:  # 兼容旧版 QMultiMap
                raw = headers.value("Range", "")
            if isinstance(raw, bytes):
                range_hdr = raw.decode("latin-1", errors="ignore")
            elif raw:
                range_hdr = str(raw)
        except Exception:  # noqa: BLE001 拿不到头就当无 Range
            range_hdr = ""

        start = 0
        end = total - 1
        is_partial = False
        if range_hdr.lower().startswith("bytes="):
            spec = range_hdr[6:].strip()
            if "-" in spec:
                s, e = spec.split("-", 1)
                if s:
                    start = int(s)
                if e:
                    end = int(e)
                else:
                    end = total - 1
                if start > end or start >= total:
                    # 越界：返回 416（通过 fail + RequestDenied 近似表达）
                    job.fail(QWebEngineUrlRequestJob.RequestDenied)
                    return
                end = min(end, total - 1)
                is_partial = True

        chunk = data[start:end + 1]
        buf = QBuffer()
        buf.setParent(job)  # 生命周期随 job
        buf.setData(chunk)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)

        resp_headers = QHttpHeaders()
        resp_headers.append("Accept-Ranges", "bytes")
        resp_headers.append("Content-Length", str(len(chunk)))
        if is_partial:
            resp_headers.append(
                "Content-Range",
                f"bytes {start}-{end}/{total}")
        job.setAdditionalResponseHeaders(resp_headers)
        job.reply(guess_mime(path).encode("ascii"), buf)
