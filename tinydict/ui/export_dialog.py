"""导出生词本前的选项对话框：先选导出哪些生词本，再选导出格式。

范围默认「全部生词本」。取消「全部」后可以多选具体分组；此时导出的文件里
**只记录被选中的分组**，导入回任意一端都不会凭空带出没选的分组（一个词
同时属于选中和未选中的分组时，只保留选中那部分归属）。选「全部」时数据
与旧行为逐字节一致。

格式默认 CSV；TXT 是纯词表（不含分组与时间），JSON 是完整备份，顶层
``groups`` 只包含所选分组，因此连没有生词的空分组也能保留下来。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QRadioButton, QVBoxLayout,
)

from ..i18n import _
from . import theme as _theme

#: 分组项里存分组 id，避免拿显示文本（带计数、可能被翻译）去反查
_ID_ROLE = Qt.ItemDataRole.UserRole

#: 界面顺序，第一项即默认格式
FORMATS = ("csv", "txt", "json")


def format_hint(ext: str) -> str:
    """格式说明。写成函数而不是模块级字典，语言切换后才不会残留旧译文。"""
    if ext == "txt":
        return _("每行一个词，不含分组与收藏时间，适合纯词表。")
    if ext == "json":
        return _("完整备份：保留分组结构（含空分组）与各分组收藏时间。")
    return _("含分组与各分组收藏时间，Excel 可直接打开。")


# 这两个 QSS 只作用于本对话框：wb_qss 里没有 QCheckBox / QRadioButton 规则，
# 深色主题下若不加，控件文字会继承成难以辨认的默认色。
_EXPORT_QSS_LIGHT = """
QCheckBox, QRadioButton { color:#374151; font-size:13px; padding:2px 0; }
QLabel#export_section { color:#374151; font-size:12px; font-weight:600; }
QLabel#export_hint { color:#6b7280; font-size:12px; padding:2px 4px; }
QListWidget#export_group_list {
    border:1px solid #e5e7eb; border-radius:6px; background:#fff;
    color:#374151; font-size:13px; outline:0;
}
QListWidget#export_group_list::item { padding:5px 8px; }
"""

_EXPORT_QSS_DARK = """
QCheckBox, QRadioButton { color:#d4d4d4; font-size:13px; padding:2px 0; }
QLabel#export_section { color:#e5e7eb; font-size:12px; font-weight:600; }
QLabel#export_hint { color:#9ca3af; font-size:12px; padding:2px 4px; }
QListWidget#export_group_list {
    border:1px solid #374151; border-radius:6px; background:#2d2d30;
    color:#d4d4d4; font-size:13px; outline:0;
}
QListWidget#export_group_list::item { padding:5px 8px; }
"""


class ExportOptionsDialog(QDialog):
    """``accept()`` 之后读 :attr:`selected_group_ids` 和 :attr:`format`。

    :param items: ``[(group_id, name, word_count), ...]``，按界面顺序。
    :param selected_group_ids: ``None`` 表示全部（默认）；否则只勾这些分组。
    """

    def __init__(self, items, config=None, theme_manager=None, parent=None,
                 group_ids=None, fmt="csv"):
        super().__init__(parent)
        self._items = list(items)
        self._config = config
        self._theme_manager = theme_manager
        self._radios = {}
        self.selected_group_ids = None      # None = 全部
        self.format = fmt if fmt in FORMATS else "csv"

        self.setWindowTitle(_("导出生词本"))
        self.resize(430, 480)
        self._build_ui()
        self._apply_qss()
        if self._theme_manager is not None:
            self._theme_manager.theme_changed.connect(self._apply_qss)
        if group_ids is not None or fmt != "csv":
            self.set_selection(group_ids, self.format)

    # ------------------------------------------------------------------ 界面
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)

        layout.addWidget(QLabel(_("导出哪些生词本："),
                                objectName="export_section"))

        self._chk_all = QCheckBox(_("全部生词本（默认）"))
        self._chk_all.setChecked(True)       # 先设再连，避免启动时触发清空
        self._chk_all.toggled.connect(self._on_all_toggled)
        layout.addWidget(self._chk_all)

        self._list = QListWidget(objectName="export_group_list")
        for gid, name, count in self._items:
            item = QListWidgetItem(_("{}（{}）").format(name, count))
            item.setData(_ID_ROLE, gid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._list.addItem(item)
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, stretch=1)

        tools = QHBoxLayout()
        self._btn_select_all = QPushButton(_("全选"))
        self._btn_select_all.clicked.connect(lambda: self._check_all(True))
        tools.addWidget(self._btn_select_all)
        self._btn_select_none = QPushButton(_("全不选"))
        self._btn_select_none.clicked.connect(lambda: self._check_all(False))
        tools.addWidget(self._btn_select_none)
        tools.addStretch(1)
        layout.addLayout(tools)
        self._tools = (self._btn_select_all, self._btn_select_none)

        layout.addWidget(QLabel(_("导出格式："), objectName="export_section"))

        # hint 先建好再接 radio 的 toggled：默认项 setChecked 会立刻触发回调
        self._hint = QLabel(objectName="export_hint")
        self._hint.setWordWrap(True)
        self._hint.setMinimumHeight(36)

        labels = {
            "csv": _("CSV 表格（推荐）"),
            "txt": _("纯文本（每行一个词）"),
            "json": _("JSON 完整备份"),
        }
        for ext in FORMATS:
            radio = QRadioButton(labels[ext])
            radio.toggled.connect(
                lambda checked, e=ext: self._on_format_toggled(checked, e))
            self._radios[ext] = radio
            layout.addWidget(radio)
        layout.addWidget(self._hint)
        self._radios[self.format].setChecked(True)
        self._update_hint()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText(_("导出"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            _("取消"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync_ok()

    def _apply_qss(self, mode=None):
        if mode is None:
            if self._theme_manager is not None:
                mode = self._theme_manager.mode
            elif self._config is not None:
                mode = _theme.resolve_theme(str(self._config["theme"]))
            else:
                mode = "light"
        extra = (_EXPORT_QSS_DARK if mode == "dark"
                 else _EXPORT_QSS_LIGHT)
        self.setStyleSheet(_theme.wb_qss(mode) + extra)

    # ------------------------------------------------------------------ 行为
    def _on_all_toggled(self, checked: bool):
        """勾「全部」时把列表全勾；取消「全部」时保留列表现状，让用户微调。
        列表始终可编辑：用户在「全部」勾选状态下取消某个单项，会触发
        _on_item_changed 自动退出「全部」模式，而不是被强制锁死。"""
        if checked:
            self._list.blockSignals(True)
            for i in range(self._list.count()):
                self._list.item(i).setCheckState(Qt.CheckState.Checked)
            self._list.blockSignals(False)
        self._sync_ok()

    def _on_item_changed(self, item):
        """单项勾选/取消时，让「全部」复选框与「是否所有单项都已勾选」保持
        一致（双向联动）：

        - 正处于「全部」模式（即全勾）时取消某单项 → 自动退出「全部」，
          并保留其余勾选（不再被强制锁死或覆盖）；
        - 未处于「全部」模式时，若用户手动把所有单项都勾上 → 自动勾上
          「全部」；反之若取消到并非全勾，则保持「全部」不勾。
        """
        all_checked = all(
            self._list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self._list.count()))
        if self._chk_all.isChecked() != all_checked:
            self._chk_all.blockSignals(True)
            self._chk_all.setChecked(all_checked)
            self._chk_all.blockSignals(False)
        self._sync_ok()

    def _check_all(self, checked: bool):
        """全选 / 全不选按钮：设置所有单项后，让「全部」复选框与结果保持一致
        （全选→自动勾上「全部」；全不选→自动取消「全部」），避免「全部」与
        列表现状脱节。"""
        state = (Qt.CheckState.Checked if checked
                 else Qt.CheckState.Unchecked)
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)
        self._list.blockSignals(False)
        if self._chk_all.isChecked() != checked:
            self._chk_all.blockSignals(True)
            self._chk_all.setChecked(checked)
            self._chk_all.blockSignals(False)
        self._sync_ok()

    def _on_format_toggled(self, checked: bool, ext: str):
        if checked:
            self.format = ext
            self._update_hint()

    def _update_hint(self):
        self._hint.setText(format_hint(self.format))

    def _sync_ok(self):
        has_choice = self._chk_all.isChecked() or any(
            self._list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self._list.count()))
        self._ok_button.setEnabled(has_choice)

    def set_selection(self, group_ids, fmt="csv"):
        """直接指定选择结果（用于记忆上次选择 / 测试）。``None`` = 全部。"""
        if fmt in FORMATS:
            self._radios[fmt].setChecked(True)
        if group_ids is None:
            self._chk_all.setChecked(True)
            return
        wanted = set(group_ids)
        self._chk_all.setChecked(False)
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setCheckState(
                Qt.CheckState.Checked if item.data(_ID_ROLE) in wanted
                else Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        self._sync_ok()

    def accept(self):
        if self._chk_all.isChecked():
            self.selected_group_ids = None
        else:
            ids = [self._list.item(i).data(_ID_ROLE)
                   for i in range(self._list.count())
                   if self._list.item(i).checkState()
                   == Qt.CheckState.Checked]
            if not ids:
                return                       # 理论上 OK 按钮已禁用
            self.selected_group_ids = ids
        super().accept()
