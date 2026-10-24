# Benchmark Windows de arranque ligero (no certificación del notebook)

El workflow `Windows Lite Startup Memory & Latency Gate` mide tres procesos
Windows independientes que precargan el **modelo real faster-whisper/base**
mediante la misma función `transcription.whisper_transcriber._get_model`
utilizada por JARVIS. El modelo se descarga **fuera de la ventana medida**,
se carga desde disco con `HF_HUB_OFFLINE=1` y se registra el SHA-256 de
`model.bin` y el commit de Hugging Face resuelto al comenzar la campaña.

Cada proceso aplica la política AUTO de 4 GiB totales y 2 GiB disponibles
**simulados como parámetros**, y ejecuta `warm_voice_models` de producción.
Debe cargar Whisper exactamente una vez y dejar Piper sin precargar. El
proceso padre mide con `psutil` el pico aproximado de RSS cada 25 ms,
y el tiempo de arranque del proceso y finalización de precarga de Whisper.

## Presupuestos fijados antes de la primera medición

- 3 procesos nuevos y completos; cualquier fallo impide aprobar.
- Pico individual RSS <= **1536 MiB**.
- P95 de precarga de Whisper <= **90 segundos**.
- P95 de tiempo total del proceso <= **105 segundos**.
- El valor P95 para tres muestras se define por el máximo de las tres:
  conservador, pero no constituye estimación estadística de P95 real.
- El resultado se marca NOT_CERTIFIED si se omite un proceso, falla la
  inferencia, cambia el modelo durante la ejecución, falta telemetría o
  se supera un presupuesto. No hay umbrales ajustados durante la ejecución.

**Interpretación responsable:** son mediciones del proceso Python/Whisper en
un runner Windows de GitHub, que dispone de más de 4 GiB físicos. No son
mediciones de la app instalada completa, ni del tiempo hasta dibujar
WebView2, ni de consumo total del PC, ni del tiempo al despertar por voz.
La carga inicial del modelo desde la red y del instalador Lean tampoco se
incluye en el reloj. Un pase de CI **no demuestra que el Acer Aspire 1
con 4 GB funcione dentro de estos límites**: para eso falta el ensayo
físico autorizado.

Para un resultado real del notebook en el futuro, habrá que medir inicio
GUI -> WebSocket/backend activo, consumo total GUI/backend/servicios y
memoria disponible mientras Whisper y Piper responden preguntas.

## Positivos humanos exactos «Hey Jarvis»

Este ensayo es solo rendimiento de arranque. No añade falsos positivos o
positivos sintetizados al corpus acústico. La ruta de positivos auténticos
sigue siendo consentimiento, licencias, WAV originales, revisión manual
de frase y hablantes disjuntos. El gate acústico original continúa
bloqueante y no se relaja.
