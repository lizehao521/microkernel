@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=C:\Users\Admin\sdk\py314\python.exe
if not exist "%PY%" (
  echo Python not found: %PY%
  pause
  exit /b 1
)
"%PY%" "工具-本地服务.py"
if errorlevel 1 pause
