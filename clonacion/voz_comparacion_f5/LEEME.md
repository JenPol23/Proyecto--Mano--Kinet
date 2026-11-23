# clonacion/voz_comparacion_f5/ — clips de referencia para clonar (ENTRADA de F5-TTS)

> No se suben (son voces reales). Cada grupo graba y recorta los suyos.

`clonacion/entrenamiento/generar_voces_f5.py` lee las referencias de:

```
clonacion/voz_comparacion_f5/referencias/<persona>/<clip>.wav     el audio
clonacion/voz_comparacion_f5/referencias/<persona>/<clip>.txt     el texto EXACTO que se dice en el clip
```

- `<persona>` y `<clip>` deben coincidir con `clonacion/entrenamiento/referencias_voz_f5.json`:
  `persona -> [principal, respaldo 1, respaldo 2]`, por ejemplo `"ana": ["ana_ref1", "ana_ref2", "ana_ref3"]`.
- **El nombre de la voz debe ser el mismo en tres lugares:** esta carpeta (`referencias/<voz>/`), la clave de
  `referencias_voz_f5.json` y `"voz_doby"` de `fusion/hora.json`.
- **Borren de `referencias_voz_f5.json` las voces del grupo original** (`camila`, `harry`, `jenpol`, `lina`): sus
  clips no vienen en el repositorio.
- Las referencias que funcionaron duraban **de 6 a 12 s**, con voz clara, sin ruido y sin pausas largas.
- Formato: las del proyecto original eran WAV de 48 kHz; otro formato es POR VERIFICAR. **Usen WAV mono de
  48 kHz.**
- El `.txt` tiene que decir exactamente lo que se oye, palabra por palabra. Si no coincide, la voz clonada sale mal.
- `referencias_f5.py` y `referencia_ef.py` (en `experimentos_voz/`) son los scripts que se usaron para recortarlas;
  tienen rutas fijas del PC original (ver [GUIA_PARA_OTROS.md](../../GUIA_PARA_OTROS.md), paso 10).
- Proceso completo: [GUIA_PARA_OTROS.md](../../GUIA_PARA_OTROS.md), paso 12.

Ver [GUIA_VOZ_CLONADA_Y_HORA.md](../../GUIA_VOZ_CLONADA_Y_HORA.md).
