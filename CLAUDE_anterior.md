# CLAUDE.md

Proyecto universitario que fusiona tres proyectos (Kinect que dibuja, mano robótica LSC y la voz de Doby).
Todo en español. Todo local, sin APIs en la nube. **Todo va por Bluetooth BLE, nada por WiFi.**
La carpeta es **autosuficiente**: nada del proyecto lee ni importa archivos fuera de ella (salvo TrOCR y ffmpeg).
Los proyectos viejos (`Dibujar/`, `proyectoDoby/`) y los originales de la raíz ya están en `_para_borrar/`.

## Qué hace

Se dibuja en el aire con el Kinect el nombre, el apellido o el nombre y apellido de un integrante → OCR con
todas las palabras y coincidencia aproximada → confirmación en pantalla → la mano deletrea por BLE **por tramos**
de letras estáticas (las letras con movimiento se muestran en grande en pantalla con la mano abierta) → al
terminar el deletreo (`deletreo_completo` y el `reset` final) suena la **voz original grabada** de esa persona
por un **MAX98357 conectado a la misma ESP32-S3 de la mano** (DIN → GPIO 7, BCLK → GPIO 15, LRC → GPIO 16: los
mismos pines con los que funcionaba en Doby; GAIN y SD libres). **Alimentación del MAX98357: VIN → pin 3V3 de la
ESP32 y GND → GND, siempre (con USB y con 12 V). Nunca al pin 5Vin si la placa va por USB:** en esta placa
(tipo YD-ESP32-S3: USB CH343, LED RGB en el GPIO 48) el pin 5Vin solo recibe los 5 V del USB si los pads
«IN-OUT» están unidos con estaño, y están separados. Con VIN en 5Vin la placa respondía `voz_ok` y no sonaba nada
(el amplificador no tenía corriente); con VIN en 3V3 suena (confirmado de oído el 2026-10-28: tono de 440 Hz y
jean.wav completo con `reproducir_voz()` del firmware `voz-2`, que queda como está).
Esto va también en `docs/SUSTENTACION.md` cuando se cree (al final de C4).
El PC manda `voz <archivo> [<archivo> ...]` y la placa reproduce `/voz/<archivo>.wav` (16 kHz, mono, 16 bits)
con 250 ms entre archivos y responde `voz_ok` o `voz_falta:<a>,<b>` (sin sonar nada). El GPIO 48 (LED RGB) ya
no se usa. Con los pines 15/48/47 la placa respondía `voz_ok` pero no sonaba. **Sin clonación de voz ni VITS.**

**Sin micrófono ni reconocimiento de voz**: la única entrada es el Kinect. Lo que queda guardado en el `.txt` del
dibujo es lo que suena por el amplificador. No se usa `MIC`, Whisper ni nada que escuche.

## Estructura

```
voces/                    ENTRADA única de audios originales del grupo (ahí se guarda lo que llega por WhatsApp)
fusion/                   programa del PC
  dibujar_fusion.py       PROGRAMA PRINCIPAL (C4): Kinect -> OCR -> confirmación -> mano -> voz
  reconocer.py            TrOCR + coincidencia aproximada con integrantes.json + tramos para la mano
  consola_mano.py         clase Mano (BLE), deletreo por tramos, detener(), modo "!orden", tiempos_mano.csv
  voz.py                  prepara los WAV para la placa y manda la orden "voz" por BLE (tiempos_voz.csv)
  pantalla_mano.py        reloj simulado de la mano + ventana/panel OpenCV sincronizado
  config_fusion.py        procesado de los audios (tasa, volumen, filtro, rampas)
  integrantes.json        personas, palabras, frases y audios
  referencia/             dibujar_original.py = copia de dibujar.py (base de C4; no se ejecuta)
  pruebas/                pruebas simuladas (OCR+sesión, mano, firmware con voz, voz por BLE, reloj),
                          comparar_firmware.py, palabra.png para el OCR
  salidas/                <fecha>_<persona>.txt de cada nombre confirmado
  registros/              tiempos_mano.csv, tiempos_voz.csv, ocr.csv (solo se agregan filas) y ocr_imagenes/
                          (lienzo <fecha>_<n>.png y lo que recibe TrOCR <fecha>_<n>_trocr.png)
  audios_placa/           SALIDA: WAV para /voz de la placa (voz.py --preparar)
  cache_audio/            intermedio, se regenera solo
firmware_mano/            main.py = firmware oficial de la placa (sin config_ble.py);
                          main_funciona_sin_voz.py = respaldo (lo usa comparar_firmware.py)
guia_graficas/            guía de formato: sus datos son SINTÉTICOS (ver LEEME.txt); las gráficas nuevas, solo reales
docs/                     PLAN_FUSION.md, LISTA_GRABACION.md, pruebas_dedos.md (README viejo de la mano)
config_ble.py             NOMBRE y TOKEN de la mano (en .gitignore; se lee sin copiarlo; el token nunca se muestra)
_para_borrar/             (en .gitignore) Dibujar/, proyectoDoby/, main.py, consola_pc.py y prueba.py viejos de la
                          raíz, firmware_mano/calibrar_pulgar2.py, fusion/esp32_voz.py, fusion/pruebas/escuchar/
```

