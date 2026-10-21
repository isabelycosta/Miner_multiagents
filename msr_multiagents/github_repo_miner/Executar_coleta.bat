@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado. Usando Python instalado no sistema.
    python -m pip install -r requirements.txt
    if errorlevel 1 pause & exit /b 1
    python run_config.py
) else (
    ".venv\Scripts\python.exe" run_config.py
)
echo.
pause
