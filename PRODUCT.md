# AudioScribe - Documento de Producto

## Resumen Ejecutivo
**AudioScribe** es una suite multimedia integral diseñada para la transcripción avanzada de voz mediante inteligencia artificial (OpenAI Whisper), descarga y conversión de medios de YouTube, edición básica de audio/video (recorte y fusión) y generación automatizada de reportes en múltiples formatos (.txt, .md, .tex).

## Capacidades Principales
1. **Transcriptor IA**: Transcripción multilingüe con detección automática de idioma, selector de modelos Whisper (`tiny`, `base`, `small`, `medium`, `large`), marcas de tiempo y exportación directa.
2. **Descarga de Videos**: Extracción de videos de YouTube en formato MP4 con selección de resoluciones hasta 1080p+.
3. **Conversión a MP3**: Extracción de pistas de audio y compresión en MP3 con bitrates configurables (hasta 320 kbps).
4. **Recortador Multimedia**: Corte preciso de segmentos de audio o video mediante marcas de tiempo (`HH:MM:SS` o `MM:SS`).
5. **Fusionador Multimedia**: Concatenación de múltiples pistas de audio o video con interfaz interactiva para reordenar elementos.
6. **Sistema de Cola por Lotes**: Procesamiento secuencial automatizado para enlaces de YouTube y subidas múltiples de archivos.
7. **Accesibilidad y Feedback**: Reproductor TTS integrado, analizador de texto (métricas y palabras clave) y notificaciones auditivas vía Web Audio API.
