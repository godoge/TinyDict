"""屏幕划词取词（剪贴板方案）。

原理：用户在任意应用中选中文字后按下取词快捷键 ->
1. 深拷贝保存当前剪贴板全部格式；
2. 模拟按下 Ctrl+C 让目标程序把选中文字写入剪贴板；
3. 轮询读取剪贴板文本；
4. 恢复原剪贴板内容。

说明：
- 本方案兼容绝大多数应用（Word / 浏览器 / PDF 阅读器等），
  但要求目标程序支持「Ctrl+C 复制选中内容」；
- 剪贴板恢复以常见格式为主（文本 / HTML / URL / 图片），
  个别私有格式可能无法完整还原；
- 必须在主线程调用（内部使用 processEvents 轮询）。
"""

import time

from PySide6.QtCore import QMimeData, QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


def _clone_clipboard() -> QMimeData:
    """深拷贝当前剪贴板全部数据格式。"""
    md = QGuiApplication.clipboard().mimeData()
    clone = QMimeData()
    for fmt in md.formats():
        try:
            data = md.data(fmt)
        except Exception:  # noqa: BLE001
            continue
        if data:
            clone.setData(fmt, data)
    # QMimeData 数据为私有副本，清空源指针防复用
    clone.setObjectName("TinyDictClipboardBackup")
    return clone


class SelectionCapture(QObject):
    captured = Signal(str)      # 取词成功（文本非空）
    failed = Signal()           # 未取到文本

    def get_selected_text(self, timeout_ms: int = 500) -> str:
        """读取当前选中文字（主线程调用），并尽量恢复剪贴板。"""
        clipboard = QGuiApplication.clipboard()
        backup = _clone_clipboard()
        old_text = clipboard.text()

        try:
            # 发送 Ctrl+C（keyboard 库负责完整的按下/释放序列）
            import keyboard
            keyboard.send("ctrl+c")
        except Exception:  # noqa: BLE001 keyboard 缺失等
            return ""

        deadline = time.monotonic() + timeout_ms / 1000.0
        text = ""
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
            t = clipboard.text()
            if t and t != old_text:
                # 再等一小段时间确保多段写入完成
                time.sleep(0.05)
                QApplication.processEvents()
                text = clipboard.text()
                break

        # 恢复原剪贴板（异步信号投递，立即返回）
        clipboard.setMimeData(backup)

        return text.strip() if text else ""

    def capture_now(self):
        """入口：取词并广播结果信号。"""
        text = self.get_selected_text()
        if text:
            # 多行选区取第一段非空行，避免把整段文章塞进查询
            first = next(
                (ln.strip() for ln in text.splitlines() if ln.strip()), ""
            )
            self.captured.emit(first[:200])
        else:
            self.failed.emit()
