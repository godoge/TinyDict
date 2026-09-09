"""TinyDict 发布辅助脚本（被 build.bat 调用）。

把原来 build.bat 里内联的 `python -c "..."` 校验/压缩逻辑抽到这里，
避免 cmd 对引号内括号的解析坑（会导致 SyntaxError）。
"""
import os
import sys
import shutil


def check(version: str) -> int:
    p = "dist/TinyDict"
    allowed = {"TinyDict.exe", "_internal"}
    items = set(os.listdir(p))
    extra = items - allowed
    if extra:
        sys.exit(
            "[ERROR] 发现非预期文件: "
            + ", ".join(sorted(extra))
            + " —— 已中止，请检查！"
        )
    print("[OK] dist/TinyDict 仅含: " + ", ".join(sorted(items)))
    return 0


def zip(version: str) -> int:
    z = "TinyDict-v" + version + "-win64.zip"
    if os.path.exists(z):
        os.remove(z)
    shutil.make_archive(z[:-4], "zip", "dist/TinyDict")
    print("[OK] 已生成 " + z)
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: build_dist.py [check|zip] VERSION")
        return 2
    cmd, version = sys.argv[1], sys.argv[2]
    if cmd == "check":
        return check(version)
    if cmd == "zip":
        return zip(version)
    print("未知命令: " + cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
