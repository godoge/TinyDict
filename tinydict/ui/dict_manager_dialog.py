"""词库管理对话框：注册（文件 / 文件夹）/ 删除 / 启用禁用 / 优先级排序。

挂载式架构：注册只读取 MDX 头部（秒级完成），词条数据留在原文件中，
后台自动挂载 key 索引（对话框与主窗口通过信号感知挂载进度）。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..core.mdx_access import scan_mdx_files
from ..core.query import DictionaryService


_STATUS_LABELS = {
    "ready": ("就绪", "#059669"),
    "loading": ("加载中", "#b45309"),
    "missing": ("文件缺失", "#dc2626"),
    "disabled": ("已禁用", "#6b7280"),
}


class DictManagerDialog(QDialog):
    dicts_changed = Signal()

    def __init__(self, service: DictionaryService, parent=None):
        super().__init__(parent)
        self._service = service

        self.setWindowTitle("词库管理")
        self.resize(680, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        tip = QLabel(
            "列表顺序即查询优先级（排在前面的词库优先展示结果）。"
            "注册即时生效：词条保留在原始 .mdx 文件中，按需读取，"
            "无需等待导入；删除仅取消注册，不影响原文件。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#6b7280;font-size:12px;")
        layout.addWidget(tip)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["启用", "词库名称", "词条数", "状态"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 50)
        self._table.setColumnWidth(2, 110)
        self._table.setColumnWidth(3, 90)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, stretch=1)

        btns = QHBoxLayout()
        self._btn_file = QPushButton("添加文件…")
        self._btn_file.clicked.connect(self._add_files)
        btns.addWidget(self._btn_file)

        self._btn_folder = QPushButton("添加文件夹…")
        self._btn_folder.clicked.connect(self._add_folder)
        btns.addWidget(self._btn_folder)

        self._btn_reload = QPushButton("重新挂载")
        self._btn_reload.clicked.connect(self._reload_mounts)
        btns.addWidget(self._btn_reload)

        self._btn_up = QPushButton("上移")
        self._btn_up.clicked.connect(lambda: self._move(-1))
        btns.addWidget(self._btn_up)

        self._btn_down = QPushButton("下移")
        self._btn_down.clicked.connect(lambda: self._move(1))
        btns.addWidget(self._btn_down)

        self._btn_delete = QPushButton("移除词库")
        self._btn_delete.clicked.connect(self._delete_selected)
        btns.addWidget(self._btn_delete)

        self._btn_close = QPushButton("关闭")
        self._btn_close.clicked.connect(self.close)
        btns.addStretch(1)
        btns.addWidget(self._btn_close)
        layout.addLayout(btns)

        # 挂载完成时自动刷新状态列
        self._service.dict_mounted.connect(self._on_mount_progress)
        self._service.mount_finished.connect(self.refresh)

        self.refresh()

    # ------------------------------------------------------------------ 列表
    def refresh(self):
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for d in self._service.all_dicts():
            row = self._table.rowCount()
            self._table.insertRow(row)

            enabled = QTableWidgetItem()
            enabled.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            enabled.setCheckState(
                Qt.CheckState.Checked if d.enabled else Qt.CheckState.Unchecked)
            enabled.setData(Qt.ItemDataRole.UserRole, d.id)

            name = QTableWidgetItem(d.name)
            name.setToolTip(d.filename)

            entries = QTableWidgetItem(
                f"{d.entry_count:,}" if d.entry_count else "—")
            entries.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            status_key = self._service.mount_status(d.id)
            label, color = _STATUS_LABELS.get(status_key, (status_key, "#6b7280"))
            status = QTableWidgetItem(label)
            status.setForeground(QColor(color))

            self._table.setItem(row, 0, enabled)
            self._table.setItem(row, 1, name)
            self._table.setItem(row, 2, entries)
            self._table.setItem(row, 3, status)
        self._table.blockSignals(False)

    def _on_mount_progress(self, dict_id: int):
        if self.isVisible():
            self.refresh()

    def _current_dict_id(self):
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        dict_id = item.data(Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == Qt.CheckState.Checked
        self._service._db.set_enabled(dict_id, enabled)
        self.refresh()
        self.dicts_changed.emit()

    # ------------------------------------------------------------------ 排序
    def _current_ids(self):
        ids = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    def _move(self, delta: int):
        row = self._table.currentRow()
        if row < 0:
            return
        target = row + delta
        if not (0 <= target < self._table.rowCount()):
            return
        ids = self._current_ids()
        ids[row], ids[target] = ids[target], ids[row]
        self._service._db.reorder(ids)
        self.refresh()
        self._table.setCurrentCell(target, 0)
        self.dicts_changed.emit()

    # ------------------------------------------------------------------ 删除
    def _delete_selected(self):
        dict_id = self._current_dict_id()
        if dict_id is None:
            return
        row = self._table.currentRow()
        name = self._table.item(row, 1).text()
        btn = QMessageBox.question(
            self, "移除词库",
            f"确定移除词库「{name}」？\n"
            "仅从词库列表取消注册，原始 .mdx/.mdd 文件不受影响，"
            "可随时重新添加。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        self._service.unregister(dict_id)
        self.refresh()
        self.dicts_changed.emit()

    # ------------------------------------------------------------------ 添加
    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 MDX 词库文件（可多选）", "",
            "MDX 词库 (*.mdx);;所有文件 (*.*)")
        registered, skipped, failed = 0, 0, []
        for p in paths:
            try:
                if self._service.register_file(p) is not None:
                    registered += 1
                else:
                    skipped += 1
            except Exception as e:  # noqa: BLE001
                failed.append(f"{p}\n  {e}")
        self._report_add_result(registered, skipped, failed)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择词库文件夹（将扫描其中全部 .mdx）")
        if not folder:
            return
        try:
            from pathlib import Path
            registered = self._service.register_folder(folder)
            total = len(scan_mdx_files(Path(folder)))
            skipped = total - len(registered)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "添加失败", str(e))
            return
        self._report_add_result(len(registered), skipped, [])

    def _report_add_result(self, registered: int, skipped: int, failed: list):
        if registered:
            # 立即触发后台挂载（加载 key 索引）
            self._service.mount_all_async()
            self.dicts_changed.emit()
        self.refresh()
        if not registered and not skipped and not failed:
            return
        if failed:
            QMessageBox.warning(
                self, "部分文件添加失败",
                "以下文件添加失败：\n\n" + "\n".join(failed))
        elif registered:
            QMessageBox.information(
                self, "添加完成",
                f"已添加 {registered} 部词库并开始后台加载。"
                f"{f'（跳过已添加 {skipped} 部）' if skipped else ''}\n"
                "加载完成后即可查询（列表「状态」列显示进度）。")

    def _reload_mounts(self):
        self._service.mount_all_async()
        self.refresh()
