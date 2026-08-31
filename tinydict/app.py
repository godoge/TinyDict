"""应用组装层：主窗口 / 系统托盘 / 全局快捷键 / 划词取词的生命周期与信号接线。"""

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .config import Config
from .core.database import Database
from .core.query import DictionaryService
from .core.wordbook import WordBook
from .paths import cache_dir, config_path, db_path
from .system.capture import SelectionCapture
from .system.hotkeys import HotkeyService
from .ui.icons import app_icon
from .ui.main_window import MainWindow


class TrayController(QObject):
    """系统托盘：图标 / 右键菜单 / 气泡通知。"""

    def __init__(self, app: "TinyDictApp", parent=None):
        super().__init__(parent)
        self._app = app
        self._tray = QSystemTrayIcon(app_icon(), self)
        self._tray.setToolTip("TinyDict 离线词典")

        menu = QMenu()
        act_toggle = menu.addAction("显示 / 隐藏主窗口")
        act_toggle.triggered.connect(app.toggle_window)
        act_dicts = menu.addAction("词库管理…")
        act_dicts.triggered.connect(app.window.open_dict_manager)
        act_wb = menu.addAction("生词本…")
        act_wb.triggered.connect(app.window.open_wordbook)
        menu.addSeparator()
        act_exit = menu.addAction("退出")
        act_exit.triggered.connect(app.quit_app)
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def is_available(self) -> bool:
        return (QSystemTrayIcon.isSystemTrayAvailable()
                and self._tray.isVisible())

    def notify(self, message: str, title: str = "TinyDict"):
        self._tray.showMessage(title, message,
                                QSystemTrayIcon.MessageIcon.Information, 4000)

    def notify_minimized(self):
        self.notify("已最小化到系统托盘，右键托盘图标可选择退出。")

    def hide_icon(self):
        """隐藏托盘图标。

        退出前必须调用：Windows 上若进程退出时图标仍可见，图标会残留在托盘区，
        要等鼠标划过才消失，看起来像"没关掉"。
        """
        self._tray.hide()

    def apply_config(self):
        # 托盘行为无动态配置项；保留接口供后续扩展
        pass

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._app.toggle_window()


class TinyDictApp:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        # 应用级图标：同时驱动主窗口标题栏与 Windows 任务栏图标。
        # 托盘图标在 TrayController 中单独设置，此处不必重复。
        self.qapp.setWindowIcon(app_icon())

        # 数据层
        self.config = Config(config_path())
        self.db = Database(db_path())
        self.service = DictionaryService(self.db, cache_dir())
        self.wordbook = WordBook(self.db)

        # 界面层
        self.window = MainWindow(self.service, self.config, self.wordbook)
        self.tray = TrayController(self)
        self.window.set_tray(self.tray)

        # 系统层
        self.capture = SelectionCapture()
        self.hotkeys = HotkeyService(self.config)

        self._wire()
        self.window.show()
        self.hotkeys.rebind()
        # 后台挂载全部启用词库（key 索引，带本地缓存）
        self.service.mount_all_async()

    def _wire(self):
        self.window.quit_requested.connect(self.quit_app)
        self.hotkeys.toggleRequested.connect(self.toggle_window)
        self.hotkeys.captureRequested.connect(self.capture.capture_now)
        self.hotkeys.errorOccurred.connect(
            lambda msg: self.window.notify(msg))
        self.capture.captured.connect(self.window.bring_up_and_lookup)
        self.capture.failed.connect(
            lambda: self.window.notify("划词取词：未获取到选中文本"))
        self.window.settings_saved.connect(self.hotkeys.rebind)
        self.qapp.aboutToQuit.connect(self._shutdown)

    # ------------------------------------------------------------------
    def toggle_window(self):
        w = self.window
        if w.isVisible() and w.isActiveWindow():
            w.hide()
        else:
            w.show()
            w.raise_()
            w.activateWindow()

    def quit_app(self):
        """彻底退出应用（关闭窗口 / 托盘菜单「退出」都走这里）。

        注意 app 设了 setQuitOnLastWindowClosed(False)，只关窗口不会结束进程，
        必须显式 quit；且退出前要先隐藏托盘图标，否则 Windows 上图标会残留。
        """
        self.tray.hide_icon()
        QApplication.instance().quit()

    def _shutdown(self):
        self.hotkeys.stop()
