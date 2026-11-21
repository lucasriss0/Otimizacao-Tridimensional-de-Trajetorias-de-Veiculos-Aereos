@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Configure o ambiente conforme o README.
    pause
    exit /b 1
)
setlocal
if /i "%~1"=="todos" goto :todos
set "MODO_NOVO="
set "CENARIO=configs/demo_coverage.yaml"
if /i "%~1"=="--novo" (
    set "MODO_NOVO=1"
    shift
)
if /i "%~1"=="serra_do_cipo" set "CENARIO=configs/serra_do_cipo.yaml"
if /i "%~1"=="monte_verde" set "CENARIO=configs/monte_verde.yaml"
if /i "%~1"=="--objetos" set "CENARIO=configs/demo_obstacles.yaml"
if not "%~1"=="" if "%CENARIO%"=="configs/demo_coverage.yaml" goto :uso
if not "%~2"=="" goto :uso

echo Mantenha o CoppeliaSim aberto e parado antes de executar.
if defined MODO_NOVO (
    echo Apresentacao do nosso metodo A* em um terreno.
    ".venv\Scripts\python.exe" -X utf8 -m src.coverage_comparison --scenario "%CENARIO%" --proposed-only --executor lua
) else (
    echo Comparacao: A* a esquerda e faixas convencionais a direita.
    ".venv\Scripts\python.exe" -X utf8 -m src.benchmark --scenario "%CENARIO%" --disable-rendering --reuse-replay
)
if errorlevel 1 (
    echo A comparacao encontrou um erro. Consulte a mensagem acima.
    exit /b 1
)
exit /b 0

:todos
if not "%~2"=="" goto :uso
".venv\Scripts\python.exe" -X utf8 -m src.scenario_presentation
exit /b %errorlevel%

:uso
echo Uso: apresentar.cmd [--novo] [serra_do_cipo ^| monte_verde ^| --objetos]
echo      apresentar.cmd todos
exit /b 1
