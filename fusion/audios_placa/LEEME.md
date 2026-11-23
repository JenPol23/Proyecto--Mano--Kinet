# fusion/audios_placa/ — WAV listos para la ESP32 (GENERADOS)

> No se suben al repositorio. Se generan a partir de [`voces/`](../../voces/LEEME.md).

## Cómo se generan

```
python fusion/voz.py --preparar
```

(Con el entorno virtual activado; necesita `ffmpeg` y `ffprobe` en el PATH.)

## Nombre y formato

- Un archivo por grabación de `voces/`, con el nombre base **en minúsculas**: `Lina_Maldonado.mp3` →
  `lina_maldonado.wav`, `JEAN.mp4` → `jean.wav` (`nombre_placa()` en `fusion/voz.py`).
- **WAV PCM, 16 000 Hz, mono, 16 bits.** Es lo que espera el firmware (`TASA_VOZ = 16000` y
  `I2S(... bits=16, format=I2S.MONO ...)` en `firmware_mano/main.py`).
- Procesado (`fusion/config_fusion.py`): volumen 0,35, filtro de graves a 100 Hz y rampa de 2 ms contra el clic.
  No se recorta nada.

## A dónde van

A la carpeta **`/voz`** de la ESP32, con Thonny y la placa **solo por USB**, sin los 12 V:
seleccionar todos los `.wav` de esta carpeta → clic derecho → «Subir a /voz»
([GUIA_PARA_OTROS.md](../../GUIA_PARA_OTROS.md), paso 7.2).

Espacio: cada segundo de audio ocupa unos **32 KB** (16 000 muestras × 2 bytes). El espacio libre se ve en la
consola de Thonny con `import os; s = os.statvfs('/'); print(s[0] * s[3] // 1024, 'KB libres')`.

Si un archivo no está en la placa, la placa responde `voz_falta:<nombre>` y en pantalla sale
«Falta audio: … (no está en la placa: súbelo a /voz con Thonny)».
