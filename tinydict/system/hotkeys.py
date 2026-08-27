"""全局快捷键服务（基于 keyboard 库）。

- 唤起 / 隐藏主窗口；
- 触发屏幕划词取词。

keyboard 库使用低级键盘钩子，在 Windows 上普通用户权限即可工作。
注意：其回调运行在 keyboard 库自身的监听线程中，因此回调内只做
信号 emit（Qt 跨线程信号自动排队投递到主线程），不直接操作 UI。
"""

from PySide6.QtCore import QObject, Signal

from ..config import Config


class HotkeyService(QObject):
    toggleRequested = Signal()   # 唤起 / 隐藏主窗口
    captureRequested = Signal()  # 划词取词
    errorOccurred = Signal(str)  # 注册失败提示

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._hooks = []

    def rebind(self):
        """按当前配置（重新）注册快捷键。"""
        self.stop()
        try:
            import keyboard
        except ImportError:
            self.errorOccurred.emit(
                "未安装 keyboard 库，全局快捷键不可用。"
                "可执行 pip install keyboard 安装。"
            )
            return

        try:
            show_hide = str(self._config["hotkey_show_hide"] or "").strip()
            if show_hide:
                self._hooks.append(
                    keyboard.add_hotkey(show_hide, self._on_toggle)
                )
        except Exception as e:  # noqa: BLE001
            self.errorOccurred.emit(f"注册窗口快捷键失败：{e}")

        if self._config["capture_enabled"]:
            try:
                capture = str(self._config["hotkey_capture"] or "").strip()
                if capture:
                    self._hooks.append(
                        keyboard.add_hotkey(capture, self._on_capture)
                    )
            except Exception as e:  # noqa: BLE001
                self.errorOccurred.emit(f"注册取词快捷键失败：{e}")

    def stop(self):
        """注销全部本服务注册的快捷键（不影响其他程序/其他模块）。"""
        while self._hooks:
            h = self._hooks.pop()
            try:
                import keyboard
                keyboard.remove_hotkey(h)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    def _on_toggle(self):
        # keyboard 库回调线程 -> Qt 信号 -> 主线程
        self.toggleRequested.emit()

    def _on_capture(self):
        self.captureRequested.emit()
