import os
import shutil
import socket
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import yt_dlp
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from audioscribe.exports import output_stem, render_latex, save_transcription
from audioscribe.jobs import check_cancelled, run_ffmpeg, run_job
from audioscribe.transcription import (
    MODELS,
    InferenceService,
    JobCancelled,
    normalize_options,
)


# Inicialización de ffmpeg mediante static-ffmpeg para Windows
def ensure_ffmpeg():
    """Resuelve FFmpeg al usar multimedia, sin descargas al importar Flask."""
    import shutil

    if not shutil.which("ffmpeg"):
        import static_ffmpeg

        static_ffmpeg.add_paths()


# Directorio raíz del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Interfaz única de AudioScribe.
STATIC_FOLDER = os.path.join(BASE_DIR, "Pagina_Web")

# Carpetas de almacenamiento local para transcripciones, subidas temporales, MP3 convertidos, Videos de YT y Recortes
OUTPUT_DIR = os.path.join(BASE_DIR, "Transcripciones")
UPLOAD_DIR = os.path.join(BASE_DIR, "temp_uploads")
CONVERTED_DIR = os.path.join(BASE_DIR, "Convertidos_MP3")
VIDEO_DOWNLOAD_DIR = os.path.join(BASE_DIR, "Descarga_Videos_YT")
TRIMMED_DIR = os.path.join(BASE_DIR, "Recortes_Archivos")
MERGED_DIR = os.path.join(BASE_DIR, "Fusionados_Archivos")

# Asegurar existencia de directorios
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CONVERTED_DIR, exist_ok=True)
os.makedirs(VIDEO_DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TRIMMED_DIR, exist_ok=True)
os.makedirs(MERGED_DIR, exist_ok=True)

# Configuración del servidor Flask apuntando al directorio web
app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path="")
CORS(app, origins=[r"http://localhost(?::\d+)?", r"http://127\.0\.0\.1(?::\d+)?"])
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024


@app.after_request
def add_no_cache_headers(response):
    """Forzar que el navegador no cachee archivos HTML para garantizar que siempre se sirva la versión más reciente."""
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Variables de estado global y sincronización
progress = {
    "status": "idle",  # idle, downloading, processing, completed, error
    "percent": 0,
    "message": "Servidor listo para recibir peticiones.",
    "transcription": "",
    "output_dir": "",
    "model": "",
    "language": "",
}

conversion_progress = {
    "status": "idle",  # idle, downloading, converting, completed, error
    "percent": 0,
    "message": "Servidor listo para recibir peticiones de conversión.",
    "filename": "",
    "filepath": "",
    "filesize": "",
    "bitrate": "",
}

video_download_progress = {
    "status": "idle",  # idle, downloading, processing, completed, error
    "percent": 0,
    "message": "Servidor listo para descargar videos de YouTube.",
    "filename": "",
    "filepath": "",
    "filesize": "",
    "quality": "",
}

trim_progress = {
    "status": "idle",  # idle, downloading, trimming, completed, error
    "percent": 0,
    "message": "Servidor listo para recortar multimedia.",
    "filename": "",
    "filepath": "",
    "filesize": "",
    "format": "",
}

merge_progress = {
    "status": "idle",  # idle, processing, merging, completed, error
    "percent": 0,
    "message": "Servidor listo para fusionar archivos multimedia.",
    "filename": "",
    "filepath": "",
    "filesize": "",
    "format": "",
}

state_lock = threading.Lock()
transcription_thread = None
conversion_thread = None
video_download_thread = None
trim_thread = None
merge_thread = None
job_events = {
    name: threading.Event()
    for name in ("transcription", "conversion", "video_download", "trim", "merge")
}
inference_service = InferenceService()


class JobBusy(Exception):
    """Indica que una tarea todavía conserva sus recursos."""


@app.errorhandler(JobBusy)
def job_is_busy(error):
    return jsonify({"error": str(error)}), 409


def make_job_thread(name, worker, state, args):
    """Reserva el estado bajo state_lock antes de iniciar un hilo."""
    current = globals().get(name + "_thread")
    if current is not None and current.is_alive():
        raise JobBusy("Ya existe una tarea activa. Espere a que termine.")
    event = job_events[name]
    event.clear()
    state.update(status="processing", percent=0, message="Preparando tarea...")
    return threading.Thread(
        target=run_job, args=(worker, state, state_lock, event, *args), daemon=True
    )


def cancel_job(name, state, thread):
    """Mantiene la tarea ocupada hasta que sus recursos queden liberados."""
    with state_lock:
        if thread is not None and thread.is_alive():
            job_events[name].set()
            state.update(status="cancelling", message="Deteniendo tarea...")
            status = "cancelling"
        else:
            status = "idle"
    return jsonify({"status": status})


def save_upload(uploaded_file, prefix=""):
    """Conserva subidas de igual nombre y rechaza nombres vacíos."""
    filename = secure_filename(uploaded_file.filename or "")
    if not filename:
        raise ValueError("El archivo debe tener un nombre válido.")
    path = os.path.join(UPLOAD_DIR, f"{prefix}{uuid4().hex[:10]}_{filename}")
    uploaded_file.save(path)
    return path


