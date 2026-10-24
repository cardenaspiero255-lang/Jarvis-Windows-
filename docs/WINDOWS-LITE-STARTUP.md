# JARVIS Windows — memoria de arranque en notebooks ligeros

JARVIS ya no precarga Whisper y Piper simultáneamente en el arranque.
`startup_resources.py` consulta `GlobalMemoryStatusEx` en Windows y
separa la fase de provisión/descarga de la precarga de inferencia.

## Perfiles

- **AUTO (predeterminado)**: perfil `lite` si el equipo tiene como máximo
  5 GiB de RAM física o como máximo 2 GiB disponibles. En este caso prioriza
  Whisper para comprobar «Hey Jarvis», y difiere Piper hasta la primera
  respuesta de voz.
- Con menos de 1 GiB libre o menos de 3 GiB de RAM total, pospone ambos
  modelos para no aumentar la presión de RAM al iniciar.
- **NORMAL**: Whisper y Piper se precargan en secuencia, no simultáneamente.
  En modo exclusivamente texto Whisper nunca se precarga.
- Se puede establecer `JARVIS_STARTUP_PROFILE=lite` o `normal`
  antes de iniciar el proceso. Valores no válidos vuelven a AUTO.
  En equipos sin lectura de RAM, AUTO usa NORMAL secuencial y registra
  solo el perfil, sin inventar métricas.

Esto es una política de control de recursos, no un benchmark físico.
**Costes**: Piper puede responder más despacio la primera vez en modo
lite y, bajo memoria crítica, también Whisper. No modifica los umbrales
de openWakeWord, ni desactiva el micrófono, ni repara las falsas activaciones
acústicas que mantiene el gate bloqueado.

La precarga se lanza sin bloquear la interfaz; los modelos se siguen
cargando por sus rutas existentes al primer uso. La provisión inicial del
instalador Lean sigue siendo independiente y puede descargar recursos
pesados la primera vez. No se certifica una experiencia física en 4 GiB
hasta medir memoria real, latencia, altavoces y grabación.
