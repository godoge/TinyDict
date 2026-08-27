"""程序图标：代码绘制（无外部资源文件依赖）。"""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2563eb"))
        p.drawRoundedRect(2, 2, 60, 60, 14, 14)
        p.setPen(QColor("white"))
        p.setFont(QFont("Segoe UI", 34, QFont.Weight.Bold))
        p.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "S")
    finally:
        p.end()
    return QIcon(pm)