def media_filename(filename):
    """Valida un nombre sin cambiar acentos ni espacios de archivos existentes."""
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise ValueError("Nombre de archivo inválido.")
    return filename


def youtube_js_runtimes():
    """Habilita los motores JavaScript instalados para los retos de YouTube."""
    return {name: {} for name in ("deno", "node") if shutil.which(name)}


@app.errorhandler(ValueError)
def invalid_request(error):
    """Devuelve errores de validación como JSON para la interfaz."""
    return jsonify({"error": str(error)}), 400


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"error": "El archivo supera 4 GB; utilice su ruta local."}), 413


def merge_thread_worker(file_paths, out_format="mp4"):
    global merge_progress
    concat_list_file = None
    if out_format not in ("mp3", "mp4"):
        raise ValueError("Formato de salida no válido.")
    if (
        not isinstance(file_paths, list)
        or len(file_paths) < 2
        or any(
            not isinstance(path, str) or not Path(path).is_file() for path in file_paths
        )
    ):
        raise ValueError("Se requieren al menos dos archivos existentes para fusionar.")
    try:
        with state_lock:
            merge_progress["status"] = "processing"
            merge_progress["percent"] = 15
            merge_progress["message"] = (
                f"Preparando {len(file_paths)} archivos para unificación..."
            )
            merge_progress["filename"] = ""
            merge_progress["filepath"] = ""
            merge_progress["filesize"] = ""
            merge_progress["format"] = out_format

        concat_list_file = os.path.join(UPLOAD_DIR, f"concat_{uuid4().hex}.txt")
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for p in file_paths:
                clean_p = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{clean_p}'\n")

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = (
            f"fusion_multimedia_{timestamp_str}_{uuid4().hex[:6]}.{out_format}"
        )
        output_filepath = os.path.join(MERGED_DIR, output_filename)

        with state_lock:
            merge_progress["status"] = "merging"
            merge_progress["percent"] = 40
            merge_progress["message"] = (
                f"Procesando fusión multimedia con FFmpeg ({out_format.upper()})..."
            )

        if out_format == "mp3":
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list_file,
                "-vn",
                "-acodec",
                "libmp3lame",
                "-ab",
                "192k",
                output_filepath,
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list_file,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                output_filepath,
            ]

        ensure_ffmpeg()
        run_ffmpeg(cmd)

        if os.path.exists(concat_list_file):
            try:
                os.remove(concat_list_file)
            except OSError:
                pass

        size_bytes = os.path.getsize(output_filepath)
        size_str = (
            f"{size_bytes / (1024 * 1024):.2f} MB"
            if size_bytes >= 1024 * 1024
            else f"{size_bytes / 1024:.2f} KB"
        )

        with state_lock:
            merge_progress["status"] = "completed"
            merge_progress["percent"] = 100
            merge_progress["message"] = "¡Fusión multimedia finalizada con éxito!"
            merge_progress["filename"] = output_filename
            merge_progress["filepath"] = os.path.abspath(output_filepath).replace(
                "\\", "/"
            )
            merge_progress["filesize"] = size_str

    except Exception as e:
        if concat_list_file and os.path.exists(concat_list_file):
            try:
                os.remove(concat_list_file)
            except OSError:
                pass
        with state_lock:
            merge_progress["status"] = "error"
            merge_progress["percent"] = 100
            merge_progress["message"] = f"Error al fusionar archivos: {str(e)}"


def parse_time_to_seconds(time_str):
    """
    Convierte cadenas de tiempo como HH:MM:SS, MM:SS o segundos a float.
    """
    import math

    parts = str(time_str or "0").strip().split(":")
    try:
        values = [float(part) for part in parts]
    except (ValueError, TypeError) as error:
        raise ValueError("Marca de tiempo no válida.") from error
    if (
        not 1 <= len(values) <= 3
        or any(not math.isfinite(value) or value < 0 for value in values)
        or (len(values) > 1 and any(value >= 60 for value in values[1:]))
    ):
        raise ValueError("Use segundos, MM:SS o HH:MM:SS válidos.")
    return sum(value * 60**power for power, value in enumerate(reversed(values)))


