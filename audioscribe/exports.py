"""Exportación segura, subtítulos y nombres sin sobrescrituras."""

import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def output_stem(source):
    """Incluye fecha y sufijo aleatorio para conservar ejecuciones anteriores."""
    source = Path(str(source).replace("\\", "/")).stem
    source = re.sub(r"[^\w-]+", "_", source, flags=re.UNICODE).strip("_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{(source or 'transcripcion')[:100]}_{stamp}_{uuid4().hex[:6]}"


def latex_escape(value):
    """Escapa caracteres de texto sin alterar comandos de la plantilla."""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in str(value))


def render_latex(text, source, model, language):
    """Genera un documento LaTeX autónomo que admite texto transcrito libre."""
    return (
        "\\documentclass[12pt,letterpaper]{article}\n"
        "\\usepackage[utf8]{inputenc}\n\\usepackage[T1]{fontenc}\n"
        "\\usepackage[spanish]{babel}\n\\usepackage[margin=1in]{geometry}\n"
        "\\title{Transcripción de audio}\n\\author{AudioScribe}\n"
        "\\date{\\today}\n\\begin{document}\n\\maketitle\n"
        "\\section*{Detalles del procesamiento}\n"
        f"Origen: {latex_escape(source)}\\\\\n"
        f"Modelo: {latex_escape(model)}\\\\\n"
        f"Idioma: {latex_escape(language)}\n"
        "\\section*{Transcripción}\n"
        + latex_escape(text).replace("\n", "\n\n")
        + "\n\\end{document}\n"
    )


def subtitle_timestamp(seconds, separator=","):
    """Convierte segundos a marcas de subtítulos sin perder milisegundos."""
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{millis:03}"


def save_transcription(directory, source, options, result):
    """Guarda texto, Markdown, LaTeX y subtítulos de una misma transcripción."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = output_stem(source)
    text = result["text"]
    markdown = (
        f"# Transcripción de audio — AudioScribe\n\n"
        f"- **Origen:** {Path(source).name}\n"
        f"- **Modelo:** {options['model']}\n"
        f"- **Idioma detectado/seleccionado:** {result['language']}\n"
        f"- **Procesamiento:** {result['device'].upper()}\n\n"
        f"## Transcripción\n\n{text}\n"
    )
    outputs = {
        "txt": text,
        "md": markdown,
        "tex": render_latex(
            text, Path(source).name, options["model"], result["language"]
        ),
    }
    for extension, separator in (("srt", ","), ("vtt", ".")):
        blocks = []
        for index, segment in enumerate(result["segments"], 1):
            start = subtitle_timestamp(segment["start"], separator)
            end = subtitle_timestamp(segment["end"], separator)
            caption = segment["text"].replace("-->", "→")
            blocks.append(f"{index}\n{start} --> {end}\n{caption}\n")
        outputs[extension] = ("WEBVTT\n\n" if extension == "vtt" else "") + "\n".join(
            blocks
        )
    filenames = {}
    for extension, content in outputs.items():
        filename = f"{stem}.{extension}"
        (directory / filename).write_text(content, encoding="utf-8")
        filenames[extension] = filename
    return filenames
