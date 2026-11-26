"""笔记的导入 / 导出，以及跨设备冲突的人工合并。

界面只负责选文件、读写磁盘、给提示；格式逻辑在 core.note_io、合并逻辑在
core.notes，两边都能脱离 Qt 单独测试。
"""

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
    QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from ..core import note_io
from ..core.notes import (STRATEGY_KEEP_LOCAL, STRATEGY_MERGE,
                          STRATEGY_OVERWRITE)
from ..i18n import _
from . import theme as _theme

_EXPORT_FILTER = (
    "JSON 笔记备份 (*.json);;CSV 表格 (*.csv);;MDX 词库 (*.mdx);;所有文件 (*)")
_IMPORT_FILTER = (
    "笔记 / 生词本备份 (*.json *.csv *.txt);;JSON (*.json);;CSV (*.csv);;"
    "所有文件 (*)")

_FORMATS = ("json", "wordbook_json", "csv", "wordbook_csv", "mdx")
_FORMAT_HINTS = {
    "json": "完整同步备份：带设备标识、修改时间、版本号和删除标记，"
            "适合电脑 ↔ 手机、电脑 ↔ 电脑双向同步。",
    "wordbook_json": "手机版现有生词本备份格式 + 可选笔记字段。"
                     "未装配套补丁的旧版手机也能导入生词，只是暂不显示笔记。",
    "csv": "通用表格，Excel 可直接打开；正文里带换行也能正确还原。",
    "wordbook_csv": "手机版生词本 CSV + 笔记扩展列，列顺序与旧版兼容。",
    "mdx": "把笔记打包成只读 MDX 词库，任何 MDX 词典软件都能查；"
           "它是快照，不参与同步与编辑。",
}
_STRATEGIES = (
    (STRATEGY_MERGE, "三路合并（推荐）"),
    (STRATEGY_KEEP_LOCAL, "只补本地没有的"),
    (STRATEGY_OVERWRITE, "以导入文件为准"),
)
_STRATEGY_HINTS = {
    STRATEGY_MERGE: "用上次同步的内容做基线：只有一端改过就自动合并；"
                    "两端都改过则保留本机，并把另一端完整存成冲突副本，"
                    "可在笔记面板的「冲突」按钮里人工合并，不会静默丢内容。",
    STRATEGY_KEEP_LOCAL: "本机已有的笔记一律不动（包括已删除的），"
                         "只把文件里本机完全没有的词补进来。",
    STRATEGY_OVERWRITE: "同名笔记无条件用文件内容覆盖本机版本。",
}

def notes_qss(mode: str) -> str:
    """笔记对话框的样式：列表型对话框基底 + 笔记面板专属样式。

    专属样式统一放在 theme.notes_panel_qss()，主窗口直接叠加同一份。
    """
    return _theme.wb_qss(mode) + _theme.notes_panel_qss(mode)


def _apply_dialog_theme(dlg, theme_manager, config=None):
    if theme_manager is not None:
        mode = theme_manager.mode
    elif config is not None:
        mode = _theme.resolve_theme(str(config["theme"]))
    else:
        mode = "light"
    dlg.setStyleSheet(notes_qss(mode))
    return mode


