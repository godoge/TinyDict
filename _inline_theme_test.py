"""回归测试：每个词条文档都必须自带配色脚本与 matchMedia 垫片。

背景：原先这两个脚本用 QWebEngineScript 注入（DocumentCreation），实测在
反复 setHtml 的页面上会出现「新文档根本没拿到脚本」的竞态——表现为同一
词条第一次配色正确、切到别的词条再切回来就变浅（注入脚本缺失时，词库按
系统 prefers-color-scheme 套了浅色皮肤，而兜底滤镜也没人加）。

改为随 HTML 内联后，脚本随文档解析执行，必然生效。本测试锁死这一点：
连续渲染 6 次（含快速连发），每次都必须同时拿到：
  1) window.__sdT0            —— 配色脚本执行过
  2) window.__mq === 'true'   —— matchMedia 垫片生效，词库看到的是深色
  3) window.__sdApplyEntryTheme —— 换肤入口可用

用法：
    QT_QPA_PLATFORM=offscreen QT_OPENGL=software \
    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
    .venv/Scripts/python _inline_theme_test.py
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

from tinydict.ui.main_window import DictPage, entry_page

# 模拟一个「用 matchMedia 决定明暗」的现代词库词条
ENTRY = (
    '<html><head><meta charset="utf-8">'
    "<style>body{background:#ffffff;color:#222222}"
    "body.dict-dark{background:#1a1a1a;color:#e0e0e0}</style>"
    "<script>"
    "try{"
    "var mq=window.matchMedia?window.matchMedia("
    "'(prefers-color-scheme: dark)').matches:null;"
    "window.__mq=String(mq);"
    "}catch(e){window.__mq='ERR:'+e.message;}"
    "</script></head><body><h3>hello</h3><p>content</p>"
    "<script>if(window.__mq==='true'){"
    "document.body.classList.add('dict-dark');}</script>"
    "</body></html>"
)

PROBE = (
    "JSON.stringify({"
    "t0:String(typeof window.__sdT0),"
    "mq:String(window.__mq),"
    "fn:String(typeof window.__sdApplyEntryTheme),"
    "inv:document.documentElement.classList.contains('sd-invert'),"
    "bodyBg:getComputedStyle(document.body).backgroundColor"
    "})"
)

results = []
FAILS = []


def static_check():
    """静态断言：生成的 HTML 必须自带两个脚本（不依赖浏览器，必现）。"""
    html = entry_page(ENTRY, "hello", "dark", "dark")
    checks = [
        ("matchMedia 垫片", "prefers-color-scheme" in html),
        ("配色脚本", "sd-invert" in html and "__sdApplyEntryTheme" in html),
    ]
    print("=== 静态检查：脚本是否随 HTML 下发 ===")
    for name, ok in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
        if not ok:
            FAILS.append(name)
    print()


def main():
    static_check()
    app = QApplication([])
    view = QWebEngineView()
    page = DictPage(view, theme_mode="dark")
    view.setPage(page)
    view.resize(400, 300)

    n = 0
    total = 6

    def render():
        nonlocal n
        n += 1
        if n > total:
            dump()
            app.quit()
            return
        page.setHtml(entry_page(ENTRY, "hello", "dark", "dark"),
                     QUrl("mdx://0.0.0.1/"))
        QTimer.singleShot(350, lambda i=n: page.runJavaScript(
            PROBE, lambda v, k=i: collect(k, v)))
        # 250ms 连发：模拟词库异步挂载时 _render_current 被反复调用
        QTimer.singleShot(250, render)

    def collect(i, v):
        results.append((i, v))

    def dump():
        print("=== 连续渲染：脚本必须随每个文档生效 ===")
        for i, v in results:
            ok = ('"t0":"number"' in v and '"mq":"true"' in v
                  and '"fn":"function"' in v)
            if not ok:
                FAILS.append(i)
            print(f"  第{i}次  {'OK ' if ok else 'FAIL'}  {v}")
        print(f"\n=== 共 {total} 项，失败 {len(FAILS)} 项 ===")
        if FAILS:
            print("→ 有文档没拿到内联脚本，主题会回退到词库按系统配色")

    QTimer.singleShot(200, render)
    app.exec()


if __name__ == "__main__":
    main()
