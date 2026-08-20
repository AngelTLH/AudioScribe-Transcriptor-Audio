import socket
import os
import sys
import threading
import webbrowser
import subprocess
import time
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import yt_dlp
import whisper

# Inicialización de ffmpeg mediante static-ffmpeg para Windows
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    print("[INFO] FFmpeg cargado dinámicamente mediante static-ffmpeg.")
except ImportError:
    print("[WARNING] static-ffmpeg no está instalado en este entorno virtual. Intentando usar FFmpeg del PATH...")

# Directorio raíz del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Carpeta del frontend web con búsqueda dinámica
possible_static_paths = [
    os.path.join(BASE_DIR, 'Pagina_Web', 'iest-main'),
    os.path.join(BASE_DIR, 'Pagina_Web', 'public'),
    os.path.join(BASE_DIR, 'Pagina_Web'),
]
STATIC_FOLDER = next((p for p in possible_static_paths if os.path.isdir(p)), os.path.join(BASE_DIR, 'Pagina_Web'))

# Carpetas de almacenamiento local para transcripciones, subidas temporales, MP3 convertidos, Videos de YT y Recortes
OUTPUT_DIR = os.path.join(BASE_DIR, 'Transcripciones')
UPLOAD_DIR = os.path.join(BASE_DIR, 'temp_uploads')
CONVERTED_DIR = os.path.join(BASE_DIR, 'Convertidos_MP3')
VIDEO_DOWNLOAD_DIR = os.path.join(BASE_DIR, 'Descarga_Videos_YT')
TRIMMED_DIR = os.path.join(BASE_DIR, 'Recortes_Archivos')
MERGED_DIR = os.path.join(BASE_DIR, 'Fusionados_Archivos')

# Asegurar existencia de directorios
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CONVERTED_DIR, exist_ok=True)
os.makedirs(VIDEO_DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TRIMMED_DIR, exist_ok=True)
os.makedirs(MERGED_DIR, exist_ok=True)

# Configuración del servidor Flask apuntando al directorio web
app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='')
CORS(app)

@app.after_request
def add_no_cache_headers(response):
    """Forzar que el navegador no cachee archivos HTML para garantizar que siempre se sirva la versión más reciente."""
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# Variables de estado global y sincronización
progress = {
    "status": "idle",  # idle, downloading, processing, completed, error
    "percent": 0,
    "message": "Servidor listo para recibir peticiones.",
    "transcription": "",
    "output_dir": "",
    "model": "",
    "language": ""
}

conversion_progress = {
    "status": "idle",  # idle, downloading, converting, completed, error
    "percent": 0,
    "message": "Servidor listo para recibir peticiones de conversión.",
    "filename": "",
    "filepath": "",
    "filesize": "",
    "bitrate": ""
}

video_download_progress = {
    "status": "idle",  # idle, downloading, processing, completed, error
    "percent": 0,
    "message": "Servidor listo para descargar videos de YouTube.",
    "filename": "",
    "filepath": "",
    "filesize": "",
    "quality": ""
}

trim_progress = {
    "status": "idle",  # idle, downloading, trimming, completed, error
    "percent": 0,
    "message": "Servidor listo para recortar multimedia.",
    "filename": "",
    "filepath": "",
    "filesize": "",
    "format": ""
}

merge_progress = {
    "status": "idle",  # idle, processing, merging, completed, error
    "percent": 0,
    "message": "Servidor listo para fusionar archivos multimedia.",
    "filename": "",
    "filepath": "",
    "filesize": "",
    "format": ""
}

state_lock = threading.Lock()
transcription_thread = None
conversion_thread = None
video_download_thread = None
trim_thread = None
merge_thread = None

def merge_thread_worker(file_paths, out_format="mp4"):
    global merge_progress
    concat_list_file = None
    try:
        with state_lock:
            merge_progress["status"] = "processing"
            merge_progress["percent"] = 15
            merge_progress["message"] = f"Preparando {len(file_paths)} archivos para unificación..."
            merge_progress["filename"] = ""
            merge_progress["filepath"] = ""
            merge_progress["filesize"] = ""
            merge_progress["format"] = out_format

        concat_list_file = os.path.join(UPLOAD_DIR, f"concat_{int(time.time())}.txt")
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for p in file_paths:
                clean_p = os.path.abspath(p).replace('\\', '/')
                f.write(f"file '{clean_p}'\n")

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"fusion_multimedia_{timestamp_str}.{out_format}"
        output_filepath = os.path.join(MERGED_DIR, output_filename)

        with state_lock:
            merge_progress["status"] = "merging"
            merge_progress["percent"] = 40
            merge_progress["message"] = f"Procesando fusión multimedia con FFmpeg ({out_format.upper()})..."

        if out_format == "mp3":
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_file,
                "-vn",
                "-acodec", "libmp3lame",
                "-ab", "192k",
                output_filepath
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_file,
                "-c:v", "libx264",
                "-preset", "fast",
                "-c:a", "aac",
                output_filepath
            ]

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)

        if os.path.exists(concat_list_file):
            try:
                os.remove(concat_list_file)
            except:
                pass

        size_bytes = os.path.getsize(output_filepath)
        size_str = f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes >= 1024 * 1024 else f"{size_bytes / 1024:.2f} KB"

        with state_lock:
            merge_progress["status"] = "completed"
            merge_progress["percent"] = 100
            merge_progress["message"] = "¡Fusión multimedia finalizada con éxito!"
            merge_progress["filename"] = output_filename
            merge_progress["filepath"] = os.path.abspath(output_filepath).replace('\\', '/')
            merge_progress["filesize"] = size_str

    except Exception as e:
        if concat_list_file and os.path.exists(concat_list_file):
            try:
                os.remove(concat_list_file)
            except:
                pass
        with state_lock:
            merge_progress["status"] = "error"
            merge_progress["percent"] = 100
            merge_progress["message"] = f"Error al fusionar archivos: {str(e)}"

