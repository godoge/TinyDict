"""生词本窗口：列表 / 删除 / 清空 / 双击查词。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout,
)

from ..core.wordbook import WordBook


class WordbookDialog(QDialog):
    lookupRequested = Signal(str)

    def __init__(self, wordbook: WordBook, parent=None):
        super().__init__(parent)
        self._wordbook = wordbook

        self.setWindowTitle("生词本")
        self.resize(420, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self._count_label = QLabel()
        layout.addWidget(self._count_label)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self._list, stretch=1)

        btns = QHBoxLayout()
        self._btn_remove = QPushButton("删除选中")
        self._btn_remove.clicked.connect(self._remove_selected)
        btns.addWidget(self._btn_remove)
        self._btn_clear = QPushButton("清空生词本")
        self._btn_clear.clicked.connect(self._clear_all)
        btns.addWidget(self._btn_clear)
        btns.addStretch(1)
        self._btn_close = QPushButton("关闭")
        self._btn_close.clicked.connect(self.close)
        btns.addWidget(self._btn_close)
        layout.addLayout(btns)

        self.refresh()

    def refresh(self):
        self._list.clear()
        words = self._wordbook.words()
        for word, added_at in words:
            item = QListWidgetItem(f"{word}    （{added_at}）")
            item.setData(Qt.ItemDataRole.UserRole, word)
            self._list.addItem(item)
        self._count_label.setText(f"共 {len(words)} 个生词（双击查词）")

    def refresh_if_visible(self):
        if self.isVisible():
            self.refresh()

    def _on_double_clicked(self, item: QListWidgetItem):
        word = item.data(Qt.ItemDataRole.UserRole)
        if word:
            self.lookupRequested.emit(word)

    def _remove_selected(self):
        item = self._list.currentItem()
        if item is None:
            return
        word = item.data(Qt.ItemDataRole.UserRole)
        if word:
            self._wordbook.remove(word)
            self.refresh()

    def _clear_all(self):
        self._wordbook.clear()
        self.refresh()
