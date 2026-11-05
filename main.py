"""TinyDict 启动入口。

注意：mdx:// URL Scheme 必须在 QApplication 创建之前注册，
否则 QWebEngineView 无法加载词条内引用的 MDD 资源（图片/样式）。
"""

import sys


def _close_splash():
    """关闭 PyInstaller 启动画面（仅打包版存在 pyi_splash，源码运行静默跳过）。

    启动画面由 bootloader 在 Python 解释器与大体积 QtWebEngine DLL 加载之前
    显示，让用户点击后立即得到反馈；这里在主窗口绘制完成后把它关掉。
    """
    try:
        import pyi_splash
    except ImportError:
        return
    try:
        pyi_splash.close()
    except Exception:  # 启动画面已关闭 / 未启用时不阻断启动
        pass


def main():
    # 必须在 QApplication 创建之前完成 scheme 注册
    # （mdx 子资源 + sound/entry 导航，缺一不可，否则点击无反应）
    from tinydict.ui.scheme_handler import register_all_schemes
    register_all_schemes()

    from PySide6.QtWidgets import QApplication

    from tinydict import APP_NAME, __version__
    from tinydict.app import TinyDictApp

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("TinyDict")
    # 主窗口关闭默认驻留托盘，退出走托盘菜单
    app.setQuitOnLastWindowClosed(False)

    # 回调在事件循环第一轮（主窗口已绘制）触发：先关启动画面让用户看到
    # 界面，再由 app 层延后执行全局快捷键 / 词库挂载等非首屏工作。
    TinyDictApp(app, on_first_idle=_close_splash)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
