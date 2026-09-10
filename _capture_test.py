"""屏幕划词取词回归测试（离屏运行，用假 keyboard 模拟目标程序）。

覆盖真实会踩的坑：
1. 剪贴板为空时备份不崩（mimeData() 可能为 None）；
2. 选中内容 == 剪贴板原有内容时也能取到（旧实现必失败）；
3. 发送 Ctrl+C 前先松开修饰键（否则热键残留的 Alt 会合成 Ctrl+Alt+C）；
4. press → 保持 → release（不是 send 的瞬间按抬）；
5. Ctrl+C 无效时回退 Ctrl+Insert；
6. 取词后剪贴板恢复原内容；两套都失败时同样恢复；
7. 延迟补恢复：只有剪贴板仍是"刚取到的词"才补恢复，不抢用户的新复制；
8. capture_now 取第一段非空行并截断。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
CLIP = QGuiApplication.clipboard()

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {extra}" if extra else ""))


class FakeKeyboard:
    """假 keyboard：记录按键序列，并在松开字母键时按脚本写剪贴板。"""

    def __init__(self, script):
        self.script = script          # {("ctrl","c"): "文本" 或 None}
        self.events = []              # (kind, key, t)
        self.pressed = []

    # ---- keyboard 库的接口子集
    def press(self, key):
        self.events.append(("press", key, time.monotonic()))
        self.pressed.append(key)

    def release(self, key):
        self.events.append(("release", key, time.monotonic()))
        if key in ("ctrl", "alt", "shift", "windows"):
            return
        # press 时已把字母键记入 pressed（如 press ctrl -> press c）
        combo = tuple(self.pressed)
        self.pressed = []
        text = self.script.get(combo)
        if text is not None:
            CLIP.setText(text)

    def send(self, combo):            # 旧实现用的接口：本实现不应走它
        self.events.append(("send", combo, time.monotonic()))
        # 也按脚本写入，好让"旧版对照实验"公平（旧版只调 send）
        key = tuple(p.strip() for p in str(combo).split("+"))
        text = self.script.get(key)
        if text is not None:
            CLIP.setText(text)

    # ---- 断言辅助
    def kinds(self):
        return [k for k, _key, _t in self.events]

    def first_index(self, kind, key=None):
        for i, (k, key_, _t) in enumerate(self.events):
            if k == kind and (key is None or key_ == key):
                return i
        return -1


def install(script):
    fake = FakeKeyboard(script)
    sys.modules["keyboard"] = fake
    return fake


def main():
    from tinydict.system.capture import SelectionCapture, _clone_clipboard

    print("== 剪贴板备份 ==")
    CLIP.clear()
    QApplication.processEvents()
    try:
        md = _clone_clipboard()
        check("剪贴板为空时备份不崩", md is not None)
    except Exception as e:  # noqa: BLE001
        check("剪贴板为空时备份不崩", False, f"{type(e).__name__}: {e}")

    print("== 关键回归：选中内容 == 剪贴板原内容 ==")
    # 旧实现用 t != old_text 判断，这种场景永远等不到，必定取词失败
    CLIP.setText("hello")
    QApplication.processEvents()
    fake = install({("ctrl", "c"): "hello"})
    cap = SelectionCapture()
    got = cap.get_selected_text(timeout_ms=200)
    check("选中内容与剪贴板相同也能取到", got == "hello", f"got={got!r}")
    check("取词后恢复原剪贴板", (CLIP.text() or "") == "hello",
          f"clip={CLIP.text()!r}")

    print("== 正常取词 ==")
    CLIP.setText("原始剪贴板内容")
    QApplication.processEvents()
    fake = install({("ctrl", "c"): "  dictionary  "})
    cap = SelectionCapture()
    got = cap.get_selected_text(timeout_ms=200)
    check("取到并去除首尾空白", got == "dictionary", f"got={got!r}")
    check("剪贴板恢复为原始内容",
          (CLIP.text() or "") == "原始剪贴板内容", f"clip={CLIP.text()!r}")

    print("== 发送序列 ==")
    check("发送前先松开 alt",
          fake.first_index("release", "alt") < fake.first_index("press", "ctrl"),
          f"events={fake.kinds()}")
    check("四个修饰键都松开",
          all(fake.first_index("release", m) >= 0
              for m in ("alt", "ctrl", "shift", "windows")))
    check("使用 press/release 而非 send", "send" not in fake.kinds(),
          f"events={fake.kinds()}")
    check("先按 ctrl 再按 c",
          fake.first_index("press", "ctrl") < fake.first_index("press", "c"))
    # 按住时长：release('c') 与 press('c') 之间应有一定间隔
    pc = next(t for k, key, t in fake.events if k == "press" and key == "c")
    rc = next(t for k, key, t in fake.events if k == "release" and key == "c")
    check("按住后保持一段时间再抬起", rc - pc >= 0.03, f"hold={rc-pc:.3f}s")

    print("== 回退 Ctrl+Insert ==")
    CLIP.setText("原始")
    QApplication.processEvents()
    fake = install({("ctrl", "insert"): "terminal"})   # Ctrl+C 无效
    cap = SelectionCapture()
    got = cap.get_selected_text(timeout_ms=200)
    check("Ctrl+C 无效时回退 Ctrl+Insert", got == "terminal", f"got={got!r}")
    check("回退时确实按过 insert", fake.first_index("press", "insert") >= 0)

    print("== 完全失败 ==")
    CLIP.setText("原始")
    QApplication.processEvents()
    fake = install({})                                  # 目标程序不响应复制
    cap = SelectionCapture()
    fired = []
    cap.failed.connect(lambda: fired.append(1))
    got = cap.get_selected_text(timeout_ms=150)
    check("取不到时返回空串", got == "", f"got={got!r}")
    check("剪贴板仍被恢复", (CLIP.text() or "") == "原始",
          f"clip={CLIP.text()!r}")
    cap.capture_now()
    check("失败时发出 failed 信号", fired == [1], f"fired={fired}")

    print("== 延迟补恢复 ==")
    CLIP.setText("原始")
    QApplication.processEvents()
    cap = SelectionCapture()
    cap._backup = _clone_clipboard()
    CLIP.setText("picked")            # 目标程序在我们读取后又写了一次
    cap._restore_if_unchanged("picked")
    check("内容仍是取到的词 → 补恢复",
          (CLIP.text() or "") == "原始", f"clip={CLIP.text()!r}")
    CLIP.setText("用户自己复制的新内容")
    cap._restore_if_unchanged("picked")
    check("用户已复制新内容 → 不抢",
          (CLIP.text() or "") == "用户自己复制的新内容",
          f"clip={CLIP.text()!r}")

    print("== capture_now 取词文本处理 ==")
    cap = SelectionCapture()
    got_words = []
    cap.captured.connect(got_words.append)
    cap.get_selected_text = lambda *a, **k: "  first line  \nsecond line\n"
    cap.capture_now()
    check("多行取第一段并去空白", got_words == ["first line"], f"got={got_words}")
    cap.get_selected_text = lambda *a, **k: "x" * 300
    cap.capture_now()
    check("超长截断到 200", len(got_words[-1]) == 200, f"len={len(got_words[-1])}")

    print()
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
