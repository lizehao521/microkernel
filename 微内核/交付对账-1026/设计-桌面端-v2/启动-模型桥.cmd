@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=C:\Users\Admin\sdk\py314\python.exe
if not exist "%PY%" (
  echo Python not found: %PY%
  pause
  exit /b 1
)

rem Optional model component. The core stays local and makes 0 model calls
rem unless this bridge is running AND the in-app switch is on.
rem The key is read from the environment only; never write it into a file.

if not defined WEIHETAI_MODEL_BASE_URL (
  echo WEIHETAI_MODEL_BASE_URL is not set.
  echo   set WEIHETAI_MODEL_BASE_URL=https://your-endpoint/v1
  echo   set WEIHETAI_MODEL=your-model-name
  echo   set WEIHETAI_MODEL_KEY=...   ^(current window only, never saved^)
  pause
  exit /b 1
)
if not defined WEIHETAI_MODEL (
  echo WEIHETAI_MODEL is not set.
  pause
  exit /b 1
)
if not defined WEIHETAI_MODEL_KEY (
  echo WARNING: WEIHETAI_MODEL_KEY is not set. Real endpoints usually require it.
)

set BRIDGE_PORT=8765
set WEIHETAI_MODEL_BRIDGE=http://127.0.0.1:%BRIDGE_PORT%
start "weihetai-model-bridge" "%PY%" "模型桥.py" --port %BRIDGE_PORT%
timeout /t 3 /nobreak >nul
"%PY%" "工具-本地服务.py"
if errorlevel 1 pause
