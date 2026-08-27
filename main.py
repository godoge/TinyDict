"""TinyDict 启动入口。

注意：mdx:// URL Scheme 必须在 QApplication 创建之前注册，
否则 QWebEngineView 无法加载词条内引用的 MDD 资源（图片/样式）。
"""

import sys


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

    TinyDictApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