def parse_time_to_seconds(time_str):
    """
    Convierte cadenas de tiempo como HH:MM:SS, MM:SS o segundos a float.
    """
    if not time_str:
        return 0.0
    time_str = str(time_str).strip()
    parts = time_str.split(':')
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        else:
            return float(parts[0])
    except ValueError:
        return 0.0

def trim_media_ffmpeg(input_path, output_path, start_sec, end_sec, out_format="mp4"):
    """
    Recorta un segmento de audio o video usando FFmpeg entre start_sec y end_sec.
    """
    duration = max(0.1, end_sec - start_sec)
    if out_format == "mp3":
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-t", str(duration),
            "-i", input_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ab", "192k",
            output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-t", str(duration),
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "aac",
            output_path
        ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)

def trim_thread_worker(source_type, params):
    """
    Hilo asíncrono para recortar archivos de audio o video.
    """
    global trim_progress
    temp_download_file = None
    try:
        with state_lock:
            trim_progress["status"] = "processing"
            trim_progress["percent"] = 10
            trim_progress["message"] = "Iniciando proceso de recorte multimedia..."
            trim_progress["filename"] = ""
            trim_progress["filepath"] = ""
            trim_progress["filesize"] = ""
            trim_progress["format"] = params.get("format", "mp4")

        input_path = None
        title = "recorte_multimedia"

        if source_type == 'url':
            with state_lock:
                trim_progress["status"] = "downloading"
                trim_progress["percent"] = 20
                trim_progress["message"] = "Descargando recurso desde el enlace web..."
            input_path, title = download_raw_audio(params["url"], UPLOAD_DIR)
            temp_download_file = input_path
        elif source_type == 'local_path':
            input_path = params["local_path"]
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"No se encontró el archivo local: {input_path}")
            base_name = os.path.basename(input_path)
            title = os.path.splitext(base_name)[0]
        elif source_type == 'upload':
            input_path = params["upload_path"]
            base_name = os.path.basename(input_path)
            title = os.path.splitext(base_name)[0]
            temp_download_file = input_path

        out_format = params.get("format", "mp4")
        start_sec = parse_time_to_seconds(params.get("start_time", "0"))
        end_sec = parse_time_to_seconds(params.get("end_time", "0"))

        if end_sec <= start_sec:
            raise ValueError("El tiempo de fin debe ser mayor que el tiempo de inicio.")

        safe_title = "".join([c if c.isalnum() or c in (' ', '_', '-') else '_' for c in title])
        safe_title = safe_title.replace(' ', '_').strip('_')
        if not safe_title:
            safe_title = "recorte"

        output_filename = f"{safe_title}_recorte_{int(start_sec)}s_a_{int(end_sec)}s.{out_format}"
        output_filepath = os.path.join(TRIMMED_DIR, output_filename)

        with state_lock:
            trim_progress["status"] = "trimming"
            trim_progress["percent"] = 50
            trim_progress["message"] = f"Recortando fragmento con FFmpeg ({params.get('start_time')} a {params.get('end_time')})..."

        trim_media_ffmpeg(input_path, output_filepath, start_sec, end_sec, out_format)

        if temp_download_file and os.path.exists(temp_download_file):
            try:
                os.remove(temp_download_file)
            except Exception as e:
                print(f"[WARNING] No se pudo eliminar el archivo temporal: {e}")

        size_bytes = os.path.getsize(output_filepath)
        size_str = f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes >= 1024 * 1024 else f"{size_bytes / 1024:.2f} KB"

        with state_lock:
            trim_progress["status"] = "completed"
            trim_progress["percent"] = 100
            trim_progress["message"] = "Recorte finalizado con éxito."
            trim_progress["filename"] = output_filename
            trim_progress["filepath"] = os.path.abspath(output_filepath).replace('\\', '/')
            trim_progress["filesize"] = size_str

    except Exception as e:
        if temp_download_file and os.path.exists(temp_download_file):
            try:
                os.remove(temp_download_file)
            except:
                pass
        with state_lock:
            trim_progress["status"] = "error"
            trim_progress["percent"] = 100
            trim_progress["message"] = f"Error al recortar: {str(e)}"

def video_progress_hook(d):
    global video_download_progress
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        pct = int(downloaded / total * 100) if total > 0 else 0
        with state_lock:
            video_download_progress["status"] = "downloading"
            video_download_progress["percent"] = min(pct, 95)
            speed_mb = (d.get('speed') or 0) / (1024 * 1024)
            video_download_progress["message"] = f"Descargando video... {pct}% ({speed_mb:.1f} MB/s)"
    elif d['status'] == 'finished':
        with state_lock:
            video_download_progress["percent"] = 95
            video_download_progress["message"] = "Descarga finalizada. Unificando formato de video y audio..."

