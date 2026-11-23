# CLAUDE.md

Proyecto universitario (en español): se **dibuja en el aire con el Kinect** el nombre, el apellido o el nombre y
apellido de un integrante → **TrOCR** lo lee → confirmación en pantalla → una **mano robótica** (ESP32-S3,
MicroPython, 6 servos) lo deletrea en **LSC** por **Bluetooth BLE** → al final suena la **voz original grabada** de
esa persona por un **MAX98357** en la misma placa. Detalle completo (hardware, protocolo, letras, audios, estado,
números reales): **`INFORME_PROYECTO.md`**.

## Reglas del proyecto (obligatorias)

- **BLE sí, WiFi no.** Todo local, sin APIs en la nube (TrOCR offline). **Sin micrófono** ni reconocimiento de voz.
- **Sin voces clonadas ni sintéticas**, EXCEPTO los fragmentos de fecha y hora del botón Hora (`voces_clonadas/` y
  las horas de Doby); los nombres siempre con la grabación original de `voces/`. Cómo se clonaron y cómo funciona
  el botón: [GUIA_VOZ_CLONADA_Y_HORA.md](GUIA_VOZ_CLONADA_Y_HORA.md).
- **Solo el primer apellido.** **Harry se escribe y se graba solo «Harry», nunca «Jean»**: «Jean» es solo de Jean
  Paul Miranda («Jean Harry» = mezcla de personas → se rechaza).
- Antes de crear o tocar un archivo: decir cuál y esperar el visto bueno. Trabajar por fases.
- **No borrar nada** sin aprobación. **No hacer git commit ni push** (lo hace el usuario).
- **No subir ni descargar nada de la ESP32**: el usuario sube firmware y WAV con Thonny.
- **No mostrar el TOKEN** de `config_ble.py` (solo «token cargado (N caracteres)»); `config_ble.py` no va a git.
- `voces/` solo se lee; las conversiones van a `fusion/cache_audio/` y `fusion/audios_placa/`.
- No usar nunca `Jean.wav`, `0-000.wav` ni `output.wav` (`no_usar` de `integrantes.json`).
- No tocar la caché de Hugging Face (`~/.cache/huggingface/hub`).
- La parte de la mano del firmware no se cambia sin comprobar con `fusion/pruebas/comparar_firmware.py`.
- En `dibujar_fusion.py`, `import torch` va antes de cv2/mediapipe/PIL/bleak (si no: WinError 1114 en c10.dll).

## Estructura

```
fusion/                    programa del PC
  dibujar_fusion.py        PROGRAMA PRINCIPAL: cámara, gestos, OCR, confirmación, mano + voz, registros
  reconocer.py             TrOCR + coincidencia (difflib, UMBRAL 0.75, MARGEN 0.10) + tramos
  consola_mano.py          clase Mano (BLE, bleak): deletreo por tramos, hablar, detener, cerrar; consola "!orden"
  voz.py                   voces/ -> WAV 16 kHz (audios_placa/) y orden "voz" por BLE
  pantalla_mano.py         reloj de la mano simulado con el propio firmware + panel sincronizado
  config_fusion.py         procesado del audio
  integrantes.json         personas, palabras, frases, audios, ambiguos, no_usar
  referencia/              dibujar_original.py (copia del original; NO se ejecuta)
  pruebas/                 pruebas sin Kinect ni placa + palabra.png
  salidas/                 <fecha>_<persona>.txt de cada nombre confirmado
  registros/               tiempos_mano.csv, tiempos_voz.csv, ocr.csv (solo se agregan filas), ocr_imagenes/
  audios_placa/            WAV para /voz de la placa (generado; fuera de git)
  cache_audio/             intermedio (generado; fuera de git)
firmware_mano/main.py      firmware oficial (VERSION "voz-2"); main_funciona_sin_voz.py = respaldo
voces/                     ENTRADA: grabaciones originales (en .gitignore; 9 quedaron versionadas antes)
clonacion/                 scripts de F5-TTS copiados de Doby (sin modelos ni audios) + requirements_clonacion.txt
voces_clonadas/            fechas con voz clonada (generado; fuera de git)
GUIA_VOZ_CLONADA_Y_HORA.md botón Hora de punta a punta y cómo clonar las voces
GUIA_CAMBIAR_VOCES.md      cómo usar el proyecto con otro grupo
CLAUDE_anterior.md         copia del CLAUDE.md anterior (historia detallada de las fases)
docs/                      PLAN_FUSION.md, LISTA_GRABACION.md, pruebas_dedos.md
guia_graficas/             plantilla de formato con datos SINTÉTICOS (no son resultados)
config_ble.py              NOMBRE + TOKEN (secreto, en .gitignore); plantilla: config_ble.ejemplo.py
INFORME_PROYECTO.md        informe técnico completo
```

## Comandos

