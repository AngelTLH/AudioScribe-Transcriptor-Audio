#!/usr/bin/env bash
# ====================================================================
# AudioScribe - Script de Inicio para Linux / macOS
# ====================================================================

# Navegar al directorio donde reside este script
cd "$(dirname "$0")" || exit 1

echo "===================================================================="
echo "                 AUDIOSCRIBE - TRANSCRIPTOR MULTIMEDIA"
echo "===================================================================="
echo ""

# 1. Comprobar entorno virtual local .venv
if [ -f ".venv/bin/python" ]; then
    if .venv/bin/python -c "import flask, flask_cors, whisper, yt_dlp" >/dev/null 2>&1; then
        echo "[INFO] Entorno virtual .venv detectado con todas las dependencias."
        .venv/bin/python serve_dashboard.py
        exit 0
    fi
fi

# 2. Comprobar python3 del sistema
if python3 -c "import flask, flask_cors, whisper, yt_dlp" >/dev/null 2>&1; then
    echo "[INFO] Utilizando Python3 del sistema con dependencias instaladas."
    python3 serve_dashboard.py
    exit 0
fi

# 3. Configuración automática de .venv e instalación de dependencias
echo "[WARNING] No se detectaron las dependencias requeridas."
echo "[INFO] Creando entorno virtual e instalando paquetes necesarios..."

if [ ! -f ".venv/bin/python" ]; then
    python3 -m venv .venv || {
        echo "[ERROR] No se pudo crear el entorno virtual. Verifica que python3-venv este instalado."
        exit 1
    }
fi

echo "[INFO] Instalando dependencias desde requirements.txt..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "[INFO] Iniciando AudioScribe..."
.venv/bin/python serve_dashboard.py
