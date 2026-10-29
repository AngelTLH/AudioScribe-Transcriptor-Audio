# AudioScribe

Aplicación local de transcripción de audio y video con interfaz web en español. Utiliza faster-whisper y permite procesar archivos locales y enlaces, convertir audio a MP3, descargar videos y recortar o fusionar archivos multimedia.

## Inicio en Windows

1. Instala Python 3.10 o posterior. La aplicación se ha probado con Python 3.12.
2. Abre `iniciar_servidor.bat`. La primera ejecución crea el entorno virtual e instala las dependencias.
3. Selecciona archivos o un enlace y pulsa **Iniciar transcripción**. Detén el servidor con Ctrl+C en la consola.

La configuración inicial es **Large v3 Turbo, Español, Automático y Equilibrado**. La primera vez que utilices un modelo se descargan sus archivos. La transcripción se realiza localmente. Los resultados se guardan en `Transcripciones/` en TXT, Markdown, LaTeX, SRT y VTT.

Para usar una GPU NVIDIA compatible en Windows, ejecuta `instalar_gpu.bat` después de crear el entorno con el lanzador. La instalación de CUDA/cuDNN requiere espacio y un controlador compatible. En modo Automático se utiliza CPU cuando los componentes GPU no están disponibles.

En Linux o macOS ejecuta `sh iniciar_servidor.sh`. La configuración automática de bibliotecas GPU del proyecto está orientada a Windows.

## Instalación manual

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe serve_dashboard.py
```

El servidor abre `http://localhost:5000/` o un puerto disponible. Para reproducir las versiones verificadas en Windows con Python 3.12 se puede instalar `requirements-lock.txt`. Para YouTube puede ser necesario Node.js 22 o superior o Deno, además de conexión a Internet.

## Funciones

- Cola secuencial y cancelación de tareas.
- Modelos Tiny, Base, Small, Medium, Large v3 y Large v3 Turbo en CPU o GPU NVIDIA.
- Glosario opcional y exportación de texto y subtítulos por segmento.
- Descarga de medios, conversión, recorte y fusión con FFmpeg.

Revisa nombres, números y partes con ruido o voces superpuestas: el reconocimiento automático puede cometer errores. La aplicación no identifica hablantes por separado.

## Estructura y desarrollo

`serve_dashboard.py` es el servidor Flask; `audioscribe/` contiene el motor y las exportaciones; `Pagina_Web/` contiene la interfaz; `tests/` reúne las pruebas. Las carpetas de salida contienen `.gitkeep`; `.gitignore` excluye sus resultados generados.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check serve_dashboard.py audioscribe tests
```

El servidor escucha localmente por defecto. `AUDIOSCRIBE_HOST=0.0.0.0` permite acceso desde una red local de confianza. El servidor permite operaciones con archivos de la computadora donde se ejecuta.

Consulta [LICENSE](LICENSE) para conocer la licencia.