```
py -3.11 fusion/dibujar_fusion.py                 todo junto (--camara N, --diagnostico)
py -3.11 fusion/voz.py --preparar                 convierte voces/ -> fusion/audios_placa/ y lista lo que falta
py -3.11 fusion/consola_mano.py                   consola de la mano (!version, !voz jean, reset, salir)
py -3.11 fusion/voz.py --texto "Lina" --deletrear deletrea con panel y suena
```

Pruebas (sin hardware; deben pasar todas):

```
py -3.11 fusion/reconocer.py --pruebas
py -3.11 fusion/pruebas/prueba_dibujar_falsa.py
py -3.11 fusion/pruebas/prueba_mano_falsa.py
py -3.11 fusion/pruebas/prueba_firmware_voz.py
py -3.11 fusion/pruebas/prueba_voz_ble_falsa.py
py -3.11 fusion/pruebas/prueba_reloj.py
py -3.11 fusion/pruebas/comparar_firmware.py
```

Con la placa: 12 V **sin USB** (no van a la vez), Bluetooth del PC activado, Thonny y cualquier otro programa
conectado a la mano cerrados (un solo cliente BLE).

## Datos clave

- Placa: servos índice 1, meñique 2, medio 42, anular 4, pulgar 40, pulgar2 39. **MAX98357: DIN 7, BCLK 15,
  LRC 16** (los correctos, `firmware_mano/main.py`, VERSION "voz-2"), **VIN a 3V3** (nunca 5Vin). Los pines
  15/48/47 eran la configuración vieja que **no funcionaba** (la placa respondía `voz_ok` y no sonaba): no usarlos.
- BLE: `Mano-LSC`, UART de Nordic (`6E400001/2/3-B5A3-F393-E0A9-E50E24DCCA9E`), primera línea `auth <TOKEN>`.
  Órdenes: palabra, letra, `reset`, `?`/`version` → `version:voz-2`, `voz a b` → `voz_ok`/`voz_falta:`/`voz_error:`.
- Letras: la mano hace las 21 estáticas (a b c d e f i k l m n o p q r t u v w x y); **g h j ñ s z** solo en
  pantalla con la mano abierta; `rr`/`ll` = dos letras.
- Gestos: índice dibuja · mano abierta levanta · 👎 1 s siguiente palabra · 👍 terminar (👍 1,5 s confirma) · ✌️ 1 s
  deshacer · 🤙 borrar/volver · 3 dedos color. Máx. 4 palabras. Teclas r / d / Esc.

## Audios: convención de nombres

- En `voces/`, nombre base exacto **sin tildes, con guion bajo**; extensión libre (`.mp3 .mp4 .m4a .wav .ogg
  .mpeg`, también la doble de WhatsApp `X.mp3.mpeg`); sin distinguir mayúsculas. **Al menos 1 s**, con silencio
  antes y después; no se recorta nada.
- 18 esperados: Jean Paul `JEAN`, `Paul`, `Miranda`, `Jean_Miranda`, `Jean_Paul_Miranda` · Harry `Harry`,
  `Raigozo`, `Harry_Raigozo` · Lina `Lina`, `Tatiana`, `Maldonado`, `Lina_Maldonado`, `Lina_Tatiana_Maldonado` ·
  Paula `Paula`, `Camila`, `Enriquez`, `Paula_Enriquez`, `Paula_Camila_Enriquez`.
- Si existe la frase grabada suena solo esa; si no, las palabras sueltas con 250 ms. Si falta uno: «Falta audio».

## Estado (2026-11-12)

Fases A, B, C1–C4 y limpieza hechas; programa completo probado con el Kinect y la placa real; todas las pruebas
pasan. Audios: **17 de 18**; falta `Paula` (ver `INFORME_PROYECTO.md` §7). La copia del CLAUDE.md anterior, con
la historia detallada de las fases, está en `CLAUDE_anterior.md`.

## Pendientes

1. Grabar el audio **«Paula»** (`voces/Paula.*`, al menos 1 s, con silencio antes y después).
2. **Escuchar `voces/Harry_Raigozo.mp3`** y confirmar que dice «Harry Raigozo» (dura lo mismo que `harry.mp3`).
3. `voz.py --preparar` y subir los WAV nuevos a `/voz` (`lina_maldonado.wav` y, cuando exista, `paula.wav`).
4. Sacar `voces/` del versionado: `git rm -r --cached voces` (**lo hace el usuario**).
5. Corregir el autor de git (hoy `tu_correo@ejemplo.com`) (**lo hace el usuario**).
6. Actualizar `docs/LISTA_GRABACION.md` y `docs/PLAN_FUSION.md` §9 (gesto ✌️ en vez del botón).
7. Crear `docs/SUSTENTACION.md`.
8. Commit de los registros nuevos (lo hace el usuario).
9. Gráficas con datos reales de `fusion/registros/` (guía solo de formato) e informe final.
10. Más pruebas del OCR con el Kinect para ajustar `UMBRAL`.
