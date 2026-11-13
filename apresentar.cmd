@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Configure o ambiente conforme o README.
    pause
    exit /b 1
)
echo Comparacao padrao: A* a esquerda e faixas convencionais a direita.
echo Mantenha o CoppeliaSim aberto e parado antes de executar.
".venv\Scripts\python.exe" -X utf8 -m src.benchmark --scenario configs/demo_coverage.yaml --disable-rendering
if errorlevel 1 (
    echo A comparacao encontrou um erro. Consulte a mensagem acima.
    exit /b 1
)
exit /b 0
