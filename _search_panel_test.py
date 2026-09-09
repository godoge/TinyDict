"""回归测试：搜索输入框与候选列表必须一眼能区分（不同底色）。

两者同属 #search_panel 一张卡片（用户要求"同属一个部分"），如果底色
相同、只靠一条 1px 分隔线，视觉上就分不清哪里能打字。本测试实测两块的
像素底色，断言存在可感知的差异且明暗方向正确：
    浅色主题：输入框比列表略深；深色主题：输入框比列表略浅。

用法：
    QT_QPA_PLATFORM=offscreen QT_OPENGL=software \
    .venv/Scripts/python _search_panel_test.py
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")

from PySide6.QtWidgets import (QApplication, QFrame, QLineEdit, QListWidget,
                               QVBoxLayout, QWidget)

from tinydict.ui.theme import app_qss


def luma(c):
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


def build(mode: str):
    host = QWidget()
    host.setStyleSheet(app_qss(mode))
    outer = QVBoxLayout(host)
    panel = QFrame(objectName="search_panel")
    vbox = QVBoxLayout(panel)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(0)
    edit = QLineEdit(objectName="search_edit")
    edit.setPlaceholderText("输入单词")
    lst = QListWidget(objectName="suggest_list")
    lst.addItems(["hello", "world", "tiny"])
    vbox.addWidget(edit)
    vbox.addWidget(lst, stretch=1)
    outer.addWidget(panel)
    host.resize(260, 320)
    host.show()
    return host, edit, lst


def check(mode: str):
    app = QApplication.instance() or QApplication([])
    host, edit, lst = build(mode)
    app.processEvents()
    img = host.grab().toImage()

    # 输入框：取右侧空白区（避开文字），列表：取输入框下方
    ex = edit.geometry().right() - 12
    ey = edit.geometry().center().y()
    lx = lst.geometry().center().x()
    ly = lst.geometry().top() + 40
    ecol = img.pixelColor(ex, ey)
    lcol = img.pixelColor(lx, ly)
    el, ll = luma(ecol), luma(lcol)
    diff = abs(el - ll)
    ok_dir = (el < ll) if mode == "light" else (el > ll)
    ok = diff >= 6 and ok_dir
    print(f"[{mode}] 输入框 #{ecol.name()} luma={el:.1f} | "
          f"列表 #{lcol.name()} luma={ll:.1f} | 差值={diff:.1f}")
    print(f"  {'PASS' if ok else 'FAIL'} {mode} 输入框与列表可区分")
    host.close()
    return ok


def main():
    r1 = check("light")
    r2 = check("dark")
    print("\n结果:", "全部通过" if (r1 and r2) else "存在失败")
    return 0 if (r1 and r2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
