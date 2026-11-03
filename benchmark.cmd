@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Configure o ambiente conforme o README.
    pause
    exit /b 1
)
echo Benchmark: 3 recortes, 2 repeticoes e 5 metodos, total de 30 voos.
echo Abra o CoppeliaSim e deixe a simulacao parada. A cena atual sera copiada.
pause
".venv\Scripts\python.exe" -X utf8 -m src.benchmark
if errorlevel 1 echo Houve erro. Os resultados parciais permanecem em output/experiments.
pause
