@echo off
rem Single-file double-click launcher for No_More_VFS. ASCII only above the blank line.
setlocal
set "ROOT=%~dp0"

if not exist "%ROOT%env\Scripts\pythonw.exe" (
    echo [ERROR] missing venv: env\Scripts\pythonw.exe
    echo         create it with: pip install -r requirements.txt
    pause
    exit /b 1
)
if not exist "%ROOT%scripts\gui.py" (
    echo [ERROR] missing scripts\gui.py
    pause
    exit /b 1
)

start "NoMoreVFS" /d "%ROOT%" "%ROOT%env\Scripts\pythonw.exe" "%ROOT%scripts\gui.py"
exit /b 0
