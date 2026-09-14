"""程序图标：代码绘制（无外部资源文件依赖）。

设计：蓝色渐变圆角底 + 翻开的白书 + 金色书签（像「词典」本身）。
绘制全部用 QPainter 图元（矩形 / 曲线 / 渐变）完成，不依赖字体，
因此运行时窗口 / 托盘图标与打包嵌入的 assets/icon.ico 像素级一致。
"""

from math import cos, pi, sin

from PySide6.QtCore import QPointF, Qt
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


# ---------------------------------------------------------------------------
# 顶栏导航图标（置顶 / 词库 / 生词本 / 历史 / 设置 / 关于）
#
# 与主图标一样只用 QPainter 图元绘制，不依赖字体：
#   - 打包后不会因缺字形而变成方框"豆腐块"；
#   - 描边颜色由调用方传入，可跟随明 / 暗主题切换（见 theme.toolbutton_fg）。
# ---------------------------------------------------------------------------

# 线宽占画布边长的比例，六个图标统一，保证视觉重量一致
_NAV_STROKE = 0.085

#: 支持的导航图标名
NAV_ICONS = ("pin", "dict", "wordbook", "history", "settings", "about")


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


# ---------------------------------------------------------------------------
# 导航图标：每个绘制函数拿到「已设好描边画笔」的 QPainter 和画布边长 s，
# 只在 s×s 画布内作画，不关心画笔本身，因此六个图标风格天然统一。
# ---------------------------------------------------------------------------


def _nav_pen(color: QColor, size: int) -> QPen:
    """统一描边画笔：圆头圆角，避免小尺寸下关节处出现毛刺。"""
    pen = QPen(color)
    pen.setWidthF(max(1.0, size * _NAV_STROKE))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw_pin(p: QPainter, s: int) -> None:
    """置顶：图钉（圆头 + 向下收尖的针身）。"""
    cx = s / 2
    head_r = s * 0.19
    head_cy = s * 0.30
    p.drawEllipse(QPointF(cx, head_cy), head_r, head_r)
    top_y = head_cy + head_r * 0.8
    needle = QPainterPath()
    needle.moveTo(cx - head_r * 0.9, top_y)
    needle.lineTo(cx + head_r * 0.9, top_y)
    needle.lineTo(cx, s * 0.84)
    needle.closeSubpath()
    p.drawPath(needle)


def _draw_dict(p: QPainter, s: int) -> None:
    """词库：一本书（封面轮廓 + 靠左的书脊线）。

    不用「三本书叠放」：那种设计在 18px 下三条线的间距不足 1px，
    会和相邻线条糊成一块，反而看不出是书。
    """
    x0 = s * 0.16
    y0 = s * 0.22
    w = s * 0.68
    h = s * 0.56
    p.drawRoundedRect(x0, y0, w, h, s * 0.05, s * 0.05)
    # 书脊：封面内侧一条竖线，把书脊面与正文页分开
    spine_x = x0 + w * 0.24
    p.drawLine(QPointF(spine_x, y0), QPointF(spine_x, y0 + h))


def _draw_wordbook(p: QPainter, s: int) -> None:
    """生词本：五角星轮廓（与顶栏 ★ 按钮语义一致）。"""
    cx = cy = s / 2
    outer = s * 0.34
    # 内外半径比约 0.4 是标准五角星；偏大会让五个角显得"胖"而失去星形感
    inner = outer * 0.40
    pts = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        a = -pi / 2 + i * pi / 5
        pts.append(QPointF(cx + r * cos(a), cy + r * sin(a)))
    p.drawPolygon(pts)


def _draw_history(p: QPainter, s: int) -> None:
    """历史：时钟（圆盘 + 分针 + 时针）。"""
    cx = cy = s / 2
    r = s * 0.33
    p.drawEllipse(QPointF(cx, cy), r, r)
    # 分针朝 12 点且更长，时针朝约 2 点且更短
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.62))
    p.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.42, cy - r * 0.30))


def _draw_settings(p: QPainter, s: int) -> None:
    """设置：齿轮（六个梯形齿 + 中心孔）。

    齿形按角度逐个取点：每个齿在外径上取一段平顶，两侧收到内径的凹槽，
    首尾相接即闭合多边形。
    """
    cx = cy = s / 2
    ro = s * 0.38
    ri = ro * 0.62
    # 六个齿而不是八个：18px 下八齿的齿间凹槽不足 1px，会糊成一坨黑饼
    teeth = 6
    step = 2 * pi / teeth
    pts = []
    for i in range(teeth):
        a = i * step
        b = a + step / 2          # 相邻齿之间的凹槽中心
        pts.append(QPointF(cx + ro * cos(a - step * 0.19),
                           cy + ro * sin(a - step * 0.19)))
        pts.append(QPointF(cx + ro * cos(a + step * 0.19),
                           cy + ro * sin(a + step * 0.19)))
        pts.append(QPointF(cx + ri * cos(b - step * 0.19),
                           cy + ri * sin(b - step * 0.19)))
        pts.append(QPointF(cx + ri * cos(b + step * 0.19),
                           cy + ri * sin(b + step * 0.19)))
    p.drawPolygon(pts)
    p.drawEllipse(QPointF(cx, cy), ri * 0.45, ri * 0.45)


def _draw_about(p: QPainter, s: int) -> None:
    """关于：圆圈里的小写 i（圆点 + 竖杠，全靠图元、不使用字体）。"""
    cx = cy = s / 2
    r = s * 0.33
    p.drawEllipse(QPointF(cx, cy), r, r)
    dot_r = max(1.0, s * 0.038)
    p.setBrush(QBrush(p.pen().color()))
    p.drawEllipse(QPointF(cx, cy - r * 0.46), dot_r, dot_r)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(cx, cy - r * 0.14), QPointF(cx, cy + r * 0.46))


_NAV_GLYPHS = {
    "pin": _draw_pin,
    "dict": _draw_dict,
    "wordbook": _draw_wordbook,
    "history": _draw_history,
    "settings": _draw_settings,
    "about": _draw_about,
}


def nav_icon(kind: str, color: QColor, size: int = 32) -> QIcon:
    """生成一个顶栏导航图标，描边色为 color。

    kind 取值见 NAV_ICONS。size 默认 32：实际按钮约 18px，先画大再由 Qt
    缩放，比直接按 18px 画抗锯齿效果更好。未知 kind 抛 KeyError。
    """
    fn = _NAV_GLYPHS.get(kind)
    if fn is None:
        raise KeyError(
            "未知导航图标: %s（可用：%s）" % (kind, ", ".join(NAV_ICONS)))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_nav_pen(color, size))
        fn(painter, size)
    finally:
        painter.end()
    return QIcon(pm)
