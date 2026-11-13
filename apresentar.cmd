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
set "REPLAY_OPTION=--reuse-replay"
if /i "%~1"=="--novo" set "REPLAY_OPTION="
".venv\Scripts\python.exe" -X utf8 -m src.benchmark --scenario configs/demo_coverage.yaml --disable-rendering %REPLAY_OPTION%
if errorlevel 1 (
    echo A comparacao encontrou um erro. Consulte a mensagem acima.
    exit /b 1
)
exit /b 0
