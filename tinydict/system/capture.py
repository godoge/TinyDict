"""屏幕划词取词（剪贴板方案）。

原理：用户在任意应用中选中文字后按下取词快捷键 ->
1. 深拷贝保存当前剪贴板全部格式；
2. 清空剪贴板（关键：否则"选中的内容恰好等于剪贴板里原有的内容"时
   无法区分新旧，会误判成"没取到"）；
3. 松开所有修饰键，再模拟按下 Ctrl+C 让目标程序把选中文字写入剪贴板；
4. 轮询读取剪贴板文本；
5. 恢复原剪贴板内容（含延迟补恢复，见 _restore）。

稳定性要点（都是真实会踩的坑）：
- **先松开修饰键**：取词热键本身带修饰键（如 Ctrl+Alt+Q），回调触发时
  用户往往还没松手，此时直接发 Ctrl+C 会被系统合成 Ctrl+Alt+C，
  目标程序收不到复制指令。所以发送前逐个 release 掉 alt/ctrl/shift/win。
- **手动 press→hold→release**：`keyboard.send()` 的按下与抬起几乎连在一起，
  部分程序来不及识别修饰键状态；这里按下后保持约 40ms 再抬起。
- **两套复制键**：Ctrl+C 失败再试 Ctrl+Insert（终端、部分老程序只认后者）。
- **取词前清空剪贴板**：见上面第 2 点。
- **延迟补恢复**：某些程序（浏览器复制大段文本）会在我们读取之后
  再异步写一次剪贴板，把我们刚恢复的旧内容覆盖掉。因此先立即恢复，
  再在 250ms 后检查：若剪贴板还是"刚取到的那段词"，说明之后再无写入，
  补恢复一次。若期间用户自己复制了别的内容，则不动（不抢用户操作）。

说明：
- 本方案兼容绝大多数应用（Word / 浏览器 / PDF 阅读器等），
  但要求目标程序支持「Ctrl+C 或 Ctrl+Insert 复制选中内容」；
- 剪贴板恢复以常见格式为主（文本 / HTML / URL / 图片），
  个别私有格式可能无法完整还原；
- 必须在主线程调用（内部使用 processEvents 轮询）。
"""

import time

from PySide6.QtCore import QMimeData, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

# 两套复制键：主用 Ctrl+C，失败后回退 Ctrl+Insert（终端 / 部分老程序）
_COMBOS = (("ctrl", "c"), ("ctrl", "insert"))
# 发送前先松开这些键，避免与取词热键自身的修饰键叠加
_MODIFIERS = ("alt", "ctrl", "shift", "windows")

_RELEASE_DELAY = 0.06     # 松开修饰键后等待系统稳定
_HOLD_DELAY = 0.04        # Ctrl+C 按住时长
_POLL_INTERVAL = 0.02     # 剪贴板轮询间隔
_SETTLE_DELAY = 0.05      # 读到内容后再等一会儿，等多段格式写完
_RESTORE_DELAY_MS = 250   # 延迟补恢复的时间点

DEFAULT_TIMEOUT_MS = 700  # 单套按键的等待上限


def _clone_mime(md) -> QMimeData:
    """深拷贝一份 QMimeData（剪贴板为空时 md 可能是 None）。"""
    clone = QMimeData()
    if md is None:
        return clone
    for fmt in md.formats():
        try:
            data = md.data(fmt)
        except Exception:  # noqa: BLE001 单个格式读不出不影响其它格式
            continue
        if data:
            clone.setData(fmt, data)
    return clone


def _clone_clipboard() -> QMimeData:
    """深拷贝当前剪贴板全部数据格式。"""
    return _clone_mime(QGuiApplication.clipboard().mimeData())


class SelectionCapture(QObject):
    captured = Signal(str)      # 取词成功（文本非空）
    failed = Signal()           # 未取到文本

    def __init__(self, parent=None):
        super().__init__(parent)
        # 持有备份引用：setMimeData 后由 Qt 接管，但保留 Python 引用可避免
        # 延迟补恢复时对象生命周期出现意外
        self._backup = None

    # ------------------------------------------------------------------
    def get_selected_text(self, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
        """读取当前选中文字（主线程调用），并尽量恢复剪贴板。"""
        try:
            import keyboard
        except Exception:  # noqa: BLE001 keyboard 缺失
            return ""

        clipboard = QGuiApplication.clipboard()
        backup = _clone_clipboard()
        self._backup = backup
        old_text = clipboard.text() or ""

        text = ""
        for combo in _COMBOS:
            # 每轮开始前清空：这样"新内容 == 旧内容"也能被检测出来。
            # 清空失败（如被其它程序占用剪贴板）时退回按 old_text 比较。
            cleared = self._clear_clipboard(clipboard)
            compare = "" if cleared else old_text
            got = self._try_copy(keyboard, clipboard, combo, timeout_ms, compare)
            if got:
                text = got
                break
            # 第二轮给短一点的时间，避免两次都失败时干等太久
            timeout_ms = max(int(timeout_ms * 0.6), 150)

        self._restore(clipboard, backup, text)
        return text.strip() if text else ""

    def _try_copy(self, keyboard, clipboard, combo, timeout_ms: int,
                  old_text: str) -> str:
        """按一套按键复制一次，返回取到的文本（失败返回空串）。"""
        self._release_modifiers(keyboard)
        time.sleep(_RELEASE_DELAY)
        try:
            for k in combo:
                keyboard.press(k)
            time.sleep(_HOLD_DELAY)
            for k in reversed(combo):
                keyboard.release(k)
        except Exception:  # noqa: BLE001 键盘模拟失败则本轮作废
            return ""

        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(_POLL_INTERVAL)
            t = clipboard.text() or ""
            if not t or t == old_text:
                continue
            # 再等一小段时间确保多段写入完成
            time.sleep(_SETTLE_DELAY)
            QApplication.processEvents()
            return clipboard.text() or t
        return ""

    # ------------------------------------------------------------------ 剪贴板
    @staticmethod
    def _clear_clipboard(clipboard) -> bool:
        """清空剪贴板，成功返回 True（失败时调用方退回旧比较逻辑）。"""
        try:
            clipboard.clear()
            QApplication.processEvents()
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _release_modifiers(keyboard):
        """松开全部修饰键。

        取词热键（如 Ctrl+Alt+Q）触发时用户往往还没松手，残留的 Alt 会把
        我们发出的 Ctrl+C 合成 Ctrl+Alt+C，目标程序根本收不到复制指令。
        """
        for k in _MODIFIERS:
            try:
                keyboard.release(k)
            except Exception:  # noqa: BLE001
                pass

    def _restore(self, clipboard, backup: QMimeData, captured_text: str):
        """恢复剪贴板：立即一次 + 延迟补一次。"""
        try:
            clipboard.setMimeData(backup)
        except Exception:  # noqa: BLE001
            pass
        if captured_text:
            # 见模块文档：防止目标程序在我们读取之后又异步写了一次
            QTimer.singleShot(
                _RESTORE_DELAY_MS,
                lambda: self._restore_if_unchanged(captured_text))

    def _restore_if_unchanged(self, captured_text: str):
        """剪贴板里仍是刚取到的那段词时，补一次恢复。"""
        clipboard = QGuiApplication.clipboard()
        try:
            if (clipboard.text() or "") == captured_text:
                clipboard.setMimeData(_clone_mime(self._backup))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 入口
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
