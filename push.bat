@echo off
chcp 65001 >nul
title Git Quick Push

git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] git not found, please install Git
    pause
    exit /b 1
)

git rev-parse --is-inside-work-tree >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Not a git repository
    echo Please put this script in the project root
    pause
    exit /b 1
)

git status --porcelain >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] No changes detected, nothing to commit
    pause
    exit /b 0
)

echo.
echo ========== Changed Files ==========
git status --short
echo ===================================
echo.

set "commit_msg="
set /p "commit_msg=Input commit message (empty for auto): "

if "%commit_msg%"=="" (
    set "commit_msg=auto update %date% %time%"
)

echo.
echo Commit message: [%commit_msg%]
echo.
set "confirm="
set /p "confirm=Confirm push? [Y/N]: "
if /i not "%confirm%"=="Y" (
    echo Canceled.
    pause
    exit /b 0
)

for /f "delims=" %%b in ('git symbolic-ref --short HEAD') do set "cur_branch=%%b"

echo.
echo [1/3] git add .
git add .
if %errorlevel% neq 0 goto ERR

echo [2/3] git commit -m "%commit_msg%"
git commit -m "%commit_msg%"
if %errorlevel% neq 0 goto ERR

echo [3/3] git push origin %cur_branch%
git push origin %cur_branch%
if %errorlevel% neq 0 goto ERR

echo.
echo ===================================
echo SUCCESS: Push finished (branch: %cur_branch%)
echo ===================================
goto END

:ERR
echo.
echo ===================================
echo [ERROR] Operation failed
echo ===================================

:END
echo.
pause
