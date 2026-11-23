# fusion/cache_audio/ — archivos intermedios (GENERADOS)

> No se suben al repositorio. Se pueden borrar cuando quieran: se vuelven a generar solos.

`fusion/voz.py` guarda aquí cada grabación de [`voces/`](../../voces/LEEME.md) ya decodificada por ffmpeg y
pasada a 16 kHz mono, antes de procesarla para la placa.

- Nombre: `<Base>_<huella>.wav`, por ejemplo `Lina_Maldonado_1a2b3c4d.wav`. La huella son 8 caracteres que
  cambian si cambia el archivo original, así que una grabación nueva se vuelve a convertir sola.
- Se genera con `python fusion/voz.py --preparar` (con el entorno virtual activado), o automáticamente al usar el
  programa.
