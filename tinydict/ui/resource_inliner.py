"""将词条 HTML 内的外链资源（<img>/<link>/<script>/url()）内联为 data URI。

为彻底规避 Qt WebEngine 在不同版本下对自定义 scheme 子资源加载的脆弱性，
在 setHtml 之前把图片、CSS、脚本等资源直接转成 data URI 嵌入 HTML，浏览器
无需再发任何 mdx:// 子资源请求——图标、CSS 必现。资源仍由
DictionaryService.find_resource 从 MDD 按需读取（带 LRU 块缓存，重复快）。
"""

import base64
import json
import os
import re
from html import escape
from typing import Callable, Optional
from urllib.parse import unquote

_DEBUG = os.environ.get("SD_DEBUG_RESOURCES", "0") == "1"

from ..core.query import DictionaryService
from .scheme_handler import DEFAULT_MIME, guess_mime

# (tag, attribute) 列表：命中即把对应属性值改写为 data URI
_TAG_ATTRS = (
    ("img", "src"),
    ("img", "srcset"),      # 响应式图片：1x/2x/3x 多 URL
    ("input", "src"),       # type=image
    ("embed", "src"),
    ("source", "src"),
    ("source", "srcset"),
    ("audio", "src"),
    ("video", "src"),
    ("video", "poster"),
    ("script", "src"),
    # <link> 不在此处处理：stylesheet 由 _inline_stylesheets 合并为单 <style>，
    # 其余 link（icon/prefetch）由 _rewrite_other_links 处理。
    # <a href=entry://...> 不在内：仍由 acceptNavigationRequest 拦截
)

# url(...) 出现在 <style> 块或 style="..." 属性里时使用
_URL_RE = re.compile(r"""url\(\s*(['"]?)([^)'"]+)\1\s*\)""")
_STYLE_BLOCK_RE = re.compile(
    r"(<style\b[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)
_STYLE_ATTR_RE = re.compile(
    r'(\bstyle\s*=\s*)(["\'])((?:(?!\2).)*?)\2',
    re.IGNORECASE | re.DOTALL)


def _attr_re(tag: str, attr: str) -> re.Pattern:
    """匹配 <TAG ... attr="value"> 中 attr 的值（值内不含同名引号）。"""
    return re.compile(
        rf'(<\s*{tag}\b[^>]*?\b{attr}\s*=\s*)(["\'])((?:(?!\2).)*)\2',
        re.IGNORECASE | re.DOTALL,
    )


# 不需解析的 URL scheme（避免误把 entry://、外链、JS 锚点当资源路径）
_SKIP_PREFIXES = (
    "data:", "http:", "https:", "entry:", "javascript:",
    "about:", "mailto:", "mms:", "tel:", "sound:", "#",
)

# 资源路径常见目录前缀（HTML 写相对路径，MDD 里可能放在这些目录下）
_COMMON_PREFIXES = ("", "images/", "image/", "img/", "pic/", "pics/", "css/")

# 图片扩展名（用于判断是否对缺失引用生成占位徽标）
_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico")


def _is_remote(url: str) -> bool:
    """是否指向远程 / 非本地资源（这类不应生成占位图）。"""
    low = (url or "").strip().lower()
    return low.startswith(_SKIP_PREFIXES)


def _looks_like_image(url: str) -> bool:
    low = (url or "").strip().lower().split("?")[0].split("#")[0]
    return low.endswith(_IMG_EXT)


def _basename_label(url: str) -> str:
    s = (url or "").strip().split("?")[0].split("#")[0].rsplit("/", 1)[-1]
    s = unquote(s)
    for ext in _IMG_EXT:
        if s.lower().endswith(ext):
            s = s[: -len(ext)]
            break
    return s or "?"


def _placeholder_img(label: str) -> str:
    """为缺失的图标生成一个浅灰圆角文字徽标（显示来源缩写，如 v/mw/lus）。

    仅作为「找不到真实图标」时的可读占位，避免浏览器显示破图框。
    """
    from urllib.parse import quote
    label = (label or "?").strip()[:6]
    safe = escape(label, quote=False)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
        '<rect width="40" height="20" rx="4" fill="#e5e7eb"/>'
        f'<text x="20" y="14" font-size="11" text-anchor="middle" '
        f'fill="#6b7280" font-family="Microsoft YaHei,sans-serif">{safe}</text>'
        '</svg>'
    )
    return "data:image/svg+xml;utf8," + quote(svg)

