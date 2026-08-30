"""词库管理对话框：注册（文件 / 文件夹）/ 删除 / 启用禁用 / 优先级排序。

挂载式架构：注册只读取 MDX 头部（秒级完成），词条数据留在原文件中，
后台自动挂载 key 索引（对话框与主窗口通过信号感知挂载进度）。
"""

from pathlib import Path

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

_STATUS_TOOLTIP = {
    "ready": "已加载完成，可正常查询",
    "loading": "正在后台加载 key 索引，稍候即可查询",
    "disabled": "已取消启用，不参与查询（勾选可重新启用）",
    "missing": "原始 .mdx 文件找不到，需「修复路径」",
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

        # 缺失文件告警条：有词库文件找不到时显示，引导用户用「修复路径」
        self._warn_label = QLabel("")
        self._warn_label.setWordWrap(True)
        self._warn_label.setStyleSheet(
            "color:#dc2626;font-size:12px;background:#fef2f2;"
            "border:1px solid #fecaca;border-radius:6px;padding:6px 8px;")
        self._warn_label.hide()
        layout.addWidget(self._warn_label)

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

        self._btn_repair = QPushButton("修复路径…")
        self._btn_repair.setToolTip(
            "为路径失效（改名 / 移动过文件夹）的词库重新指定 .mdx 文件")
        self._btn_repair.clicked.connect(self._repair_selected)
        btns.addWidget(self._btn_repair)

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
        # 双击「文件缺失」的行 = 直接修复路径
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self.refresh()

    # ------------------------------------------------------------------ 列表
    def refresh(self):
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        missing_rows = []
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
            # 缺失：把原因（含失效的原路径）写进 tooltip，让用户一键看懂
            if status_key == "missing":
                err = self._service.mount_error(d.id)
                reason = err or "原始 .mdx 文件找不到（可能被改名 / 移动 / 删除）"
                status.setToolTip(reason)
                name.setToolTip(f"{d.filename}\n\n{reason}")
                missing_rows.append(d.name)
            else:
                status.setToolTip(_STATUS_TOOLTIP.get(status_key, label))

            self._table.setItem(row, 0, enabled)
            self._table.setItem(row, 1, name)
            self._table.setItem(row, 2, entries)
            self._table.setItem(row, 3, status)
        self._table.blockSignals(False)

        # 缺失告警条
        if missing_rows:
            self._warn_label.setText(
                f"⚠ 有 {len(missing_rows)} 部词库文件缺失（通常是文件夹被改名 / 移动后"
                f"路径失效）：{', '.join(missing_rows)}。\n"
                f"选中后点「修复路径…」重新指定 .mdx 文件即可恢复。")
            self._warn_label.show()
        else:
            self._warn_label.hide()

    def _on_mount_progress(self, dict_id: int):
        if self.isVisible():
            self.refresh()

    # ------------------------------------------------------------------ 修复
    def _repair_selected(self):
        """为选中的词库重新指定 .mdx 文件（路径失效时恢复）。"""
        dict_id = self._current_dict_id()
        if dict_id is None:
            QMessageBox.information(self, "修复路径", "请先选中一行词库。")
            return
        d = next((x for x in self._service.all_dicts() if x.id == dict_id), None)
        if d is None:
            return
        start_dir = str(Path(d.filename).parent) \
            if Path(d.filename).parent.is_dir() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, f"为「{d.name}」选择 .mdx 文件", start_dir,
            "MDX 词库 (*.mdx);;所有文件 (*.*)")
        if not path:
            return
        try:
            self._service.repair_path(dict_id, path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "修复失败", str(e))
            return
        self.refresh()
        self.dicts_changed.emit()
        QMessageBox.information(
            self, "修复成功",
            f"已更新「{d.name}」的词库路径为：\n{path}\n\n正在后台重新加载。")

    def _on_cell_double_clicked(self, row: int, _col: int):
        item = self._table.item(row, 0)
        if item is None:
            return
        dict_id = item.data(Qt.ItemDataRole.UserRole)
        if self._service.mount_status(dict_id) == "missing":
            self._repair_selected()

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
