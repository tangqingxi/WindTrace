@echo off
rem 使用调用方指定或当前Python环境；不硬编码开发机器路径。
if defined WINDTRACE_PYTHON (
  "%WINDTRACE_PYTHON%" "%~dp0app.py" %*
) else if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0app.py" %*
) else (
  python "%~dp0app.py" %*
)
