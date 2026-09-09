"""临时回归测试：验证浅/深主题下列表滚动条轨道与滑块的颜色。

用法：
    QT_QPA_PLATFORM=offscreen QT_OPENGL=software .venv/Scripts/python _scrollbar_test.py
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFrame, QListWidget, QVBoxLayout,
)

from tinydict.ui import theme as _theme  # noqa: E402


def build(mode: str):
    """构造一个含滚动条的候选列表，返回 (list_widget, 截图)。"""
    app = QApplication.instance() or QApplication([])

    cfg = {"theme": mode, "entry_theme": "follow"}
    tm = _theme.ThemeManager(cfg, app)
    tm.apply_to_qt()

    panel = QFrame(objectName="search_panel")
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    lst = QListWidget(objectName="suggest_list")
    for i in range(200):
        lst.addItem(f"candidate word {i:03d}")
    lay.addWidget(lst)

    panel.setStyleSheet(_theme.app_qss(mode))
    panel.resize(260, 300)
    panel.show()
    app.processEvents()

    return lst, panel.grab().toImage()


def sample(img, xf, y):
    """按 x 比例采样某行的颜色（xf=1.0 为最右侧像素）。"""
    x = min(img.width() - 1, int(img.width() * xf))
    return img.pixelColor(x, y)


def luma(c: QColor) -> float:
    return 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()


def check(mode: str, expect_light: bool):
    lst, img = build(mode)
    w, h = img.width(), img.height()

    # 滚动条在列表最右侧（宽 12px）；取 x = w-6 落在滚动条中间。
    # 列表未滚动时滑块贴在顶部（min-height 28px），所以：
    #   y=6      -> 滑块
    #   y=h//2   -> 滑块之外的轨道
    x = w - 6
    mid = img.pixelColor(x, 6)          # 滑块
    track = img.pixelColor(x, h // 2)   # 轨道
    lt, lm = luma(track), luma(mid)

    print(f"[{mode}] size={w}x{h} 轨道={track.name()} luma={lt:.1f} "
          f"| 滑块={mid.name()} luma={lm:.1f}")

    ok = True
    if expect_light:
        if lt < 200:
            print(f"  FAIL 浅色主题轨道应接近浅灰，实测 luma={lt:.1f}")
            ok = False
        if lm > 235:
            print(f"  FAIL 浅色主题滑块应比轨道深，实测 luma={lm:.1f}")
            ok = False
    else:
        if lt > 80:
            print(f"  FAIL 深色主题轨道应接近深灰，实测 luma={lt:.1f}")
            ok = False

    # 滑块必须能与轨道区分开
    if abs(lt - lm) < 12:
        print(f"  FAIL 滑块与轨道对比不足（差值 {abs(lt - lm):.1f}）")
        ok = False

    print(f"  {'PASS' if ok else 'FAIL'} {mode} 滚动条配色")
    return ok


def main():
    r1 = check("light", expect_light=True)
    r2 = check("dark", expect_light=False)

    # 顺带导出两张截图，便于肉眼确认
    for mode in ("light", "dark"):
        _, img = build(mode)
        path = os.path.abspath(f"_scrollbar_{mode}.png")
        img.save(path)
        print("  截图:", path)

    print("\n结果:", "全部通过" if (r1 and r2) else "存在失败")
    return 0 if (r1 and r2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
