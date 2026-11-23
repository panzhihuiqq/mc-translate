@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 检查翻译通道
echo 正在测试翻译通道，请稍候...
echo.
set "PY="
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do (
  if not defined PY if exist %%P set "PY=%%~P"
)
if not defined PY set "PY=python"
"%PY%" mc_translate.py --check
echo.
pause
