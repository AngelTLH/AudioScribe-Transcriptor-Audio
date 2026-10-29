"""Inferencia local reutilizable, con progreso y cancelación real en Windows."""

import atexit
import ctypes
import gc
import multiprocessing
import os
import sysconfig
import threading
import time
from pathlib import Path
from queue import Empty

MODELS = ("tiny", "base", "small", "medium", "large-v3", "turbo")
LANGUAGES = set(
    "auto es en fr de it pt ja zh ko ar ru ca gl eu nl pl uk hi tr sv fi da no cs el he id vi th ro hu fa ur ta te la cy af sw ms bn sr hr sk sl lt lv et mk bg az hy ka ne si km lo my bo mn ps sd gu mr pa zu yo ha so tl mt is mi sa tt uz kk be bs sq am as ba br fo haw ht lb ln mg oc sn su tk yi yue".split()
)
_DLL_HANDLES = []


class JobCancelled(BaseException):
    """Interrumpe también bibliotecas que capturan Exception internamente."""


def normalize_options(data):
    """Valida parámetros antes de reservar recursos o descargar modelos."""
    model = data.get("model", "turbo")
    model = "large-v3" if model == "large" else model
    language = data.get("language", "es")
    device = data.get("device", "auto")
    quality = data.get("quality", "balanced")
    prompt = data.get("initial_prompt", "")
    if not all(isinstance(value, str) for value in (model, language, device, quality)):
        raise ValueError("Los parámetros de transcripción deben ser texto.")
    if model not in MODELS:
        raise ValueError("Modelo no válido.")
    if language not in LANGUAGES:
        raise ValueError("Idioma no válido.")
    if device not in ("auto", "cpu", "cuda"):
        raise ValueError("Dispositivo no válido.")
    if quality not in ("fast", "balanced", "accurate"):
        raise ValueError("Perfil de calidad no válido.")
    if not isinstance(prompt, str) or len(prompt) > 1000:
        raise ValueError("El glosario debe contener hasta 1000 caracteres.")
    return dict(
        model=model,
        language=language,
        device=device,
        quality=quality,
        initial_prompt=prompt.strip(),
    )


def configure_cuda_paths():
    """Registra las DLL de NVIDIA instaladas dentro del entorno virtual."""
    if os.name != "nt" or _DLL_HANDLES:
        return
    site = Path(sysconfig.get_path("purelib"))
    candidates = [
        site / "nvidia" / name / "bin" for name in ("cublas", "cudnn", "cuda_runtime")
    ]
    for directory in candidates:
        if directory.is_dir():
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ["PATH"]
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))


def detect_device(requested="auto"):
    """Comprueba GPU y bibliotecas CUDA; auto conserva un respaldo en CPU."""
    if requested == "cpu":
        return "cpu"
    configure_cuda_paths()
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            raise RuntimeError("No se detectó una GPU NVIDIA compatible.")
        if os.name == "nt":
            ctypes.WinDLL("cublas64_12.dll")
            ctypes.WinDLL("cudnn64_9.dll")
        return "cuda"
    except (ImportError, OSError, RuntimeError) as error:
        if requested == "cuda":
            raise RuntimeError(
                "GPU no disponible. Instale requirements-gpu.txt "
                "o seleccione Automático/CPU."
            ) from error
        return "cpu"


def _transcribe(model, audio_path, options, output, device):
    """Consume el generador completo y publica el avance por segmentos."""
    started = time.perf_counter()
    fast = options["quality"] == "fast"
    segments, info = model.transcribe(
        audio_path,
        language=None if options["language"] == "auto" else options["language"],
        task="transcribe",
        beam_size=1 if fast else 5,
        best_of=1 if fast else 5,
        patience=1.5 if options["quality"] == "accurate" else 1.0,
        temperature=0.0 if fast else (0.0, 0.2, 0.4),
        condition_on_previous_text=False,
        initial_prompt=options["initial_prompt"] or None,
        vad_filter=True,
        vad_parameters=dict(
            threshold=0.45, min_silence_duration_ms=500, speech_pad_ms=400
        ),
    )
    collected = []
    for segment in segments:
        collected.append(
            dict(start=segment.start, end=segment.end, text=segment.text.strip())
        )
        percent = min(95, 35 + int(60 * segment.end / max(info.duration, 1)))
        output.put(
            dict(
                type="progress",
                percent=percent,
                message=f"Transcribiendo: {segment.end:.0f} / "
                f"{info.duration:.0f} segundos ({device.upper()}).",
            )
        )
    return dict(
        text="\n".join(s["text"] for s in collected if s["text"]),
        segments=collected,
        language=info.language,
        language_probability=info.language_probability,
        duration=info.duration,
        speech_duration=info.duration_after_vad,
        inference_seconds=time.perf_counter() - started,
        device=device,
        compute_type="int8_float16" if device == "cuda" else "int8",
    )


