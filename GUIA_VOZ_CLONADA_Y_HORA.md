# Guía: voz clonada y botón Hora

Cómo funciona el botón **Hora** (la mano dice la fecha y la hora con la voz clonada de un integrante), cómo se
clonaron las voces con **F5-TTS** y cómo otro grupo puede clonar las suyas. Todo sale del código y de los registros
reales; lo que no se pudo comprobar está marcado **POR VERIFICAR**.

> **Regla del proyecto:** la voz clonada se usa **solo para la fecha y la hora**. Los nombres suenan siempre con la
> grabación original de cada persona (`voces/`). Clonar la voz de alguien requiere su permiso.

Índice: [1. El botón Hora de punta a punta](#1-el-botón-hora-de-punta-a-punta) ·
[2. Cómo clonamos las voces](#2-cómo-clonamos-las-voces) ·
[3. Paso a paso para otro grupo](#3-paso-a-paso-para-otro-grupo) ·
[4. Si `hora.json` apunta a una ruta que no existe](#4-si-horajson-apunta-a-una-ruta-que-no-existe)

---

## 1. El botón Hora de punta a punta

### Qué archivo hace qué

| Archivo | Qué hace |
|---|---|
| `fusion/dibujar_fusion.py` | El botón en pantalla, el menú de voces, la tecla `h` y el hilo que pide la hora (con el candado de la mano). |
| `fusion/hora.json` | Configuración: dónde están los audios, qué voces hay y el rango de fechas. |
| `fusion/hora.py` | Lógica: textos de fecha y hora, qué archivo corresponde, `decir()` (manda o reproduce) y el registro `tiempos_hora.csv`. |
| `fusion/mano_wifi.py` | Cliente WiFi del PC: busca la placa (`mano.local` y luego `IP_FIJA`), se autentica con TOKEN y envía el audio. |
| `firmware_mano/wifi_hora.py` | En la placa: recibe el audio por WiFi y lo hace sonar en el MAX98357 mientras llega. |
| `fusion/voz_pc.py` | Plan B: el mismo audio por los parlantes del PC (`--voz-pc`), sin WiFi. |
| `fusion/herramientas/generar_fechas.py` | Genera una vez las frases de la fecha con la voz clonada (sección 2.5). |
| `voces_clonadas/fecha/<persona>/` | Las frases de la fecha generadas (y su `generacion.csv`). **No van a git.** |
| `<Doby>/voz_cache_f5/<voz>/hora/` | Las 1440 frases de la hora de cada voz, generadas en el proyecto Doby (sección 2.4). |

### Flujo

1. **Pantalla** (`dibujar_fusion.py`), solo mientras se dibuja:
   - índice sostenido **1 s** sobre el botón **Hora** (arriba a la derecha, `BOTON_HORA = (1360, 190, 1640, 300)`)
     o la tecla **h** → se abre el menú;
   - menú con las voces de `orden_menu` de `hora.json`: índice 1 s sobre una, o teclas **1–4**; shaka, **Esc** o
     5 s sin elegir lo cierran;
   - no se abre si la mano está deletreando o deteniéndose.
2. **Hilo aparte con el candado de la mano** (`ControlMano.decir_hora`): el mismo candado del deletreo, la voz de
   los nombres y la conexión Bluetooth, así que nunca suenan a la vez. Si el candado está ocupado, espera hasta
   10 s (`SEG_ESPERA_HORA`) y si no, avisa «La mano está ocupada».
3. **`hora.decir(config, persona)`** (`fusion/hora.py`):
   - lee el **reloj del PC** (sin segundos);
   - `elegir()` busca dos archivos: la **fecha** y la **hora**;
   - comprueba que sean WAV de 16 kHz, mono, 16 bits (`leer_pcm`);
   - abre **una** conexión WiFi, manda la fecha y luego la hora (dos órdenes `wav`) y cierra;
   - anota una fila en `fusion/registros/tiempos_hora.csv` (también si falla);
   - **nunca lanza errores**: devuelve `ok`, `falta_audio`, `sin_wifi` o `error` con un mensaje para la pantalla.
4. **Placa** (`wifi_hora.py`): servidor TCP en el `PUERTO` de `config_wifi.py` (5001). Primera línea
   `auth <TOKEN>`; luego `wav <n>` + `n` bytes PCM, que suenan **mientras llegan** (bloques de 4 KB, `ibuf=20000`;
   la placa no tiene PSRAM para guardar la frase entera). Responde `voz_ok:<ms>`. Lo atiende `main.py` entre
   órdenes del Bluetooth, con 2 líneas agregadas en la placa.
5. **Vuelve a dibujar** sin borrar el lienzo, con el mensaje de lo que sonó o del error.

### De dónde salen los audios (`fusion/hora.json`)

```json
"doby": "C:/Users/miran/proyectoDoby",
"horas": "{doby}/voz_cache_f5/{voz_doby}/hora",
"fechas": "voces_clonadas/fecha/{persona}",
"rango_fechas": {"desde": "2026-11-12", "hasta": "2026-12-31"},
"orden_menu": ["jeanpaul", "harry", "lina", "paula"],
"personas": {
  "jeanpaul": {"mostrar": "Jean Paul", "voz_doby": "jenpol"},
  "harry":    {"mostrar": "Harry",     "voz_doby": "harry"},
  "lina":     {"mostrar": "Lina",      "voz_doby": "lina"},
  "paula":    {"mostrar": "Paula",     "voz_doby": "camila"}
}
```

- **Hora**: `<horas>/hora_HHMM_<md5>.wav`, por ejemplo `hora_1535_xxxxxxxx.wav`. Son las frases enteras del
  proyecto Doby, leídas tal cual. `voz_doby` es el nombre de la voz en Doby (Paula es «camila» en Doby).
- **Fecha**: `voces_clonadas/fecha/<persona>/fecha_AAAAMMDD_<md5>.wav`, una por **fecha del calendario** (el día de
  la semana depende del año), solo dentro de `rango_fechas` (hoy: 2026-11-12 a 2026-12-31, 50 fechas).
- El `<md5>` son los 8 primeros caracteres del md5 del **texto** de la frase: si cambia el texto, cambia el archivo.

### Cómo se arma la frase

No se pega nada: suenan **dos archivos completos, uno detrás del otro**.

| Parte | Texto (`hora.py`) | Ejemplo |
|---|---|---|
| Fecha | `texto_fecha(d)`: «Hoy es <día> <número> de <mes>.» (día 1 = «uno», sin año) | «Hoy es jueves doce de noviembre.» |
| Hora | `texto_hora(h, m)`, misma regla de Doby | «Son las tres y treinta y cinco de la tarde.» |

Reglas de la hora (iguales a `pc/hora.py` de Doby): reloj de 12 horas; «Es la una» / «Son las …»; minuto 0 = «en
punto», si no «y <número>»; momento del día: **madrugada** 1:00–5:59, **mañana** 6:00–11:59, **del mediodía**
12:00–12:59, **tarde** 13:00–18:59, **noche** 19:00–0:59.

Entre las dos frases hay una pausa: en la placa, unos 0,9 s (0,3 s de silencio + vaciado del I2S); en el PC
(`--voz-pc`), `PAUSA_PC = 0.4` s.

- Si **falta la fecha** (fuera de `rango_fechas`), suena **solo la hora**, con el aviso «Falta audio de la fecha …».
- Si **falta la hora**, **no suena nada**: «Falta audio de la hora HH:MM (…)».

### Plan B: por los parlantes del PC

```
py -3.11 fusion/dibujar_fusion.py --voz-pc          todo el programa; la hora sale por el PC, sin WiFi
py -3.11 fusion/hora.py --decir --voz lina --pc     solo la fecha y la hora, en el PC
```

Usa los mismos WAV y `voz_pc.sonar()` (winsound de Windows). La mano sigue deletreando por Bluetooth igual.

### Comandos útiles

```
py -3.11 fusion/hora.py                                 qué sonaría ahora con cada voz (no suena nada)
py -3.11 fusion/hora.py --fecha 2026-12-01 --a-las 00:01
py -3.11 fusion/hora.py --cobertura                     cuántas horas (de 1440) y fechas hay por voz
py -3.11 fusion/hora.py --decir --voz lina              suena en la mano por WiFi
py -3.11 fusion/hora.py --decir --voz lina --ip 192.168.43.228
py -3.11 fusion/pruebas/prueba_hora.py                  pruebas sin hardware
```

---

## 2. Cómo clonamos las voces

### 2.1 Herramientas y equipo

- **Modelo**: F5-TTS con **F5-Spanish** (`jpgallegoar/F5-Spanish`, `model_1200000.safetensors`, 1286 MB), arquitectura
  `F5TTS_Base`, vocoder `vocos-mel-24khz` (52 MB). Sin entrenar: clona con un clip de referencia de 6–12 s.
- **Control automático**: Whisper `medium` (faster-whisper) transcribe cada audio generado.
- **Entorno**: `venv_f5` con Python 3.11.9 y CUDA 12.8; versiones exactas en
  [`clonacion/requirements_clonacion.txt`](clonacion/requirements_clonacion.txt).
- **Equipo**: portátil con **NVIDIA GeForce RTX 5050 Laptop (8 GB, 8151 MiB)**, driver 621.14.
  - Memoria de GPU medida: generador F5 + Whisper en un mismo proceso, **2881 MiB**; F5 solo, ~1 GB (pico ~2 GB).
  - Con unos **4 GB de VRAM NVIDIA** debería alcanzar (estimado a partir de lo medido): **POR VERIFICAR**.
  - Sin GPU: Whisper pasa solo a la CPU (`stt.py`); F5 en CPU no se probó: **POR VERIFICAR** (sería mucho más lento).
- Todo sin internet: los scripts ponen `HF_HUB_OFFLINE=1` (los modelos deben estar descargados antes).

### 2.2 Los scripts (copiados en `clonacion/`)

Se copiaron del proyecto Doby **sin modelos, entornos, cachés, audios ni secretos**, con la misma estructura de
carpetas (`pc/`, `entrenamiento/`) para que sus importaciones funcionen. La «raíz» de esos scripts es la carpeta que
contiene `pc/` y `entrenamiento/` (en el original, `C:\Users\miran\proyectoDoby`).

| Archivo | Qué hace |
|---|---|
| `clonacion/entrenamiento/experimentos_voz/referencias_f5.py` | Prepara los clips de referencia: corta 3 clips de 6–12 s por persona en pausas naturales y escribe su `.txt` exacto (con Whisper). |
| `clonacion/entrenamiento/experimentos_voz/referencia_ef.py` | Clip extra de jenpol (`refEF`). |
| `clonacion/entrenamiento/validar_audios.py` + `preproceso.py` | Identifican los bloques del guion en las grabaciones (los usa `referencias_f5.py`). |
| `clonacion/entrenamiento/referencias_voz_f5.json` | Persona → [referencia principal, respaldo 1, respaldo 2]. |
| `clonacion/entrenamiento/experimentos_voz/f5_prueba_minima.py` | Prueba mínima: una frase con un clip. Incluye el «apaño» de `soundfile` que necesita torchaudio 2.11. |
| `clonacion/entrenamiento/generar_voces_f5.py` | El **motor** (`Motor`: carga F5 + vocoder + Whisper; `generar`, `plan_intentos`, `semilla`, `cargar_referencias`). También genera las frases de Doby (`--piloto`, `--persona`). |
| `clonacion/entrenamiento/generar_hora.py` | Las **1440 horas** de una voz con F5 y control estricto. |
| `clonacion/entrenamiento/generar_hora_noche.py` | Las 1440 horas de las 4 voces seguidas, para dejarlo toda la noche. |
| `clonacion/pc/` (`config.py`, `tts.py`, `voz_clonada.py`, `hora.py`, `texto.py`, `stt.py`) | Dependencias: configuración (tasa 16 kHz, volumen 0,35), procesado `_pulir`, textos de la hora, `normalizar` y Whisper. |
| `clonacion/referencias/referencias.csv` | Registro de los clips de referencia (texto, duración, origen). Los WAV no se copiaron. |
| `fusion/herramientas/generar_fechas.py` (ya estaba en este repo) | Las **fechas**, usando el `Motor` de Doby. |

**Rutas absolutas** (no se cambiaron): `referencias_f5.py` (línea 7), `referencia_ef.py` (línea 5) y
`f5_prueba_minima.py` (línea 20) tienen `C:\Users\miran\proyectoDoby`; en este repo, `fusion/hora.json` (`"doby"`).
Los demás scripts calculan la raíz a partir de su propia ubicación.

### 2.3 Audios de referencia

Cada integrante grabó con el celular el **guion de voces de Doby** (bloques A–E; jenpol también un bloque F de habla
libre). Para clonar se usaron el bloque **C** (habla libre, 1–2 min), **D** (frases para clonar) y **E** (lectura
continua). `referencias_f5.py` buscó tramos de **6 a 12 s** cortados en pausas naturales (≥ 0,3 s), sin muletillas y
con buena confianza de Whisper, y escribió el texto exacto en un `.txt` al lado del WAV (`referencias.csv`).
La principal de cada persona se eligió **de oído** con la prueba piloto (30-sep).

| Persona (en Doby) | Clip | Uso | Duración | Hz | Texto de referencia |
|---|---|---|---|---|---|
| jenpol (Jean Paul) | `jenpol_refE2` | **principal** | 11,1 s | 48 000 | «Por fin escuchó su nombre y respondió, hoy Doby puede encender el bombillo, prender el ventilador y mover un pequeño carro, sin embargo todavía le falta aprender algo importante, reconocer quién le está hablando.» |
| | `jenpol_refE3` | respaldo | 9,6 s | 48 000 | «Él sabrá que no debe obedecer, y cuando uno de nosotros los llame podrá contestarnos con nuestra propia voz. Parece magia, pero en realidad son matemáticas, datos y mucha paciencia.» |
| | `jenpol_refF2` | respaldo | 6,5 s | 48 000 | «Hola, mi nombre es Jean-Paul Miranda, soy estudiante de Ingeniería de Sistemas y Computación.» |
| harry | `harry_refE2` | **principal** | 11,1 s | 44 100 | «nadie sabía si iba a funcionar. Después de muchas pruebas, cables sueltos y noches sin dormir, por fin escuchó su nombre y respondió, ¡Hola, Doby! Puede encender el bombillo.» |
| | `harry_refE1` | respaldo | 10,3 s | 44 100 | «Doby nació como un proyecto de clase, pero poco a poco se convirtió en algo más, al principio solo era una placa pequeña, un micrófono y un parlante viejo sacado de un radio.» |
| | `harry_refE3` | respaldo | 6,7 s | 44 100 | «reconocer quién le está hablando para eso necesita escuchar muchas veces la voz de cada integrante del grupo» |
| lina | `lina_refC2` | **principal** | 6,7 s | 48 000 | «mi casa es acogedora y es el lugar donde puedo descansar después de un día largo, por lo general» |
| | `lina_refC1` | respaldo | 8,7 s | 48 000 | «Es un barrio bastante tranquilo, es un barrio de casas, de esos donde uno ya conoce a varios de los vecinos y normalmente se siente en un ambiente familiar.» |
| | `lina_refC3` | respaldo | 9,1 s | 48 000 | «Los fines de semana hay un poco más de movimiento porque las familias están en sus casas, salen a comprar cosas o reciben visitas.» |
| camila (Paula) | `camila_refC1` | **principal** | 8,6 s | 48 000 | «es una gata parda con las huellas rosadas, le gusta mucho el pan porque cuando era chiquita su mamá era panadera.» |
| | `camila_refC2` | respaldo | 7,0 s | 48 000 | «Tengo una perrita que se llama Laika, tiene el rostro negro y el cuerpo café.» |
| | `camila_refD3` | respaldo | 6,8 s | 48 000 | «Hoy aprendimos procesamiento de lenguaje natural, redes neuronales y reconocimiento de voz.» |

Los WAV de referencia están en `<Doby>/voz_comparacion_f5/referencias/<persona>/` (mono, frecuencia nativa del
celular). No se suben al repo.

### 2.4 Cómo se generó cada audio

Para **cada frase** (`generar_voces_f5.Motor` + `plan_intentos`):
1. F5 genera a 24 kHz con la referencia principal y una **semilla fija** (crc32 de persona, frase e intento:
   reproducible) → se pasa a **16 kHz** (`resample_poly`) → `tts._pulir` (mismo procesado del parlante) → int16.
2. Whisper `medium` transcribe **ese audio final** y se compara con el texto.
3. Hasta **6 intentos**: 3 con la referencia principal y 3 con los respaldos. Se acepta el primero que pasa el control.
4. Si ninguno pasa, el mejor va a `_revisar_de_oido/` para decidir escuchándolo (`--aprobar` / `--rechazar`).

| Qué | Control | Comando (desde la raíz de Doby) |
|---|---|---|
| **Horas** (1440 por voz) | similitud ≥ 0,95 **y** la hora y los minutos exactos (`numeros_ok`; se aceptan «doce» por «dos» con «las dos» y los homófonos de 10:06, 10:07, 10:09, 22:06, 22:07, 22:09) | `venv_f5\Scripts\python.exe entrenamiento/generar_hora.py --persona jenpol --muestra` (60 horas para escuchar) y luego `--persona jenpol` (las 1440); toda la noche: `venv_f5\Scripts\python.exe -u entrenamiento/generar_hora_noche.py` |
| **Fechas** (50 por voz) | similitud ≥ 0,95 **y** exactamente «<día> <número> de <mes>» (`hora.fecha_ok`) | desde **este** repo: `C:\Users\miran\proyectoDoby\venv_f5\Scripts\python.exe fusion/herramientas/generar_fechas.py --piloto`, luego `--estimar` y `--persona jeanpaul` (y las otras 3) |

**Tiempos reales**:

| Corrida | Resultado | Tiempo |
|---|---|---|
| Horas, noche del 15 al 16-oct-2026 (`logs/hora_noche_2026-10-15.log` de Doby) | jenpol 1435 + 5 en revisión (803 generadas esa noche, el resto antes), camila 1440/1440, harry 1435 + 5 en revisión, lina 1438 + 2 | jenpol 50 min (803 frases), camila 79,3 min, harry 91,9 min, lina 63,0 min: **unas 5 h** en total, ~3,4 s por frase |
| Fechas, 12-nov-2026 (`voces_clonadas/fecha/<persona>/generacion.csv`) | **200 de 200 aprobadas al primer intento** (piloto de 7 con jeanpaul, escuchado y aprobado) | 9,5 min de generación en total (2,2–3,3 s por fecha de media) más la carga del modelo (el script estima ~1 min por voz); harry, lina y paula entre 1,8 y 2,5 min cada una |
| Frases de Doby (referencia) | 124 frases, 386 candidatos | 18,7 min |

Hoy `py -3.11 fusion/hora.py --cobertura` da **1440/1440 horas y 50/50 fechas** para las 4 voces. Cómo se resolvieron
las 12 horas que quedaron en revisión aquella noche (de oído o regeneradas): **POR VERIFICAR** en los
`generacion.csv` de Doby.

### 2.5 Los `generacion.csv` de las fechas

`fusion/herramientas/generar_fechas.py` escribe **una fila por intento** en
`voces_clonadas/fecha/<persona>/generacion.csv`:

`fecha_hora, persona, fecha, texto, intento, referencia, texto_whisper, similitud, duracion_s, seg_intento, estado`

Ejemplo real: `2026-11-12 15:02:07, lina, 2026-11-12, Hoy es jueves doce de noviembre., 1, lina_refC2,
Hoy es jueves 12 de noviembre., 1.000, 2.21, 3.68, aprobada`. `estado` es `aprobada`, `revisar_de_oido` o
`descartada`. `--estimar` usa `seg_intento` para calcular cuánto falta. El script se puede retomar: salta lo que ya
existe (también en `_revisar_de_oido/`).

---

## 3. Paso a paso para otro grupo

Con un integrante ficticio **Ana** (clave `ana`) como ejemplo.

1. **Permiso.** Cada persona acepta que se clone su voz, solo para la fecha y la hora.
2. **Equipo y entorno.** PC con GPU NVIDIA (sección 2.1) y Python 3.11:
   ```
   py -3.11 -m venv venv_f5
   venv_f5\Scripts\python.exe -m pip install -r clonacion\requirements_clonacion.txt
   ```
   Que la instalación limpia funcione igual que el original: **POR VERIFICAR** (ver el comentario del archivo).
3. **Modelos.** Descargar F5-Spanish y el vocoder (enlaces en `requirements_clonacion.txt`) a
   `clonacion/modelos/f5-spanish/` (`model_1200000.safetensors`, `vocab.txt`, `vocos-mel-24khz/config.yaml`,
   `vocos-mel-24khz/pytorch_model.bin`), y dejar descargado Whisper `medium` (POR VERIFICAR el comando exacto).
   `clonacion/modelos/` y las demás salidas están en `.gitignore`.
4. **Grabar.** Cada persona graba con el celular **1–2 minutos de habla libre**, en un lugar silencioso, con voz
   natural y sin muletillas.
5. **Clips de referencia.** Por persona, **3 clips de 6–12 s**, cortados en pausas, en
   `clonacion/voz_comparacion_f5/referencias/ana/ana_refC1.wav` (mono), cada uno con su `.txt` al lado con **el texto
   exacto** de lo que se dice (`ana_refC1.txt`).
   - A mano (Audacity u otro editor): lo más simple.
   - Automático con `referencias_f5.py`: está hecho para el guion de Doby (personas, bloques y carpetas
     `datos_voz/originales/<Nombre>/` escritos en el script, y la ruta absoluta de la línea 7). Adaptarlo:
     **POR VERIFICAR**.
6. **`clonacion/entrenamiento/referencias_voz_f5.json`**: `"ana": ["ana_refC1", "ana_refC2", "ana_refC3"]` (la
   primera es la principal). Para elegirla de oído:
   `venv_f5\Scripts\python.exe clonacion/entrenamiento/generar_voces_f5.py --piloto --persona ana` (genera 2 frases de
   Doby con cada referencia en `clonacion/voz_cache_f5/_piloto/ana/`).
7. **Las 1440 horas**, desde la carpeta del repo:
   ```
   venv_f5\Scripts\python.exe clonacion/entrenamiento/generar_hora.py --persona ana --muestra
   venv_f5\Scripts\python.exe clonacion/entrenamiento/generar_hora.py --persona ana
   ```
   Salen en `clonacion/voz_cache_f5/ana/hora/` (~1–1,5 h por voz en la RTX 5050). Para las de revisión:
   `--aprobar ana 2123` / `--rechazar ana 2123`. `generar_hora_noche.py` sirve para varias voces seguidas, pero
   tiene la lista `VOCES = ["jenpol", "camila", "harry", "lina"]` escrita en el código: hay que cambiarla.
8. **`fusion/hora.json`** de este repo:
   ```json
   "doby": "C:/ruta/completa/al/repo/clonacion",
   "orden_menu": ["ana"],
   "personas": {"ana": {"mostrar": "Ana", "voz_doby": "ana"}},
   "rango_fechas": {"desde": "AAAA-MM-DD", "hasta": "AAAA-MM-DD"},
   "piloto": {"persona": "ana", "fechas": ["7 fechas dentro del rango, una por día de la semana"]}
   ```
   `"doby"` es la carpeta que tiene `pc/`, `entrenamiento/`, `modelos/` y `voz_cache_f5/` (aquí, `clonacion/`). Usar
   ruta **absoluta** (sección 4). El menú del botón tiene sitio para 4 voces.
9. **Las fechas** (`voces_clonadas/fecha/ana/`):
   ```
   venv_f5\Scripts\python.exe fusion/herramientas/generar_fechas.py --piloto
   venv_f5\Scripts\python.exe fusion/herramientas/generar_fechas.py --estimar
   venv_f5\Scripts\python.exe fusion/herramientas/generar_fechas.py --persona ana
   ```
   Escuchar el piloto antes de seguir. Las de `_revisar_de_oido/`: `--aprobar ana AAAA-MM-DD` o `--rechazar ana
   AAAA-MM-DD` (genera otra con semillas nuevas).
10. **Verificar**:
    - `py -3.11 fusion/hora.py --cobertura` → 1440/1440 horas y todas las fechas;
    - `py -3.11 fusion/hora.py --decir --voz ana --pc` → suena en el PC;
    - `py -3.11 fusion/hora.py --decir --voz ana` → suena en la mano por WiFi;
    - `py -3.11 fusion/pruebas/prueba_hora.py`: algunas comprobaciones usan las voces actuales (orden del menú,
      `jeanpaul→jenpol`) y hay que adaptarlas: **POR VERIFICAR** cuáles exactamente.

---

## 4. Si `hora.json` apunta a una ruta que no existe

`fusion/hora.json` trae `"doby": "C:/Users/miran/proyectoDoby"`, que solo existe en el PC original.

**Qué pasa en otro PC:**
- `py -3.11 fusion/hora.py --cobertura` muestra `horas 0/1440`;
- el botón Hora dice «Falta audio de la hora HH:MM (…)» y **no suena nada** (sin la hora tampoco suena la fecha);
- el resto del programa (dibujar, deletrear, voz de los nombres) funciona igual;
- `prueba_hora.py` se salta la parte de Doby («no está …: se salta»);
- `generar_fechas.py` no puede generar (importa el motor desde esa carpeta).

**Qué hacer:**
1. **Si el PC tiene las horas** (el proyecto Doby o solo las carpetas `voz_cache_f5/<voz>/hora/`, unos 98–136 MB por
   voz), poner en `"doby"` la ruta **absoluta** real, con `/`. Si solo están las carpetas de horas en otro lugar,
   cambiar `"horas"`, por ejemplo `"D:/voces/{voz_doby}/hora"`.
   - Ojo: `"horas"` y `"doby"` relativas se resuelven desde la carpeta donde se ejecuta el comando (no desde el
     repo), por eso mejor absolutas. `"fechas"` sí es relativa a la raíz del repo.
2. **Las fechas** (`voces_clonadas/`) no van en git: copiarlas aparte o regenerarlas (sección 3, paso 9).
3. **Sin horas ni GPU**: no usar el botón Hora; todo lo demás sigue igual. Para generarlas, sección 3.

Otros archivos con rutas del PC original: `fusion/pruebas/prueba_wifi_envio.py` (`DOBY_VOCES`, línea 46; solo esa
prueba de la fase WiFi), el comentario de uso de `fusion/herramientas/generar_fechas.py` y los 3 scripts de
`clonacion/` de la sección 2.2.
