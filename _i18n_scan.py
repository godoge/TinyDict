"""AST 扫描：找出所有「把 i18n 的 _ 当局部变量」冲突的函数。

判定条件（同一函数内同时满足即为 bug）：
  1. `_` 被绑定为局部变量（赋值 / 元组解包 / for 目标 / with as / 推导式）
  2. `_` 被当作函数调用（`_("xxx")`）
→ Python 会把 `_` 视为局部变量，`_("xxx")` 抛 UnboundLocalError。
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent / "tinydict"

BINDERS = (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For, ast.comprehension,
           ast.With, ast.NamedExpr)

found = 0
scanned = 0

for py in sorted(ROOT.rglob("*.py")):
    try:
        src = py.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception as e:  # noqa: BLE001
        print(f"跳过 {py}: {e}")
        continue

    # 该文件是否把 `_` 作为 i18n 导入
    imports_i18n = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
                a.name == "_" for a in node.names):
            imports_i18n = True
            break
    if not imports_i18n:
        continue

    scanned += 1

    class FnVisitor(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def _enter(self, node, name):
            self.stack.append((node, name))
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node):
            self._enter(node, node.name)

        def visit_AsyncFunctionDef(self, node):
            self._enter(node, node.name)

    # 逐函数检查
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def owning_function(node):
        cur = node
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur
            cur = parents.get(cur)
        return None

    # 收集每个函数内的两种用法
    binds = {}   # func -> [lineno]
    calls = {}   # func -> [lineno]

    for node in ast.walk(tree):
        fn = owning_function(node)
        if fn is None:
            continue
        # 绑定 _
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.For, ast.comprehension)):
            targets = [node.target]
        elif isinstance(node, ast.With):
            targets = list(node.items)
        elif isinstance(node, ast.NamedExpr):
            targets = [node.target]
        for t in targets:
            tt = t.optional_vars if isinstance(t, ast.withitem) else t
            for sub in ast.walk(tt):
                if isinstance(sub, ast.Name) and sub.id == "_":
                    binds.setdefault(fn, []).append(getattr(node, "lineno", 0))
        # 调用 _()
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "_":
            calls.setdefault(fn, []).append(node.lineno)

    for fn in binds:
        if fn in calls:
            found += 1
            rel = py.relative_to(ROOT.parent)
            print(f"\n❌ {rel}")
            print(f"   函数 {fn.name}()  定义行 {fn.lineno}")
            print(f"   `_` 被绑定为局部变量的行: {sorted(set(binds[fn]))}")
            print(f"   `_()` 被调用的行:         {sorted(set(calls[fn]))}")
            print(f"   → 这些 `_()` 会抛 UnboundLocalError")

print(f"\n扫描了 {scanned} 个使用 i18n `_` 的文件，发现 {found} 处冲突")
sys.exit(1 if found else 0)