def _worker_main(incoming, outgoing):
    """Conserva un solo modelo en memoria entre archivos consecutivos."""
    configure_cuda_paths()
    from faster_whisper import WhisperModel

    cached_key = None
    cached_model = None
    while True:
        request = incoming.get()
        if request is None:
            return
        options = request["options"]
        try:
            device = detect_device(options["device"])
            model_name = (
                "large-v3-turbo" if options["model"] == "turbo" else options["model"]
            )
            warning = ""
            for attempt in range(2):
                try:
                    key = (model_name, device)
                    if cached_key != key:
                        cached_model = None
                        cached_key = None
                        gc.collect()
                        outgoing.put(
                            dict(
                                type="progress",
                                percent=25,
                                message=f"Cargando {options['model']} en {device.upper()}. "
                                "La primera vez se descargan sus pesos.",
                            )
                        )
                        cached_model = WhisperModel(
                            model_name,
                            device=device,
                            compute_type="int8_float16" if device == "cuda" else "int8",
                            cpu_threads=min(6, os.cpu_count() or 4),
                            num_workers=1,
                        )
                        cached_key = key
                    outgoing.put(
                        dict(
                            type="progress",
                            percent=35,
                            message="Detectando voz y omitiendo silencios...",
                        )
                    )
                    result = _transcribe(
                        cached_model, request["path"], options, outgoing, device
                    )
                    result["warning"] = warning
                    outgoing.put(dict(type="result", result=result))
                    break
                except RuntimeError as error:
                    gpu_error = any(
                        term in str(error).lower()
                        for term in (
                            "cuda",
                            "cudnn",
                            "cublas",
                            "out of memory",
                            "allocation",
                        )
                    )
                    if (
                        device != "cuda"
                        or options["device"] != "auto"
                        or not gpu_error
                        or attempt
                    ):
                        raise
                    device = "cpu"
                    warning = "La GPU no pudo completar el proceso; se utilizó CPU."
                    outgoing.put(dict(type="progress", percent=25, message=warning))
        except Exception as error:
            outgoing.put(dict(type="error", message=str(error)))


class InferenceService:
    """Aísla inferencia para poder terminarla sin hilos ni resultados huérfanos."""

    def __init__(self, worker_target=None):
        """Permite sustituir el proceso de inferencia durante pruebas."""
        self._context = multiprocessing.get_context("spawn")
        self._target = worker_target or _worker_main
        self._lock = threading.Lock()
        self._process = None
        self._incoming = None
        self._outgoing = None
        atexit.register(self.close)

    def close(self):
        """Termina el proceso y libera colas; se invoca al cancelar o salir."""
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=3)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=3)
            self._process.close()
            self._process = None
        for queue in (self._incoming, self._outgoing):
            if queue is not None:
                queue.cancel_join_thread()
                queue.close()
        self._incoming = self._outgoing = None

    def transcribe(self, path, options, cancel_event, on_progress):
        """Ejecuta una tarea, conservando el modelo hasta cambiarlo o cancelar."""
        with self._lock:
            if cancel_event.is_set():
                raise JobCancelled()
            if self._process is None or not self._process.is_alive():
                self.close()
                self._incoming = self._context.Queue()
                self._outgoing = self._context.Queue()
                self._process = self._context.Process(
                    target=self._target,
                    args=(self._incoming, self._outgoing),
                    daemon=True,
                )
                self._process.start()
            self._incoming.put(dict(path=str(path), options=options))
            while True:
                if cancel_event.is_set():
                    self.close()
                    raise JobCancelled()
                try:
                    message = self._outgoing.get(timeout=0.2)
                except Empty:
                    if not self._process.is_alive():
                        code = self._process.exitcode
                        self.close()
                        raise RuntimeError(
                            f"El proceso de transcripción terminó ({code})."
                        )
                    continue
                if message["type"] == "progress":
                    on_progress(message)
                elif message["type"] == "result":
                    return message["result"]
                else:
                    raise RuntimeError(message["message"])
