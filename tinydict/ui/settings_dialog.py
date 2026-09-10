"""设置对话框：全局快捷键 / 划词开关 / 关闭行为 / 主题模式。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QKeySequenceEdit, QPushButton, QVBoxLayout,
)

from ..config import Config
from . import theme as _theme

# 主题下拉框的可选值
_THEME_OPTIONS = [
    ("跟随系统", "system"),
    ("浅色", "light"),
    ("深色", "dark"),
]


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

        # ---- 显示 / 隐藏主窗口
        self._kse_toggle = QKeySequenceEdit(
            QKeySequence(self._keyboard_to_sequence(
                str(self._config["hotkey_show_hide"]))))
        self._btn_reset_toggle = QPushButton("默认")
        self._btn_reset_toggle.setToolTip(
            "恢复为默认快捷键：" + str(Config.DEFAULTS["hotkey_show_hide"]))
        self._btn_reset_toggle.clicked.connect(
            lambda: self._kse_toggle.setKeySequence(
                QKeySequence(self._keyboard_to_sequence(
                    Config.DEFAULTS["hotkey_show_hide"]))))
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.addWidget(self._kse_toggle)
        toggle_row.addWidget(self._btn_reset_toggle)
        toggle_row.addStretch(1)
        form.addRow(QLabel("显示 / 隐藏主窗口："), toggle_row)

        # ---- 屏幕划词取词
        self._kse_capture = QKeySequenceEdit(
            QKeySequence(self._keyboard_to_sequence(
                str(self._config["hotkey_capture"]))))
        self._btn_reset_capture = QPushButton("默认")
        self._btn_reset_capture.setToolTip(
            "恢复为默认快捷键：" + str(Config.DEFAULTS["hotkey_capture"]))
        self._btn_reset_capture.clicked.connect(
            lambda: self._kse_capture.setKeySequence(
                QKeySequence(self._keyboard_to_sequence(
                    Config.DEFAULTS["hotkey_capture"]))))
        capture_row = QHBoxLayout()
        capture_row.setContentsMargins(0, 0, 0, 0)
        capture_row.addWidget(self._kse_capture)
        capture_row.addWidget(self._btn_reset_capture)
        capture_row.addStretch(1)
        form.addRow(QLabel("屏幕划词取词："), capture_row)

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

        self._chk_history = QCheckBox("记录查询历史（可在「历史」中查看）")
        self._chk_history.setChecked(bool(self._config["history_enabled"]))
        self._chk_history.setToolTip(
            "开启后：每次查词会自动记入查询历史，方便回头翻看。\n"
            "关闭后：不再新增记录，已有历史仍保留，可随时在「历史」中清空。")
        layout.addWidget(self._chk_history)

        # ---- 主题选择
        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(0, 6, 0, 2)
        theme_row.addWidget(QLabel("外观主题："))
        self._cmb_theme = QComboBox()
        current_theme = str(self._config["theme"])
        for label, value in _THEME_OPTIONS:
            self._cmb_theme.addItem(label, value)
            if value == current_theme:
                self._cmb_theme.setCurrentIndex(self._cmb_theme.count() - 1)
        self._cmb_theme.setToolTip(
            "选择「跟随系统」后，会根据 Windows 的深色/浅色设置自动切换。\n"
            "切换主题会立即生效，无需重启。")
        theme_row.addWidget(self._cmb_theme)
        theme_row.addStretch(1)
        layout.addLayout(theme_row)

        # ---- 词条页配色
        entry_row = QHBoxLayout()
        entry_row.setContentsMargins(0, 0, 0, 2)
        entry_row.addWidget(QLabel("词条页配色："))
        self._cmb_entry_theme = QComboBox()
        current_entry = str(self._config["entry_theme"])
        for label, value in _theme.ENTRY_THEME_OPTIONS:
            self._cmb_entry_theme.addItem(label, value)
            if value == current_entry:
                self._cmb_entry_theme.setCurrentIndex(
                    self._cmb_entry_theme.count() - 1)
        self._cmb_entry_theme.setToolTip(
            "只对「词条正文」生效，应用窗口本身始终跟随上面的外观主题。\n"
            "跟随应用主题：对所有词库使用同一套通用方案，不针对任何具体词库。\n"
            "保持词库原样：完全不干预词条页，词库设计是什么样就显示什么样。\n"
            "若觉得通用方案的处理效果不理想，选「保持词库原样」即可。")
        entry_row.addWidget(self._cmb_entry_theme)
        entry_row.addStretch(1)
        layout.addLayout(entry_row)

        tip = QLabel(
            "提示：快捷键请避免与其他软件冲突；划词取词通过模拟 Ctrl+C 读取"
            "选中文字，随后自动恢复剪贴板内容。")
        tip.setWordWrap(True)
        # 按当前实际主题取色（跟随系统时需先解析），深色下不能用浅色的灰
        tip.setStyleSheet(
            "color:"
            f"{_theme.tip_color(_theme.resolve_theme(str(self._config['theme'])))}"
            ";font-size:12px;")
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
        self._config["history_enabled"] = self._chk_history.isChecked()
        self._config["theme"] = self._cmb_theme.currentData()
        self._config["entry_theme"] = self._cmb_entry_theme.currentData()
        super().accept()
