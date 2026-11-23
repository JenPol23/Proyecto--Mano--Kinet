# voces_clonadas/ — frases de FECHA con voz clonada (GENERADAS)

> No se suben al repositorio (son voces de personas reales). Cada grupo genera las suyas.
> Proceso completo (opcional y la parte más difícil): [GUIA_PARA_OTROS.md](../GUIA_PARA_OTROS.md), paso 12, y
> [GUIA_VOZ_CLONADA_Y_HORA.md](../GUIA_VOZ_CLONADA_Y_HORA.md).

Solo las usa el **botón Hora**. Sin estos audios, el resto del programa funciona igual.

```
voces_clonadas/
  fecha/
    <persona>/                       jeanpaul, harry, lina, paula (claves de fusion/hora.json, "personas")
      fecha_AAAAMMDD_<md5>.wav       una por fecha del calendario: "Hoy es viernes veinte de noviembre."
      generacion.csv                 registro de cada intento (tampoco se sube)
```

- Formato: **WAV PCM, 16 000 Hz, mono, 16 bits**. `fusion/hora.py` rechaza cualquier otro formato.
- Rango de fechas: `"rango_fechas"` de `fusion/hora.json`. Hoy va del 2026-11-12 al 2026-12-31: 50 fechas por voz.
- `<md5>` = 8 caracteres del MD5 del texto de la frase. El nombre lo pone solo el generador; no se escribe a mano.
- Se generan con `fusion/herramientas/generar_fechas.py`, usando el entorno `venv_f5`. Este script usa los de
  `clonacion/`, que vienen del proyecto anterior del grupo (Doby) y **no se probaron desde este repositorio**.
- `"piloto"` → `"persona"` de `fusion/hora.json` debe ser una de sus voces; si no, `--piloto` falla.
- Si falta la fecha de hoy, el botón Hora dice **solo la hora**, con el aviso «Falta audio de la fecha …».

Las **horas** (1440 por voz) no van aquí: van en [`clonacion/voz_cache_f5/`](../clonacion/voz_cache_f5/LEEME.md).
