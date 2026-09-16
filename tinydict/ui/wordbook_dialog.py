"""生词本窗口：分组管理 + 生词列表（加入分组 / 移除 / 删除 / 双击查词）。

左侧是分组栏（全部 / 各分组，可新建、重命名、删除、排序），
右侧是当前分组的生词列表（可多选后批量加入其它分组或从本分组移除）。
分组为标签式多归属：一个生词可以同时出现在多个分组里。

没有「未分组」：每个生词至少属于一个分组。把词移出最后一个分组、
删除分组或清空分组时，它会自动归入「默认分组」，不会变成无归属。
"""

import os
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from ..core import wordbook_io as _io
from ..core.wordbook import (
    ALL_GROUPS, DEFAULT_GROUP_ID, WordBook,
)
from ..i18n import _
from . import theme as _theme

#: 导出 / 导入的文件类型过滤器。格式由用户在这里选（或由后缀推断）。
_EXPORT_FILTER = ("CSV 表格（含分组与时间） (*.csv);;"
                  "纯文本（每行一个词） (*.txt);;"
                  "JSON 完整备份（含分组结构） (*.json)")
_IMPORT_FILTER = ("生词文件 (*.txt *.csv *.json);;CSV 表格 (*.csv);;"
                  "纯文本 (*.txt);;JSON 备份 (*.json);;所有文件 (*.*)")

#: 分组项的「名称」（不带计数后缀）存在 UserRole+1，便于跨语言正确取分组名。
_NAME_ROLE = Qt.ItemDataRole.UserRole + 1


