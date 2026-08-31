"""程序图标：代码绘制（无外部资源文件依赖）。

设计：蓝色渐变圆角底 + 翻开的白书 + 金色书签（像「词典」本身）。
绘制全部用 QPainter 图元（矩形 / 曲线 / 渐变）完成，不依赖字体，
因此运行时窗口 / 托盘图标与打包嵌入的 assets/icon.ico 像素级一致。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def paint_icon(p: QPainter, size: int) -> None:
    """在已建立的 size×size 透明画布上绘制 TinyDict 图标。

    p 需已开启 Antialiasing；本函数不负责创建 / 销毁 QPainter。
    """
    m = max(1, int(size * 0.04))
    r = int(size * 0.22)

    # 1) 蓝色渐变圆角底（右上深、左下亮，制造体积感）
    bg = QLinearGradient(0, 0, size, size)
    bg.setColorAt(0.0, QColor("#4f8cff"))
    bg.setColorAt(1.0, QColor("#1e54d6"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(bg))
    p.drawRoundedRect(m, m, size - 2 * m, size - 2 * m, r, r)

    # 2) 翻开的白书（上下边缘在书脊处对称下凹，外缘真正圆角收口，
    #    避免底部平直、避免四角向内兜起产生「翘角」错觉；整体放大以协调书签比例）
    cx = size / 2
    top = size * 0.24
    bottom = size * 0.80
    left = size * 0.12
    right = size * 0.88
    dip = size * 0.05   # 书脊处上下下凹量
    rc = size * 0.024   # 外缘圆角半径
    k = size * 0.06     # 顶/底曲线控制点水平偏移

    page = QLinearGradient(0, top, 0, bottom)
    page.setColorAt(0.0, QColor("#ffffff"))
    page.setColorAt(1.0, QColor("#e8edf7"))
    p.setBrush(QBrush(page))

    # 左页：左上圆角 → 顶边至书脊 → 书脊 → 底边(外缘圆角) → 闭合为外缘直线
    lp = QPainterPath()
    lp.moveTo(left, top + rc)
    lp.quadTo(left, top, left + rc, top)
    lp.quadTo(cx - k, top + dip, cx, top + dip)
    lp.lineTo(cx, bottom - dip)
    lp.quadTo(left + rc, bottom, left, bottom - rc)
    lp.closeSubpath()
    p.drawPath(lp)

    # 右页（镜像）
    rp = QPainterPath()
    rp.moveTo(right, top + rc)
    rp.quadTo(right, top, right - rc, top)
    rp.quadTo(cx + k, top + dip, cx, top + dip)
    rp.lineTo(cx, bottom - dip)
    rp.quadTo(right - rc, bottom, right, bottom - rc)
    rp.closeSubpath()
    p.drawPath(rp)

    # 2.1) 书页裁剪区（仅供文字线使用，避免溢出到蓝底）
    book = QPainterPath()
    book.addPath(lp)
    book.addPath(rp)
    p.setClipPath(book)

    # 2.2) 书页文字线（仅 >=32px 才画，避免小尺寸糊成一片；
    #      书放大后横线更明显，与居中书签比例更协调）
    if size >= 32:
        lc = QColor(150, 165, 200, 130)
        lh = max(1, int(size * 0.010))
        for fy in (0.47, 0.55):
            y = int(size * fy)
            p.fillRect(int(left + size * 0.06), y,
                       int((cx - left) * 0.60), lh, lc)
            p.fillRect(int(cx + size * 0.06), y,
                       int((right - cx) * 0.60), lh, lc)
    p.setClipping(False)

    # 3) 书脊细线（强调两页交界）
    p.setPen(QPen(QColor("#c4d0ea"), max(1, int(size * 0.012))))
    p.drawLine(cx, top + dip, cx, bottom - dip)
    p.setPen(Qt.PenStyle.NoPen)

    # 4) 金色书签（金箔渐变 + 干净 V 形尖，居中落在书脊上、从上缘探出；
    #    宽度略小于放大的白书，保持比例秀气）
    gold = QLinearGradient(0, top - size * 0.03, 0, bottom - size * 0.28)
    gold.setColorAt(0.0, QColor("#ffd36b"))
    gold.setColorAt(1.0, QColor("#e09a17"))
    bw = size * 0.042
    top_bm = top - size * 0.03
    bm_bottom = bottom - size * 0.28
    notch = size * 0.038
    bp = QPainterPath()
    bp.moveTo(cx - bw, top_bm)
    bp.lineTo(cx + bw, top_bm)
    bp.lineTo(cx + bw, bm_bottom)
    bp.lineTo(cx, bm_bottom - notch)
    bp.lineTo(cx - bw, bm_bottom)
    bp.closeSubpath()
    p.setBrush(QBrush(gold))
    p.drawPath(bp)


def app_icon() -> QIcon:
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_icon(p, size)
    finally:
        p.end()
    return QIcon(pm)
