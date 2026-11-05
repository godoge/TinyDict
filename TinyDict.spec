# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("keyboard"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 启动画面：由 bootloader 在 Python 解释器与 200MB+ 的 QtWebEngineCore.dll
# 加载之前显示，冷启动时立刻给用户反馈，避免「点了没反应」。图片内已含
# 提示文字，故不启用 text_pos（Tcl 默认字体渲染中文会变方框）。
splash = Splash(
    'assets/splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,                 # onedir：splash 目标本身传给 EXE
    [],
    exclude_binaries=True,
    name='TinyDict',
    icon='assets/icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # 实测 357 个 PE 无一被压缩，UPX 只增加构建/解压开销
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    splash.binaries,        # onedir：Tcl/Tk 运行时传给 COLLECT
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TinyDict',
)
