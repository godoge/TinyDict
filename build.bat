@echo off
REM TinyDict 一键发布打包脚本
REM 用法：build.bat [版本号]   例：build.bat 1.0.0
REM 不传版本号时默认 1.0.0

setlocal
cd /d %~dp0

set "VERSION=%~1"
if "%VERSION%"=="" set "VERSION=1.0.0"

echo ============================================
echo  TinyDict 发布打包  (v%VERSION%)
echo ============================================

echo [1/4] 激活虚拟环境并确认 PyInstaller...
call .venv\Scripts\activate.bat
if not exist .venv\Scripts\pyinstaller.exe pip install pyinstaller

echo [2/4] 打包 (pyinstaller TinyDict.spec)...
pyinstaller TinyDict.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] 打包失败，请检查上方报错。
    exit /b 1
)

echo [3/4] 校验打包产物不含用户数据...
python -c "import os,sys; p='dist/TinyDict'; items=set(os.listdir(p)); allowed={'TinyDict.exe','_internal'}; extra=items-allowed; sys.exit('[ERROR] 发现非预期文件: '+', '.join(sorted(extra))+' —— 已中止，请检查！') if extra else print('[OK] dist/TinyDict 仅含: '+', '.join(sorted(items))))"
if errorlevel 1 exit /b 1

echo [4/4] 压缩为发布包...
python -c "import shutil,os; v=os.environ['VERSION']; z='TinyDict-v'+v+'-win64.zip'; shutil.rmtree(z,ignore_errors=True) if os.path.exists(z) else None; shutil.make_archive(z[:-4],'zip','dist/TinyDict'); print('[OK] 已生成 '+z)"
if errorlevel 1 exit /b 1

echo.
echo 完成！发布包：TinyDict-v%VERSION%-win64.zip
echo 之后把它上传到 GitHub Releases 即可。
endlocal

