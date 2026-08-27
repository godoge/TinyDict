"""设置对话框：全局快捷键 / 划词开关 / 关闭行为。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QKeySequenceEdit, QVBoxLayout,
)

from ..config import Config


def key_sequence_to_keyboard_format(seq_text: str) -> str:
    """把 QKeySequence 文本（如 "Ctrl+Alt+D"）转成 keyboard 库格式
    （"ctrl+alt+d"；Meta 键映射为 windows）。"""
    if not seq_text:
        return ""
    mapping = {"ctrl": "ctrl", "alt": "alt", "shift": "shift",
               "meta": "windows"}
    parts = []
    for p in seq_text.split("+"):
        key = p.strip().lower()
        if not key:
            continue
        parts.append(mapping.get(key, key))
    return "+".join(parts)


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("设置")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)

        form = QFormLayout()
        self._kse_toggle = QKeySequenceEdit(
            QKeySequence(self._keyboard_to_sequence(
                str(self._config["hotkey_show_hide"]))))
        form.addRow(QLabel("显示 / 隐藏主窗口："), self._kse_toggle)

        self._kse_capture = QKeySequenceEdit(
            QKeySequence(self._keyboard_to_sequence(
                str(self._config["hotkey_capture"]))))
        form.addRow(QLabel("屏幕划词取词："), self._kse_capture)
        layout.addLayout(form)

        self._chk_capture = QCheckBox("启用屏幕划词取词")
        self._chk_capture.setChecked(bool(self._config["capture_enabled"]))
        layout.addWidget(self._chk_capture)

        self._chk_tray = QCheckBox(
            "点击关闭按钮时最小化到系统托盘（不勾选则直接退出）")
        self._chk_tray.setChecked(bool(self._config["minimize_to_tray"]))
        layout.addWidget(self._chk_tray)

        self._chk_sync_input = QCheckBox(
            "点击左侧候选词条时，将词条填入搜索框")
        self._chk_sync_input.setChecked(
            bool(self._config["fill_input_on_select"]))
        self._chk_sync_input.setToolTip(
            "关闭时：点击左侧词条只显示释义，不改变上方搜索框内容；"
            "开启时：点击后搜索框也会变成该词条（默认关闭）")
        layout.addWidget(self._chk_sync_input)

        self._chk_offline = QCheckBox("禁止词典访问网络（强制离线）")
        self._chk_offline.setChecked(bool(self._config["offline_mode"]))
        self._chk_offline.setToolTip(
            "勾选后：所有词库的网络请求（在线发音 / 图片等）将被拦截，"
            "仅可使用词库自带的离线资源。\n不勾选（默认）：允许词库按需在线获取资源。")
        layout.addWidget(self._chk_offline)

        tip = QLabel(
            "提示：快捷键请避免与其他软件冲突；划词取词通过模拟 Ctrl+C 读取"
            "选中文字，随后自动恢复剪贴板内容。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#6b7280;font-size:12px;")
        layout.addWidget(tip)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _keyboard_to_sequence(seq: str) -> str:
        """keyboard 库格式 -> QKeySequence 可解析格式（仅用于界面回显）。"""
        if not seq:
            return ""
        mapping = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift",
                   "windows": "Meta", "win": "Meta"}
        parts = [mapping.get(p.strip().lower(), p.strip().title())
                 for p in seq.split("+") if p.strip()]
        return "+".join(parts)

    def accept(self):
        toggle = key_sequence_to_keyboard_format(
            self._kse_toggle.keySequence().toString())
        capture = key_sequence_to_keyboard_format(
            self._kse_capture.keySequence().toString())

        if not toggle:
            # 未设置新快捷键时保留原值，避免误清空导致热键失效
            toggle = str(self._config["hotkey_show_hide"])
        if not capture:
            capture = str(self._config["hotkey_capture"])

        self._config["hotkey_show_hide"] = toggle
        self._config["hotkey_capture"] = capture
        self._config["capture_enabled"] = self._chk_capture.isChecked()
        self._config["minimize_to_tray"] = self._chk_tray.isChecked()
        self._config["fill_input_on_select"] = self._chk_sync_input.isChecked()
        self._config["offline_mode"] = self._chk_offline.isChecked()
        super().accept()
