"""查询历史窗口：查看 / 搜索 / 删除 / 清空查过的词。

顶部是过滤框（输入片段即时筛选），下面是按最近查询时间倒序的记录列表，
双击任意一条即可重新查词。与生词本不同，这里只是"查过什么"的流水，
不影响收藏。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout,
)

from ..core.history import HistoryBook, display_text
from . import theme as _theme


def _copy_text(text: str):
    """本地实现复制：不引用 main_window，避免两个模块互相 import。"""
    QGuiApplication.clipboard().setText(text)


class HistoryDialog(QDialog):
    lookupRequested = Signal(str)   # 双击 / 右键「查词」

    def __init__(self, history: HistoryBook, config=None,
                 theme_manager=None, parent=None):
        super().__init__(parent)
        self._history = history
        self._config = config
        self._theme_manager = theme_manager

        self.setWindowTitle("查询历史")
        self.resize(520, 560)
        self._apply_qss()

        self._build_ui()
        self.refresh()

        # 主题变化时自动刷新（历史窗口可能在主题切换时已经打开）
        if self._theme_manager is not None:
            self._theme_manager.theme_changed.connect(self._apply_qss)

    def _apply_qss(self, mode=None):
        """根据当前主题设置本窗口的 QSS。"""
        if mode is None:
            if self._theme_manager is not None:
                mode = self._theme_manager.mode
            elif self._config is not None:
                mode = _theme.resolve_theme(str(self._config["theme"]))
            else:
                mode = "light"
        self.setStyleSheet(_theme.wb_qss(mode))

    # ------------------------------------------------------------------ 界面
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._filter = QLineEdit(objectName="history_filter")
        self._filter.setPlaceholderText("输入片段筛选查过的词")
        self._filter.setClearButtonEnabled(True)
        self._filter.setToolTip("只显示包含这段文字的记录（不区分大小写）")
        self._filter.textChanged.connect(self.refresh)
        self._filter.returnPressed.connect(self._lookup_first)
        layout.addWidget(self._filter)

        self._count_label = QLabel(objectName="history_count")
        layout.addWidget(self._count_label)

        self._list = QListWidget(objectName="history_list")
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.itemDoubleClicked.connect(self._on_double_clicked)
        self._list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self._list, stretch=1)

        btns = QHBoxLayout()
        self._btn_lookup = QPushButton("查词")
        self._btn_lookup.setToolTip("查询选中的记录（也可直接双击）")
        self._btn_lookup.clicked.connect(self._lookup_selected)
        btns.addWidget(self._btn_lookup)
        self._btn_copy = QPushButton("复制")
        self._btn_copy.clicked.connect(self._copy_selected)
        btns.addWidget(self._btn_copy)
        self._btn_delete = QPushButton("删除")
        self._btn_delete.setToolTip("从历史中移除选中的记录")
        self._btn_delete.clicked.connect(self._delete_selected)
        btns.addWidget(self._btn_delete)
        self._btn_clear = QPushButton("清空历史")
        self._btn_clear.clicked.connect(self._clear_all)
        btns.addWidget(self._btn_clear)
        btns.addStretch(1)
        self._btn_close = QPushButton("关闭")
        self._btn_close.clicked.connect(self.close)
        btns.addWidget(self._btn_close)
        layout.addLayout(btns)

    # ------------------------------------------------------------------ 刷新
    def refresh(self):
        keyword = self._filter.text().strip()
        rows = self._history.recent(limit=500, keyword=keyword)
        self._list.clear()
        for word, queried_at, times in rows:
            item = QListWidgetItem(display_text(word, queried_at, times))
            item.setData(Qt.ItemDataRole.UserRole, word)
            item.setToolTip(f"{word} · 查过 {times} 次")
            self._list.addItem(item)

        total = self._history.count()
        if keyword:
            text = (f"匹配 {len(rows)} 条（共 {total} 条） · 双击查词")
        else:
            text = f"共 {total} 条查询记录 · 双击查词"
        self._count_label.setText(text)

        has_item = bool(rows)
        self._btn_lookup.setEnabled(has_item)
        self._btn_copy.setEnabled(has_item)
        self._btn_delete.setEnabled(has_item)
        self._btn_clear.setEnabled(total > 0)

    def refresh_if_visible(self):
        if self.isVisible():
            self.refresh()

    # ------------------------------------------------------------------ 操作
    def _selected_words(self) -> list[str]:
        words = []
        for item in self._list.selectedItems():
            w = item.data(Qt.ItemDataRole.UserRole)
            if w:
                words.append(w)
        return words

    def _on_double_clicked(self, item: QListWidgetItem):
        word = item.data(Qt.ItemDataRole.UserRole)
        if word:
            self.lookupRequested.emit(word)

    def _lookup_first(self):
        item = self._list.item(0)
        if item is not None:
            self._on_double_clicked(item)

    def _lookup_selected(self):
        for word in self._selected_words():
            self.lookupRequested.emit(word)

    def _copy_selected(self):
        words = self._selected_words()
        if words:
            _copy_text("\n".join(words))

    def _delete_selected(self):
        words = self._selected_words()
        if not words:
            QMessageBox.information(
                self, "删除记录", "请先选择要删除的记录（可按住 Ctrl / Shift 多选）。")
            return
        btn = QMessageBox.question(
            self, "删除记录",
            f"确定从查询历史中删除选中的 {len(words)} 条记录？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        for w in words:
            self._history.remove(w)
        self.refresh()

    def _clear_all(self):
        btn = QMessageBox.question(
            self, "清空历史",
            "确定清空全部查询历史？\n（只清除这里的记录，不影响生词本和词库）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        self._history.clear()
        self.refresh()

    def _menu(self, pos):
        item = self._list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act_lookup = menu.addAction("查词")
        act_copy = menu.addAction("复制")
        menu.addSeparator()
        act_delete = menu.addAction("删除这条记录")
        act_clear = menu.addAction("清空历史")
        chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
        if chosen is act_lookup:
            self._on_double_clicked(item)
        elif chosen is act_copy:
            _copy_text(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        elif chosen is act_delete:
            self._delete_selected()
        elif chosen is act_clear:
            self._clear_all()
