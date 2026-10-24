# JARVIS Windows · Recopilación PRIVADA de positivos humanos «Hey Jarvis»

Estado: **preparado para recopilar; SIN voces humanas recogidas ni FNR certificado**.

## Qué se consiguió y qué falta

La investigación no encontró un corpus público con múltiples grabaciones humanas
de la frase *exacta* «Hey Jarvis» con licencias, consentimientos y hablantes
independientes verificables. Los datos de Picovoice dicen **«Jarvis»**, así que
continúan siendo **negativos difíciles**, no positivos. Los conjuntos de voz TTS
sintética no sustituyen positivos humanos. Este módulo no descarga audios, no
entrena modelos y no cambia el umbral de producción de openWakeWord (0.4).

La captura e importación solo ocurren tras una acción explícita del operador.
No hay almacenamiento en nube ni subida a GitHub. Las grabaciones, consentimientos
y el manifiesto se conservan **fuera del checkout** en una carpeta PRIVADA que
el operador protege y puede eliminar. Se recomienda Windows EFS/BitLocker o
almacenamiento cifrado; el código **no cifra los WAV por sí mismo**. No almacenar
nombres reales, teléfonos, rostros, edades ni datos de identificación en el
manifiesto. El operador debe gestionar por separado y en privado la prueba de
consentimiento y las instrucciones para revocarlo/eliminar datos.

## Consentimiento y protocolo (personas adultas)

Antes de abrir el micrófono, explicar: «Queremos grabar tres frases cortas
diciendo Hey Jarvis para comprobar un detector local. No publicaremos el audio,
no lo usaremos para identificarte, puedes rechazarlo o solicitar su eliminación
en cualquier momento. Estas grabaciones son solo para evaluación privada y no
autorizan entrenamiento ni explotación comercial». Registrar consentimiento
explícito verificable **fuera** del repositorio. No grabar voces de terceros
sin permiso ni obtener voces desde llamadas, videos o redes sociales sin licencia.

Asignar un ID pseudónimo sin datos personales (por ejemplo `speaker_001`) y
una partición **antes** de ejecutar cualquier detector. Mantener a cada
participante siempre en `development` o siempre en `holdout`.
Nunca ajustar umbrales/modelos/transcript-verifier con resultados del holdout.

Condiciones sugeridas por hablante: `quiet` cerca; `fan` con ventilador;
`far_field` a varios metros. También puede utilizarse `traffic` si es
viable, sin exponerse a peligros. Solicitar el saludo exacto «Hey Jarvis».
Variar naturalmente acento y volumen; evitar leer datos privados. Para medir
respuesta real también harán falta controles negativos de los mismos entornos
que **no** contienen el saludo.

## Uso en Windows

Ejecutar en PowerShell desde `jarvis-studio-backend` con Python 3.11 y
`pyaudio` instalado (solo la opción `record` necesita PyAudio).
El directorio privado **debe** estar fuera de la copia Git:

```powershell
$private = Join-Path $env:USERPROFILE "JARVIS-WAKE-PRIVATE"
python human_wake_positive_intake.py record --root $private --seconds 4 --consent-verified
```

`record` crea un WAV PCM16 / 16 kHz / mono bajo `pending`; no lo incluye
como positivo todavía. Abrirlo y escucharlo **manualmente**, comprobar
que procede de una persona (no TTS) y contiene exactamente «Hey Jarvis».
Con consentimiento documentado, importarlo indicando la partición
predefinida del hablante y la condición:

```powershell
python human_wake_positive_intake.py import --root $private --file "$private\pending\REEMPLAZAR.wav" --speaker-id speaker_001 --split development --accent es-CL --condition quiet --distance near --consent-verified --human-confirmed --reviewed-exact-phrase
python human_wake_positive_intake.py summary --root $private
```

Cambiar `--split` a `holdout` solamente para participantes distintos,
preasignados. WAV grabados con otro dispositivo también se pueden importar
si ya son PCM16 mono 16 kHz, tienen 1–10 s de duración y pasan la revisión.
No marcar `--human-confirmed` ni `--reviewed-exact-phrase` sin escuchar
la muestra auténtica. El programa no puede comprobar automáticamente
identidad, consentimiento ni pronunciación exacta: esas opciones documentan
*atestaciones del operador*, no certificación independiente.

El programa calcula hash SHA-256, rechaza duplicados exactos y WAV
silenciosos, no PCM o fuera de límites; guarda metadatos pseudónimos y
registros bajo `manifest.private.json`, sin incluir contenidos ni hashes
en el resumen público. Rechaza al mismo `speaker_id` en particiones distintas.
Un mismo humano que cambie de ID tampoco puede ser identificado por el código:
la independencia real se comprueba manteniendo un registro de participantes
separado, consentido y protegido.

Cuando haya **como mínimo** 3 hablantes y 9 muestras en cada partición y
tres condiciones diferentes por partición, se puede congelar el manifiesto:

```powershell
python human_wake_positive_intake.py seal --root $private
```

Ese mínimo habilita **solo un experimento inicial**, no una estimación
estadísticamente sólida. Se recomiendan más hablantes y varias sesiones
independientes antes de evaluar. `seal` registra un SHA-256 del manifiesto
y bloquea nuevas incorporaciones. No permite consultar los resultados del
holdout; hace falta un evaluador posterior separado que utilice exactamente
el umbral y verificador congelados. Si aparece una corrección, crear otro
holdout nuevo y no reutilizar el anterior como prueba ciega.

## Prohibiciones y límites

- NO subir WAV, consentimiento, identidades, manifest privado ni hash por muestra a GitHub o CI.
- NO usar voces sintéticas ni la palabra «Jarvis» aislada como positivos humanos.
- NO afirmar FNR, recall, FAR ni falsas activaciones por hora antes de observar los positivos y suficientes negativos medidos.
- NO cambiar el umbral 0.4 ni desactivar el gate acústico anterior para obtener verde.
- NO interpretar el estado `PRIVATE_HOLDOUT_SEALED` como autenticidad humana, derecho comercial o seguridad del producto.

La publicación comercial sigue bloqueada de forma independiente por las
licencias de los pesos preentrenados, el E2E FULL firmado y la auditoría.