## Integrantes y audios

Clave → nombres / apellido (**solo el primer apellido**):
- `jeanpaul` ("jenpol" en Doby, el usuario) → Jean, Paul / Miranda
- `harry` → Harry / Raigozo (solo usa «Harry», nunca «Jean»: «Jean» es solo de Jean Paul; «Jean Harry» = mezcla)
- `lina` → Lina, Tatiana / Maldonado
- `paula` ("camila" en Doby) → Paula, Camila / Enríquez

5 audios por integrante (Harry 3; 18 en total): sus dos nombres, su apellido, «primer nombre + apellido» y el nombre
completo (p. ej. `Lina_Maldonado`, `Lina_Tatiana_Maldonado`; Harry: `Harry`, `Raigozo`, `Harry_Raigozo`), en `voces/`,
sin tildes y con guion bajo. **Cada audio dura al
menos 1 s** con un poco de silencio antes y después; no se recorta ni se agrega nada. Hoy hay 10 (los 5 de Jean
Paul y los 5 de Lina). Faltan 8: Harry, Raigozo, Harry_Raigozo; Paula, Camila, Enriquez, Paula_Enriquez,
Paula_Camila_Enriquez. Los que faltan solo dan «Falta audio» al dibujar ese nombre. Extensiones:
`.mp3 .mp4 .m4a .wav .ogg .mpeg`, también la doble de WhatsApp (`Maldonado.mp3.mpeg` = `Maldonado`). Un segundo
apellido (p. ej. `Rivera.mp3`) se ignora. Si existe la grabación exacta de la frase, suena solo esa
(`voz lina_maldonado`); si no, las palabras sueltas con 250 ms (`voz tatiana maldonado`). "Jean" dibujado solo →
Jean Paul (`voces/JEAN.mp4`). Lista: `docs/LISTA_GRABACION.md`. Si falta un audio: pantalla «Falta audio:
<palabra>», no suena nada y el programa no se cae.

Letras: la mano solo hace las **21 estáticas de LSC**: a b c d e f i k l m n o p q r t u v w x y. **g, h, j, ñ,
s, z llevan movimiento**: no se hacen con la mano. `rr` y `ll` se deletrean como `r`+`r` y `l`+`l`.

Estado: A (plan) ✔ · B (lista de grabación) ✔ · C1 (OCR) ✔ · C2 mano ✔ (probada con la mano real) ·
C3 ✔ (suena en la placa real) · C4 ✔ `fusion/dibujar_fusion.py` (probado con el Kinect y la placa real) ·
D limpieza ✔ (todo lo viejo en `_para_borrar/`). Falta: `docs/SUSTENTACION.md`, los 8 audios, gráficas reales e
informe.
Decisiones abiertas en `docs/PLAN_FUSION.md` §9.

## Reglas (obligatorias)

1. **No tocar `_para_borrar/`** (ni modificar, ni leer desde el programa). Solo el usuario decide cuándo borrarla.
2. Nada del proyecto importa ni lee `_para_borrar/` ni rutas fuera de esta carpeta. Excepciones: la
   caché de Hugging Face (TrOCR) y ffmpeg (en `C:\Users\miran\Downloads\ffmpeg-9.0.1-essentials_build\...\bin`,
   en el PATH).
3. Los audios originales solo se leen (`voces/`); las conversiones van a `fusion/cache_audio/` y
   `fusion/audios_placa/`.
4. **No subir ni descargar nada de ninguna ESP32**: el usuario sube el firmware (`firmware_mano/main.py`) y los
   WAV (a `/voz`) con Thonny.
5. Antes de crear o tocar cada archivo: decir cuál y esperar el visto bueno.
6. Trabajar por fases y esperar aprobación en cada una; probar cada parte por separado.
7. **No borrar nada.** Lo que sobre se mueve a `_para_borrar/` (con su misma ruta), con aprobación del usuario.
8. No usar nunca `Jean.wav`, `0-000.wav` ni `output.wav` (están en `no_usar` de `integrantes.json`).
9. No tocar la caché de Hugging Face (`~/.cache/huggingface/hub`).
10. No mostrar el TOKEN BLE (solo «token cargado (N caracteres)»).

## La placa (ESP32-S3 N16R8)

