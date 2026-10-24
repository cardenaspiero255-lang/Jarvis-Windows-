# Fase 2 — aceptación física de JARVIS en Windows

**Estado inicial: NOT_CERTIFIED.** El NSIS Lean y su prueba WebView2/CDP de GitHub
Actions no prueban micrófono, altavoz, wake-word o permisos en hardware personal.
El ensayo de este documento exige presencia de un operador en un PC **físico**
con Windows, JARVIS instalado, el micrófono y salida de audio disponibles.

## Procedimiento (no modifica políticas ni graba audio)

1. Abre la aplicación JARVIS instalada en el propio PC. Verifica que se ve la
   interfaz y que has permitido el micrófono solo si deseas utilizarlo.
2. Descarga o clona esta rama del repositorio y, desde una terminal Windows
   PowerShell interactiva abierta en el directorio del proyecto, ejecuta:

   ```powershell
   .\scripts\windows-physical-acceptance.ps1 -JarvisExePath "RUTA_REAL\jarvis-studio-gui.exe"
   ```

   Sustituye `RUTA_REAL` por la ruta **real del ejecutable instalado**.
   No ejecutes el antiguo `validate-installer.ps1`: está diseñado
   exclusivamente para máquinas CI desechables.
3. Sigue las diez pruebas en pantalla. Para cada una escribe `P` si
   verificaste lo que ocurrió *en la app y el hardware*, `F` si falló
   u `O` si no pudiste ejecutarla. No marques `P` por presencia de
   un botón, ausencia de errores en logs o una prueba de GitHub verde.
4. La prueba de revocación de micrófono cambia permisos **solo manualmente**.
   Restaura inmediatamente la configuración que tenías y verifica que
   JARVIS vuelve a escuchar. No fuerces cierres ni cortes de energía.
5. Se creará un JSON local en la carpeta temporal de Windows, con el hash
   SHA-256 del ejecutable, observación de proceso/audio y resultados.
   No incluye grabaciones, secretos, rutas del usuario, seriales ni contenido hablado.
6. Valida su consistencia, con Python instalado en cualquier equipo que
   disponga del repositorio:

   ```powershell
   python .\jarvis-studio-backend\physical_windows_acceptance.py "RUTA_DEL_COMPROBANTE.json"
   ```

   Código de salida `0` = diez casos reportados como observados,
   equipo Windows físico declarado, adaptador de audio y proceso observados;
   no implica medición acústica independiente. `1` = `NOT_CERTIFIED`.

## Criterios de seguridad y alcance

- El script rechaza el entorno GitHub Actions y no acepta una VM como PC físico;
  la detección de virtualización por modelo es heurística. La declaración
  del operador no equivale a autenticación criptográfica.
- La denegación de permisos debe mostrar que no ocurrió ninguna acción.
  Solo autorices acciones **de lectura y reversibles** para la prueba positiva.
  Evita comandos de borrado, apagado, escritura o ejecución externa.
- Cancelación: comprueba escucha, reproducción TTS y una tarea solo lectura;
  no confundas un botón en pantalla con interrupción efectiva.
- Recuperación: verifica reinicio de JARVIS y denegación/restauración de
  micrófono; no apagues físicamente el PC ni detengas el servicio remoto.
- `USER_ATTESTED_PHYSICAL` significa **observado y declarado por el operador**.
  Los campos `physical_certified` e `independently_certified` permanecen
  deliberadamente en `false`. Para certificación instrumental aún se requieren
  mediciones reproducibles de captura/STT, latencia TTS, logs de consentimiento
  y cancelación sin datos sensibles, ejecutadas sobre hardware autorizado.
- El instalador Lean es **sin firma**. Este procedimiento no elimina el
  bloqueo de publicación, no prueba el instalador FULL offline, no demuestra
  pérdida eléctrica ni completa la auditoría de seguridad del PR #1.

Si no hay un PC accesible, conserva el estado `NOT_CERTIFIED`. No llenes
resultados físicos utilizando eventos simulados de GitHub.
