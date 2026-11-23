# clonacion/voz_cache_f5/ — las 1440 HORAS por voz (GENERADAS)

> No se suben (son voces clonadas de personas reales). Cada grupo genera las suyas.
> **Sin estos audios el botón Hora no funciona**; el resto del programa, sí.

```
clonacion/voz_cache_f5/
  <voz>/                             el nombre de la voz en "voz_doby" de fusion/hora.json (jenpol, harry, lina, camila)
    hora/
      hora_HHMM_<md5>.wav            1440: de hora_0000 a hora_2359. "Son las nueve y veintitrés de la noche."
      generacion.csv                 registro de cada intento
```

- Formato: **WAV PCM, 16 000 Hz, mono, 16 bits**. Las del proyecto original duran de 1,6 a 2,8 s.
- `<md5>` = 8 caracteres del MD5 del texto. Lo pone solo el generador.
- Se generan con `clonacion/entrenamiento/generar_hora.py --persona <voz>`, una voz a la vez, usando el entorno
  `venv_f5`. `generar_hora_noche.py` (todas seguidas) tiene fijas las voces del grupo original.
- Con una RTX 5050 Laptop tardaron de 50 a 92 min por voz (~3,4 s por frase). Sin GPU NVIDIA: POR VERIFICAR.
  **Mídanlo con `--muestra`** (60 frases) antes de generar las 1440.
- **Los scripts de `clonacion/` vienen del proyecto anterior del grupo (Doby) y no se probaron desde este
  repositorio.** Es la parte opcional y más difícil.
- `fusion/hora.json` busca las horas en `"horas": "{doby}/voz_cache_f5/{voz_doby}/hora"`. Para usar esta
  carpeta, `"doby"` debe apuntar a la carpeta `clonacion` de este repo, con **ruta absoluta**.

Ver [GUIA_PARA_OTROS.md](../../GUIA_PARA_OTROS.md), paso 12.
