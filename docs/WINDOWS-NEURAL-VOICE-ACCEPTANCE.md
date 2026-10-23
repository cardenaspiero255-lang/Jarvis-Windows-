# Fase 2 — modelos neurales de voz reales en Windows CI

El workflow **Windows Neural Voice Models Acceptance** separa dos pruebas
independientes que nunca requieren el PC del propietario:

- `piper-real` instala Piper, descarga `en_GB-alan-medium` solo al runner,
  llama al código genuino `TTSEngine._speak_piper`, intercepta exclusivamente
  el dispositivo de reproducción e inspecciona tres WAV generados realmente
  mediante ONNX. Guarda estadísticas, tiempos observados y SHA-256 del modelo,
  pero no distribuye audios ni pesos. Una cuarta síntesis prueba el rechazo
  de reproducción si se produjo un STOP antes del envío al mezclador.
- `wake-acoustic-real` genera cuatro archivos WAV en Windows SAPI con
  positivos y negativos de la frase «Hey Jarvis» y alimenta al modelo ONNX
  `wake_word.openwakeword.BuiltinInference` con frames PCM16 de 80ms,
  usando exactamente el umbral de JARVIS (_THRESHOLD). Incluye un control
  de silencio y almacena puntuaciones reales para diagnosticar falsos
  positivos o negativos. Un único positivo detectado y los tres negativos
  rechazados son el mínimo de este **ensayo sintético limitado**, no una
  garantía de desempeño en campo. Los WAV son eliminados, no se publican.

Todos los errores reales producen `NOT_CERTIFIED` y retornan exit code 1.
Los artefactos JSON se guardan incluso si falla la prueba. El modelo Piper
se descarga sin un hash esperado previamente fijado: el hash observado es
trazabilidad, **no autenticación independiente de su origen**. Para venta
o lanzamiento se requieren SBOM, licencias de voces y manifiesto con hashes
fijados y verificables.

**Advertencia de licencia:** el modelo preentrenado `hey_jarvis` de
openWakeWord se distribuye bajo condiciones no comerciales. Que su prueba
funcione en CI no concede derecho a distribuirlo en una versión comercial
de JARVIS. No publicar los pesos ni el instalador hasta resolver licencias.

No se certifican micrófono, altavoces, voz del propietario, identidad
biométrica, eco, cancelación de mezcla de sonido, ni el paquete FULL offline.
Estos requieren ensayos adicionales y, finalmente, hardware autorizado.

## Primer resultado acústico observado (23 octubre 2026)

En la primera ejecución real (commit `7d68a6e`) Piper produjo tres WAV
válidos en Windows. openWakeWord ejecutó inferencia real pero **falló el gate**
por un falso positivo comprobable:

- Picos positivos: 0.997838 y 0.997663
- Control negativo «The quick brown fox…»: 0.000125
- Control negativo «Jarvis is a digital assistant…»: **0.545066**
- Silencio: 0.000086; umbral productivo del modelo: **0.4**

El control de mención sin saludo activa el modelo acústico, aunque
`main._command_from_clip` dispone de una segunda verificación de
`command_after_wake` que rechaza el texto cuando no contiene el saludo.
Se añaden pruebas adversariales explícitas de ese contrato, pero **no se
declara certificación acústica** ni se modifica el umbral para forzar verde
a partir de cuatro clips sintéticos. Antes de calibrar el modelo se necesita
un conjunto de evaluación suficientemente variado e independiente.

El test `wake-acoustic-real` permanece bloqueante: su failure es evidencia,
no una razón para omitirlo ni deshabilitarlo. El gate firmado/comercial
permanece cerrado por las razones del informe de seguridad.
