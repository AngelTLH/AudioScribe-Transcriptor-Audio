@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ejecute primero iniciar_servidor.bat para crear el entorno.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-gpu.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -c "from audioscribe.transcription import detect_device; print('Dispositivo:', detect_device('cuda'))"
pause
