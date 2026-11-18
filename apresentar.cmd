@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Configure o ambiente conforme o README.
    pause
    exit /b 1
)
echo Mantenha o CoppeliaSim aberto e parado antes de executar.
if not "%~1"=="" if /i not "%~1"=="--novo" (
    echo Use apresentar.cmd ou apresentar.cmd --novo.
    exit /b 1
)
if /i "%~1"=="--novo" (
    echo Apresentacao do nosso metodo A* em um terreno.
    ".venv\Scripts\python.exe" -X utf8 -m src.coverage_comparison --scenario configs/demo_coverage.yaml --proposed-only --executor lua
) else (
    echo Comparacao: A* a esquerda e faixas convencionais a direita.
    ".venv\Scripts\python.exe" -X utf8 -m src.benchmark --scenario configs/demo_coverage.yaml --disable-rendering --reuse-replay
)
if errorlevel 1 (
    echo A comparacao encontrou um erro. Consulte a mensagem acima.
    exit /b 1
)
exit /b 0
