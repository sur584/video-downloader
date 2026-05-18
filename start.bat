@echo off
chcp 65001 >nul 2>&1
title 抖音视频解析下载工具

echo.
echo ========================================
echo   抖音视频解析下载工具
echo ========================================
echo.

cd /d "%~dp0backend"

echo [1/2] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [2/2] 启动服务...
echo.
echo 打开浏览器访问: http://127.0.0.1:8866
echo 按 Ctrl+C 停止服务
echo.
python main.py

pause