Firmware oficial `firmware_mano/main.py` (MicroPython). Servos: índice 1, meñique 2, medio 42, anular 4,
pulgar 40, pulgar2 39. Pulgar2: abierto 700, cerrado 2300, mitad 1600. `reset_all` abre la mano empezando por el
pulgar: pulgar2, pulgar, índice, medio, anular, meñique. El PWM **no** se suelta en reposo (se caían el anular y
el pulgar). **BLE** (UART de Nordic, `auth <TOKEN>`, nombre `Mano-LSC`) + USB. Respuestas: `ok:auth`/`error:auth`,
`gesto_x_ok`, `letra_actual:x`, `letra_x_no_disponible`, `deletreo_completo` (y abre la mano), `reset_ok`,
`voz_ok`, `voz_falta:…`, `voz_error:<i2s|lectura>` (la voz nunca se cuelga ni detiene la mano),
`version:voz-2` (órdenes `version` o `?`; voz-2 = pines 7/15/16 y sin LED; el PC usa `?` porque el firmware sin voz respondería
`comando_no_reconocido` sin mover nada, mientras que `version` lo deletrearía), `comando_no_reconocido`.
En el PCB no se pueden conectar el USB y los 12 V a la vez. El `main.py` original con los pines viejos está en
`_para_borrar/`. `firmware_mano/main_funciona_sin_voz.py` = respaldo de lo que funcionaba en la placa (lo guarda el
usuario); `fusion/pruebas/comparar_firmware.py` muestra el diff y comprueba que la parte de la mano sea idéntica.

**Pantalla sincronizada** (`fusion/pantalla_mano.py`, sin tocar el firmware): `RelojMano` ejecuta en el PC las
funciones de la mano del propio `firmware_mano/main.py` en tiempo virtual (0,4 s por dedo que se mueve, 1 s
mostrando, `reset_all` en su orden) y `Seguimiento` lo corrige con cada `letra_actual:x` y `deletreo_completo`.
Comparado con el deletreo real de «Tatiana Maldonado»: ±0,09 s por letra. `VentanaMano` (OpenCV) la abre
`voz.py --deletrear`.

**Cerrar**: Ctrl+C, Esc o q cortan enseguida (las esperas van en pasos de 0,2 s); `Mano.cerrar()` siempre suelta
el Bluetooth (también con `atexit`). La espera de `voz_ok` = duración del audio + 0,93 s + 5 s.

De Doby solo se copiaron (ya dentro del proyecto): `_pulir()`, `normalizar()` y la configuración del I2S (16 bits,
mono, 16 kHz, `ibuf=20000`, 630 ms de vaciado). Procesado de los audios (`config_fusion.py`): **sin recorte** (ya
vienen cortados; el WAV dura lo mismo que el original), pasa-altos 100 Hz, pico 0,35 igual para todos, rampas de
2 ms; la placa pone 250 ms entre archivos y 0,3 s al final.

## Entorno

- `py -3.11` (Python del sistema): mediapipe, opencv, transformers, bleak 3.0.2, pygame, numpy, scipy.
  No hay `rapidfuzz`: la coincidencia aproximada se hace con `difflib`.
- ffmpeg/ffprobe en el PATH (`C:\Users\miran\Downloads\ffmpeg-9.0.1-essentials_build\...\bin`).
- Windows 11, PowerShell / Git Bash.

## Pruebas

```
py -3.11 fusion/reconocer.py --pruebas
py -3.11 fusion/pruebas/prueba_mano_falsa.py
py -3.11 fusion/pruebas/prueba_firmware_voz.py
py -3.11 fusion/pruebas/prueba_voz_ble_falsa.py
py -3.11 fusion/pruebas/prueba_reloj.py
py -3.11 fusion/pruebas/prueba_dibujar_falsa.py
py -3.11 fusion/pruebas/comparar_firmware.py
py -3.11 fusion/voz.py --preparar
```

Con la placa (12 V, sin USB): `py -3.11 fusion/consola_mano.py` y `!version`, `!voz jean`; después
`py -3.11 fusion/voz.py --texto "Tatiana Maldonado" --deletrear`. Todo junto con el Kinect:
`py -3.11 fusion/dibujar_fusion.py` (`--diagnostico` muestra el gesto; `--camara N` si no abre la 1).

## Limpieza (punto D) ✔

Hecha el 2026-10-29: `Dibujar/`, `proyectoDoby/` (el usuario tiene copia de los dos), `main.py`, `consola_pc.py` y
`prueba.py` de la raíz, `firmware_mano/calibrar_pulgar2.py`, `fusion/esp32_voz.py` y `fusion/pruebas/escuchar/` se
movieron a `_para_borrar/` (en `.gitignore`). Se quitaron `VozWifi` de `voz.py` e `IP_ESP32`/`PUERTO` de
`config_fusion.py` (WiFi fuera del proyecto). Los PNG de `fusion/salidas/dibujos/` pasaron a
`fusion/registros/ocr_imagenes/` (datos reales para el informe). No se copiaron nunca (decidido): las grabaciones
de Doby, el modelo VITS ni el dataset IAM.