class NotesTransferDialog(QDialog):
    """两页：导出笔记备份 / 从另一台设备导入并合并。"""

    def __init__(self, notes, wordbook=None, theme_manager=None,
                 config=None, parent=None):
        super().__init__(parent)
        self._notes = notes
        self._wordbook = wordbook
        self._theme_manager = theme_manager
        self._records = []
        self._peer_id = ""
        self._fmt_radios = {}
        self._strategy_radios = {}

        self.setWindowTitle(_("笔记导入 / 导出"))
        self.resize(520, 420)
        tabs = QTabWidget(self)
        tabs.addTab(self._build_export_tab(), _("导出"))
        tabs.addTab(self._build_import_tab(), _("导入"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(_("关闭"))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        _apply_dialog_theme(self, theme_manager, config)

    # ------------------------------------------------------------------ 界面
    def _build_export_tab(self):
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(6)
        stats = self._notes.stats()
        self._stats_label = QLabel(
            _("当前共 {} 条笔记、{} 条删除记录、{} 条未处理冲突。").format(
                stats["notes"], stats["tombstones"], stats["conflicts"]),
            objectName="notes_hint")
        self._stats_label.setWordWrap(True)
        vbox.addWidget(self._stats_label)
        vbox.addWidget(QLabel(_("导出格式："), objectName="notes_section"))

        labels = {
            "json": _("JSON 完整备份（推荐，可双向同步）"),
            "wordbook_json": _("手机版生词本备份 JSON（带笔记）"),
            "csv": _("CSV 表格"),
            "wordbook_csv": _("手机版生词本 CSV（带笔记）"),
            "mdx": _("MDX 词库快照（只读）"),
        }
        self._fmt_hint = QLabel(objectName="notes_hint")
        self._fmt_hint.setWordWrap(True)
        self._fmt_hint.setMinimumHeight(48)
        for fmt in _FORMATS:
            radio = QRadioButton(labels[fmt])
            radio.toggled.connect(
                lambda checked, f=fmt: self._on_fmt(checked, f))
            self._fmt_radios[fmt] = radio
            vbox.addWidget(radio)
        vbox.addWidget(self._fmt_hint)
        self._fmt_radios["json"].setChecked(True)
        self._on_fmt(True, "json")

        self._btn_export = QPushButton(_("导出到文件…"))
        self._btn_export.clicked.connect(self._export)
        vbox.addWidget(self._btn_export)
        vbox.addStretch(1)
        return page

    def _build_import_tab(self):
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(6)
        vbox.addWidget(QLabel(_("从手机或另一台电脑导出的笔记文件："),
                             objectName="notes_section"))
        self._file_label = QLabel(_("尚未选择文件"), objectName="notes_hint")
        self._file_label.setWordWrap(True)
        self._file_label.setMinimumHeight(40)
        vbox.addWidget(self._file_label)
        self._btn_choose = QPushButton(_("选择文件…"))
        self._btn_choose.clicked.connect(self._choose_file)
        vbox.addWidget(self._btn_choose)

        vbox.addWidget(QLabel(_("冲突处理方式："), objectName="notes_section"))
        self._strategy_hint = QLabel(objectName="notes_hint")
        self._strategy_hint.setWordWrap(True)
        self._strategy_hint.setMinimumHeight(52)
        for key, label in _STRATEGIES:
            radio = QRadioButton(_(label))
            radio.toggled.connect(
                lambda checked, k=key: self._on_strategy(checked, k))
            self._strategy_radios[key] = radio
            vbox.addWidget(radio)
        vbox.addWidget(self._strategy_hint)
        self._strategy_radios[STRATEGY_MERGE].setChecked(True)
        self._on_strategy(True, STRATEGY_MERGE)

        self._btn_import = QPushButton(_("开始导入"))
        self._btn_import.setEnabled(False)
        self._btn_import.clicked.connect(self._import)
        vbox.addWidget(self._btn_import)
        vbox.addStretch(1)
        return page

    # ------------------------------------------------------------------ 行为
    def _on_fmt(self, checked, fmt):
        if checked:
            self._fmt_hint.setText(_(_FORMAT_HINTS[fmt]))

    def _on_strategy(self, checked, key):
        if checked:
            self._strategy_hint.setText(_(_STRATEGY_HINTS[key]))

    def _format(self) -> str:
        return next((f for f, r in self._fmt_radios.items() if r.isChecked()),
                    "json")

    def _strategy(self) -> str:
        return next((k for k, r in self._strategy_radios.items()
                     if r.isChecked()), STRATEGY_MERGE)

    def _groups_by_word(self, records):
        """手机版格式需要每个词所属的生词本名；没有分组的词归到默认分组。"""
        if self._wordbook is None:
            return {}
        out = {}
        for note in records:
            try:
                groups = self._wordbook.groups_of(note.word)
            except Exception:
                groups = []
            if groups:
                out[note.word.strip().casefold()] = list(groups)
        return out

    @staticmethod
    def _write_text(path, text, encoding):
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(text)

    def _export(self):
        fmt = self._format()
        records = self._notes.all(include_deleted=True)
        if not records:
            QMessageBox.information(self, _("导出笔记"), _("还没有任何笔记。"))
            return
        ext = "mdx" if fmt == "mdx" else ("csv" if "csv" in fmt else "json")
        stamp = datetime.now().strftime("%Y%m%d")
        default = f"TinyDict-notes-{stamp}.{ext}"
        path, _chosen = QFileDialog.getSaveFileName(
            self, _("导出笔记"), default, _EXPORT_FILTER)
        if not path:
            return
        if note_io.ext_of(path) != ext:
            path = os.path.splitext(path)[0] + "." + ext

        now = datetime.now().isoformat(timespec="seconds")
        groups = (self._groups_by_word(records)
                  if fmt.startswith("wordbook") else {})
        try:
            if fmt == "mdx":
                note_io.dump_mdx(
                    [n for n in records if not n.deleted and n.body],
                    path, title="TinyDict 笔记")
            else:
                if fmt == "json":
                    text = note_io.dump_json(records, self._notes.device_id,
                                             now, "desktop")
                elif fmt == "wordbook_json":
                    text = note_io.dump_wordbook_json(records, now, groups,
                                                      added_at=now)
                elif fmt == "csv":
                    text = note_io.dump_csv(records)
                else:
                    text = note_io.dump_wordbook_csv(records, groups,
                                                     added_at=now)
                encoding = "utf-8-sig" if ext == "csv" else "utf-8"
                self._write_text(path, text, encoding)
        except (OSError, ValueError, ImportError) as exc:
            QMessageBox.warning(self, _("导出失败"),
                                _("写入文件失败：\n{}").format(exc))
            return

        # 只在写文件成功之后推进基线；MDX 是只读快照，不参与双端同步，
        # 推进它反而会让下次真正的同步误判「本机已经同步过」。
        if fmt != "mdx":
            self._notes.mark_synced("export")
        QMessageBox.information(
            self, _("导出完成"),
            _("已导出 {} 条记录到 {}。\n\n已记录同步基线：之后在另一台设备上"
              "的修改可以正确区分，不会误判成冲突。").format(
                len(records), os.path.basename(path)))

    def _choose_file(self):
        path, _chosen = QFileDialog.getOpenFileName(
            self, _("导入笔记"), "", _IMPORT_FILTER)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
        except OSError as exc:
            QMessageBox.warning(self, _("导入失败"),
                                _("读取文件失败：\n{}").format(exc))
            return
        try:
            records, device, exported = note_io.parse_notes(text, path)
        except ValueError as exc:
            QMessageBox.warning(self, _("导入失败"), str(exc))
            return
        if not records:
            QMessageBox.information(
                self, _("导入笔记"),
                _("这个文件里没有笔记。\n如果是手机版导出的生词本备份，"
                  "需要先在手机端合入笔记导出补丁。"))
            return
        self._records = records
        self._peer_id = device or os.path.basename(path)
        self._file_label.setText(
            _("{}：{} 条笔记，来源 {}，导出时间 {}").format(
                os.path.basename(path), len(records),
                self._peer_id, exported or _("未知")))
        self._btn_import.setEnabled(True)

    def _import(self):
        if not self._records:
            return
        strategy = self._strategy()
        btn = QMessageBox.question(
            self, _("导入笔记"),
            _("即将合并 {} 条笔记（来源 {}）。\n\n处理方式：{}\n\n"
              "三路合并会保留本机最近一次的修改；两端都改过的词不会静默覆盖，"
              "而是留下冲突副本供人工合并。继续吗？").format(
                len(self._records), self._peer_id,
                _(dict(_STRATEGIES)[strategy])),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if btn != QMessageBox.StandardButton.Yes:
            return
        report = self._notes.merge(self._records, peer_id=self._peer_id,
                                   strategy=strategy)
        msg = _("导入完成：{}。").format(report.summary())
        if report.conflicts:
            msg += _("\n\n{} 条笔记在两端都被修改过：已保留本机版本，"
                     "另一端的完整内容存为冲突副本。点笔记面板右上角的"
                     "「冲突」按钮即可人工合并。").format(len(report.conflicts))
        QMessageBox.information(self, _("导入完成"), msg)
        self._records = []
        self._peer_id = ""
        self._btn_import.setEnabled(False)
        self._file_label.setText(_("导入完成，可以继续选择其它文件。"))
        self._stats_label.setText(
            _("当前共 {} 条笔记、{} 条删除记录、{} 条未处理冲突。").format(
                *[self._notes.stats()[k]
                  for k in ("notes", "tombstones", "conflicts")]))


class NoteConflictDialog(QDialog):
    """列出未解决的冲突，左右对照两端内容，由用户决定保留哪个或手工合并。"""

    def __init__(self, notes, theme_manager=None, config=None, parent=None):
        super().__init__(parent)
        self._notes = notes
        self._conflicts = []
        self.setWindowTitle(_("合并冲突的笔记"))
        self.resize(720, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addWidget(QLabel(
            _("两端都修改过同一条笔记时，本机版本已保留。"
              "下面可以逐条选择保留哪个版本，或手工拼出最终内容。"),
            objectName="notes_hint"))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget(objectName="export_group_list")
        self._list.currentItemChanged.connect(self._on_selected)
        splitter.addWidget(self._list)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        rv.addWidget(QLabel(_("本机版本"), objectName="notes_section"))
        self._local = QTextEdit(objectName="notes_editor")
        self._local.setReadOnly(True)
        self._local.setMaximumHeight(110)
        rv.addWidget(self._local)
        rv.addWidget(QLabel(_("导入版本"), objectName="notes_section"))
        self._remote = QTextEdit(objectName="notes_editor")
        self._remote.setReadOnly(True)
        self._remote.setMaximumHeight(110)
        rv.addWidget(self._remote)
        rv.addWidget(QLabel(_("合并结果（可编辑）"), objectName="notes_section"))
        self._merged = QTextEdit(objectName="notes_editor")
        rv.addWidget(self._merged, stretch=1)
        splitter.addWidget(right)
        splitter.setSizes([210, 490])
        root.addWidget(splitter, stretch=1)

        buttons = QHBoxLayout()
        self._btn_keep = QPushButton(_("保留本机"))
        self._btn_take = QPushButton(_("采用导入"))
        self._btn_merge = QPushButton(_("保存合并结果"))
        self._btn_keep.clicked.connect(
            lambda: self._resolve("keep_local"))
        self._btn_take.clicked.connect(
            lambda: self._resolve("take_remote"))
        self._btn_merge.clicked.connect(
            lambda: self._resolve("merged"))
        for b in (self._btn_keep, self._btn_take, self._btn_merge):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self._btn_close = QPushButton(_("关闭"))
        self._btn_close.clicked.connect(self.accept)
        buttons.addWidget(self._btn_close)
        root.addLayout(buttons)

        self._empty = QLabel("", objectName="notes_state")
        root.addWidget(self._empty)
        _apply_dialog_theme(self, theme_manager, config)
        self._reload()

    def _reload(self):
        self._conflicts = self._notes.conflicts()
        self._list.clear()
        for conflict in self._conflicts:
            item = QListWidgetItem(
                _("{}（{}）").format(conflict.word,
                                     conflict.remote_updated_at or _("时间未知")))
            item.setData(Qt.ItemDataRole.UserRole, conflict.id)
            self._list.addItem(item)
        has = bool(self._conflicts)
        for btn in (self._btn_keep, self._btn_take, self._btn_merge):
            btn.setEnabled(has)
        if has:
            self._list.setCurrentRow(0)
            self._empty.setText(
                _("还有 {} 条冲突待处理。").format(len(self._conflicts)))
        else:
            self._local.clear()
            self._remote.clear()
            self._merged.clear()
            self._empty.setText(_("所有冲突都已处理。"))

    def _current(self):
        item = self._list.currentItem()
        if item is None:
            return None
        cid = item.data(Qt.ItemDataRole.UserRole)
        return next((c for c in self._conflicts if c.id == cid), None)

    def _on_selected(self):
        conflict = self._current()
        if conflict is None:
            return
        self._local.setPlainText(conflict.local_body)
        self._remote.setPlainText(conflict.remote_body)
        parts = [p for p in (conflict.local_body, conflict.remote_body) if p]
        self._merged.setPlainText("\n\n".join(parts))

    def _resolve(self, choice):
        conflict = self._current()
        if conflict is None:
            return
        body = self._merged.toPlainText() if choice == "merged" else ""
        self._notes.resolve_conflict(conflict.id, choice, body)
        self._reload()