class WordbookDialog(QDialog):
    lookupRequested = Signal(str)
    groupsChanged = Signal()      # 分组增删改序，主窗口据此刷新顶栏下拉框
    wordsChanged = Signal()       # 生词增删，主窗口据此刷新 ★ 状态

    def __init__(self, wordbook: WordBook, config=None,
                 theme_manager=None, parent=None):
        super().__init__(parent)
        self._wordbook = wordbook
        self._config = config
        self._theme_manager = theme_manager
        self._current_group = ALL_GROUPS
        self._note = ""           # 操作反馈（显示在计数行末尾，切换分组时清空）

        self.setWindowTitle(_("生词本"))
        self.resize(780, 540)
        self._apply_qss()

        self._build_ui()
        self.refresh()

        # 主题变化时自动刷新（生词本窗口可能在主题切换时已经打开）
        if self._theme_manager is not None:
            self._theme_manager.theme_changed.connect(self._apply_qss)

    def _apply_qss(self, mode=None):
        """根据当前主题设置生词本对话框的 QSS。"""
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

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- 左：分组栏
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        lv.addWidget(QLabel(_("分组"), objectName="wb_title"))

        self._group_list = QListWidget(objectName="wb_group_list")
        self._group_list.currentItemChanged.connect(self._on_group_changed)
        self._group_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._group_list.customContextMenuRequested.connect(self._group_menu)
        lv.addWidget(self._group_list, stretch=1)

        row1 = QHBoxLayout()
        self._btn_new = QPushButton(_("新建"))
        self._btn_new.clicked.connect(self._new_group)
        row1.addWidget(self._btn_new)
        self._btn_rename = QPushButton(_("重命名"))
        self._btn_rename.clicked.connect(self._rename_group)
        row1.addWidget(self._btn_rename)
        self._btn_del = QPushButton(_("删除"))
        self._btn_del.clicked.connect(self._delete_group)
        row1.addWidget(self._btn_del)
        lv.addLayout(row1)

        row2 = QHBoxLayout()
        self._btn_up = QPushButton(_("上移"))
        self._btn_up.clicked.connect(lambda: self._move_group(-1))
        row2.addWidget(self._btn_up)
        self._btn_down = QPushButton(_("下移"))
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
        self._btn_add_to = QPushButton(_("加入到分组 ▸"))
        self._btn_add_to.setToolTip(_(
            "把选中的生词加入其它分组（保留原有分组归属）"))
        self._btn_add_to.clicked.connect(self._add_to_group)
        btns.addWidget(self._btn_add_to)
        self._btn_remove_from = QPushButton(_("从本分组移除"))
        self._btn_remove_from.setToolTip(_(
            "把选中的生词移出当前分组；只属于本分组的词会自动归入「默认分组」"))
        self._btn_remove_from.clicked.connect(self._remove_from_group)
        btns.addWidget(self._btn_remove_from)
        self._btn_delete = QPushButton(_("彻底删除"))
        self._btn_delete.clicked.connect(self._delete_words)
        btns.addWidget(self._btn_delete)
        self._btn_clear = QPushButton(_("清空本分组"))
        self._btn_clear.clicked.connect(self._clear_group)
        btns.addWidget(self._btn_clear)
        # 导入 / 导出是「文件级」操作，和左边的增删分开、靠右放
        btns.addStretch(1)
        self._btn_import = QPushButton(_("导入…"))
        self._btn_import.setToolTip(_(
            "从 txt / csv 导入生词，或从 json 备份恢复"))
        self._btn_import.clicked.connect(self._import_words)
        btns.addWidget(self._btn_import)
        self._btn_export = QPushButton(_("导出…"))
        self._btn_export.setToolTip(_(
            "导出当前分组的生词；选 json 则导出含分组结构的完整备份"))
        self._btn_export.clicked.connect(self._export_words)
        btns.addWidget(self._btn_export)
        self._btn_close = QPushButton(_("关闭"))
        self._btn_close.clicked.connect(self.close)
        btns.addWidget(self._btn_close)
        layout.addLayout(btns)

    # ------------------------------------------------------------------ 刷新
    def refresh(self):
        stats = self._wordbook.stats()
        counts = stats["groups"]

        self._group_list.blockSignals(True)
        self._group_list.clear()
        self._add_group_item(
            _("全部（{}）").format(stats['all']), ALL_GROUPS, _("全部"))
        for g in self._wordbook.groups():
            self._add_group_item(
                f"{g.name}（{counts.get(g.id, 0)}）", g.id, g.name)
        # 分组可能已经不存在（例如配置里还留着被删掉的分组 id）：
        # 这时必须回退到「全部」，否则会出现「左栏高亮『全部（N）』、
        # 右侧却按失效 id 查词而一片空白」，要手点一下分组才恢复。
        row = self._row_of_group(self._current_group)
        if row < 0:
            self._current_group = ALL_GROUPS
            row = self._row_of_group(ALL_GROUPS)
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

    def _add_group_item(self, text: str, group_id: int, name: str = ""):
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, group_id)
        item.setData(_NAME_ROLE, name)
        if group_id == ALL_GROUPS:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setForeground(Qt.GlobalColor.darkGray)
        self._group_list.addItem(item)

    def _row_of_group(self, group_id: int) -> int:
        """返回该分组在左栏的行号；不存在时返回 -1（调用方负责回退）。"""
        for i in range(self._group_list.count()):
            if self._group_list.item(i).data(Qt.ItemDataRole.UserRole) == group_id:
                return i
        return -1

    def _refresh_words(self):
        words = self._wordbook.words(self._current_group)
        self._word_list.clear()
        for word, added_at in words:
            item = QListWidgetItem(
                _("{}    （{}）").format(word, added_at))
            item.setData(Qt.ItemDataRole.UserRole, word)
            self._word_list.addItem(item)

        text = _("「{}」共 {} 个生词 · 双击查词").format(
            self._current_group_name(), len(words))
        if self._note:
            text += f" · {self._note}"
        self._count_label.setText(text)

        is_real_group = self._current_group > 0
        self._btn_remove_from.setEnabled(is_real_group)
        self._btn_add_to.setEnabled(bool(words))
        self._btn_clear.setText(
            _("清空生词本") if self._current_group == ALL_GROUPS
            else _("清空本分组"))

    def _current_group_name(self) -> str:
        """当前分组的名称（不带计数后缀），跨语言安全。

        名称在 _add_group_item 里以 UserRole+1 单独存了一份，
        避免靠「（）」括号切分——英文译文用的是半角括号，切分会失效。
        """
        item = self._group_list.currentItem()
        if item is None:
            return ""
        return item.data(_NAME_ROLE) or ""

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
        name, ok = QInputDialog.getText(
            self, _("新建分组"), _("分组名称："))
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        if self._wordbook.add_group(name) is None:
            QMessageBox.warning(
                self, _("新建分组"), _("分组「{}」已存在。").format(name))
            return
        self._note = _("已新建分组「{}」").format(name)
        self.refresh()
        self.groupsChanged.emit()

    def _rename_group(self):
        gid = self._current_group
        if gid <= 0:
            return
        old = self._wordbook.group_name(gid)
        name, ok = QInputDialog.getText(
            self, _("重命名分组"), _("分组名称："), text=old)
        if not ok:
            return
        name = (name or "").strip()
        if not name or name == old:
            return
        if not self._wordbook.rename_group(gid, name):
            QMessageBox.warning(
                self, _("重命名分组"), _("分组「{}」已存在。").format(name))
            return
        self._note = _("已重命名为「{}」").format(name)
        self.refresh()
        self.groupsChanged.emit()

    def _delete_group(self):
        gid = self._current_group
        if gid <= 0:
            return
        if gid == DEFAULT_GROUP_ID:
            QMessageBox.information(
                self, _("删除分组"),
                _("「默认分组」不可删除（可重命名）。\n"
                  "它是点 ★ 时的兜底分组，删除后新收藏的生词将无处可放。"))
            return
        name = self._wordbook.group_name(gid)
        box = QMessageBox(self)
        box.setWindowTitle(_("删除分组"))
        box.setText(_("确定删除分组「{}」？").format(name))
        box.setInformativeText(_(
            "「仅删除分组」：分组内的生词继续保留在生词本中"
            "（只属于本分组的词会自动归入「默认分组」）。\n"
            "「同时删除生词」：这些生词将从生词本彻底移除"
            "（包括它们在其它分组中的记录）。"))
        btn_keep = box.addButton(_("仅删除分组"),
                                QMessageBox.ButtonRole.AcceptRole)
        btn_all = box.addButton(_("同时删除生词"),
                                QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(_("取消"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_keep:
            n = self._wordbook.remove_group(gid, with_words=False)
            self._note = _("已删除分组「{}」（{} 个生词保留）").format(name, n)
        elif clicked is btn_all:
            n = self._wordbook.remove_group(gid, with_words=True)
            self._note = _("已删除分组「{}」及其中的 {} 个生词").format(name, n)
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
        act_new = menu.addAction(_("新建分组…"))
        act_rename = menu.addAction(_("重命名…"))
        act_delete = menu.addAction(_("删除分组…"))
        menu.addSeparator()
        act_up = menu.addAction(_("上移"))
        act_down = menu.addAction(_("下移"))
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
                self, _("加入到分组"),
                _("请先在右侧选择生词（可按住 Ctrl / Shift 多选）。"))
            return

        groups = self._wordbook.groups()
        menu = QMenu(self)
        actions = {}
        for g in groups:
            actions[menu.addAction(g.name)] = g.id
        menu.addSeparator()
        act_new = menu.addAction(_("新建分组…"))
        chosen = menu.exec(self._btn_add_to.mapToGlobal(
            self._btn_add_to.rect().bottomLeft()))
        if chosen is None:
            return

        if chosen is act_new:
            name, ok = QInputDialog.getText(
                self, _("新建分组"), _("分组名称："))
            if not ok or not (name or "").strip():
                return
            g = self._wordbook.add_group((name or "").strip())
            if g is None:
                QMessageBox.warning(
                    self, _("新建分组"),
                    _("分组「{}」已存在。").format((name or "").strip()))
                return
            gid, gname = g.id, g.name
            self.groupsChanged.emit()
        else:
            gid = actions.get(chosen)
            gname = chosen.text()

        added = self._wordbook.add_words(words, gid)
        self._note = _("已把 {} 个生词加入「{}」（{} 个已在其中）").format(
            added, gname, len(words) - added)
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
        self._note = _("已从「{}」移除 {} 个生词").format(name, removed)
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _delete_words(self):
        words = self._selected_words()
        if not words:
            return
        btn = QMessageBox.question(
            self, _("彻底删除"),
            _("确定从生词本彻底删除选中的 {} 个生词？\n"
              "（会同时移除它们在所有分组中的记录，不可撤销）").format(len(words)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        for w in words:
            self._wordbook.remove(w)
        self._note = _("已彻底删除 {} 个生词").format(len(words))
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _clear_group(self):
        gid = self._current_group
        name = self._current_group_name()
        if gid == ALL_GROUPS:
            text = _("确定清空整个生词本？\n"
                     "所有生词及其分组关联都会被删除，不可撤销。")
        elif gid == DEFAULT_GROUP_ID:
            text = _("确定清空分组「{}」？\n"
                     "只属于本分组的生词会被彻底删除"
                     "（同时也在其它分组的词会保留在那些分组里）。").format(name)
        else:
            text = _("确定清空分组「{}」？\n"
                     "只属于本分组的生词会自动归入「默认分组」，不会丢失。").format(name)
        btn = QMessageBox.question(
            self, _("清空"), text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        self._wordbook.clear(gid)
        self._note = _("已清空「{}」").format(name)
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    # ------------------------------------------------------------ 导入 / 导出
    @staticmethod
    def _write_text(path: str, text: str, encoding: str):
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(text)

    @staticmethod
    def _ext_from_filter(selected: str) -> str:
        """文件名没写后缀时，按用户在对话框里选的过滤器判断格式。"""
        for ext in ("csv", "txt", "json"):
            if f"*.{ext}" in (selected or ""):
                return ext
        return ""

    @staticmethod
    def _safe_name(name: str) -> str:
        """去掉文件名里不能用的字符（分组名是用户随便起的）。"""
        for ch in '\\/:*?"<>|':
            name = name.replace(ch, "_")
        return name.strip() or "生词本"

    def _export_words(self):
        rows = self._wordbook.export_rows(self._current_group)
        if not rows:
            QMessageBox.information(
                self, _("导出"), _("当前分组没有可导出的生词。"))
            return

        stamp = datetime.now().strftime("%Y%m%d")
        group = self._safe_name(self._current_group_name())
        default = f"TinyDict-{group}-{stamp}.csv"
        path, chosen = QFileDialog.getSaveFileName(
            self, _("导出生词本"), default, _EXPORT_FILTER)
        if not path:
            return

        ext = _io.ext_of(path) or self._ext_from_filter(chosen) or "csv"
        if _io.ext_of(path) != ext:
            path = f"{path}.{ext}"

        try:
            if ext == "txt":
                self._write_text(path, _io.dump_txt(rows), "utf-8")
            elif ext == "csv":
                # utf-8-sig：带 BOM，Excel 双击打开不乱码
                self._write_text(path, _io.dump_csv(rows), "utf-8-sig")
            else:
                # 备份不看当前分组，始终导出全部分组与归属
                all_rows = self._wordbook.export_rows(ALL_GROUPS)
                groups = [g.name for g in self._wordbook.groups()]
                self._write_text(
                    path,
                    _io.dump_json(all_rows, groups,
                                  datetime.now().isoformat(timespec="seconds")),
                    "utf-8")
                rows = all_rows
        except OSError as e:
            QMessageBox.warning(
                self, _("导出失败"), _("写入文件失败：\n{}").format(e))
            return

        self._note = _("已导出 {} 个生词到 {}").format(
            len(rows), os.path.basename(path))
        self._refresh_words()

    def _import_words(self):
        path, _chosen = QFileDialog.getOpenFileName(
            self, _("导入生词"), "", _IMPORT_FILTER)
        if not path:
            return
        try:
            # utf-8-sig：兼容 Excel 导出的带 BOM 的 CSV
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
        except OSError as e:
            QMessageBox.warning(
                self, _("导入失败"), _("读取文件失败：\n{}").format(e))
            return

        if _io.ext_of(path) == "json":
            self._import_backup(text)
            return

        words = _io.parse_words(text)
        if not words:
            QMessageBox.information(
                self, _("导入"),
                _("没有从「{}」读到生词。\n"
                  "纯文本 / CSV 里每行写一个词即可（CSV 取第一列）。").format(
                    os.path.basename(path)))
            return
        self._import_plain(words, os.path.basename(path))

    def _import_plain(self, words: list, filename: str):
        """把读到的词表导入用户指定的分组（分组由弹出的菜单选择）。"""
        menu = QMenu(self)
        actions = {}
        for g in self._wordbook.groups():
            actions[menu.addAction(g.name)] = g.id
        menu.addSeparator()
        act_new = menu.addAction(_("新建分组…"))
        chosen = menu.exec(self._btn_import.mapToGlobal(
            self._btn_import.rect().bottomLeft()))
        if chosen is None:
            return

        if chosen is act_new:
            name, ok = QInputDialog.getText(
                self, _("新建分组"), _("分组名称："))
            if not ok or not (name or "").strip():
                return
            g = self._wordbook.add_group((name or "").strip())
            if g is None:
                QMessageBox.warning(
                    self, _("新建分组"),
                    _("分组「{}」已存在。").format((name or "").strip()))
                return
            gid, gname = g.id, g.name
            self.groupsChanged.emit()
        else:
            gid, gname = actions[chosen], chosen.text()

        added = self._wordbook.add_words(words, gid)
        dup = len(words) - added
        self._note = (_("已从 {} 导入 {} 个生词到「{}」{}").format(
            filename, added, gname,
            _("（{} 个已在其中）").format(dup) if dup else ""))
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _import_backup(self, text: str):
        try:
            payload = _io.parse_backup(text)
        except ValueError as e:
            QMessageBox.warning(self, _("导入失败"), str(e))
            return
        words = payload["words"]
        if not words:
            QMessageBox.information(self, _("导入"), _("备份文件里没有生词。"))
            return
        btn = QMessageBox.question(
            self, _("导入备份"),
            _("备份包含 {} 个生词、{} 个分组。\n"
              "将合并到现有生词本：缺少的分组自动新建，重复的词跳过。").format(
                len(words), len(payload['groups'])),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if btn != QMessageBox.StandardButton.Yes:
            return

        stat = self._wordbook.restore(payload)
        self._note = (_("已导入备份：新增 {} 个生词、"
                        "{} 条分组归属、{} 个分组").format(
                            stat['words'], stat['tags'], stat['groups']))
        self.refresh()
        self.groupsChanged.emit()
        self.wordsChanged.emit()

    def _word_menu(self, pos):
        item = self._word_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act_lookup = menu.addAction(_("查词"))
        menu.addSeparator()
        act_add = menu.addAction(_("加入到分组 ▸"))
        act_remove = menu.addAction(
            _("从「{}」移除").format(self._current_group_name())
            if self._current_group > 0 else _("从本分组移除"))
        act_remove.setEnabled(self._current_group > 0)
        menu.addSeparator()
        act_delete = menu.addAction(_("彻底删除"))
        chosen = menu.exec(self._word_list.viewport().mapToGlobal(pos))
        if chosen is act_lookup:
            self._on_double_clicked(item)
        elif chosen is act_add:
            self._add_to_group()
        elif chosen is act_remove:
            self._remove_from_group()
        elif chosen is act_delete:
            self._delete_words()
