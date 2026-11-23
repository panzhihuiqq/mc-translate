@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title MC 聊天翻译

set "PY="
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
) do (
  if not defined PY if exist %%P (
    %%~P -c "import tkinter" >nul 2>&1
    if not errorlevel 1 set "PY=%%~P"
  )
)

if not defined PY (
  echo.
  echo   [x] 没有找到可用的 Python（需要 3.10 以上、带 tkinter 的版本）
  echo.
  echo   请到 python.org 下载安装，安装时勾选：
  echo       [x] tcl/tk and IDLE
  echo.
  pause
  exit /b 1
)

start "" "%PY%" "%~dp0mc_translate.py"
exit /b 0
