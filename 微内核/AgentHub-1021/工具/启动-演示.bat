@echo off
chcp 65001 >nul
rem 演示启动件：另起一本干净账 + 本机假端点（它不是模型）+ 流式停顿，起完开浏览器。
rem 要放行写文件/执行，自己往下加 -allow-write / -allow-exec；这两条不默认开。
cd /d "%~dp0.."
if not exist 构建-hubd\hubd.exe (
  echo 没有 exe，先编一下：
  C:\Users\Admin\sdk\go\bin\go.exe -C src\hubd build -o ..\..\构建-hubd\hubd.exe .
  if errorlevel 1 exit /b 2
)
start "" "http://127.0.0.1:8790/?run=1"
构建-hubd\hubd.exe -port 8790 -tools-dir src\hubd\tools -data "%TEMP%\hubd-演示" -fake-endpoint -step-delay 120ms
