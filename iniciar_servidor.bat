@echo off
setlocal
title AudioScribe - Transcripcion local
cd /d "%~dp0"
set "PYTHON_EXE=.venv\Scripts\python.exe"

if exist "%PYTHON_EXE%" goto :check_dependencies
echo [INFO] Creando el entorno virtual de AudioScribe...
where py >nul 2>&1
if errorlevel 1 (
    python -m venv .venv
) else (
    py -3 -m venv .venv
)
if errorlevel 1 goto :error

:check_dependencies
"%PYTHON_EXE%" -c "import flask, flask_cors, faster_whisper, yt_dlp, static_ffmpeg" >nul 2>&1
if not errorlevel 1 goto :run_server
echo [INFO] Instalando las dependencias del proyecto...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

:run_server
echo [INFO] Iniciando AudioScribe. Cierre con Ctrl+C.
"%PYTHON_EXE%" serve_dashboard.py
if errorlevel 1 goto :error
exit /b 0

:error
echo [ERROR] No se pudo iniciar AudioScribe. Revise el mensaje anterior.
pause
exit /b 1