def download_youtube_video(video_url, quality="best", output_dir=None):
    """
    Descarga un video de YouTube en formato MP4 unificando video y audio con FFmpeg.
    """
    if output_dir is None:
        output_dir = VIDEO_DOWNLOAD_DIR
    abs_output_dir = os.path.abspath(output_dir)
    os.makedirs(abs_output_dir, exist_ok=True)
    
    format_selector = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    if quality == '1080p':
        format_selector = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]'
    elif quality == '720p':
        format_selector = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]'
    elif quality == '480p':
        format_selector = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]'
    elif quality == '360p':
        format_selector = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]'
        
    ydl_opts = {
        'format': format_selector,
        'outtmpl': os.path.join(abs_output_dir, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'progress_hooks': [video_progress_hook],
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        prepared = ydl.prepare_filename(info)
        base_path, _ = os.path.splitext(prepared)
        mp4_filename = base_path + ".mp4"
        
        if os.path.exists(mp4_filename):
            return os.path.abspath(mp4_filename)
            
        if os.path.exists(prepared):
            return os.path.abspath(prepared)
            
        video_id = info.get('id', '')
        for f in os.listdir(abs_output_dir):
            if video_id and video_id in f:
                return os.path.abspath(os.path.join(abs_output_dir, f))
                
        return os.path.abspath(mp4_filename)

def video_download_worker(params):
    """
    Hilo asíncrono para descargar videos de YouTube en MP4.
    """
    global video_download_progress
    try:
        with state_lock:
            video_download_progress["status"] = "processing"
            video_download_progress["percent"] = 5
            video_download_progress["message"] = "Iniciando descarga del video..."
            video_download_progress["filename"] = ""
            video_download_progress["filepath"] = ""
            video_download_progress["filesize"] = ""
            video_download_progress["quality"] = params.get("quality", "best")
            
        video_path = download_youtube_video(params["url"], params.get("quality", "best"))
        
        size_bytes = os.path.getsize(video_path) if os.path.exists(video_path) else 0
        size_str = f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes >= 1024 * 1024 else f"{size_bytes / 1024:.2f} KB"
        filename = os.path.basename(video_path)
        
        with state_lock:
            video_download_progress["status"] = "completed"
            video_download_progress["percent"] = 100
            video_download_progress["message"] = "Video descargado con éxito."
            video_download_progress["filename"] = filename
            video_download_progress["filepath"] = os.path.abspath(video_path).replace('\\', '/')
            video_download_progress["filesize"] = size_str
            
    except Exception as e:
        with state_lock:
            video_download_progress["status"] = "error"
            video_download_progress["percent"] = 100
            video_download_progress["message"] = f"Error al descargar el video: {str(e)}"

def download_audio(video_url, output_dir=None):
    """
    Descarga el audio de un video de YouTube u otra plataforma compatible
    y lo convierte a formato MP3.
    """
    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, "Descarga_audio_YT")
    abs_output_dir = os.path.abspath(output_dir)
    os.makedirs(abs_output_dir, exist_ok=True)
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(abs_output_dir, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        prepared = ydl.prepare_filename(info)
        base_path, _ = os.path.splitext(prepared)
        mp3_filename = base_path + ".mp3"
        
        if os.path.exists(mp3_filename):
            return os.path.abspath(mp3_filename)
            
        if os.path.exists(prepared):
            return os.path.abspath(prepared)
            
        video_id = info.get('id', '')
        for f in os.listdir(abs_output_dir):
            if f.endswith('.mp3') and video_id and video_id in f:
                return os.path.abspath(os.path.join(abs_output_dir, f))
                
        return os.path.abspath(mp3_filename)

def download_raw_audio(video_url, output_dir):
    """
    Descarga el formato de mejor audio usando yt-dlp y retorna la ruta del archivo descargado
    y el título del video.
    """
    abs_output_dir = os.path.abspath(output_dir)
    os.makedirs(abs_output_dir, exist_ok=True)
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(abs_output_dir, '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            video_id = info.get('id', '')
            for f in os.listdir(abs_output_dir):
                if video_id and video_id in f:
                    filename = os.path.join(abs_output_dir, f)
                    break
        return os.path.abspath(filename), info.get('title', 'audio_convertido')

def convert_to_mp3_ffmpeg(input_path, output_path, bitrate):
    """
    Convierte cualquier archivo de audio/video a MP3 usando FFmpeg con el bitrate especificado.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ab", f"{bitrate}k",
        output_path
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)

def conversion_thread_worker(source_type, params):
    """
    Hilo de procesamiento asíncrono para descargar y convertir videos/audios a MP3.
    """
    global conversion_progress
    temp_download_file = None
    try:
        with state_lock:
            conversion_progress["status"] = "processing"
            conversion_progress["percent"] = 10
            conversion_progress["message"] = "Iniciando el proceso de conversión..."
            conversion_progress["filename"] = ""
            conversion_progress["filepath"] = ""
            conversion_progress["filesize"] = ""
            conversion_progress["bitrate"] = str(params["bitrate"])
            
        bitrate = params["bitrate"]
        input_path = None
        title = "audio_convertido"
        
        if source_type == 'url':
            with state_lock:
                conversion_progress["status"] = "downloading"
                conversion_progress["percent"] = 20
                conversion_progress["message"] = "Descargando video/audio desde el enlace (puede tardar unos minutos)..."
            input_path, title = download_raw_audio(params["url"], UPLOAD_DIR)
            temp_download_file = input_path
            
        elif source_type == 'local_path':
            input_path = params["local_path"]
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"No se encontró el archivo local: {input_path}")
            base_name = os.path.basename(input_path)
            title = os.path.splitext(base_name)[0]
            
        elif source_type == 'upload':
            input_path = params["upload_path"]
            base_name = os.path.basename(input_path)
            title = os.path.splitext(base_name)[0]
            temp_download_file = input_path
            
        # Nombre de archivo MP3 seguro
        safe_title = "".join([c if c.isalnum() or c in (' ', '_', '-') else '_' for c in title])
        safe_title = safe_title.replace(' ', '_').strip('_')
        if not safe_title:
            safe_title = "audio_convertido"
            
        output_filename = f"{safe_title}_{bitrate}kbps.mp3"
        output_filepath = os.path.join(CONVERTED_DIR, output_filename)
        
        with state_lock:
            conversion_progress["status"] = "converting"
            conversion_progress["percent"] = 60
            conversion_progress["message"] = f"Extrayendo y codificando audio a MP3 ({bitrate} kbps)..."
            
        # Ejecutar conversión FFmpeg
        convert_to_mp3_ffmpeg(input_path, output_filepath, bitrate)
        
        # Eliminar archivo temporal si es descarga o subida
        if temp_download_file and os.path.exists(temp_download_file):
            try:
                os.remove(temp_download_file)
            except Exception as e:
                print(f"[WARNING] No se pudo eliminar el archivo temporal: {e}")
                
        # Calcular tamaño del archivo
        size_bytes = os.path.getsize(output_filepath)
        size_str = f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes >= 1024 * 1024 else f"{size_bytes / 1024:.2f} KB"
        
        with state_lock:
            conversion_progress["status"] = "completed"
            conversion_progress["percent"] = 100
            conversion_progress["message"] = "Conversión completada con éxito."
            conversion_progress["filename"] = output_filename
            conversion_progress["filepath"] = os.path.abspath(output_filepath).replace('\\', '/')
            conversion_progress["filesize"] = size_str
            
    except Exception as e:
        if temp_download_file and os.path.exists(temp_download_file):
            try:
                os.remove(temp_download_file)
            except:
                pass
        with state_lock:
            conversion_progress["status"] = "error"
            conversion_progress["percent"] = 100
            conversion_progress["message"] = f"Error en la conversión: {str(e)}"

def execution_thread_worker(source_type, params):
    """
    Hilo de procesamiento asíncrono para descarga y transcripción de audios.
    """
    global progress
    try:
        with state_lock:
            progress["status"] = "processing"
            progress["percent"] = 5
            progress["message"] = "Inicializando el flujo de transcripción..."
            progress["transcription"] = ""
            progress["model"] = params.get("model", "small")
            progress["language"] = params.get("language", "es")
            
        audio_path = None
        
        if source_type == 'url':
            with state_lock:
                progress["percent"] = 10
                progress["message"] = "Descargando audio de enlace web (puede tardar unos minutos)..."
            audio_path = download_audio(params["url"])
            
        elif source_type == 'local_path':
            audio_path = params["local_path"]
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"No se encontró el archivo local especificado: {audio_path}")
                
        elif source_type == 'upload':
            audio_path = params["upload_path"]
            
        # Carga del modelo Whisper
        with state_lock:
            progress["percent"] = 30
            progress["message"] = f"Cargando modelo Whisper '{params['model']}' en memoria (descargando pesos en la primera ejecución)..."
        
        model = whisper.load_model(params["model"])
        
        # Transcripción del audio
        with state_lock:
            progress["percent"] = 55
            progress["message"] = "Transcribiendo y decodificando audio ( Whisper Inference )..."
            
        transcribe_opts = {}
        if params["language"] != "auto":
            transcribe_opts["language"] = params["language"]
            
        result = model.transcribe(audio_path, **transcribe_opts)
        text = result.get("text", "").strip()
        
        # Escritura del archivo de salida de texto plano
        safe_filename = "".join([c if c.isalnum() or c in (' ', '_', '-') else '_' for c in os.path.basename(audio_path)])
        safe_filename = safe_filename.replace(' ', '_').strip('_')
        if not safe_filename:
            safe_filename = "transcripcion"
            
        output_txt_path = os.path.join(OUTPUT_DIR, f"{safe_filename}.txt")
        with open(output_txt_path, "w", encoding="utf-8") as txt_file:
            txt_file.write(text)
            
        output_md_path = os.path.join(OUTPUT_DIR, f"{safe_filename}.md")
        with open(output_md_path, "w", encoding="utf-8") as md_file:
            md_file.write(f"# Transcripción de Audio - AudioScribe\n\n- **Origen:** {audio_path}\n- **Modelo:** {params['model']}\n- **Idioma:** {params['language']}\n\n---\n\n## Transcripción\n\n{text}\n")
            
        with state_lock:
            progress["status"] = "completed"
            progress["percent"] = 100
            progress["message"] = "Proceso finalizado exitosamente."
            progress["transcription"] = text
            progress["output_dir"] = OUTPUT_DIR
            
    except Exception as e:
        with state_lock:
            progress["status"] = "error"
            progress["percent"] = 100
            progress["message"] = f"Error en el procesamiento: {str(e)}"

@app.route('/')
def serve_index():
    """
    Redirección de la raíz del servidor al transcriptor web.
    """
    if os.path.exists(os.path.join(app.static_folder, 'transcriptor.html')):
        return send_from_directory(app.static_folder, 'transcriptor.html')
    elif os.path.exists(os.path.join(app.static_folder, 'index.html')):
        return send_from_directory(app.static_folder, 'index.html')
    return send_from_directory(app.static_folder, 'transcriptor.html')

@app.route('/<path:path>')
def serve_static(path):
    """
    Servicio de archivos de frontend estáticos.
    """
    return send_from_directory(app.static_folder, path)

@app.route('/api/transcribe/cancel', methods=['POST'])
def api_cancel_transcription():
    """
    Endpoint para cancelar/resetear el estado de transcripción atascado.
    Permite iniciar una nueva transcripción aunque la anterior no haya finalizado.
    """
    global progress, transcription_thread
    with state_lock:
        progress["status"] = "idle"
        progress["percent"] = 0
        progress["message"] = "Transcripción cancelada por el usuario."
        progress["transcription"] = ""
    return jsonify({"status": "cancelled"})

@app.route('/api/transcribe', methods=['POST'])
def api_start_transcription():
    """
    Endpoint para iniciar el proceso de transcripción de audio.
    """
    global progress, transcription_thread
    
    with state_lock:
        if progress["status"] == "processing":
            if transcription_thread and transcription_thread.is_alive():
                return jsonify({"error": "Ya existe un proceso de transcripción activo en curso. Puede cancelarla para iniciar una nueva."}), 409
            else:
                progress["status"] = "idle"
            
    # Verificación del tipo de origen (Upload multipart vs JSON)
    if 'file' in request.files:
        uploaded_file = request.files['file']
        model = request.form.get('model', 'small')
        language = request.form.get('language', 'es')
        
        if uploaded_file.filename == '':
            return jsonify({"error": "Archivo de subida no válido."}), 400
            
        sec_name = secure_filename(uploaded_file.filename)
        upload_path = os.path.join(UPLOAD_DIR, sec_name)
        uploaded_file.save(upload_path)
        
        params = {
            "upload_path": upload_path,
            "model": model,
            "language": language
        }
        with state_lock:
            transcription_thread = threading.Thread(target=execution_thread_worker, args=('upload', params))
            transcription_thread.start()
        return jsonify({"status": "started"})
        
    else:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Datos de petición vacíos."}), 400
            
        source_type = data.get("source_type")
        
        params = {
            "model": data.get("model", "small"),
            "language": data.get("language", "es")
        }
        
        if source_type == 'url':
            params["url"] = data.get("url")
            if not params["url"]:
                return jsonify({"error": "Debe ingresar una URL válida."}), 400
        elif source_type == 'local_path':
            params["local_path"] = data.get("local_path")
            if not params["local_path"]:
                return jsonify({"error": "Debe especificar la ruta absoluta local."}), 400
        else:
            return jsonify({"error": "Tipo de origen no especificado o no soportado."}), 400
            
        with state_lock:
            transcription_thread = threading.Thread(target=execution_thread_worker, args=(source_type, params))
            transcription_thread.start()
        return jsonify({"status": "started"})

@app.route('/api/files', methods=['GET'])
def api_get_files():
    yt_dir = os.path.join(BASE_DIR, "Descarga_audio_YT")
    upload_dir = os.path.join(BASE_DIR, "temp_uploads")
    mp3_dir = os.path.join(BASE_DIR, "Convertidos_MP3")
    video_dir = os.path.join(BASE_DIR, "Descarga_Videos_YT")
    trimmed_dir = os.path.join(BASE_DIR, "Recortes_Archivos")
    merged_dir = os.path.join(BASE_DIR, "Fusionados_Archivos")
    
    # Asegurar existencia de los directorios
    os.makedirs(yt_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(mp3_dir, exist_ok=True)
    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(trimmed_dir, exist_ok=True)
    os.makedirs(merged_dir, exist_ok=True)
    
    def get_file_list(directory):
        file_list = []
        for f in os.listdir(directory):
            path = os.path.join(directory, f)
            if os.path.isfile(path) and f != '.gitkeep':
                size_bytes = os.path.getsize(path)
                # Formatear tamaño de forma legible
                size_str = f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes >= 1024 * 1024 else f"{size_bytes / 1024:.2f} KB"
                file_list.append({
                    "name": f,
                    "size": size_str,
                    "path": os.path.abspath(path).replace('\\', '/')
                })
        return file_list

    return jsonify({
        "yt_files": get_file_list(yt_dir),
        "uploaded_files": get_file_list(upload_dir),
        "mp3_files": get_file_list(mp3_dir),
        "video_files": get_file_list(video_dir),
        "trimmed_files": get_file_list(trimmed_dir),
        "merged_files": get_file_list(merged_dir)
    })

@app.route('/api/files', methods=['DELETE'])
def api_delete_files():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Petición vacía."}), 400
        
    category = data.get("category")
    filename = data.get("filename")
    
    if category == 'yt':
        target_dir = os.path.join(BASE_DIR, "Descarga_audio_YT")
    elif category == 'upload':
        target_dir = os.path.join(BASE_DIR, "temp_uploads")
    elif category == 'mp3':
        target_dir = os.path.join(BASE_DIR, "Convertidos_MP3")
    elif category == 'video':
        target_dir = os.path.join(BASE_DIR, "Descarga_Videos_YT")
    elif category == 'trimmed':
        target_dir = os.path.join(BASE_DIR, "Recortes_Archivos")
    elif category == 'merged':
        target_dir = os.path.join(BASE_DIR, "Fusionados_Archivos")
    else:
        return jsonify({"error": "Categoría inválida. Debe ser 'yt', 'upload', 'mp3', 'video', 'trimmed' o 'merged'."}), 400
        
    # Eliminar un archivo específico
    if filename:
        filename = secure_filename(filename)
        file_path = os.path.join(target_dir, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            try:
                os.remove(file_path)
                return jsonify({"status": "success", "message": f"Archivo '{filename}' eliminado."})
            except Exception as e:
                return jsonify({"error": f"No se pudo eliminar el archivo: {str(e)}"}), 500
        else:
            return jsonify({"error": f"Archivo no encontrado: {filename}"}), 404
            
    # Vaciar todo el directorio
    else:
        try:
            deleted_count = 0
            for f in os.listdir(target_dir):
                file_path = os.path.join(target_dir, f)
                if os.path.isfile(file_path) and f != '.gitkeep':
                    os.remove(file_path)
                    deleted_count += 1
            return jsonify({"status": "success", "message": f"Se eliminaron {deleted_count} archivos de la carpeta."})
        except Exception as e:
            return jsonify({"error": f"Error al vaciar la carpeta: {str(e)}"}), 500

@app.route('/api/status', methods=['GET'])
def api_get_status():
    """
    Retorna el estado y avance actual del transcriptor.
    """
    with state_lock:
        return jsonify(progress)

@app.route('/api/convert/status', methods=['GET'])
def api_get_conversion_status():
    """
    Retorna el estado y avance actual del convertidor de MP3.
    """
    with state_lock:
        return jsonify(conversion_progress)

@app.route('/api/trim/status', methods=['GET'])
def api_get_trim_status():
    """
    Retorna el estado y avance del recortador multimedia.
    """
    with state_lock:
        return jsonify(trim_progress)

@app.route('/api/merge/status', methods=['GET'])
def api_get_merge_status():
    """
    Retorna el estado y avance del fusionador multimedia.
    """
    with state_lock:
        return jsonify(merge_progress)

@app.route('/api/merge/cancel', methods=['POST'])
def api_cancel_merge():
    global merge_progress
    with state_lock:
        merge_progress["status"] = "idle"
        merge_progress["percent"] = 0
        merge_progress["message"] = "Fusión cancelada por el usuario."
    return jsonify({"status": "cancelled"})

@app.route('/api/merge', methods=['POST'])
def api_start_merge():
    """
    Endpoint para iniciar la fusión de múltiples archivos de audio/video.
    """
    global merge_progress, merge_thread
    
    with state_lock:
        if merge_progress["status"] in ("processing", "merging"):
            if merge_thread and merge_thread.is_alive():
                return jsonify({"error": "Ya existe una tarea de fusión en curso."}), 409
            else:
                merge_progress["status"] = "idle"

    file_paths = []
    out_format = "mp4"

    if request.files:
        out_format = request.form.get("format", "mp4")
        uploaded_files = request.files.getlist('files')
        if not uploaded_files:
            return jsonify({"error": "No se seleccionaron archivos para subir."}), 400
            
        for uf in uploaded_files:
            if uf.filename:
                sec_name = secure_filename(uf.filename)
                save_path = os.path.join(UPLOAD_DIR, f"merge_tmp_{int(time.time())}_{sec_name}")
                uf.save(save_path)
                file_paths.append(save_path)
    else:
        data = request.get_json()
        if not data or not data.get("paths"):
            return jsonify({"error": "No se recibieron rutas de archivos para fusionar."}), 400
        file_paths = data.get("paths", [])
        out_format = data.get("format", "mp4")

    if len(file_paths) < 2:
        return jsonify({"error": "Se requieren al menos 2 archivos para realizar la fusión."}), 400

    with state_lock:
        merge_thread = threading.Thread(target=merge_thread_worker, args=(file_paths, out_format))
        merge_thread.start()
    return jsonify({"status": "started"})

@app.route('/api/merge/file/<path:filename>', methods=['GET'])
def api_serve_merged_file(filename):
    """
    Endpoint para descargar un archivo fusionado.
    """
    filename = secure_filename(filename)
    return send_from_directory(MERGED_DIR, filename, as_attachment=True)

@app.route('/api/trim/cancel', methods=['POST'])
def api_cancel_trim():
    global trim_progress
    with state_lock:
        trim_progress["status"] = "idle"
        trim_progress["percent"] = 0
        trim_progress["message"] = "Recorte cancelado por el usuario."
    return jsonify({"status": "cancelled"})

@app.route('/api/trim', methods=['POST'])
def api_start_trim():
    """
    Endpoint para iniciar el recorte de audio/video.
    """
    global trim_progress, trim_thread
    
    with state_lock:
        if trim_progress["status"] in ("downloading", "trimming", "processing"):
            if trim_thread and trim_thread.is_alive():
                return jsonify({"error": "Ya existe una tarea de recorte en curso."}), 409
            else:
                trim_progress["status"] = "idle"
                
    if 'file' in request.files:
        uploaded_file = request.files['file']
        start_time = request.form.get('start_time', '0')
        end_time = request.form.get('end_time', '0')
        out_format = request.form.get('format', 'mp4')
        
        if uploaded_file.filename == '':
            return jsonify({"error": "Archivo de subida no válido."}), 400
            
        sec_name = secure_filename(uploaded_file.filename)
        upload_path = os.path.join(UPLOAD_DIR, sec_name)
        uploaded_file.save(upload_path)
        
        params = {
            "upload_path": upload_path,
            "start_time": start_time,
            "end_time": end_time,
            "format": out_format
        }
        with state_lock:
            trim_thread = threading.Thread(target=trim_thread_worker, args=('upload', params))
            trim_thread.start()
        return jsonify({"status": "started"})
        
    else:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Datos de petición vacíos."}), 400
            
        source_type = data.get("source_type")
        start_time = data.get("start_time", "0")
        end_time = data.get("end_time", "0")
        out_format = data.get("format", "mp4")
        
        params = {
            "start_time": start_time,
            "end_time": end_time,
            "format": out_format
        }
        
        if source_type == 'url':
            params["url"] = data.get("url")
            if not params["url"]:
                return jsonify({"error": "Debe ingresar una URL válida."}), 400
        elif source_type == 'local_path':
            params["local_path"] = data.get("local_path")
            if not params["local_path"]:
                return jsonify({"error": "Debe especificar la ruta absoluta local."}), 400
        else:
            return jsonify({"error": "Tipo de origen no especificado."}), 400
            
        with state_lock:
            trim_thread = threading.Thread(target=trim_thread_worker, args=(source_type, params))
            trim_thread.start()
        return jsonify({"status": "started"})

@app.route('/api/trim/file/<path:filename>', methods=['GET'])
def api_serve_trimmed_file(filename):
    """
    Endpoint para descargar un archivo recortado.
    """
    filename = secure_filename(filename)
    return send_from_directory(TRIMMED_DIR, filename, as_attachment=True)

@app.route('/api/download/mp3/<filename>', methods=['GET'])
def api_download_mp3(filename):
    """
    Endpoint para descargar un MP3 convertido.
    """
    # secure_filename para evitar path traversal
    filename = secure_filename(filename)
    return send_from_directory(CONVERTED_DIR, filename, as_attachment=True)

@app.route('/api/convert', methods=['POST'])
def api_start_conversion():
    """
    Endpoint para iniciar el proceso de conversión a MP3.
    """
    global conversion_progress, conversion_thread
    
    with state_lock:
        if conversion_progress["status"] in ("downloading", "converting", "processing"):
            if conversion_thread and conversion_thread.is_alive():
                return jsonify({"error": "Ya existe una tarea de conversión en curso."}), 409
            else:
                conversion_progress["status"] = "idle"
            
    if 'file' in request.files:
        uploaded_file = request.files['file']
        bitrate_str = request.form.get('bitrate', '192')
        try:
            bitrate = int(bitrate_str)
            if not (124 <= bitrate <= 332):
                raise ValueError()
        except ValueError:
            return jsonify({"error": "El bitrate debe ser un número entero entre 124 y 332."}), 400
            
        if uploaded_file.filename == '':
            return jsonify({"error": "Archivo de subida no válido."}), 400
            
        sec_name = secure_filename(uploaded_file.filename)
        upload_path = os.path.join(UPLOAD_DIR, sec_name)
        uploaded_file.save(upload_path)
        
        params = {
            "upload_path": upload_path,
            "bitrate": bitrate
        }
        with state_lock:
            conversion_thread = threading.Thread(target=conversion_thread_worker, args=('upload', params))
            conversion_thread.start()
        return jsonify({"status": "started"})
        
    else:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Datos de petición vacíos."}), 400
            
        source_type = data.get("source_type")
        bitrate_str = data.get("bitrate", "192")
        try:
            bitrate = int(bitrate_str)
            if not (124 <= bitrate <= 332):
                raise ValueError()
        except ValueError:
            return jsonify({"error": "El bitrate debe ser un número entero entre 124 y 332."}), 400
            
        params = {
            "bitrate": bitrate
        }
        
        if source_type == 'url':
            params["url"] = data.get("url")
            if not params["url"]:
                return jsonify({"error": "Debe ingresar una URL válida."}), 400
        elif source_type == 'local_path':
            params["local_path"] = data.get("local_path")
            if not params["local_path"]:
                return jsonify({"error": "Debe especificar la ruta absoluta local."}), 400
        else:
            return jsonify({"error": "Tipo de origen no especificado o no soportado."}), 400
            
        with state_lock:
            conversion_thread = threading.Thread(target=conversion_thread_worker, args=(source_type, params))
            conversion_thread.start()
        return jsonify({"status": "started"})

@app.route('/api/download_video/status', methods=['GET'])
def api_get_video_download_status():
    """
    Retorna el estado y avance actual del descargador de videos de YouTube.
    """
    with state_lock:
        return jsonify(video_download_progress)

@app.route('/api/download_video/cancel', methods=['POST'])
def api_cancel_video_download():
    """
    Endpoint para cancelar/resetear la descarga de video.
    """
    global video_download_progress
    with state_lock:
        video_download_progress["status"] = "idle"
        video_download_progress["percent"] = 0
        video_download_progress["message"] = "Descarga de video cancelada por el usuario."
    return jsonify({"status": "cancelled"})

@app.route('/api/download_video', methods=['POST'])
def api_start_video_download():
    """
    Endpoint para iniciar el proceso de descarga de video de YouTube.
    """
    global video_download_progress, video_download_thread
    data = request.get_json()
    if not data or not data.get("url"):
        return jsonify({"error": "Debe ingresar una URL válida de YouTube."}), 400
        
    with state_lock:
        if video_download_progress["status"] in ("downloading", "processing"):
            if video_download_thread and video_download_thread.is_alive():
                return jsonify({"error": "Ya existe una descarga de video activa en curso."}), 409
            else:
                video_download_progress["status"] = "idle"
                
    params = {
        "url": data.get("url"),
        "quality": data.get("quality", "best")
    }
    
    with state_lock:
        video_download_thread = threading.Thread(target=video_download_worker, args=(params,))
        video_download_thread.start()
    return jsonify({"status": "started"})

@app.route('/api/download_video/file/<path:filename>', methods=['GET'])
def api_serve_downloaded_video_file(filename):
    """
    Endpoint para descargar el archivo MP4 generado.
    """
    filename = secure_filename(filename)
    return send_from_directory(VIDEO_DOWNLOAD_DIR, filename, as_attachment=True)

@app.route('/api/save_tex', methods=['POST'])
def api_save_tex():
    """
    Exporta e inicializa la compilación LaTeX (.tex) de la transcripción.
    """
    data = request.get_json()
    if not data or not data.get('transcription'):
        return jsonify({"error": "No se proveyó contenido de transcripción."}), 400
        
    transcription = data['transcription']
    source = data.get('source', 'Desconocido')
    model = data.get('model', 'small')
    language = data.get('language', 'es')
    
    try:
        # Formateo del nombre seguro de archivo
        base_source = os.path.basename(source)
        safe_name = "".join([c if c.isalnum() or c in (' ', '_', '-') else '_' for c in base_source])
        safe_name = safe_name.replace(' ', '_').strip('_')
        if not safe_name:
            safe_name = "transcripcion"
            
        tex_filepath = os.path.join(OUTPUT_DIR, f"{safe_name}.tex")
        
        # Plantilla LaTeX adaptada al diseño institucional y estilo de escritura
        tex_template = r"""\documentclass[12pt,letterpaper]{{article}}
\usepackage[utf8]{{inputenc}}
\usepackage[spanish]{{babel}}
\usepackage{{geometry}}
\geometry{{letterpaper, margin=1in}}
\usepackage{{xcolor}}
\usepackage{{booktabs}}
 
\definecolor{{IESTnavy}}{{HTML}}{{142E4C}}
\definecolor{{IESTcyan}}{{HTML}}{{2F95A3}}
 
\title{{\color{{IESTnavy}}\textbf{{Transcripción de Audio Automatizada}}}}
\author{{Consultora IEST}}
\date{{\today}}
 
\begin{{document}}
 
\maketitle
 
\section*{{Detalles del Procesamiento}}
\begin{{itemize}}
    \item \textbf{{Origen de Datos/Archivo:}} {source}
    \item \textbf{{Modelo Whisper Seleccionado:}} {model}
    \item \textbf{{Idioma del Audio:}} {language}
    \item \textbf{{Ruta Local del Reporte:}} {output_dir}
\end{{itemize}}
 
\section*{{Transcripción de Audio}}
{transcription}
 
\end{{document}}
""".format(
            source=source.replace('_', '\\_').replace('&', '\\&'),
            model=model,
            language=language,
            output_dir=OUTPUT_DIR.replace('\\', '/'),
            transcription=transcription
        )
        
        with open(tex_filepath, "w", encoding="utf-8") as tex_file:
            tex_file.write(tex_template)
            
        return jsonify({
            "status": "success",
            "path": tex_filepath,
            "filename": f"{safe_name}.tex",
            "content": tex_template
        })
        
    except Exception as e:
        return jsonify({"error": f"Error al generar archivo LaTeX: {str(e)}"}), 500

@app.route('/api/save_md', methods=['POST'])
def api_save_md():
    """
    Exporta e inicializa el documento Markdown (.md) de la transcripción.
    """
    data = request.get_json()
    if not data or not data.get('transcription'):
        return jsonify({"error": "No se proveyó contenido de transcripción."}), 400
        
    transcription = data['transcription']
    source = data.get('source', 'Desconocido')
    model = data.get('model', 'small')
    language = data.get('language', 'es')
    
    try:
        base_source = os.path.basename(source)
        safe_name = "".join([c if c.isalnum() or c in (' ', '_', '-') else '_' for c in base_source])
        safe_name = safe_name.replace(' ', '_').strip('_')
        if not safe_name:
            safe_name = "transcripcion"
            
        md_filepath = os.path.join(OUTPUT_DIR, f"{safe_name}.md")
        
        md_template = f"""# Transcripción de Audio - AudioScribe

## Detalles del Procesamiento
- **Origen de Datos / Archivo:** {source}
- **Modelo Whisper Seleccionado:** {model}
- **Idioma del Audio:** {language}
- **Ruta Local:** {OUTPUT_DIR.replace('\\', '/')}

---

## Transcripción

{transcription}
"""
        with open(md_filepath, "w", encoding="utf-8") as md_file:
            md_file.write(md_template)
            
        return jsonify({
            "status": "success",
            "path": md_filepath,
            "filename": f"{safe_name}.md",
            "content": md_template
        })
    except Exception as e:
        return jsonify({"error": f"Error al generar archivo Markdown: {str(e)}"}), 500

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Conexión ficticia a DNS de Google para determinar la IP del adaptador de red activo
        s.connect(('8.8.8.8', 80))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def start_server():
    local_ip = get_ip()
    port = 5000
    max_attempts = 10
    
    # Buscar un puerto libre a partir del 5000
    for attempt in range(max_attempts):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("0.0.0.0", port))
            s.close()
            break
        except OSError:
            print(f"[INFO] Puerto {port} ocupado, intentando con el puerto {port + 1}...")
            port += 1
            
    local_url = f"http://localhost:{port}/transcriptor.html"
    wifi_url = f"http://{local_ip}:{port}/transcriptor.html"
    
    print("\n" + "=" * 70)
    print("           SERVIDOR FLASK INICIADO CON EXITO")
    print("=" * 70)
    print(f"  Acceso en esta Computadora:")
    print(f"    --> Dashboard:  {local_url}")
    print(f"    --> Inicio:     http://localhost:{port}/")
    print()
    print(f"  Acceso desde otras Notebooks/Celulares (mismo Wi-Fi):")
    print(f"    --> Dashboard:  {wifi_url}")
    print(f"    --> Inicio:     http://{local_ip}:{port}/")
    print("=" * 70)
    print("  * IMPORTANTE: Asegurate de que los otros dispositivos esten")
    print("    conectados al mismo Wi-Fi que esta computadora.")
    print("=" * 70)
    print("  Presiona Ctrl+C en esta consola para apagar el servidor.")
    print("=" * 70 + "\n")
    
    # Abrir URL automáticamente en el navegador por defecto
    try:
        webbrowser.open(local_url)
    except Exception as e:
        print(f"No se pudo abrir el navegador automaticamente: {e}")
        
    # Iniciar la aplicación Flask escuchando en todas las interfaces de red (0.0.0.0)
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    start_server()
