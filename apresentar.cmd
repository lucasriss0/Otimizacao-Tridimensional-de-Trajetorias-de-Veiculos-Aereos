@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Configure o ambiente conforme o README.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m src.presentation_command %*
exit /b %errorlevel%
