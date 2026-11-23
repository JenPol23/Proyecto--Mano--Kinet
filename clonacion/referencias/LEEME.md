# clonacion/referencias/ — registro de los clips de referencia

> No se sube nada de esta carpeta, salvo este archivo. Ni los clips ni `referencias.csv`, porque tiene datos
> personales.

`referencias.csv` lo escribe `clonacion/entrenamiento/experimentos_voz/referencias_f5.py`: una fila por clip
recortado, con las columnas `persona, clip, segundos, sr, origen, texto, whisper_clip, coincide_palabras,
fluidez, pausas_internas, revisar`. Sirve para decidir **de oído** qué clip usar como referencia principal y cuáles
como respaldo.

Los clips que usa F5-TTS **no van aquí**: van en
[`clonacion/voz_comparacion_f5/referencias/<persona>/`](../voz_comparacion_f5/LEEME.md).
