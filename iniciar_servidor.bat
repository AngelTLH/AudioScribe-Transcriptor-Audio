@echo off
title AudioScribe - Servidor Local
cd /d "%~dp0"

echo ====================================================================
echo                 AUDIOSCRIBE - TRANSCRIPTOR MULTIMEDIA
echo ====================================================================
echo.

:: 1. Probar primero el entorno virtual local .venv
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import flask, flask_cors, whisper, yt_dlp" >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Detectado entorno virtual local .venv correctamente configurado.
        set PYTHON_CMD=".venv\Scripts\python.exe"
        goto :run_server
    )
)

:: 2. Probar Python global del sistema
python -c "import flask, flask_cors, whisper, yt_dlp" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Utilizando Python global del sistema con dependencias instaladas.
    set PYTHON_CMD=python
    goto :run_server
)

:: 3. Si no hay dependencias listas, configurar .venv local e instalar
echo [WARNING] No se detecto un entorno listo con todas las dependencias.
echo [INFO] Configurando e instalando librerias necesarias automaticamente...

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creando entorno virtual .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual. Asegurate de tener Python instalado y anadido al PATH.
        pause
        exit /b 1
    )
)

echo [INFO] Instalando dependencias desde requirements.txt...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

".venv\Scripts\python.exe" -c "import flask, flask_cors, whisper, yt_dlp" >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=".venv\Scripts\python.exe"
    goto :run_server
)

echo [ERROR] Ocurrio un error al instalar las dependencias.
echo Por favor ejecuta la consola como Administrador o instala las librerias manualmente con:
echo pip install -r requirements.txt
pause
exit /b 1

:run_server
echo.
echo [INFO] Iniciando AudioScribe con %PYTHON_CMD%...
echo.

%PYTHON_CMD% serve_dashboard.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Ocurrio un fallo al ejecutar serve_dashboard.py.
    echo.
    pause
)