def trim_media_ffmpeg(input_path, output_path, start_sec, end_sec, out_format="mp4"):
    """
    Recorta un segmento de audio o video usando FFmpeg entre start_sec y end_sec.
    """
    if out_format not in ("mp3", "mp4"):
        raise ValueError("Formato de salida no válido.")
    if end_sec <= start_sec or start_sec < 0:
        raise ValueError(
            "El fin debe ser mayor que el inicio y ambos deben ser positivos."
        )
    duration = end_sec - start_sec
    if out_format == "mp3":
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_sec),
            "-t",
            str(duration),
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ab",
            "192k",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_sec),
            "-t",
            str(duration),
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-c:a",
            "aac",
            output_path,
        ]
    ensure_ffmpeg()
    run_ffmpeg(cmd)


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

        if source_type == "url":
            with state_lock:
                trim_progress["status"] = "downloading"
                trim_progress["percent"] = 20
                trim_progress["message"] = "Descargando recurso desde el enlace web..."
            if params.get("format", "mp4") == "mp4":
                input_path = download_youtube_video(
                    params["url"], output_dir=UPLOAD_DIR, track_progress=False
                )
                title = Path(input_path).stem
            else:
                input_path, title = download_raw_audio(params["url"], UPLOAD_DIR)
            temp_download_file = input_path
        elif source_type == "local_path":
            input_path = params["local_path"]
            if not os.path.exists(input_path):
                raise FileNotFoundError(
                    f"No se encontró el archivo local: {input_path}"
                )
            base_name = os.path.basename(input_path)
            title = os.path.splitext(base_name)[0]
        elif source_type == "upload":
            input_path = params["upload_path"]
            base_name = os.path.basename(input_path)
            title = os.path.splitext(base_name)[0]
            temp_download_file = input_path

        out_format = params.get("format", "mp4")
        start_sec = parse_time_to_seconds(params.get("start_time", "0"))
        end_sec = parse_time_to_seconds(params.get("end_time", "0"))

        if end_sec <= start_sec:
            raise ValueError("El tiempo de fin debe ser mayor que el tiempo de inicio.")

        safe_title = "".join(
            [c if c.isalnum() or c in (" ", "_", "-") else "_" for c in title]
        )
        safe_title = safe_title.replace(" ", "_").strip("_")
        if not safe_title:
            safe_title = "recorte"

        output_filename = f"{output_stem(safe_title)}_recorte.{out_format}"
        output_filepath = os.path.join(TRIMMED_DIR, output_filename)

        with state_lock:
            trim_progress["status"] = "trimming"
            trim_progress["percent"] = 50
            trim_progress["message"] = (
                f"Recortando fragmento con FFmpeg ({params.get('start_time')} a {params.get('end_time')})..."
            )

        trim_media_ffmpeg(input_path, output_filepath, start_sec, end_sec, out_format)

        if temp_download_file and os.path.exists(temp_download_file):
            try:
                os.remove(temp_download_file)
            except Exception as e:
                print(f"[WARNING] No se pudo eliminar el archivo temporal: {e}")

        size_bytes = os.path.getsize(output_filepath)
        size_str = (
            f"{size_bytes / (1024 * 1024):.2f} MB"
            if size_bytes >= 1024 * 1024
            else f"{size_bytes / 1024:.2f} KB"
        )

        with state_lock:
            trim_progress["status"] = "completed"
            trim_progress["percent"] = 100
            trim_progress["message"] = "Recorte finalizado con éxito."
            trim_progress["filename"] = output_filename
            trim_progress["filepath"] = os.path.abspath(output_filepath).replace(
                "\\", "/"
            )
            trim_progress["filesize"] = size_str

    except Exception as e:
        if temp_download_file and os.path.exists(temp_download_file):
            try:
                os.remove(temp_download_file)
            except OSError:
                pass
        with state_lock:
            trim_progress["status"] = "error"
            trim_progress["percent"] = 100
            trim_progress["message"] = f"Error al recortar: {str(e)}"


def video_progress_hook(d):
    global video_download_progress
    if d["status"] == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        downloaded = d.get("downloaded_bytes", 0)
        pct = int(downloaded / total * 100) if total > 0 else 0
        with state_lock:
            video_download_progress["status"] = "downloading"
            video_download_progress["percent"] = min(pct, 95)
            speed_mb = (d.get("speed") or 0) / (1024 * 1024)
            video_download_progress["message"] = (
                f"Descargando video... {pct}% ({speed_mb:.1f} MB/s)"
            )
    elif d["status"] == "finished":
        with state_lock:
            video_download_progress["percent"] = 95
            video_download_progress["message"] = (
                "Descarga finalizada. Unificando formato de video y audio..."
            )


