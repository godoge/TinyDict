"""验证「添加文件…」按钮在各类场景下的行为，定位「点击无效」的原因。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

app = QApplication(sys.argv)

from tinydict.core.database import Database  # noqa: E402
from tinydict.core.query import DictionaryService  # noqa: E402
from tinydict.ui import dict_manager_dialog as dmd  # noqa: E402

PASS, FAIL = 0, 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def make_env(tmp, dicts=()):
    db = Database(os.path.join(tmp, "t.db"))
    for name, path in dicts:
        db.add_dict(name, path, "utf-8")
    svc = DictionaryService(db, tmp, None)
    dlg = dmd.DictManagerDialog(svc)
    return svc, dlg


class Recorder:
    """拦截 QMessageBox / QFileDialog，记录调用。"""

    def __init__(self):
        self.info = []
        self.warning = []
        self.critical = []
        self.open_calls = []
        self.mount = []

    def install(self, paths):
        self._paths = paths
        self._real_info = QMessageBox.information
        self._real_warn = QMessageBox.warning
        self._real_crit = QMessageBox.critical
        QMessageBox.information = staticmethod(
            lambda *a, **k: self.info.append(a[2] if len(a) > 2 else a))
        QMessageBox.warning = staticmethod(
            lambda *a, **k: self.warning.append(a[2] if len(a) > 2 else a))
        QMessageBox.critical = staticmethod(
            lambda *a, **k: self.critical.append(a[2] if len(a) > 2 else a))
        QFileDialog.getOpenFileNames = staticmethod(self._fake_open)

    def uninstall(self):
        QMessageBox.information = self._real_info
        QMessageBox.warning = self._real_warn
        QMessageBox.critical = self._real_crit

    def _fake_open(self, *a, **k):
        self.open_calls.append(a[1] if len(a) > 1 else "")
        return self._paths, ""


NEW_MDX = r"D:\fake\brand-new.mdx"
OLD_MDX = r"D:\fake\already.mdx"

print("场景 1：选择一部【全新的】词库（register_file 返回 DictInfo）")
tmp = tempfile.mkdtemp()
svc, dlg = make_env(tmp)
rec = Recorder()
rec.install([NEW_MDX])
svc.register_file = lambda p: object()          # 模拟注册成功
svc.mount_all_async = lambda: rec.mount.append(1)
changed = []
dlg.dicts_changed.connect(lambda: changed.append(1))
dlg._btn_file.click()
rec.uninstall()
check("文件选择框被调用", len(rec.open_calls) == 1, f"calls={rec.open_calls}")
check("触发后台挂载", len(rec.mount) == 1, f"mount={rec.mount}")
check("发出 dicts_changed", len(changed) == 1)
check("有成功提示弹窗", len(rec.info) == 1, f"info={rec.info}")

print("\n场景 2：选择一部【已经注册过】的词库（register_file 返回 None）")
tmp = tempfile.mkdtemp()
svc, dlg = make_env(tmp)
rec = Recorder()
rec.install([OLD_MDX])
svc.register_file = lambda p: None              # 已注册 → 返回 None
svc.mount_all_async = lambda: rec.mount.append(1)
dlg._btn_file.click()
rec.uninstall()
print(f"   实际：弹窗 info={rec.info} warning={rec.warning}")
check("用户能看到反馈（提示/警告任一）",
      bool(rec.info or rec.warning),
      "完全静默——用户点完毫无反应，等同于「点击无效」")

print("\n场景 3：用户【取消】选择（paths 为空）")
tmp = tempfile.mkdtemp()
svc, dlg = make_env(tmp)
rec = Recorder()
rec.install([])
svc.register_file = lambda p: object()
svc.mount_all_async = lambda: rec.mount.append(1)
dlg._btn_file.click()
rec.uninstall()
check("取消时静默（不弹窗、不挂载）",
      not rec.info and not rec.warning and not rec.mount)

print("\n场景 4：注册【抛异常】（文件不存在 / 不是 .mdx）")
tmp = tempfile.mkdtemp()
svc, dlg = make_env(tmp)
rec = Recorder()
rec.install([r"D:\fake\not-mdx.txt"])
svc.register_file = lambda p: (_ for _ in ()).throw(RuntimeError("不是 .mdx 文件"))
svc.mount_all_async = lambda: rec.mount.append(1)
dlg._btn_file.click()
rec.uninstall()
check("失败时有警告弹窗", len(rec.warning) == 1, f"warning={rec.warning}")

print("\n场景 5：「修复路径…」未选中行（此前 224 行就抛 UnboundLocalError）")
tmp = tempfile.mkdtemp()
svc, dlg = make_env(tmp)
rec = Recorder()
rec.install([])
dlg._table.setCurrentCell(-1, -1)
try:
    dlg._btn_repair.click()
    crashed = False
except UnboundLocalError as e:
    crashed = True
    print(f"   抛出 UnboundLocalError: {e}")
rec.uninstall()
check("修复路径不再崩溃", not crashed)
check("未选中时给出提示", len(rec.info) == 1, f"info={rec.info}")

print("\n场景 6：「修复路径…」正常选中一行并选到新 .mdx")
tmp = tempfile.mkdtemp()
svc, dlg = make_env(tmp, dicts=[("测试词库", r"D:\fake\old.mdx")])
rec = Recorder()
rec.install([])
repaired = []
svc.repair_path = lambda i, p: repaired.append((i, p))
QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **k: (r"D:\fake\new.mdx", ""))
dlg._table.setCurrentCell(0, 0)
try:
    dlg._btn_repair.click()
    crashed = False
except UnboundLocalError as e:
    crashed = True
    print(f"   抛出 UnboundLocalError: {e}")
rec.uninstall()
check("修复路径执行不崩溃", not crashed)
check("调用了 service.repair_path", len(repaired) == 1, f"repaired={repaired}")

print(f"\n=== 结果：{PASS} 通过 / {FAIL} 失败 ===")
