"""Regresiones de concurrencia, cancelación, exportación y validación."""

import io
import os
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import serve_dashboard as server
from audioscribe.exports import latex_escape, save_transcription, subtitle_timestamp
from audioscribe.jobs import run_ffmpeg, run_job
from audioscribe.transcription import InferenceService, JobCancelled, normalize_options


def test_audio_decoder_accepts_a_real_wav():
    """Detecta incompatibilidades reales entre faster-whisper y PyAV."""
    from faster_whisper.audio import decode_audio

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)
    buffer.seek(0)
    samples = decode_audio(buffer, sampling_rate=16000)
    assert len(samples) == 16000
    assert not samples.any()


def sample_result():
    """Entrega datos con caracteres que antes rompían el reporte LaTeX."""
    return dict(
        text="El 50% usa A_B & C #1.",
        language="es",
        device="cpu",
        compute_type="int8",
        language_probability=1.0,
        inference_seconds=0.1,
        duration=10,
        speech_duration=8,
        segments=[dict(start=0.25, end=2.75, text="El 50% usa A_B & C #1.")],
        warning="",
    )


def echo_worker(incoming, outgoing):
    """Proceso ligero para comprobar aislamiento sin descargar modelos."""
    while True:
        request = incoming.get()
        if request is None:
            return
        if request["path"] == "block":
            time.sleep(60)
        outgoing.put(dict(type="result", result={"pid": os.getpid()}))


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Aísla las pruebas del historial real y de cualquier audio del usuario."""
    for variable in (
        "OUTPUT_DIR",
        "UPLOAD_DIR",
        "CONVERTED_DIR",
        "MERGED_DIR",
        "TRIMMED_DIR",
        "VIDEO_DOWNLOAD_DIR",
    ):
        folder = tmp_path / variable
        folder.mkdir()
        monkeypatch.setattr(server, variable, str(folder))
    for variable in (
        "transcription_thread",
        "conversion_thread",
        "trim_thread",
        "merge_thread",
        "video_download_thread",
    ):
        monkeypatch.setattr(server, variable, None)
    monkeypatch.setattr(
        server, "job_events", {name: threading.Event() for name in server.job_events}
    )
    monkeypatch.setattr(server, "progress", {"status": "idle", "percent": 0})
    monkeypatch.setattr(
        server.inference_service, "transcribe", lambda *_args: sample_result()
    )
    server.app.config["TESTING"] = True
    yield server.app.test_client()
    for variable in (
        "transcription_thread",
        "conversion_thread",
        "trim_thread",
        "merge_thread",
        "video_download_thread",
    ):
        thread = getattr(server, variable)
        if thread:
            for event in server.job_events.values():
                event.set()
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_exports_do_not_overwrite_and_escape_latex(tmp_path):
    options = normalize_options({})
    first = save_transcription(tmp_path, "grabación.mp3", options, sample_result())
    second = save_transcription(tmp_path, "grabación.mp3", options, sample_result())
    assert set(first.values()).isdisjoint(second.values())
    assert len(list(tmp_path.iterdir())) == 10
    tex = (tmp_path / first["tex"]).read_text(encoding="utf-8")
    assert r"50\%" in tex and r"A\_B \& C \#1" in tex
    assert "00:00:00,250 --> 00:00:02,750" in (tmp_path / first["srt"]).read_text()
    assert (tmp_path / first["vtt"]).read_text().startswith("WEBVTT\n")
    assert latex_escape(r"\input{x}") == r"\textbackslash{}input\{x\}"
    assert subtitle_timestamp(3599.9996) == "01:00:00,000"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"model": "unknown"},
        {"language": []},
        {"model": {}},
        {"device": "bad"},
        {"quality": "bad"},
        {"initial_prompt": "a" * 1001},
        {"source_type": "local_path", "local_path": "missing"},
        {"source_type": "url", "url": "file:///etc/passwd"},
    ],
)
def test_bad_requests_are_rejected_before_start(client, payload):
    response = client.post("/api/transcribe", json=payload)
    assert response.status_code == 400
    assert "error" in response.json
    assert server.transcription_thread is None


def test_same_upload_name_keeps_both_inputs(client):
    for content in (b"first audio", b"second audio"):
        response = client.post(
            "/api/transcribe",
            data={
                "file": (io.BytesIO(content), "grabacion.wav"),
                "model": "small",
                "language": "es",
                "device": "cpu",
            },
        )
        assert response.status_code == 200
        server.transcription_thread.join(timeout=5)
        assert server.progress["status"] == "completed"
    files = list(Path(server.UPLOAD_DIR).iterdir())
    assert len(files) == 2
    assert {path.read_bytes() for path in files} == {b"first audio", b"second audio"}
    assert len(list(Path(server.OUTPUT_DIR).iterdir())) == 10


def test_cancel_stops_job_and_blocks_competing_requests(client, monkeypatch, tmp_path):
    entered = threading.Event()

    def blocked(_path, _options, event, _update):
        entered.set()
        event.wait(timeout=10)
        raise JobCancelled()

    monkeypatch.setattr(server.inference_service, "transcribe", blocked)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"test")
    payload = dict(source_type="local_path", local_path=str(audio))
    barrier = threading.Barrier(2)

    def start():
        barrier.wait()
        with server.app.test_client() as independent_client:
            return independent_client.post("/api/transcribe", json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: start(), range(2))) == [200, 409]
    assert entered.wait(timeout=3)
    assert client.delete("/api/files", json={"category": "upload"}).status_code == 409
    assert client.post("/api/transcribe/cancel").json["status"] == "cancelling"
    server.transcription_thread.join(timeout=5)
    assert not server.transcription_thread.is_alive()
    assert client.get("/api/status").json["status"] == "idle"
    assert not list(Path(server.OUTPUT_DIR).iterdir())
    monkeypatch.setattr(
        server.inference_service, "transcribe", lambda *_args: sample_result()
    )
    assert client.post("/api/transcribe", json=payload).status_code == 200
    server.transcription_thread.join(timeout=5)
    assert server.progress["status"] == "completed"


def test_inference_process_is_reused_and_terminated_on_cancel():
    service = InferenceService(worker_target=echo_worker)
    event = threading.Event()
    try:
        first = service.transcribe("first", {}, event, lambda _: None)
        assert service.transcribe("second", {}, event, lambda _: None) == first
        cancelled = threading.Event()

        def run():
            try:
                service.transcribe("block", {}, event, lambda _: None)
            except JobCancelled:
                cancelled.set()

        thread = threading.Thread(target=run)
        thread.start()
        time.sleep(0.3)
        event.set()
        thread.join(timeout=8)
        assert cancelled.is_set() and not thread.is_alive()
        assert service._process is None
        event.clear()
        assert (
            service.transcribe("new", {}, event, lambda _: None)["pid"] != first["pid"]
        )
    finally:
        service.close()


def test_ffmpeg_cancel_terminates_the_subprocess(tmp_path):
    event = threading.Event()
    state = {}
    output = tmp_path / "partial.mp3"
    output.write_bytes(b"partial")
    command = [sys.executable, "-c", "import time; time.sleep(60)", str(output)]
    thread = threading.Thread(
        target=run_job,
        args=(lambda: run_ffmpeg(command), state, threading.Lock(), event),
    )
    thread.start()
    time.sleep(0.3)
    event.set()
    thread.join(timeout=8)
    assert not thread.is_alive() and state["status"] == "idle"
    assert not output.exists()


def test_unicode_download_names_and_traversal(client):
    filename = "reunión miércoles.srt"
    (Path(server.OUTPUT_DIR) / filename).write_text("subtitles", encoding="utf-8")
    assert client.get("/api/transcriptions/" + filename).data == b"subtitles"
    assert client.get("/api/transcriptions/../requirements.txt").status_code == 400


@pytest.mark.parametrize("timestamp", ["abc", "-1", "NaN", "inf", "00:80", "1:2:3:4"])
def test_invalid_trim_times_are_rejected(timestamp):
    with pytest.raises(ValueError):
        server.parse_time_to_seconds(timestamp)


def test_mp4_trim_url_keeps_the_video_track(client, monkeypatch, tmp_path):
    """El recortador MP4 antes descargaba solo audio de una URL."""
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video with audio")
    called = []

    def video_download(url, **kwargs):
        called.append(url)
        return str(source)

    def unexpected_audio(*_args):
        raise AssertionError("Una salida MP4 requiere descargar video.")

    monkeypatch.setattr(server, "download_youtube_video", video_download)
    monkeypatch.setattr(server, "download_raw_audio", unexpected_audio)
    monkeypatch.setattr(
        server,
        "trim_media_ffmpeg",
        lambda _input, output, *_args: Path(output).write_bytes(b"mp4"),
    )
    server.trim_thread_worker(
        "url",
        dict(
            url="https://example.org/video", format="mp4", start_time="0", end_time="1"
        ),
    )
    assert called == ["https://example.org/video"]
    assert server.trim_progress["status"] == "completed"