def download_youtube_video(
    video_url, quality="best", output_dir=None, track_progress=True
):
    """
    Descarga un video de YouTube en formato MP4 unificando video y audio con FFmpeg.
    """
    if output_dir is None:
        output_dir = VIDEO_DOWNLOAD_DIR
    ensure_ffmpeg()
    abs_output_dir = os.path.abspath(output_dir)
    os.makedirs(abs_output_dir, exist_ok=True)

    format_selector = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    if quality == "1080p":
        format_selector = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]"
    elif quality == "720p":
        format_selector = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]"
    elif quality == "480p":
        format_selector = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]"
    elif quality == "360p":
        format_selector = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]"

    ydl_opts = {
        "format": format_selector,
        "outtmpl": os.path.join(abs_output_dir, "%(title).140B [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 2,
        "progress_hooks": [check_cancelled]
        + ([video_progress_hook] if track_progress else []),
        "postprocessor_hooks": [check_cancelled],
        "js_runtimes": youtube_js_runtimes(),
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

        video_id = info.get("id", "")
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

        video_path = download_youtube_video(
            params["url"], params.get("quality", "best")
        )

        size_bytes = os.path.getsize(video_path) if os.path.exists(video_path) else 0
        size_str = (
            f"{size_bytes / (1024 * 1024):.2f} MB"
            if size_bytes >= 1024 * 1024
            else f"{size_bytes / 1024:.2f} KB"
        )
        filename = os.path.basename(video_path)

        with state_lock:
            video_download_progress["status"] = "completed"
            video_download_progress["percent"] = 100
            video_download_progress["message"] = "Video descargado con éxito."
            video_download_progress["filename"] = filename
            video_download_progress["filepath"] = os.path.abspath(video_path).replace(
                "\\", "/"
            )
            video_download_progress["filesize"] = size_str

    except Exception as e:
        with state_lock:
            video_download_progress["status"] = "error"
            video_download_progress["percent"] = 100
            video_download_progress["message"] = (
                f"Error al descargar el video: {str(e)}"
            )


def download_audio(video_url, output_dir=None):
    """
    Descarga el audio de un video de YouTube u otra plataforma compatible
    y lo convierte a formato MP3.
    """
    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, "Descarga_audio_YT")
    ensure_ffmpeg()
    abs_output_dir = os.path.abspath(output_dir)
    os.makedirs(abs_output_dir, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(abs_output_dir, "%(title).140B [%(id)s].%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 2,
        "progress_hooks": [check_cancelled],
        "postprocessor_hooks": [check_cancelled],
        "js_runtimes": youtube_js_runtimes(),
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

        video_id = info.get("id", "")
        for f in os.listdir(abs_output_dir):
            if f.endswith(".mp3") and video_id and video_id in f:
                return os.path.abspath(os.path.join(abs_output_dir, f))

        return os.path.abspath(mp3_filename)


def download_raw_audio(video_url, output_dir):
    """
    Descarga el formato de mejor audio usando yt-dlp y retorna la ruta del archivo descargado
    y el título del video.
    """
    ensure_ffmpeg()
    abs_output_dir = os.path.abspath(output_dir)
    os.makedirs(abs_output_dir, exist_ok=True)
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(abs_output_dir, "%(title).140B [%(id)s].%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 2,
        "progress_hooks": [check_cancelled],
        "postprocessor_hooks": [check_cancelled],
        "js_runtimes": youtube_js_runtimes(),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            video_id = info.get("id", "")
            for f in os.listdir(abs_output_dir):
                if video_id and video_id in f:
                    filename = os.path.join(abs_output_dir, f)
                    break
        if not os.path.isfile(filename):
            raise FileNotFoundError(
                "La descarga no produjo un archivo de audio válido."
            )
        return os.path.abspath(filename), info.get("title", "audio_convertido")


def convert_to_mp3_ffmpeg(input_path, output_path, bitrate):
    """
    Convierte cualquier archivo de audio/video a MP3 usando FFmpeg con el bitrate especificado.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-acodec",
        "libmp3lame",
        "-ab",
        f"{bitrate}k",
        output_path,
    ]
    ensure_ffmpeg()
    run_ffmpeg(cmd)


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

        if source_type == "url":
            with state_lock:
                conversion_progress["status"] = "downloading"
                conversion_progress["percent"] = 20
                conversion_progress["message"] = (
                    "Descargando video/audio desde el enlace (puede tardar unos minutos)..."
                )
            input_path, title = download_raw_audio(params["url"], UPLOAD_DIR)
            temp_download_file = input_path

        elif source_type == "local_path":
            input_path = params["local_path"]
            if not os.path.exists(input_path):
                raise FileNotFoundError(
                    f"No se encontró el archivo local: {input_path}"
                )
            base_name = os.path.basename(input_path)
            title = os.path.splitext(base_name)[0]

        elif source_type == "upload":
            input_path = params["upload_path"]
            base_name = os.path.basename(input_path)
            title = os.path.splitext(base_name)[0]
            temp_download_file = input_path

        # Nombre de archivo MP3 seguro
        safe_title = "".join(
            [c if c.isalnum() or c in (" ", "_", "-") else "_" for c in title]
        )
        safe_title = safe_title.replace(" ", "_").strip("_")
        if not safe_title:
            safe_title = "audio_convertido"

        output_filename = f"{output_stem(safe_title)}_{bitrate}kbps.mp3"
        output_filepath = os.path.join(CONVERTED_DIR, output_filename)

        with state_lock:
            conversion_progress["status"] = "converting"
            conversion_progress["percent"] = 60
            conversion_progress["message"] = (
                f"Extrayendo y codificando audio a MP3 ({bitrate} kbps)..."
            )

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
        size_str = (
            f"{size_bytes / (1024 * 1024):.2f} MB"
            if size_bytes >= 1024 * 1024
            else f"{size_bytes / 1024:.2f} KB"
        )

        with state_lock:
            conversion_progress["status"] = "completed"
            conversion_progress["percent"] = 100
            conversion_progress["message"] = "Conversión completada con éxito."
            conversion_progress["filename"] = output_filename
            conversion_progress["filepath"] = os.path.abspath(output_filepath).replace(
                "\\", "/"
            )
            conversion_progress["filesize"] = size_str

    except Exception as e:
        if temp_download_file and os.path.exists(temp_download_file):
            try:
                os.remove(temp_download_file)
            except OSError:
                pass
        with state_lock:
            conversion_progress["status"] = "error"
            conversion_progress["percent"] = 100
            conversion_progress["message"] = f"Error en la conversión: {str(e)}"


def execution_thread_worker(source_type, params):
    """Transcribe con modelo reutilizable y guarda formatos y subtítulos."""
    options = normalize_options(params)
    event = job_events["transcription"]
    with state_lock:
        progress.update(
            model=options["model"],
            language=options["language"],
            transcription="",
            output_files={},
            warning="",
        )
    if source_type == "url":
        with state_lock:
            progress.update(percent=10, message="Descargando audio original...")
        audio_path, _ = download_raw_audio(
            params["url"], os.path.join(BASE_DIR, "Descarga_audio_YT")
        )
    else:
        audio_path = params.get("local_path") or params.get("upload_path")
    if not audio_path or not os.path.isfile(audio_path):
        raise ValueError("No se encontró el archivo de audio seleccionado.")
    check_cancelled()

    def update_status(message):
        with state_lock:
            if not event.is_set():
                progress.update(
                    percent=max(progress["percent"], message["percent"]),
                    message=message["message"],
                )

    result = inference_service.transcribe(audio_path, options, event, update_status)
    check_cancelled()
    with state_lock:
        if event.is_set():
            raise JobCancelled()
        output_files = save_transcription(OUTPUT_DIR, audio_path, options, result)
        message = (
            "Transcripción finalizada."
            if result["text"]
            else "No se detectó voz. Compruebe que el audio contenga habla audible."
        )
        progress.update(
            status="completed",
            percent=100,
            message=message,
            transcription=result["text"],
            output_dir=OUTPUT_DIR,
            output_files=output_files,
            language=result["language"],
            device=result["device"],
            compute_type=result["compute_type"],
            inference_seconds=round(result["inference_seconds"], 2),
            audio_seconds=round(result["duration"], 2),
            warning=result["warning"],
        )


@app.route("/")
def serve_index():
    """
    Redirección de la raíz del servidor al transcriptor web.
    """
    if os.path.exists(os.path.join(app.static_folder, "transcriptor.html")):
        return send_from_directory(app.static_folder, "transcriptor.html")
    elif os.path.exists(os.path.join(app.static_folder, "index.html")):
        return send_from_directory(app.static_folder, "index.html")
    return send_from_directory(app.static_folder, "transcriptor.html")


@app.route("/<path:path>")
def serve_static(path):
    """
    Servicio de archivos de frontend estáticos.
    """
    return send_from_directory(app.static_folder, path)


@app.route("/api/transcribe/cancel", methods=["POST"])
def api_cancel_transcription():
    """Detiene inferencia/descarga antes de permitir otra transcripción."""
    return cancel_job("transcription", progress, transcription_thread)


@app.route("/api/transcribe", methods=["POST"])
def api_start_transcription():
    """Valida la entrada y reserva una sola tarea, incluidos sus estados iniciales."""
    global transcription_thread
    data = request.form if "file" in request.files else request.get_json(silent=True)
    if not data or not isinstance(data, (dict, type(request.form))):
        return jsonify({"error": "Petición vacía o no válida."}), 400
    params = normalize_options(data)
    with state_lock:
        if transcription_thread and transcription_thread.is_alive():
            return jsonify(
                {
                    "error": "Ya hay una transcripción activa. Espere a que termine o se cancele."
                }
            ), 409
        if "file" in request.files:
            source_type = "upload"
            params["upload_path"] = save_upload(request.files["file"])
        else:
            source_type = data.get("source_type")
            if source_type == "url":
                url = data.get("url", "")
                if (
                    not isinstance(url, str)
                    or urlparse(url).scheme not in ("http", "https")
                    or not urlparse(url).netloc
                ):
                    raise ValueError("Debe ingresar una URL HTTP o HTTPS válida.")
                params["url"] = url
            elif source_type == "local_path":
                local_path = data.get("local_path", "")
                if not isinstance(local_path, str) or not Path(local_path).is_file():
                    raise ValueError("No se encontró el archivo local seleccionado.")
                params["local_path"] = str(Path(local_path).resolve())
            else:
                raise ValueError("Tipo de origen no soportado.")
        transcription_thread = make_job_thread(
            "transcription", execution_thread_worker, progress, (source_type, params)
        )
        transcription_thread.start()
    return jsonify({"status": "started"})


@app.route("/api/transcription/config")
def api_transcription_config():
    """Describe los modelos admitidos sin cargar pesos de inferencia."""
    return jsonify(
        {
            "engine": "faster-whisper",
            "models": list(MODELS),
            "default_model": "turbo",
            "default_language": "es",
            "default_device": "auto",
            "default_quality": "balanced",
        }
    )


@app.route("/api/transcriptions/<path:filename>")
def api_download_transcription(filename):
    """Descarga únicamente archivos de salida de transcripción."""
    return send_from_directory(OUTPUT_DIR, media_filename(filename), as_attachment=True)


@app.route("/api/files", methods=["GET"])
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
            if os.path.isfile(path) and f != ".gitkeep":
                size_bytes = os.path.getsize(path)
                # Formatear tamaño de forma legible
                size_str = (
                    f"{size_bytes / (1024 * 1024):.2f} MB"
                    if size_bytes >= 1024 * 1024
                    else f"{size_bytes / 1024:.2f} KB"
                )
                file_list.append(
                    {
                        "name": f,
                        "size": size_str,
                        "path": os.path.abspath(path).replace("\\", "/"),
                    }
                )
        return file_list

    return jsonify(
        {
            "yt_files": get_file_list(yt_dir),
            "uploaded_files": get_file_list(upload_dir),
            "mp3_files": get_file_list(mp3_dir),
            "video_files": get_file_list(video_dir),
            "trimmed_files": get_file_list(trimmed_dir),
            "merged_files": get_file_list(merged_dir),
        }
    )


@app.route("/api/files", methods=["DELETE"])
def api_delete_files():
    with state_lock:
        if any(
            thread is not None and thread.is_alive()
            for thread in (
                transcription_thread,
                conversion_thread,
                video_download_thread,
                trim_thread,
                merge_thread,
            )
        ):
            raise JobBusy(
                "Espere a que terminen las tareas antes de eliminar archivos."
            )
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Petición vacía."}), 400

    category = data.get("category")
    filename = data.get("filename")

    if category == "yt":
        target_dir = os.path.join(BASE_DIR, "Descarga_audio_YT")
    elif category == "upload":
        target_dir = os.path.join(BASE_DIR, "temp_uploads")
    elif category == "mp3":
        target_dir = os.path.join(BASE_DIR, "Convertidos_MP3")
    elif category == "video":
        target_dir = os.path.join(BASE_DIR, "Descarga_Videos_YT")
    elif category == "trimmed":
        target_dir = os.path.join(BASE_DIR, "Recortes_Archivos")
    elif category == "merged":
        target_dir = os.path.join(BASE_DIR, "Fusionados_Archivos")
    else:
        return jsonify(
            {
                "error": "Categoría inválida. Debe ser 'yt', 'upload', 'mp3', 'video', 'trimmed' o 'merged'."
            }
        ), 400

    # Eliminar un archivo específico
    if filename:
        filename = media_filename(filename)
        file_path = os.path.join(target_dir, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            try:
                os.remove(file_path)
                return jsonify(
                    {"status": "success", "message": f"Archivo '{filename}' eliminado."}
                )
            except Exception as e:
                return jsonify(
                    {"error": f"No se pudo eliminar el archivo: {str(e)}"}
                ), 500
        else:
            return jsonify({"error": f"Archivo no encontrado: {filename}"}), 404

    # Vaciar todo el directorio
    else:
        try:
            deleted_count = 0
            for f in os.listdir(target_dir):
                file_path = os.path.join(target_dir, f)
                if os.path.isfile(file_path) and f != ".gitkeep":
                    os.remove(file_path)
                    deleted_count += 1
            return jsonify(
                {
                    "status": "success",
                    "message": f"Se eliminaron {deleted_count} archivos de la carpeta.",
                }
            )
        except Exception as e:
            return jsonify({"error": f"Error al vaciar la carpeta: {str(e)}"}), 500


@app.route("/api/status", methods=["GET"])
def api_get_status():
    """
    Retorna el estado y avance actual del transcriptor.
    """
    with state_lock:
        return jsonify(progress)


@app.route("/api/convert/status", methods=["GET"])
def api_get_conversion_status():
    """
    Retorna el estado y avance actual del convertidor de MP3.
    """
    with state_lock:
        return jsonify(conversion_progress)


@app.route("/api/trim/status", methods=["GET"])
def api_get_trim_status():
    """
    Retorna el estado y avance del recortador multimedia.
    """
    with state_lock:
        return jsonify(trim_progress)


@app.route("/api/merge/status", methods=["GET"])
def api_get_merge_status():
    """
    Retorna el estado y avance del fusionador multimedia.
    """
    with state_lock:
        return jsonify(merge_progress)


@app.route("/api/merge/cancel", methods=["POST"])
def api_cancel_merge():
    """Solicita detener el trabajo y conserva su reserva hasta finalizar."""
    return cancel_job("merge", merge_progress, merge_thread)


@app.route("/api/merge", methods=["POST"])
def api_start_merge():
    """
    Endpoint para iniciar la fusión de múltiples archivos de audio/video.
    """
    global merge_progress, merge_thread

    with state_lock:
        if merge_thread and merge_thread.is_alive():
            if merge_thread and merge_thread.is_alive():
                return jsonify(
                    {"error": "Ya existe una tarea de fusión en curso."}
                ), 409
            else:
                merge_progress["status"] = "idle"

    file_paths = []
    out_format = "mp4"

    if request.files:
        out_format = request.form.get("format", "mp4")
        uploaded_files = request.files.getlist("files")
        if not uploaded_files:
            return jsonify({"error": "No se seleccionaron archivos para subir."}), 400

        for uf in uploaded_files:
            if uf.filename:
                save_path = save_upload(uf, "merge_")
                file_paths.append(save_path)
    else:
        data = request.get_json(silent=True)
        if not data or not data.get("paths"):
            return jsonify(
                {"error": "No se recibieron rutas de archivos para fusionar."}
            ), 400
        file_paths = data.get("paths", [])
        out_format = data.get("format", "mp4")

    if len(file_paths) < 2:
        return jsonify(
            {"error": "Se requieren al menos 2 archivos para realizar la fusión."}
        ), 400

    with state_lock:
        merge_thread = make_job_thread(
            "merge", merge_thread_worker, merge_progress, (file_paths, out_format)
        )
        merge_thread.start()
    return jsonify({"status": "started"})


@app.route("/api/merge/file/<path:filename>", methods=["GET"])
def api_serve_merged_file(filename):
    """
    Endpoint para descargar un archivo fusionado.
    """
    filename = media_filename(filename)
    return send_from_directory(MERGED_DIR, filename, as_attachment=True)


@app.route("/api/trim/cancel", methods=["POST"])
def api_cancel_trim():
    """Solicita detener el trabajo y conserva su reserva hasta finalizar."""
    return cancel_job("trim", trim_progress, trim_thread)


@app.route("/api/trim", methods=["POST"])
def api_start_trim():
    """
    Endpoint para iniciar el recorte de audio/video.
    """
    global trim_progress, trim_thread

    with state_lock:
        if trim_thread and trim_thread.is_alive():
            if trim_thread and trim_thread.is_alive():
                return jsonify(
                    {"error": "Ya existe una tarea de recorte en curso."}
                ), 409
            else:
                trim_progress["status"] = "idle"

    if "file" in request.files:
        uploaded_file = request.files["file"]
        start_time = request.form.get("start_time", "0")
        end_time = request.form.get("end_time", "0")
        out_format = request.form.get("format", "mp4")

        if uploaded_file.filename == "":
            return jsonify({"error": "Archivo de subida no válido."}), 400

        upload_path = save_upload(uploaded_file)

        params = {
            "upload_path": upload_path,
            "start_time": start_time,
            "end_time": end_time,
            "format": out_format,
        }
        with state_lock:
            trim_thread = make_job_thread(
                "trim", trim_thread_worker, trim_progress, ("upload", params)
            )
            trim_thread.start()
        return jsonify({"status": "started"})

    else:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Datos de petición vacíos."}), 400

        source_type = data.get("source_type")
        start_time = data.get("start_time", "0")
        end_time = data.get("end_time", "0")
        out_format = data.get("format", "mp4")

        params = {"start_time": start_time, "end_time": end_time, "format": out_format}

        if source_type == "url":
            params["url"] = data.get("url")
            if not params["url"]:
                return jsonify({"error": "Debe ingresar una URL válida."}), 400
        elif source_type == "local_path":
            params["local_path"] = data.get("local_path")
            if not params["local_path"]:
                return jsonify(
                    {"error": "Debe especificar la ruta absoluta local."}
                ), 400
        else:
            return jsonify({"error": "Tipo de origen no especificado."}), 400

        with state_lock:
            trim_thread = make_job_thread(
                "trim", trim_thread_worker, trim_progress, (source_type, params)
            )
            trim_thread.start()
        return jsonify({"status": "started"})


@app.route("/api/trim/file/<path:filename>", methods=["GET"])
def api_serve_trimmed_file(filename):
    """
    Endpoint para descargar un archivo recortado.
    """
    filename = media_filename(filename)
    return send_from_directory(TRIMMED_DIR, filename, as_attachment=True)


@app.route("/api/download/mp3/<filename>", methods=["GET"])
def api_download_mp3(filename):
    """
    Endpoint para descargar un MP3 convertido.
    """
    # secure_filename para evitar path traversal
    filename = media_filename(filename)
    return send_from_directory(CONVERTED_DIR, filename, as_attachment=True)


@app.route("/api/convert", methods=["POST"])
def api_start_conversion():
    """
    Endpoint para iniciar el proceso de conversión a MP3.
    """
    global conversion_progress, conversion_thread

    with state_lock:
        if conversion_thread and conversion_thread.is_alive():
            if conversion_thread and conversion_thread.is_alive():
                return jsonify(
                    {"error": "Ya existe una tarea de conversión en curso."}
                ), 409
            else:
                conversion_progress["status"] = "idle"

    if "file" in request.files:
        uploaded_file = request.files["file"]
        bitrate_str = request.form.get("bitrate", "192")
        try:
            bitrate = int(bitrate_str)
            if not (124 <= bitrate <= 332):
                raise ValueError()
        except ValueError:
            return jsonify(
                {"error": "El bitrate debe ser un número entero entre 124 y 332."}
            ), 400

        if uploaded_file.filename == "":
            return jsonify({"error": "Archivo de subida no válido."}), 400

        upload_path = save_upload(uploaded_file)

        params = {"upload_path": upload_path, "bitrate": bitrate}
        with state_lock:
            conversion_thread = make_job_thread(
                "conversion",
                conversion_thread_worker,
                conversion_progress,
                ("upload", params),
            )
            conversion_thread.start()
        return jsonify({"status": "started"})

    else:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Datos de petición vacíos."}), 400

        source_type = data.get("source_type")
        bitrate_str = data.get("bitrate", "192")
        try:
            bitrate = int(bitrate_str)
            if not (124 <= bitrate <= 332):
                raise ValueError()
        except ValueError:
            return jsonify(
                {"error": "El bitrate debe ser un número entero entre 124 y 332."}
            ), 400

        params = {"bitrate": bitrate}

        if source_type == "url":
            params["url"] = data.get("url")
            if not params["url"]:
                return jsonify({"error": "Debe ingresar una URL válida."}), 400
        elif source_type == "local_path":
            params["local_path"] = data.get("local_path")
            if not params["local_path"]:
                return jsonify(
                    {"error": "Debe especificar la ruta absoluta local."}
                ), 400
        else:
            return jsonify(
                {"error": "Tipo de origen no especificado o no soportado."}
            ), 400

        with state_lock:
            conversion_thread = make_job_thread(
                "conversion",
                conversion_thread_worker,
                conversion_progress,
                (source_type, params),
            )
            conversion_thread.start()
        return jsonify({"status": "started"})


@app.route("/api/download_video/status", methods=["GET"])
def api_get_video_download_status():
    """
    Retorna el estado y avance actual del descargador de videos de YouTube.
    """
    with state_lock:
        return jsonify(video_download_progress)


@app.route("/api/download_video/cancel", methods=["POST"])
def api_cancel_video_download():
    """Solicita detener el trabajo y conserva su reserva hasta finalizar."""
    return cancel_job("video_download", video_download_progress, video_download_thread)


@app.route("/api/download_video", methods=["POST"])
def api_start_video_download():
    """
    Endpoint para iniciar el proceso de descarga de video de YouTube.
    """
    global video_download_progress, video_download_thread
    data = request.get_json(silent=True)
    if not data or not data.get("url"):
        return jsonify({"error": "Debe ingresar una URL válida de YouTube."}), 400

    with state_lock:
        if video_download_thread and video_download_thread.is_alive():
            if video_download_thread and video_download_thread.is_alive():
                return jsonify(
                    {"error": "Ya existe una descarga de video activa en curso."}
                ), 409
            else:
                video_download_progress["status"] = "idle"

    params = {"url": data.get("url"), "quality": data.get("quality", "best")}

    with state_lock:
        video_download_thread = make_job_thread(
            "video_download", video_download_worker, video_download_progress, (params,)
        )
        video_download_thread.start()
    return jsonify({"status": "started"})


@app.route("/api/download_video/file/<path:filename>", methods=["GET"])
def api_serve_downloaded_video_file(filename):
    """
    Endpoint para descargar el archivo MP4 generado.
    """
    filename = media_filename(filename)
    return send_from_directory(VIDEO_DOWNLOAD_DIR, filename, as_attachment=True)


@app.route("/api/save_tex", methods=["POST"])
def api_save_tex():
    """Exporta LaTeX escapando texto, porcentajes y rutas."""
    data = request.get_json(silent=True)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("transcription"), str)
        or not data["transcription"].strip()
    ):
        raise ValueError("No se proporcionó contenido de transcripción.")
    source = str(data.get("source", "Audio"))
    filename = output_stem(source) + ".tex"
    content = render_latex(
        data["transcription"],
        source,
        data.get("model", "turbo"),
        data.get("language", "es"),
    )
    path = Path(OUTPUT_DIR) / filename
    path.write_text(content, encoding="utf-8")
    return jsonify(status="success", path=str(path), filename=filename, content=content)


@app.route("/api/save_md", methods=["POST"])
def api_save_md():
    """Guarda Markdown sin sobrescribir exportaciones anteriores."""
    data = request.get_json(silent=True)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("transcription"), str)
        or not data["transcription"].strip()
    ):
        raise ValueError("No se proporcionó contenido de transcripción.")
    source = str(data.get("source", "Audio"))
    filename = output_stem(source) + ".md"
    content = (
        "# Transcripción de audio — AudioScribe\n\n"
        f"- **Origen:** {source}\n"
        f"- **Modelo:** {data.get('model', 'turbo')}\n"
        f"- **Idioma:** {data.get('language', 'es')}\n\n"
        f"## Transcripción\n\n{data['transcription']}\n"
    )
    path = Path(OUTPUT_DIR) / filename
    path.write_text(content, encoding="utf-8")
    return jsonify(status="success", path=str(path), filename=filename, content=content)


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Conexión ficticia a DNS de Google para determinar la IP del adaptador de red activo
        s.connect(("8.8.8.8", 80))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()
    return IP


def start_server():
    local_ip = get_ip()
    port = int(os.environ.get("AUDIOSCRIBE_PORT", "5000"))
    host = os.environ.get("AUDIOSCRIBE_HOST", "127.0.0.1")
    max_attempts = 10

    # Buscar un puerto libre a partir del 5000
    for attempt in range(max_attempts):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((host, port))
            s.close()
            break
        except OSError:
            print(
                f"[INFO] Puerto {port} ocupado, intentando con el puerto {port + 1}..."
            )
            port += 1

    local_url = f"http://localhost:{port}/transcriptor.html"
    wifi_url = f"http://{local_ip}:{port}/transcriptor.html"

    print("\n" + "=" * 70)
    print("           SERVIDOR FLASK INICIADO CON EXITO")
    print("=" * 70)
    print("  Acceso en esta Computadora:")
    print(f"    --> Dashboard:  {local_url}")
    print(f"    --> Inicio:     http://localhost:{port}/")
    print()
    if host == "0.0.0.0":
        print("  Acceso desde otros dispositivos de la red local:")
        print(f"    --> Dashboard: {wifi_url}")
    else:
        print("  Acceso local. AUDIOSCRIBE_HOST=0.0.0.0 habilita la red local.")
    print("=" * 70)
    print("  Presiona Ctrl+C en esta consola para apagar el servidor.")
    print("=" * 70 + "\n")

    # Abrir URL automáticamente en el navegador por defecto
    try:
        if os.environ.get("AUDIOSCRIBE_NO_BROWSER") != "1":
            webbrowser.open(local_url)
    except Exception as e:
        print(f"No se pudo abrir el navegador automaticamente: {e}")

    # Iniciar Flask en la interfaz elegida por el usuario.
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    start_server()
