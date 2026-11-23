# voces/ — grabaciones originales de los nombres (ENTRADA)

> El repositorio **no incluye** las grabaciones. Cada grupo graba las suyas y las pone aquí.
> Guía completa: [GUIA_PARA_OTROS.md](../GUIA_PARA_OTROS.md), pasos 5 y 6.

## Qué va aquí

Una grabación por **palabra** (nombre o primer apellido) y, si quieren, una por **frase** (nombre + apellido).
El nombre del archivo es exactamente el campo `"audio"` de [`fusion/integrantes.json`](../fusion/integrantes.json).

Con el `integrantes.json` actual, el programa espera estos 18 archivos:

| Integrante | Palabras | Frases (opcionales) |
|---|---|---|
| Jean Paul Miranda | `JEAN`, `Paul`, `Miranda` | `Jean_Miranda`, `Jean_Paul_Miranda` |
| Harry Raigozo | `Harry`, `Raigozo` | `Harry_Raigozo` |
| Lina Tatiana Maldonado | `Lina`, `Tatiana`, `Maldonado` | `Lina_Maldonado`, `Lina_Tatiana_Maldonado` |
| Paula Camila Enríquez | `Paula`, `Camila`, `Enriquez` | `Paula_Enriquez`, `Paula_Camila_Enriquez` |

## Reglas del nombre y del formato

- Nombre base **sin tildes y con guion bajo** entre palabras (`Paula_Camila_Enriquez`), sin distinguir
  mayúsculas: `Lina.mp3` y `lina.mp3` valen igual.
- Extensiones aceptadas (`integrantes.json`, `"extensiones"`): `.mp3 .mp4 .m4a .wav .ogg .mpeg`.
  También vale la doble extensión de WhatsApp: `Lina.mp3.mpeg`.
- Cualquier frecuencia y número de canales: `fusion/voz.py` los convierte con **ffmpeg**.
  Las grabaciones originales eran de 44,1 o 48 kHz, mono o estéreo, de 1,5 a 9,2 s.
- **Al menos 1 s**, con un poco de silencio antes y después. **No se recorta nada**
  (`RECORTAR_SILENCIO = False` en `fusion/config_fusion.py`).
- Nunca se usan `Jean.wav`, `0-000.wav` ni `output.wav` (lista `"no_usar"` de `integrantes.json`).

## Cómo se usa

1. Poner los archivos aquí.
2. Convertirlos, con el entorno virtual activado (necesita `ffmpeg` y `ffprobe` en el PATH):
   ```
   python fusion/voz.py --preparar
   ```
   Deja los WAV listos en `fusion/audios_placa/` y lista los que faltan.
3. Subir esos WAV a la carpeta `/voz` de la ESP32 con Thonny (guía, paso 7.2). Cada segundo de audio ocupa unos
   32 KB en la placa.

## Qué pasa si falta uno

- Si existe la grabación de la **frase** completa, suena solo esa. Si no, suenan las **palabras sueltas**
  con 250 ms entre ellas (`"pausa_entre_palabras_ms"`).
- Si falta alguna palabra necesaria, la mano **deletrea igual**, pero **no suena nada** y la pantalla dice
  «Falta audio: …».
