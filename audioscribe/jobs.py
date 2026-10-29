"""Cancelación cooperativa de descargas y terminación de procesos FFmpeg."""

import subprocess
import threading
from pathlib import Path

from audioscribe.transcription import JobCancelled

_context = threading.local()


def check_cancelled(_progress=None):
    """Funciona también como hook de yt-dlp dentro del hilo de una tarea."""
    event = getattr(_context, "cancel_event", None)
    if event is not None and event.is_set():
        raise JobCancelled()


def run_job(worker, state, lock, event, *args):
    """Publica cancelación solo después de detener el trabajo correspondiente."""
    _context.cancel_event = event
    try:
        check_cancelled()
        worker(*args)
        check_cancelled()
    except JobCancelled:
        with lock:
            state.update(
                status="idle", percent=0, message="Tarea cancelada por el usuario."
            )
            if "transcription" in state:
                state["transcription"] = ""
    except Exception as error:
        with lock:
            state.update(status="error", percent=100, message=str(error))
    finally:
        _context.cancel_event = None


def run_ffmpeg(command):
    """Espera sin bloquear la cancelación y elimina una salida incompleta."""
    check_cancelled()
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        while True:
            check_cancelled()
            try:
                _, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError(f"FFmpeg: {stderr[-2500:]}")
    except JobCancelled:
        process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        Path(command[-1]).unlink(missing_ok=True)
        raise
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