# 未命中资源诊断记录：(原始引用 url, 尝试过的候选路径列表)
_MISS_LOG: list = []


def _normalize(path: str) -> str:
    s = (path or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith(_SKIP_PREFIXES):
        return ""
    if low.startswith("mdx://"):
        s = re.sub(r"^mdx://[^/]*/?", "", s, flags=re.I)
    # 去掉 query / fragment，浏览器常附加随机参数防缓存
    s = s.split("?")[0].split("#")[0]
    # 浏览器对 URL 路径会做百分号编码；与 scheme handler 归一化保持一致
    return unquote(s).replace("\\", "/").lstrip("/").lower()


def _to_data_uri(data: bytes, src: str, force_mime: str = None) -> str:
    mime = force_mime or guess_mime(src) or DEFAULT_MIME
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


# <script src> 即便文件扩展名是 .ini/.txt，其本质也是 JS（如 TLD 的 config.ini
# 实为全局变量赋值脚本）。浏览器会按 data URI 的 MIME 校验脚本可执行性，
# 非 JS MIME（如 application/octet-stream / text/plain）会被拒绝执行，导致
# 依赖这些全局变量的后续脚本（如 fy.js 的 applyConfig）读到 undefined 而错乱。
# 因此内联脚本一律强制 text/javascript。
def _resolve_js(url: str, service: DictionaryService, dict_id: int) -> Optional[str]:
    p = _normalize(url)
    if not p:
        return None
    for cand in _build_candidates(p):
        data = service.find_resource(dict_id, cand)
        if data is not None:
            return "data:text/javascript;base64," + base64.b64encode(data).decode("ascii")
    return None


def _resolve(url: str, service: DictionaryService,
             dict_id: int) -> Optional[str]:
    p = _normalize(url)
    if not p:
        if _DEBUG and url.strip():
            print(f"[SD-RES] skip non-resource: {url[:80]!r}")
        return None
    return _resolve_normalized(p, service, dict_id, original=url)


def _build_candidates(p: str) -> list:
    """由归一化路径生成待查候选列表（含常见目录前缀变体与去目录变体）。"""
    if not p:
        return []
    candidates = [p]
    base = p.lstrip("/")
    seen = {p}
    for prefix in _COMMON_PREFIXES:
        cand = (prefix + base).strip("/")
        if cand and cand not in seen:
            candidates.append(cand)
            seen.add(cand)
    if "/" in base:
        cand = base.rsplit("/", 1)[-1]
        if cand not in seen:
            candidates.append(cand)
            seen.add(cand)
    return candidates


def _resolve_normalized(p: str, service: DictionaryService,
                        dict_id: int, original: str = "") -> Optional[str]:
    """按归一化路径查找资源，失败后尝试常见目录前缀变体。"""
    for cand in _build_candidates(p):
        data = service.find_resource(dict_id, cand)
        if data is not None:
            if _DEBUG:
                print(f"[SD-RES] hit {original[:60]!r} -> {cand} ({len(data)} bytes)")
            return _to_data_uri(data, cand)
    _MISS_LOG.append((original, _build_candidates(p)))
    if _DEBUG:
        print(f"[SD-RES] miss {original[:60]!r} (tried {_build_candidates(p)})")
    return None


# 样式表原文缓存：(dict_id, normalized_path) -> CSS 文本
_CSS_CACHE: dict = {}


def _fetch_text(service: DictionaryService, dict_id: int,
                p: str) -> Optional[str]:
    """按归一化路径取资源原文（用于把样式表合并进 <style>），找不到返回 None。"""
    if not p:
        return None
    key = (dict_id, p)
    if key in _CSS_CACHE:
        return _CSS_CACHE[key]
    for cand in _build_candidates(p):
        data = service.find_resource(dict_id, cand)
        if data is not None:
            if _DEBUG:
                print(f"[SD-RES] css hit {p} -> {cand} ({len(data)} bytes)")
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("utf-8", "ignore")
            if len(_CSS_CACHE) >= _CACHE_MAX:
                for k in list(_CSS_CACHE)[: _CACHE_MAX // 2]:
                    _CSS_CACHE.pop(k, None)
            _CSS_CACHE[key] = text
            return text
    if _DEBUG:
        print(f"[SD-RES] css miss {p}")
    return None


def _rewrite_srcset(value: str, service: DictionaryService,
                    dict_id: int) -> str:
    """处理 srcset='a.jpg 1x, b.jpg 2x'，保留 descriptor。"""
    parts = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            parts.append(chunk)
            continue
        tokens = chunk.split()
        url = tokens[0]
        desc = " ".join(tokens[1:])
        new = _resolve(url, service, dict_id)
        parts.append(f"{new or url}{(' ' + desc) if desc else ''}")
    return ", ".join(parts)


def _rewrite_attrs(html: str, service: DictionaryService,
                   dict_id: int) -> str:
    for tag, attr in _TAG_ATTRS:
        rx = _attr_re(tag, attr)
        is_srcset = attr == "srcset"

        def _sub(m, _tag=tag, _attr=attr, _srcset=is_srcset):
            prefix, quote, value = m.group(1), m.group(2), m.group(3)
            if _srcset:
                new = _rewrite_srcset(value, service, dict_id)
            elif _tag == "script":
                # 脚本一律以 text/javascript 内联，确保可执行
                new = _resolve_js(value, service, dict_id)
            else:
                new = _resolve(value, service, dict_id)
                # 本地图片引用但资源缺失：用浅灰来源徽标替代破图框
                if (new is None and _tag == "img" and not _is_remote(value)
                        and _looks_like_image(value)):
                    new = _placeholder_img(_basename_label(value))
            return f"{prefix}{quote}{new or value}{quote}"
        html = rx.sub(_sub, html)
    return html


def _rewrite_url_in_css(html: str, service: DictionaryService,
                        dict_id: int) -> str:
    def _sub_url(m):
        quote, val = m.group(1), m.group(2)
        new = _resolve(val, service, dict_id)
        return f"url({quote}{new or val}{quote})"

    # <style>...</style> 块内的 url(...)
    def _style_block_sub(m):
        open_tag, content, close_tag = m.group(1), m.group(2), m.group(3)
        return open_tag + _URL_RE.sub(_sub_url, content) + close_tag
    html = _STYLE_BLOCK_RE.sub(_style_block_sub, html)

    # style="..." 属性里的 url(...)
    def _style_attr_sub(m):
        prefix, quote, value = m.group(1), m.group(2), m.group(3)
        if "url(" not in value.lower():
            return m.group(0)
        return f"{prefix}{quote}{_URL_RE.sub(_sub_url, value)}{quote}"
    html = _STYLE_ATTR_RE.sub(_style_attr_sub, html)
    return html


# 样式表合并：把多个 <link rel="stylesheet"> 解析到的 CSS 合并为单个 <style>，
# 并把「找不到」的样式表 <link> 直接删除（不留悬空相对链接 → 不发 404 请求 →
# 不触发浏览器异步重排闪烁）。这是修复「查词时样式闪一下就变」的关键。
_LINK_RE = re.compile(
    r'<link\b[^>]*\brel\s*=\s*(["\'])(?=[^"\']*stylesheet)[^"\']*\1[^>]*>',
    re.IGNORECASE,
)
# 非样式表的 <link>（icon / prefetch 等）：能解析则内联，否则原样保留
# （这些链接非渲染阻塞，缺失时 404 也不会造成闪烁）。
_OTHER_LINK_RE = re.compile(
    r'<link\b(?![^>]*\brel\s*=\s*(["\'])[^"\']*stylesheet[^"\']*\1)[^>]*>',
    re.IGNORECASE,
)


def _inline_stylesheets(html: str, service: DictionaryService,
                        dict_id: int) -> str:
    matches = list(_LINK_RE.finditer(html))
    if not matches:
        return html
    css_parts: list = []
    for m in matches:
        tag = m.group(0)
        hm = re.search(r'\bhref\s*=\s*(["\'])(.*?)\1', tag, re.I)
        href = hm.group(2) if hm else ""
        p = _normalize(href)
        text = _fetch_text(service, dict_id, p) if p else None
        if text is not None:
            css_parts.append(text)
    # 从后往前删除所有样式表 <link>（无论是否命中，都不留悬空链接）
    out = html
    for m in reversed(matches):
        out = out[: m.start()] + out[m.end():]
    if css_parts:
        merged = "<style>\n" + "\n".join(css_parts) + "\n</style>"
        hm = re.search(r"<head[^>]*>", out, re.I)
        if hm:
            out = out[: hm.end()] + merged + out[hm.end():]
        elif re.search(r"<html", out, re.I):
            out = re.sub(r"(<html[^>]*>)", r"\1" + merged, out,
                         count=1, flags=re.I)
        else:
            out = merged + out
    return out


def _rewrite_other_links(html: str, service: DictionaryService,
                         dict_id: int) -> str:
    def _sub(m):
        tag = m.group(0)
        hm = re.search(r'\bhref\s*=\s*(["\'])(.*?)\1', tag, re.I)
        if not hm:
            return tag
        href = hm.group(2)
        new = _resolve(href, service, dict_id)  # 带缓存：data URI 或 None
        if new is None:
            return tag  # 原样保留（可能 404，但非渲染阻塞）
        return tag[: hm.start(2)] + new + tag[hm.end(2):]
    return _OTHER_LINK_RE.sub(_sub, html)


# 简单的 data-URI 缓存：(dict_id, path) -> data URI
# 避免同一图标在多次渲染/页面刷新时重复读 MDD + base64
_DATA_URI_CACHE: dict = {}
_CACHE_MAX = 1024


# 发音链接：<a href="sound://xxx.mp3"> 是部分词典使用的私有协议，浏览器无法识别、点击无反应。
# 这里把整段 href 改写为 href="#" + data-snd="mdx://<dict_id>/<file>" + onclick，
# 点击时由内联 JS 创建一个 <audio> 元素并播放。
#
# ⚠️ 关键修复：音频【绝不再】以 base64 data URI 内联进词条 HTML。
#   原因（这是「某些单词不显示」的直接根因）：
#     OALDPEX 等词典的高频短词（for / work / get …）一个词条内嵌 100~200 个发音 /
#     例句音频引用；若全部 base64 内联，单条 HTML 可达 1.5~2.8 MiB，超过 Chromium
#     经 setHtml(data:URL) 加载的体积上限，导致该词条页「静默空白」——用户看到的
#     就是「某些单词不显示」。the / much / hour 等词条音频引用少（≤68），内联后
#     体积仍在 2 MiB 内，所以能正常显示。这是数量差异、与具体词库无关。
#   修复做法：词条 HTML 里 data-snd 只放一个极小的 mdx:// 地址；真正取字节是点击时
#     才发生（见下方 onclick），因此 HTML 体积恒定很小，彻底消除该上限问题。
#
# 为什么点击时 fetch(mdx://)→Blob 播放，而不直接 <audio src="mdx://…">：
#   - 直接把自定义 scheme 当媒体 src 在部分 Chromium 版本下加载脆弱（这正是当初资源
#     改为内联的初衷）；但 fetch 取字节再包成 blob: URL 播放则不受此影响；
#   - mdx:// 是已注册且为「安全 scheme」的地址，scheme_handler 以 audio/mpeg 等正确
#     MIME 返回字节，并自带跨词库回退（本词库没有的音频会去其它词库 MDD 找同名 mp3）；
#   - href="#" + onclick 内 return false 彻底阻止导航，词条页不会被替换成空白页；
#   - 播放交给浏览器原生 <audio> 元素，不经过 Python，因此不依赖在 PySide6 6.11
#     中已被移除的 addToJavaScriptWindowObject（旧式 JS 桥接接口），从根本上绕开
#     「点击崩溃 / 页面消失」两类故障。
# 只匹配 <a> 上的 href 属性（不限定引号类型）
_SOUND_HREF_RE = re.compile(
    r'href\s*=\s*(["\'])sound://([^"\']*)\1', re.IGNORECASE
)


def _rewrite_sound_links(html: str, dict_id: int, service: DictionaryService = None) -> str:
    if "sound://" not in html:
        return html

    # 点击时复用页面内唯一的 <audio> 节点播放。data-snd 里只是 mdx:// 地址（极小），
    # 真正取字节发生在点击时：先 fetch 出字节包成 Blob URL（绕开自定义 scheme 媒体
    # 加载的兼容性隐患），失败再退回到直接把 mdx:// 设为 src 的兜底做法。
    # onclick 内 JS 用双引号，外层 onclick 属性用单引号包裹，二者不冲突。
    onclick = (
        'var a=document.getElementById("sd_audio");'
        'if(!a){a=document.createElement("audio");a.id="sd_audio";'
        'document.body.appendChild(a);}'
        'var url=this.getAttribute("data-snd");'
        'if(!url)return false;'
        # 回收上一次的 Blob URL，避免内存泄漏
        'if(a._obj){try{URL.revokeObjectURL(a._obj);}catch(e){}}'
        'function play(){var p=a.play();'
        'if(p&&p.catch){p.catch(function(e){console.error("sd-audio-fail",e);});}}'
        # 首选：fetch 取字节 → Blob URL 播放（最稳，不受 scheme 媒体兼容性影响）
        'fetch(url).then(function(r){return r.blob();}).then(function(b){'
        'a._obj=URL.createObjectURL(b);a.src=a._obj;play();'
        '}).catch(function(e){'
        # 兜底：直接以 mdx:// 作为媒体 src（个别 Chromium 版本 fetch 受限时仍能播）
        'console.error("sd-audio-fetch-fail",e);a.src=url;play();});'
        'return false;'
    )

    def _sub(m):
        # 文件名（含 sound:// 协议头后的部分，如 _apple%23_brs_2.mp3）。
        # 保留原始编码写入 mdx:// 地址：# 在 URL 中是 fragment 分隔符，必须保持
        # %23 编码，否则路径会被截断；点击时 scheme_handler 会 unquote 后到 MDD
        # 里查 _apple#_brs_2.mp3，跨词库回退也能命中。
        rest = m.group(2)
        src = "mdx://%d/%s" % (dict_id, rest)
        # data-snd 用双引号（mdx:// 地址仅含安全字符）。onclick 单引号包裹。
        return 'href="#" data-snd="%s" onclick=\'%s\'' % (src, onclick)

    return _SOUND_HREF_RE.sub(_sub, html)


def _build_storage_bridge(dict_id: int, config: dict) -> str:
    """返回注入到词条 <head> 的 localStorage 桥脚本。

    作用：把词典对 `localStorage` 的读写透明桥接到 Python 侧持久化存储
    （tinydict.core.dict_config），解决「自定义 scheme mdx:// 的 origin 没有可
    落盘的 localStorage、导致重启后词典配置被重置」的问题。

    机制：
      - 用该词典已持久化的配置 JSON 作为种子（SEED），在内存里重建一份虚拟存储 m；
      - 重写 Storage.prototype 的 getItem/setItem/removeItem/clear/key/length，
        使其全部走虚拟存储 m——因此任何词典（OALDPEX/牛津/剑桥……）只要用
        localStorage，都自动被桥接，无需写死某个词典；
      - 读取是同步的（直接返回 m[k]），词典首次 getItem 即可拿到上次保存的值，
        不依赖与 Python 的异步往返；
      - 写入时同步更新 m，并整体序列化后经 location.hash 回传：
        `sdconfig:<dict_id>:<encodeURIComponent(json)>`，由 main_window 解析后
        调用 dict_config.replace_dict_config 落盘（整份快照覆盖，删除键也能生效）。
    """
    seed = json.dumps(config or {})
    return (
        "<script>(function(){"
        "var DICT_ID=" + str(int(dict_id)) + ";"
        "var SEED=" + seed + ";"
        "var m={};for(var k in SEED){if(SEED.hasOwnProperty(k))m[k]=String(SEED[k]);}"
        "function post(){try{var o={};for(var k in m){if(m.hasOwnProperty(k))o[k]=m[k];}"
        "location.hash='sdconfig:'+DICT_ID+':'+encodeURIComponent(JSON.stringify(o));"
        "}catch(e){}}"
        "var S={"
        "getItem:function(k){k=String(k);return (k in m)?m[k]:null;},"
        "setItem:function(k,v){k=String(k);v=String(v);if(m[k]===v)return;m[k]=v;post();},"
        "removeItem:function(k){k=String(k);if(!(k in m))return;delete m[k];post();},"
        "clear:function(){for(var k in m)delete m[k];post();},"
        "key:function(i){var ks=Object.keys(m);return (i>=0&&i<ks.length)?ks[i]:null;}"
        "};"
        "try{"
        "Storage.prototype.getItem=function(k){return S.getItem(k);};"
        "Storage.prototype.setItem=function(k,v){return S.setItem(k,v);};"
        "Storage.prototype.removeItem=function(k){return S.removeItem(k);};"
        "Storage.prototype.clear=function(){return S.clear();};"
        "Storage.prototype.key=function(i){return S.key(i);};"
        "try{Object.defineProperty(Storage.prototype,'length',{configurable:true,"
        "get:function(){return Object.keys(m).length;}});}catch(e){}"
        "}catch(e){}"
        "})();</script>"
    )


def _inject_storage_bridge(html: str, dict_id: int, config: dict) -> str:
    """把 localStorage 桥脚本插到 <head> 之后（确保在词库自身脚本之前执行）。"""
    if not html:
        return html
    script = _build_storage_bridge(dict_id, config)
    m = re.search(r"(<head[^>]*>)", html, re.IGNORECASE)
    if m:
        return html[:m.end()] + script + html[m.end():]
    # 无 <head>：放到文档最前（仍早于 body 内的脚本）
    return script + html


# ---------------------------------------------------------------- color-scheme
# 这里曾经在 HTML 层改写词库 <style> 里的 @media (prefers-color-scheme: ...)。
# 已移除：改写词库 CSS 文本既容易破坏其原有规则，也只能处理"恰好写成媒体
# 查询"的那部分样式，对内联 style、JS 动态加类的词库无效，灰度不一致。
# 现在统一由 ui/main_window.py 的通用方案处理——先让词库自带主题系统切换，
# 再实测页面整体明暗，不一致时套用通用反色滤镜。它对任何词库都一视同仁，
# 且不需要理解词库 CSS 的内容。


def inline_resources(html: str, dict_id: int,
                     service: DictionaryService,
                     dict_config: dict = None) -> str:
    """把词条 HTML 中所有可内联的资源改写为 data URI / 合并 <style>。

    处理顺序：
    1) <style>/style="..." 内的 url(...) 内联；
    2) <img>/<script> 等属性内联；
    3) 把所有 <link rel=stylesheet> 解析到的 CSS 合并为单个 <style>，
       并删除找不到的样式表 <link>（消除 404 异步重排造成的闪烁）；
    4) 其余 <link>（icon 等）能内联则内联，否则原样保留；
    5) 发音链接 sound:// 改写为 href="#" + data-snd（能取到音频则内联为 data URI，
       取不到则回退 mdx://<dict_id>/文件）+ onclick 用原生 <audio> 播放，
       无需 Python 桥接，彻底绕开自定义 scheme 媒体加载兼容性隐患；
    6) 注入 localStorage 桥：把该词典已持久化的配置（dict_config）作为种子，
       重写 Storage.prototype，使词典对 localStorage 的读写落到 Python 侧持久化
       存储，重启后配置不丢失（对任意词典通用，无需写死某个词典）。
    """
    if not html:
        return html
    _MISS_LOG.clear()
    html = _rewrite_url_in_css(html, service, dict_id)
    html = _rewrite_attrs(html, service, dict_id)
    html = _inline_stylesheets(html, service, dict_id)
    html = _rewrite_other_links(html, service, dict_id)
    html = _rewrite_sound_links(html, dict_id, service)
    html = _inject_storage_bridge(html, dict_id, dict_config)
    return html


def _resolve_cached(url: str, service: DictionaryService,
                    dict_id: int) -> Optional[str]:
    """带缓存的解析（render 时直接用，加快重复渲染）。

    缓存 key 用归一化路径；实际查找走 _resolve_normalized，包含目录前缀
    等 fallback 变体。
    """
    p = _normalize(url)
    if not p:
        return None
    key = (dict_id, p)
    if key in _DATA_URI_CACHE:
        return _DATA_URI_CACHE[key]
    uri = _resolve_normalized(p, service, dict_id)
    if uri is None:
        return None
    if len(_DATA_URI_CACHE) >= _CACHE_MAX:
        # 简单 FIFO 淘汰一半
        for k in list(_DATA_URI_CACHE)[: _CACHE_MAX // 2]:
            _DATA_URI_CACHE.pop(k, None)
    _DATA_URI_CACHE[key] = uri
    return uri


# 覆盖上面 _rewrite_attrs / _rewrite_url_in_css 使用的 _resolve 为带缓存版
def _install_cached_resolver():
    import sys
    this = sys.modules[__name__]
    this._resolve = _resolve_cached  # type: ignore[attr-defined]


_install_cached_resolver()
