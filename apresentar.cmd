@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Configure o ambiente conforme o README.
    pause
    exit /b 1
)
echo Abra o CoppeliaSim e deixe a simulacao parada antes de continuar.
echo A cena aberta sera copiada para output/runs antes da preparacao.
pause
".venv\Scripts\python.exe" -X utf8 -m src.coverage_comparison
if errorlevel 1 (
    echo A demonstracao encontrou um erro. Consulte a mensagem acima.
    pause
    exit /b 1
)
pause
