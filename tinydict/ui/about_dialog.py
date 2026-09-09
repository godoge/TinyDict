"""「关于」对话框：软件介绍 / 版本 / 开源地址。

面向的是普通用户，只放看得懂的信息：这是什么软件、什么版本、源码在哪、
有问题去哪儿反馈。技术栈、运行环境、数据目录等一概不展示。
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from .. import __version__, APP_NAME
from .icons import app_icon

REPO_URL = "https://github.com/godoge/TinyDict"
RELEASES_URL = "https://github.com/godoge/TinyDict/releases"
ISSUES_URL = "https://github.com/godoge/TinyDict/issues"


def open_url(url: str):
    QDesktopServices.openUrl(QUrl(url))


def copy_to_clipboard(text: str):
    QApplication.clipboard().setText(text)


class AboutDialog(QDialog):
    """关于本软件。

    dict_summary 由主窗口传入（形如「3 部（2 部已挂载）」），
    为空则不显示该行——避免对话框自己去依赖词库服务。
    """

    def __init__(self, dict_summary: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于 {APP_NAME}")
        self.setModal(True)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        root.addLayout(self._build_header())
        root.addWidget(self._separator())
        root.addLayout(self._build_info(dict_summary))
        root.addWidget(self._separator())
        root.addWidget(self._build_note())
        root.addLayout(self._build_buttons())

    # ---------------------------------------------------------------- 结构
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(72, 72))
        icon.setFixedSize(72, 72)
        row.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        title = QLabel(
            f'<span style="font-size:19px;font-weight:600">{APP_NAME}</span>'
            f'<span style="font-size:13px"> &nbsp;v{__version__}</span>')
        col.addWidget(title)
        desc = QLabel(
            "一款 Windows 上的离线词典：添加自己的 .mdx 词库后即加即用，"
            "查词全程在你自己的电脑上完成，不联网、不上传任何内容。")
        desc.setWordWrap(True)
        desc.setFixedWidth(300)
        col.addWidget(desc)
        row.addLayout(col)
        row.addStretch(1)
        return row

    def _build_info(self, dict_summary: str) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addLayout(self._row(
            "开源地址", f'<a href="{REPO_URL}">{REPO_URL}</a>', link=True))
        box.addLayout(self._row(
            "问题反馈", f'<a href="{ISSUES_URL}">在 GitHub 上提交问题</a>',
            link=True))
        if dict_summary:
            box.addLayout(self._row("已启用词典", dict_summary))
        return box

    def _row(self, label: str, value: str, *, link: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        lab = QLabel(label)
        lab.setFixedWidth(72)
        lab.setStyleSheet("font-weight:500")
        lab.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        row.addWidget(lab, alignment=Qt.AlignmentFlag.AlignTop)

        val = QLabel(value)
        val.setWordWrap(True)
        # 地址需要能选中复制，链接还要能直接点开
        val.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            if link else Qt.TextInteractionFlag.TextSelectableByMouse)
        if link:
            val.setOpenExternalLinks(True)
        row.addWidget(val, stretch=1)
        return row

    def _build_note(self) -> QLabel:
        note = QLabel(
            '<span style="font-size:11px">本软件只负责本地解析与展示，'
            "词典文件由你自行提供，其中的内容版权归各词典原作者所有。</span>")
        note.setWordWrap(True)
        return note

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        btn_copy = QPushButton("复制开源地址")
        btn_copy.setToolTip("把项目地址复制到剪贴板")
        btn_copy.clicked.connect(lambda: copy_to_clipboard(REPO_URL))
        row.addWidget(btn_copy)

        btn_update = QPushButton("查看新版本")
        btn_update.setToolTip("打开 Releases 页面，看看有没有更新的版本")
        btn_update.clicked.connect(lambda: open_url(RELEASES_URL))
        row.addWidget(btn_update)

        row.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        row.addWidget(box)
        return row

    @staticmethod
    def _separator() -> QWidget:
        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color:palette(mid)")
        return line
