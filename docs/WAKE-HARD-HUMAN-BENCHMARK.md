# Evaluación de positivos reales y negativos difíciles — JARVIS Windows

## Datos existentes y verdad de terreno

El modelo actual detecta «Hey Jarvis», NO la palabra aislada «Jarvis».
Seleccionamos **16 grabaciones humanas reales** del benchmark original de
[Picovoice](https://github.com/Picovoice/wake-word-benchmark)
(licencia Apache 2.0), fijando su commit antes de ejecutar el detector:
`84919190fb1891bf0936dcb577d9268e467f876f`.

- 12 grabaciones de personas diciendo **«Jarvis»**: negativas difíciles.
- 2 grabaciones de **«Computer»** y 2 de **«Alexa»**: controles negativos.
- 8 clips desarrollo y 8 clips reservados, sin archivos compartidos.
- Cada grabación se evalúa limpia y con ruido blanco determinista a 10 dB:
  **32 condiciones de audio**, pero solo 16 grabaciones de origen.
- Se verifica el Git blob SHA-1 y SHA-256 de descarga, y se guardan
  únicamente métricas y procedencia. No se publican grabaciones en CI.

**Límites de independencia:** Picovoice indica >50 hablantes en total, pero
sus nombres/identidades por archivo no están en el conjunto publicado.
Los archivos desarrollo/holdout son disjuntos; NO es posible probar que
los hablantes sean disjuntos, ni la ausencia de solapamiento con entrenamiento
del propio openWakeWord. No se declara independencia por hablante ni auditoría
ciega externa. El ruido añadido es simulado.

## Comparación predefinida antes de mirar el reservado

1. Baseline: modelo original openWakeWord `hey_jarvis`, umbral congelado 0.4.
2. Segunda confirmación: **solo** cuando el baseline se activa, transcribir
   localmente con el Whisper de JARVIS (prompt real «Jarvis»), y validar
   que se reconoce la frase completa mediante `heard_wake_phrase`.
3. Se miden falsos despertares **por clip/condición**, no por hora:
   `baseline_fp / negativos` versus `verified_fp / negativos`.
4. Si aparece una falsa activación tras verificación, job ROJO.
   Si no aparece, resultado `NEGATIVE_ONLY_MEASURED`, NO certificación.
5. La partición `holdout` se ejecuta solo si la de desarrollo pasa.
   Los resultados del reservado NO autorizan modificar el umbral, los clips
   ni el verificador y repetir afirmando que sigue siendo ciego.

El gate acústico original sigue bloqueado por el adversarial conocido
«Jarvis is a digital assistant…». Este benchmark no lo oculta ni lo sustituye.

## Positivos humanos auténticos — faltan datos

No está localizado un conjunto abierto de múltiples hablantes humanos
**pronunciando exactamente** «Hey Jarvis» con audio, atribución, permisos
y splits independientes. El corpus Picovoice «Jarvis» no cubre esa necesidad.
Los modelos y datasets públicos encontrados contienen muchas voces
sintéticas; no contarán como personas reales.

Para crear un corpus válido se necesitan clips de consentimiento explícito,
con transcripción y revisión auditiva, hash SHA-256 y un ID pseudónimo de
hablante. Separar hablantes desarrollo/holdout sin reutilizarlos. El
validador `verify_real_positive_intake` comprueba coherencia de metadatos
pero **nunca** certifica autenticidad por sí solo. No se suben voces de
terceros al repositorio sin licencia y consentimiento acreditados.

### Métricas pendientes

Con `real_positives=0` la tasa de falsos rechazos (FNR) y el recall
positivo permanecen **sin valor**, no 0. La tasa de falsas activaciones
por hora tampoco se deduce de clips aislados. No se probaron distancias
de micrófono reales, identidad biométrica ni altavoces.

El modelo openWakeWord original y sus pesos requieren además revisión
de licencia antes de cualquier publicación comercial. Los ensayos no
cambian la puerta de firma, auditoría de seguridad ni paquete FULL.
