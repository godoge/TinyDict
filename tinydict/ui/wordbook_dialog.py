"""生词本窗口：分组管理 + 生词列表（加入分组 / 移除 / 删除 / 双击查词）。

左侧是分组栏（全部 / 未分组 / 各分组，可新建、重命名、删除、排序），
右侧是当前分组的生词列表（可多选后批量加入其它分组或从本分组移除）。
分组为标签式多归属：一个生词可以同时出现在多个分组里。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter, QVBoxLayout,
    QWidget,
)

from ..core.wordbook import (
    ALL_GROUPS, DEFAULT_GROUP_ID, UNGROUPED, WordBook,
)

WB_QSS = """
QListWidget#wb_group_list{
    border:1px solid #e5e7eb;border-radius:6px;background:#fff;font-size:14px;
    outline:0;
}
QListWidget#wb_group_list::item{padding:7px 10px;}
QListWidget#wb_group_list::item:selected{background:#dbeafe;color:#111827;}
QListWidget#wb_word_list{
    border:1px solid #e5e7eb;border-radius:6px;background:#fff;font-size:14px;
    outline:0;
}
QListWidget#wb_word_list::item{padding:5px 10px;}
QListWidget#wb_word_list::item:selected{background:#dbeafe;color:#111827;}
QLabel#wb_count{color:#6b7280;font-size:12px;padding:0 2px 2px 2px;}
QLabel#wb_title{color:#374151;font-size:12px;font-weight:600;}
QPushButton{padding:4px 10px;font-size:13px;}
"""


class WordbookDialog(QDialog):
    lookupRequested = Signal(str)
    groupsChanged = Signal()      # 分组增删改序，主窗口据此刷新顶栏下拉框
    wordsChanged = Signal()       # 生词增删，主窗口据此刷新 ★ 状态

    def __init__(self, wordbook: WordBook, parent=None):
        super().__init__(parent)
        self._wordbook = wordbook
        self._current_group = ALL_GROUPS
        self._note = ""           # 操作反馈（显示在计数行末尾，切换分组时清空）

        self.setWindowTitle("生词本")
        self.resize(780, 540)
        self.setStyleSheet(WB_QSS)

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- 左：分组栏
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        lv.addWidget(QLabel("分组", objectName="wb_title"))

        self._group_list = QListWidget(objectName="wb_group_list")
        self._group_list.currentItemChanged.connect(self._on_group_changed)
        self._group_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._group_list.customContextMenuRequested.connect(self._group_menu)
        lv.addWidget(self._group_list, stretch=1)

        row1 = QHBoxLayout()
        self._btn_new = QPushButton("新建")
        self._btn_new.clicked.connect(self._new_group)
        row1.addWidget(self._btn_new)
        self._btn_rename = QPushButton("重命名")
        self._btn_rename.clicked.connect(self._rename_group)
        row1.addWidget(self._btn_rename)
        self._btn_del = QPushButton("删除")
        self._btn_del.clicked.connect(self._delete_group)
        row1.addWidget(self._btn_del)
        lv.addLayout(row1)

        row2 = QHBoxLayout()
        self._btn_up = QPushButton("上移")
        self._btn_up.clicked.connect(lambda: self._move_group(-1))
        row2.addWidget(self._btn_up)
        self._btn_down = QPushButton("下移")
        self._btn_down.clicked.connect(lambda: self._move_group(1))
        row2.addWidget(self._btn_down)
        lv.addLayout(row2)

        splitter.addWidget(left)

        # ---- 右：生词列表
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(6)
        self._count_label = QLabel(objectName="wb_count")
        rv.addWidget(self._count_label)

        self._word_list = QListWidget(objectName="wb_word_list")
        self._word_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._word_list.itemDoubleClicked.connect(self._on_double_clicked)
        self._word_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._word_list.customContextMenuRequested.connect(self._word_menu)
        rv.addWidget(self._word_list, stretch=1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 520])
        layout.addWidget(splitter, stretch=1)

        # ---- 底部操作
        btns = QHBoxLayout()
        self._btn_add_to = QPushButton("加入到分组 ▸")
        self._btn_add_to.setToolTip("把选中的生词加入其它分组（保留原有分组归属）")
        self._btn_add_to.clicked.connect(self._add_to_group)
        btns.addWidget(self._btn_add_to)
        self._btn_remove_from = QPushButton("从本分组移除")
        self._btn_remove_from.clicked.connect(self._remove_from_group)
        btns.addWidget(self._btn_remove_from)
        self._btn_delete = QPushButton("彻底删除")
        self._btn_delete.clicked.connect(self._delete_words)
        btns.addWidget(self._btn_delete)
        self._btn_clear = QPushButton("清空本分组")
        self._btn_clear.clicked.connect(self._clear_group)
        btns.addWidget(self._btn_clear)
        btns.addStretch(1)
        self._btn_close = QPushButton("关闭")
        self._btn_close.clicked.connect(self.close)
        btns.addWidget(self._btn_close)
        layout.addLayout(btns)

    # ------------------------------------------------------------------ 刷新
    def refresh(self):
        stats = self._wordbook.stats()
        counts = stats["groups"]

        self._group_list.blockSignals(True)
        self._group_list.clear()
        self._add_group_item(f"全部（{stats['all']}）", ALL_GROUPS)
        self._add_group_item(f"未分组（{stats['ungrouped']}）", UNGROUPED)
        for g in self._wordbook.groups():
            self._add_group_item(f"{g.name}（{counts.get(g.id, 0)}）", g.id)
        row = self._row_of_group(self._current_group)
        self._group_list.setCurrentRow(max(row, 0))
        self._group_list.blockSignals(False)

        self._refresh_words()
        self._update_group_buttons()

    def refresh_if_visible(self):
        if self.isVisible():
            self.refresh()

    def select_group(self, group_id: int):
        """切换到指定分组（主窗口打开本窗口时同步顶栏选中的分组）。"""
        self._current_group = group_id
        self._note = ""
        self.refresh()

    def _add_group_item(self, text: str, group_id: int):
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, group_id)
        if group_id in (ALL_GROUPS, UNGROUPED):
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setForeground(Qt.GlobalColor.darkGray)
        self._group_list.addItem(item)

    def _row_of_group(self, group_id: int) -> int:
        for i in range(self._group_list.count()):
            if self._group_list.item(i).data(Qt.ItemDataRole.UserRole) == group_id:
                return i
        return 0

    def _refresh_words(self):
        words = self._wordbook.words(self._current_group)
        self._word_list.clear()
        for word, added_at in words:
            item = QListWidgetItem(f"{word}    （{added_at}）")
            item.setData(Qt.ItemDataRole.UserRole, word)
            self._word_list.addItem(item)

        text = (f"「{self._current_group_name()}」共 {len(words)} 个生词"
                f" · 双击查词")
        if self._note:
            text += f" · {self._note}"
        self._count_label.setText(text)

        is_real_group = self._current_group > 0
        self._btn_remove_from.setEnabled(is_real_group)
        self._btn_add_to.setEnabled(bool(words))
        self._btn_clear.setText(
            "清空生词本" if self._current_group == ALL_GROUPS else "清空本分组")

    def _current_group_name(self) -> str:
        item = self._group_list.currentItem()
        if item is None:
            return ""
        text = item.text()
        return text[:text.rfind("（")] if "（" in text else text

    def _update_group_buttons(self):
        gid = self._current_group
        real = gid > 0
        self._btn_rename.setEnabled(real)
        self._btn_up.setEnabled(real)
        self._btn_down.setEnabled(real)
        # 默认分组不可删除（保证 ★ 始终有可加入的分组），但可重命名
        self._btn_del.setEnabled(real and gid != DEFAULT_GROUP_ID)

    # ------------------------------------------------------------------ 分组
    def _on_group_changed(self, current, previous):  # noqa: ARG002
        if current is None:
            return
        gid = current.data(Qt.ItemDataRole.UserRole)
        if gid is None:
            return
        self._current_group = gid
        self._note = ""
        self._refresh_words()
        self._update_group_buttons()

    def _new_group(self):
        name, ok = QInputDialog.getText(self, "新建分组", "分组名称：")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        if self._wordbook.add_group(name) is None:
            QMessageBox.warning(self, "新建分组", f"分组「{name}」已存在。")
            return
        self._note = f"已新建分组「{name}」"
        self.refresh()
        self.groupsChanged.emit()

    def _rename_group(self):
        gid = self._current_group
        if gid <= 0:
            return
        old = self._wordbook.group_name(gid)
        name, ok = QInputDialog.getText(self, "重命名分组", "分组名称：", text=old)
        if not ok:
            return
        name = (name or "").strip()
        if not name or name == old:
            return
        if not self._wordbook.rename_group(gid, name):
            QMessageBox.warning(self, "重命名分组", f"分组「{name}」已存在。")
            return
        self._note = f"已重命名为「{name}」"
        self.refresh()
        self.groupsChanged.emit()

    def _delete_group(self):
        gid = self._current_group
        if gid <= 0:
            return
        if gid == DEFAULT_GROUP_ID:
            QMessageBox.information(
                self, "删除分组",
                "「默认分组」不可删除（可重命名）。\n"
                "它是点 ★ 时的兜底分组，删除后新收藏的生词将无处可放。")
            return
        name = self._wordbook.group_name(gid)
        box = QMessageBox(self)
        box.setWindowTitle("删除分组")
        box.setText(f"确定删除分组「{name}」？")
        box.setInformativeText(
            "「仅删除分组」：分组内的生词继续保留在生词本中"
            "（只属于本分组的词会归入「未分组」）。\n"
            "「同时删除生词」：这些生词将从生词本彻底移除"
            "（包括它们在其它分组中的记录）。")
        btn_keep = box.addButton("仅删除分组", QMessageBox.ButtonRole.AcceptRole)
        btn_all = box.addButton("同时删除生词",
                                QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_keep:
            n = self._wordbook.remove_group(gid, with_words=False)
            self._note = f"已删除分组「{name}」（{n} 个生词保留）"
        elif clicked is btn_all:
            n = self._wordbook.remove_group(gid, with_words=True)
            self._note = f"已删除分组「{name}」及其中的 {n} 个生词"
        else:
            return
        self._current_group = ALL_GROUPS
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _move_group(self, delta: int):
        gid = self._current_group
        if gid <= 0:
            return
        ids = [g.id for g in self._wordbook.groups()]
        pos = ids.index(gid) if gid in ids else -1
        if pos < 0:
            return
        target = pos + delta
        if not (0 <= target < len(ids)):
            return
        ids[pos], ids[target] = ids[target], ids[pos]
        self._wordbook.reorder_groups(ids)
        self.refresh()
        self.groupsChanged.emit()

    def _group_menu(self, pos):
        menu = QMenu(self)
        act_new = menu.addAction("新建分组…")
        act_rename = menu.addAction("重命名…")
        act_delete = menu.addAction("删除分组…")
        menu.addSeparator()
        act_up = menu.addAction("上移")
        act_down = menu.addAction("下移")
        gid = self._current_group
        act_rename.setEnabled(gid > 0)
        act_delete.setEnabled(gid > 0 and gid != DEFAULT_GROUP_ID)
        act_up.setEnabled(gid > 0)
        act_down.setEnabled(gid > 0)
        chosen = menu.exec(self._group_list.viewport().mapToGlobal(pos))
        if chosen is act_new:
            self._new_group()
        elif chosen is act_rename:
            self._rename_group()
        elif chosen is act_delete:
            self._delete_group()
        elif chosen is act_up:
            self._move_group(-1)
        elif chosen is act_down:
            self._move_group(1)

    # ------------------------------------------------------------------ 生词
    def _selected_words(self) -> list[str]:
        words = []
        for item in self._word_list.selectedItems():
            w = item.data(Qt.ItemDataRole.UserRole)
            if w:
                words.append(w)
        return words

    def _on_double_clicked(self, item: QListWidgetItem):
        word = item.data(Qt.ItemDataRole.UserRole)
        if word:
            self.lookupRequested.emit(word)

    def _add_to_group(self):
        words = self._selected_words()
        if not words:
            QMessageBox.information(
                self, "加入到分组", "请先在右侧选择生词（可按住 Ctrl / Shift 多选）。")
            return

        groups = self._wordbook.groups()
        menu = QMenu(self)
        actions = {}
        for g in groups:
            actions[menu.addAction(g.name)] = g.id
        menu.addSeparator()
        act_new = menu.addAction("新建分组…")
        chosen = menu.exec(self._btn_add_to.mapToGlobal(
            self._btn_add_to.rect().bottomLeft()))
        if chosen is None:
            return

        if chosen is act_new:
            name, ok = QInputDialog.getText(self, "新建分组", "分组名称：")
            if not ok or not (name or "").strip():
                return
            g = self._wordbook.add_group((name or "").strip())
            if g is None:
                QMessageBox.warning(self, "新建分组",
                                    f"分组「{(name or '').strip()}」已存在。")
                return
            gid, gname = g.id, g.name
            self.groupsChanged.emit()
        else:
            gid = actions.get(chosen)
            gname = chosen.text()

        added = self._wordbook.add_words(words, gid)
        self._note = (f"已把 {added} 个生词加入「{gname}」"
                      f"（{len(words) - added} 个已在其中）")
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _remove_from_group(self):
        words = self._selected_words()
        gid = self._current_group
        if not words or gid <= 0:
            return
        name = self._current_group_name()
        removed = self._wordbook.remove_words_from_group(words, gid)
        self._note = f"已从「{name}」移除 {removed} 个生词"
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _delete_words(self):
        words = self._selected_words()
        if not words:
            return
        btn = QMessageBox.question(
            self, "彻底删除",
            f"确定从生词本彻底删除选中的 {len(words)} 个生词？\n"
            "（会同时移除它们在所有分组中的记录，不可撤销）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        for w in words:
            self._wordbook.remove(w)
        self._note = f"已彻底删除 {len(words)} 个生词"
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _clear_group(self):
        gid = self._current_group
        name = self._current_group_name()
        if gid == ALL_GROUPS:
            text = ("确定清空整个生词本？\n"
                    "所有生词及其分组关联都会被删除，不可撤销。")
        elif gid == UNGROUPED:
            text = "确定清空「未分组」中的生词？"
        else:
            text = (f"确定清空分组「{name}」？\n"
                    "生词本体保留；只属于本分组的词会归入「未分组」。")
        btn = QMessageBox.question(
            self, "清空", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        self._wordbook.clear(gid)
        self._note = f"已清空「{name}」"
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _word_menu(self, pos):
        item = self._word_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act_lookup = menu.addAction("查词")
        menu.addSeparator()
        act_add = menu.addAction("加入到分组 ▸")
        act_remove = menu.addAction(
            f"从「{self._current_group_name()}」移除"
            if self._current_group > 0 else "从本分组移除")
        act_remove.setEnabled(self._current_group > 0)
        menu.addSeparator()
        act_delete = menu.addAction("彻底删除")
        chosen = menu.exec(self._word_list.viewport().mapToGlobal(pos))
        if chosen is act_lookup:
            self._on_double_clicked(item)
        elif chosen is act_add:
            self._add_to_group()
        elif chosen is act_remove:
            self._remove_from_group()
        elif chosen is act_delete:
            self._delete_words()
