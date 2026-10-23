# Corpus independiente de negativas de openWakeWord (congelado 2026-10-23)

## Alcance

Se eligieron estas seis voces **antes de medir puntuaciones del detector**.
Proceden de grabaciones de lectores humanos publicadas por
[OwenTyme/voice-zero](https://github.com/OwenTyme/voice-zero/tree/490cfbee850a6d409076f477c766f567000a79b6/voices),
de extractos LibriVox (CC0 según README del proyecto, verificar por origen antes
de reutilizar con fines de distribución). El corpus solo cuenta **negativos**;
no hay grabaciones naturales de personas diciendo «Hey Jarvis». Una ejecución
correcta NO significa certificación acústica completa, FAR por hora ni cobertura
de acentos de una población real.

Commit de origen inmutable:
`490cfbee850a6d409076f477c766f567000a79b6`.

| ID de lector | Acento indicado en README | Procedencia |
| --- | --- | --- |
| alana_jordan | Estadounidense, Midwest | LibriVox, Celebration of Dialects Vol. 1 |
| andi | Estadounidense, Texas | LibriVox, Celebration of Dialects Vol. 1 |
| andy | Escocés | LibriVox, Zadig |
| annise | Australiano | LibriVox, Celebration of Dialects Vol. 1 |
| anna_simon | Neerlandés | LibriVox, Celebration of Dialects Vol. 1 |
| delibab | Irlandés del norte | LibriVox, Celebration of Dialects Vol. 1 |

Los acentos son aproximaciones del mantenedor, NO evaluación externa; seis
lectores distintos tampoco prueban automáticamente independencia del
entrenamiento original del modelo. Se utiliza «independiente» aquí para la
**procedencia externa y la no reutilización de clips generados para las pruebas
de desarrollo**, no para demostrar ausencia de coincidencia con datos de
entrenamiento de openWakeWord, que no podemos verificar completamente.

## Integridad y evaluación

El manifiesto en `jarvis-studio-backend/wake_independent_corpus.py` fija la ruta
y el Git blob SHA-1 de cada FLAC. El job descarga cada clip desde el commit
inmutable, verifica su blob, registra SHA-256, convierte FLAC a PCM16 16k mono
mediante `soundfile` y `resample_poly`, y ejecuta inferencia real con
`BuiltinInference("hey_jarvis")` en frames de 80 ms. El audio no se
almacena ni se publica en artefactos. CI guarda SOLO un recibo JSON.

Se rechaza cualquier falso positivo igual o superior al **umbral de
producción 0.4**, pérdida de integridad, corpus incompleto, voz duplicada,
archivo ilegible o discrepancia del umbral. No hay selección de muestras ni
modificación de umbral después de consultar puntuaciones.

**Separación de conjuntos:** el fallo anterior `Jarvis is a digital assistant`
pertenece a la prueba adversarial *conocida*. No se reclasifica como holdout
independiente ni se utiliza para elevar el umbral. La suite sintética original
permanece bloqueante por ese resultado.

### Qué sigue impidiendo certificar el motor

Para reducir realmente las activaciones espurias sin sacrificar la detección
válida se necesita una segunda verificación estudiada con conjunto de desarrollo
separado (o un modelo correctamente licenciado), y después evaluación ciega.
El backend ya dispone de verificación lingüística post-transcripción de la
frase, pero todavía puede mostrar brevemente una UI de wake no confirmado.
La presente campaña cuantifica el problema; no lo oculta ni declara que se ha
reentrenado un detector. Certificación física, propietaria, consentimientos y
licencias siguen fuera del alcance.
