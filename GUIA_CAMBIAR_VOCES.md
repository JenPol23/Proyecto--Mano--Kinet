# Guía: usar el proyecto con otro grupo (otros nombres y otras voces)

Esta guía explica cómo adaptar el proyecto (Kinect → TrOCR → mano robótica LSC → voz original) a un grupo
nuevo de compañeros. Todo lo que dice sale del código actual; lo que no se pudo comprobar está marcado
**POR VERIFICAR**.

Todos los comandos se ejecutan desde la carpeta del proyecto, con Python 3.11 (`py -3.11`). Para convertir los
audios hacen falta **ffmpeg** y **ffprobe** instalados y en el PATH (los usa `fusion/voz.py`).

---

## 1. Qué archivos tocar y cuáles NO

### Se tocan

| Archivo o carpeta | Para qué |
|---|---|
| `fusion/integrantes.json` | **El único archivo de configuración de las personas**: nombres, apellidos, frases y qué audio corresponde a cada uno. |
| `voces/` | Las grabaciones originales de cada integrante (entrada). Solo se leen. |
| `/voz` en la placa | Los WAV convertidos, que se suben con Thonny (sección 6). |
| `fusion/reconocer.py`, lista `PRUEBAS` | Solo los casos de prueba (sección 4). No cambia el funcionamiento. |
| `fusion/hora.json` | Solo si se quiere el botón **Hora** con el grupo nuevo (ver «Botón Hora» abajo). |

### No se tocan

| Archivo | Por qué |
|---|---|
| `firmware_mano/main.py` | El firmware de la placa: dedos, letras (`acciones`), Bluetooth y la orden `voz`. No depende de los nombres. |
| `firmware_mano/wifi_hora.py` | El audio de la hora por WiFi. No depende de los nombres. |
| `LETRAS_ESTATICAS` en `fusion/reconocer.py` | Debe ser igual a la tabla de letras del firmware (las 21 que hace la mano). |
| `fusion/consola_mano.py` | Protocolo BLE con la mano (UART de Nordic, `auth <TOKEN>`). |
| `config_ble.py` | Nombre BLE y TOKEN de la placa. Solo cambia si se usa **otra placa**. Es secreto: no va a git. |
| `fusion/voz.py`, `fusion/config_fusion.py` | Conversión de audio. Solo `VOLUMEN` de `config_fusion.py` se puede bajar si el parlante distorsiona (máximo 0,5). |
| `fusion/dibujar_fusion.py`, `fusion/pantalla_mano.py` | Programa principal y pantalla. Leen los nombres de `integrantes.json`. |

### Botón Hora (fecha y hora con voz clonada)

El botón **Hora** usa voces **clonadas** de los 4 integrantes actuales, generadas con el proyecto Doby
(`fusion/hora.json` → carpeta `C:/Users/miran/proyectoDoby`) y `voces_clonadas/`. Para otro grupo **no existen
esas voces**:
- si la carpeta de Doby no está, al pedir la hora sale «Falta audio de la hora …» y no suena nada; el resto del
  programa sigue igual;
- el menú del botón muestra los nombres de `orden_menu` y `personas` de `fusion/hora.json`; si no se va a usar la
  hora, simplemente no se pulsa el botón ni la tecla `h`;
- para clonar las voces de personas nuevas (F5-TTS, scripts en `clonacion/` y
  `fusion/herramientas/generar_fechas.py`) y para qué hacer si `hora.json` apunta a una ruta que no existe, ver
  [GUIA_VOZ_CLONADA_Y_HORA.md](GUIA_VOZ_CLONADA_Y_HORA.md).

---

## 2. `fusion/integrantes.json`

### Estructura

```json
{
  "carpetas_audio": ["voces"],
  "extensiones": [".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".mpeg"],
  "no_usar": ["Jean.wav", "0-000.wav", "output.wav"],
  "pausa_entre_palabras_ms": 250,
  "personas": {
    "<clave>": {
      "nombre_completo": "Nombre completo para mostrar",
      "palabras": [
        {"texto": "Nombre",   "tipo": "nombre",   "audio": "Nombre"},
        {"texto": "Apellido", "tipo": "apellido", "audio": "Apellido"}
      ],
      "frases": [
        {"palabras": ["Nombre", "Apellido"], "audio": "Nombre_Apellido"}
      ]
    }
  },
  "ambiguos": {}
}
```

| Campo | Qué es |
|---|---|
| `carpetas_audio` | Dónde se buscan las grabaciones (relativo a la raíz del proyecto). Hoy: `voces`. |
| `extensiones` | Extensiones aceptadas, **en orden de preferencia** si hay dos archivos con el mismo nombre. |
| `no_usar` | Archivos de `voces/` que se ignoran aunque coincidan (nombre completo del archivo). |
| `pausa_entre_palabras_ms` | Pausa entre palabras sueltas cuando no hay frase grabada (250 ms). |
| `<clave>` | Identificador interno de la persona (minúsculas, sin espacios). Aparece en los registros. |
| `nombre_completo` | Se muestra entre paréntesis en la confirmación. No se usa para reconocer. |
| `palabras` | **Lo que se puede dibujar**, en el orden en que se acepta. `texto` es como se muestra (con tildes); la mano y el OCR lo usan sin tildes. `tipo` es `nombre` o `apellido`. `audio` es el nombre base del archivo de voz. |
| `frases` | Combinaciones que tienen su propia grabación. Si lo reconocido es **exactamente** una frase y su audio existe, suena solo ese archivo; si no, se unen las palabras sueltas. |
| `ambiguos` | Qué persona elegir cuando una palabra sola sirve para dos personas (ver abajo). |

Reglas que aplica el código (`fusion/reconocer.py`, función `interpretar`):
- Se acepta cualquier grupo de palabras de **una misma persona**, **en el orden** de `palabras` y sin repetir.
- Mezcla de personas, desorden o una palabra repetida → «No coincide con un integrante».
- Una palabra que no está en `palabras` (por ejemplo, un segundo apellido) → «No coincide con un integrante».
- Como máximo se dibujan **4 palabras** (`MAX_PALABRAS` en `dibujar_fusion.py`).
- Regla del proyecto: **solo el primer apellido**.

### Alias: mostrar y reconocer solo una parte del nombre

Solo se reconoce lo que está en `palabras`. `nombre_completo` es solo el texto que se muestra entre paréntesis.
Con Harry: `nombre_completo` es «Harry Raigozo» y en `palabras` están «Harry» y «Raigozo». Así, «Harry»
funciona y «Jean Harry» se rechaza (porque «Jean» es de Jean Paul).

```json
"harry": {
  "nombre_completo": "Harry Raigozo",
  "palabras": [
    {"texto": "Harry",   "tipo": "nombre",   "audio": "Harry"},
    {"texto": "Raigozo", "tipo": "apellido", "audio": "Raigozo"}
  ],
  "frases": [{"palabras": ["Harry", "Raigozo"], "audio": "Harry_Raigozo"}]
}
```

### Dos personas con el mismo nombre

Comprobado con el código, con dos personas «Ana Gómez» y «Ana Pérez»:

| Se dibuja | Resultado |
|---|---|
| `Ana` | **Rechazado**: «No coincide con un integrante» (detalle en consola: `ambiguo: ana, anap`). |
| `Ana Gomez` | Ana Gómez (el apellido desempata). |
| `Ana Perez` | Ana Pérez. |

Para que «Ana» sola vaya a una persona, se agrega en `ambiguos` la palabra normalizada (minúsculas, sin tildes)
y la clave de esa persona. Hoy se hace así con «Jean» → Jean Paul:

```json
"ambiguos": {"ana": "ana"}
```

Cada persona necesita su **propio** archivo de audio para «Ana» (el campo `audio` debe ser distinto, por ejemplo
`"Ana"` y `"Ana_P"`), porque cada uno graba con su voz.

### Nombres parecidos

Si dos palabras del grupo se parecen mucho (hoy «Paul» y «Paula»), un dibujo dudoso como «Pauls» da
«¿Paul o Paula? Dibuja de nuevo». Lo controlan `UMBRAL = 0.75` y `MARGEN = 0.10` en `fusion/reconocer.py`; no
hace falta cambiarlos para un grupo nuevo, pero conviene probar los nombres (sección 4).

---

## 3. Audios por persona

### Lista exacta

Por cada persona se graba **un archivo por cada `audio`** que aparezca en `palabras` y en `frases`. El grupo
actual tiene 18 (Jean Paul 5, Harry 3, Lina 5, Paula 5): por ejemplo Lina graba `Lina`, `Tatiana`,
`Maldonado`, `Lina_Maldonado` y `Lina_Tatiana_Maldonado`.

La lista exacta de un grupo nuevo la da el propio programa, con ✔ o ✗ por archivo:

```
py -3.11 fusion/voz.py --preparar
```

Para cada audio que falta imprime `✗ <palabra>  FALTA  (grabar como voces/<Audio>.*)`.

### Convención de nombres

- El archivo se llama como el campo `audio`, **sin tildes, sin ñ y con guion bajo** entre palabras:
  `Gomez`, `Ana_Gomez`, `Munoz`. Los nombres en la placa son esos mismos en minúsculas (`ana_gomez.wav`).
- Sin mayúsculas/minúsculas importantes: `ANA.m4a` vale para `Ana`.
- Solo letras y `_`: el firmware rechaza otros caracteres en la orden `voz` (comprueba `isalpha()` o `_`).
  Por eso **nada de números, guiones ni espacios**. Si `ñ` pasa ese control en MicroPython: **POR VERIFICAR**;
  más seguro escribir `n`.
- Extensiones aceptadas: `.mp3 .mp4 .m4a .wav .ogg .mpeg`. Vale la doble extensión de WhatsApp
  (`Gomez.mp3.mpeg` cuenta como `Gomez`; comprobado).
- `.opus` (notas de voz de WhatsApp) **no** está en la lista: el archivo no se encuentra (comprobado). Se puede
  convertir a `.m4a` o `.mp3`, o agregar `".opus"` a `extensiones` en `integrantes.json`; que ffmpeg lo lea bien
  así está **POR VERIFICAR**.

### El problema del « (1)» de Windows

Si un archivo se descarga dos veces, Windows lo guarda como `Ana (1).m4a`. El programa busca el nombre
**exacto** y no lo encuentra (comprobado): sale «Falta audio: Ana». Lo mismo pasa con un espacio antes del punto
(`Ana_Gomez .m4a`) o con tildes en el nombre del archivo (`Gómez.m4a`). Solución: renombrar el archivo para que
se llame exactamente como el campo `audio`.

Consejo: en el Explorador, activar **Vista → Mostrar → Extensiones de nombre de archivo** para ver el nombre real.

### Formato y recomendaciones de grabación

- **Al menos 1 segundo**, con unos 0,3–0,5 s de silencio **antes y después** de hablar. El programa **no recorta
  nada** (`RECORTAR_SILENCIO = False` en `config_fusion.py`): un audio cortado justo en la voz se oye incompleto.
- Cada persona graba **con su propia voz** (regla del proyecto: sin voces sintéticas ni clonadas para los nombres).
- Lugar silencioso, el celular a unos 20–30 cm, sin saturar (que no se oiga «rajado»).
- El volumen se iguala solo: `voz.py` normaliza el pico de cada grabación a `VOLUMEN` (0,35) y quita graves
  (100 Hz). Todo queda en WAV de 16 kHz, mono, 16 bits.
- Los originales de `voces/` **solo se leen**; las conversiones van a `fusion/cache_audio/` y
  `fusion/audios_placa/`. Si se reemplaza una grabación, la conversión se rehace sola (cambia la huella del
  archivo) la próxima vez que se ejecute `voz.py --preparar`.

---

## 4. Reconocimiento del Kinect (TrOCR)

**No hay que entrenar ni registrar nada en TrOCR.** El modelo (`microsoft/trocr-large-handwritten`, local) lee lo
que se dibuja como texto libre; después `fusion/reconocer.py` compara cada palabra con el vocabulario de
`integrantes.json` (exacta o parecida: similitud ≥ 0,75). Basta con poner los nombres nuevos en
`integrantes.json`.

Para probar un nombre sin Kinect:

```
py -3.11 fusion/reconocer.py --texto "Ana Gomez"
```

Muestra lo que entendió, cómo lo deletrea la mano y si encuentra cada audio (`✔ voces/...` o `FALTA`).

### Agregar casos a las pruebas

Los casos fijos están en la lista `PRUEBAS` de `fusion/reconocer.py`, como `(texto, esperado)`:

```python
("Ana Gomez", dict(ok=True, persona="ana", mostrar="Ana Gómez", tipo="nombre y apellido")),
("Anna Gmez", dict(ok=True, persona="ana", mostrar="Ana Gómez", tipo="nombre y apellido")),   # parecido
("Gomez Ana", dict(ok=False, motivo=NO_COINCIDE)),                                         # desorden
```

y se corren con:

```
py -3.11 fusion/reconocer.py --pruebas
```

Los casos actuales usan los nombres del grupo actual: con un grupo nuevo hay que **reemplazarlos**. Otras
pruebas de `fusion/pruebas/` también usan esos nombres (por ejemplo `prueba_dibujar_falsa.py`,
`prueba_voz_ble_falsa.py`, `prueba_voz_pc_falsa.py`, `prueba_reloj.py`, `prueba_hora.py`,
`prueba_boton_hora_falsa.py`) y fallarán hasta adaptarlas. Qué casos exactos hay que cambiar en cada una:
**POR VERIFICAR**.

---

## 5. Letras que la mano no hace

La mano forma las **21 letras estáticas** del LSC: `a b c d e f i k l m n o p q r t u v w x y`.

Las letras **con movimiento** (`g h j ñ s z`) no las hace la mano: cuando llega una, la mano **se abre** y la
letra se muestra en la pantalla (panel de `pantalla_mano.py`); después sigue con el resto de la palabra. `rr` y
`ll` se deletrean como dos letras.

Antes de deletrear, el texto se normaliza: minúsculas, **sin tildes** (`Gómez` → `gomez`; `ü` → `u`), la `ñ` se
conserva, los números se quitan y cualquier otro signo separa palabras (`Ana-María` serían dos palabras, `ana` y
`maria`, y las dos tendrían que estar en `palabras`).

Ejemplos reales (`reconocer.py`):

| Palabra | Lo que hace la mano (`[X]` = mano abierta + pantalla) |
|---|---|
| Ana | `ana` |
| Gómez | `[G] + ome + [Z]` |
| Muñoz | `mu + [Ñ] + o + [Z]` |
| Raigozo | `rai + [G] + o + [Z] + o` |

---

## 6. Pasar los audios a la placa

1. **Convertir** (en el PC):
   ```
   py -3.11 fusion/voz.py --preparar
   ```
   Deja un WAV por audio en `fusion/audios_placa/` (nombre en minúsculas) y al final dice
   «Listos N de M audios: X KB en total». Si falta alguno, lo lista.

2. **Subir con Thonny** (placa por **USB, sin los 12 V**; no van a la vez):
   Thonny → **Ver → Archivos**; en la placa crear la carpeta **`/voz`** si no existe; seleccionar todos los `.wav`
   de `fusion/audios_placa/` → clic derecho → **«Subir a /voz»**.

3. **Espacio en la flash**: un WAV ocupa unos **32 KB por segundo** (16 kHz × 2 bytes). Los 17 WAV del grupo
   actual suman unos **1 477 KB** (el mayor, 286 KB). Para ver el espacio libre, en la consola de Thonny (después
   de pulsar Stop):
   ```python
   import os; s = os.statvfs('/'); print(s[0] * s[3] // 1024, 'KB libres')
   ```
   Cuánto espacio total tiene el sistema de archivos de esta placa: **POR VERIFICAR** con ese comando.

4. **Borrar los WAV viejos** (del grupo anterior): en el panel de archivos de Thonny, clic derecho sobre el archivo
   de la placa → eliminar (el nombre exacto del menú: **POR VERIFICAR**). O desde la consola de Thonny:
   ```python
   import os; print(os.listdir('/voz'))
   os.remove('/voz/lina.wav')
   ```
   Borrar **solo** archivos de `/voz`. No tocar `main.py`, `config_ble.py`, `config_wifi.py` ni `wifi_hora.py`.

5. **Cerrar Thonny** y reiniciar la placa: con Thonny conectado, `main.py` queda en pausa y la mano no responde
   por Bluetooth ni por WiFi.

Los WAV viejos de `fusion/audios_placa/` en el PC no estorban (solo se usan los que nombra `integrantes.json`),
pero se pueden borrar a mano para no confundirse.

---

## 7. Checklist de verificación

En el PC, sin la placa:
- [ ] `py -3.11 fusion/reconocer.py --texto "<Nombre Apellido>"` → «Entendí …» y `✔` en cada audio.
- [ ] `py -3.11 fusion/reconocer.py --pruebas` → todos los casos pasan (con `PRUEBAS` actualizada).
- [ ] `py -3.11 fusion/voz.py --preparar` → «Listos N de N».
- [ ] WAV subidos a `/voz` y Thonny **cerrado**.

Con la placa (12 V, sin USB, Bluetooth del PC activado):
- [ ] `py -3.11 fusion/consola_mano.py` y, dentro:
  - `!version` → `version:voz-2`
  - `!voz ana` → `voz_ok` y se oye la palabra
  - `!voz ana_gomez` → `voz_ok` y se oye la frase
  - `!voz xyz` → `voz_falta:xyz` (comprueba que la placa avisa cuando falta un archivo)
  - escribir `Ana Gomez` → la mano deletrea
  - `salir`
- [ ] `py -3.11 fusion/voz.py --texto "Ana Gomez" --deletrear` → deletrea con el panel y al final suena.
- [ ] Prueba completa: `py -3.11 fusion/dibujar_fusion.py`, dibujar el nombre con el Kinect, confirmar con 👍
      1,5 s → la mano deletrea y suena la voz.
- [ ] Plan B: `py -3.11 fusion/dibujar_fusion.py --voz-pc` → la voz suena por los parlantes del PC.

---

## 8. Problemas comunes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| «Falta audio: X» en el PC | El archivo de `voces/` no se llama exactamente como `audio`: « (1)», espacio, tildes, `.opus`, otra carpeta, o está en `no_usar`. | Renombrar (sección 3) y volver a `voz.py --preparar`. |
| La placa responde `voz_falta:x` | El WAV no está en `/voz` de la placa, o tiene otro nombre. | Subirlo con Thonny (sección 6). En la placa el nombre va en minúsculas. |
| «¿X o Y? Dibuja de nuevo» | Dos nombres del grupo se parecen mucho. | Dibujar más claro; si pasa siempre, probar con `reconocer.py --texto`. |
| «No coincide con un integrante» | Mezcla de personas, desorden, palabra repetida, segundo apellido, palabra que no está en `palabras`, o nombre compartido sin `ambiguos`. | Revisar `integrantes.json`; ver el detalle que imprime la consola. |
| La voz se oye cortada al inicio o al final | Grabación de menos de 1 s o sin silencio antes/después. | Volver a grabar. |
| La voz distorsiona | Volumen alto para el parlante de 1,5 W. | Bajar `VOLUMEN` en `config_fusion.py` (máximo 0,5) y volver a `voz.py --preparar` y subir los WAV. |
| «ffmpeg no pudo leerlo» | ffmpeg/ffprobe no instalados o archivo dañado. | Instalar ffmpeg y comprobar que el audio se abre en el PC. |
| Cambié una grabación y suena la vieja | En el PC se reconvierte sola, pero en la placa sigue el WAV viejo. | `voz.py --preparar` y volver a subir ese WAV. |
| La mano no responde | Thonny abierto (pausa `main.py`), otro programa conectado por BLE, o sin 12 V. | Cerrar Thonny y `consola_mano.py`; un solo programa a la vez. |
| La voz de la placa suena con interferencia | Hardware: contactos o alimentación del MAX98357 (pasa a ratos, con o sin WiFi). | Revisar cables; mientras tanto, `dibujar_fusion.py --voz-pc`. |
| El botón Hora dice «Falta audio de la hora» | No hay voces clonadas para el grupo nuevo (sección 1). | No usar la hora, o generar las voces clonadas: [GUIA_VOZ_CLONADA_Y_HORA.md](GUIA_VOZ_CLONADA_Y_HORA.md). |

---

## 9. Ejemplo completo: Ana Gómez

Integrante ficticia: **Ana María Gómez**. Se quiere reconocer «Ana», «Gómez» y «Ana Gómez» (alias: «María» no
se usa).

**1. `fusion/integrantes.json`**, dentro de `"personas"`:

```json
"ana": {
  "nombre_completo": "Ana María Gómez",
  "palabras": [
    {"texto": "Ana",   "tipo": "nombre",   "audio": "Ana"},
    {"texto": "Gómez", "tipo": "apellido", "audio": "Gomez"}
  ],
  "frases": [
    {"palabras": ["Ana", "Gómez"], "audio": "Ana_Gomez"}
  ]
}
```

**2. Grabaciones** (Ana, con su voz, al menos 1 s con silencio antes y después), en `voces/`:

| Dice | Archivo | En la placa |
|---|---|---|
| «Ana» | `voces/Ana.m4a` | `/voz/ana.wav` |
| «Gómez» | `voces/Gomez.m4a` | `/voz/gomez.wav` |
| «Ana Gómez» | `voces/Ana_Gomez.m4a` | `/voz/ana_gomez.wav` |

**3. Probar el reconocimiento** (resultados reales con el código actual):

```
py -3.11 fusion/reconocer.py --texto "Ana Gomez"
```

| Se dibuja | Resultado | La mano |
|---|---|---|
| `Ana Gomez` | Ana Gómez (nombre y apellido) | `ana` \| `[G] + ome + [Z]` |
| `ana` | Ana (nombre) | `ana` |
| `GOMEZ` | Gómez (apellido) | `[G] + ome + [Z]` |
| `Anna Gmez` | Ana Gómez (se parece lo suficiente) | igual que arriba |
| `Gomez Ana` | Rechazado: desorden | — |
| `Ana Maria` | Rechazado: «maria» no está en `palabras` | — |

**4. Qué suena**: «Ana Gómez» es exactamente la frase → suena solo `ana_gomez.wav`. Si esa frase no estuviera
grabada, sonaría `ana.wav` + 250 ms + `gomez.wav`.

**5. Casos de prueba** en `PRUEBAS` de `fusion/reconocer.py`:

```python
("Ana Gomez", dict(ok=True, persona="ana", mostrar="Ana Gómez", tipo="nombre y apellido",
                   tramos=[[("mano", "ana")], [("movimiento", "g"), ("mano", "ome"), ("movimiento", "z")]])),
("Gomez Ana", dict(ok=False, motivo=NO_COINCIDE)),
```

**6. Placa**: `py -3.11 fusion/voz.py --preparar` → subir `ana.wav`, `gomez.wav` y `ana_gomez.wav` a `/voz` →
cerrar Thonny → 12 V.

**7. Verificar**: `py -3.11 fusion/consola_mano.py` → `!voz ana_gomez` → `voz_ok`; escribir `Ana Gomez` → la
mano deletrea; después la prueba completa con `py -3.11 fusion/dibujar_fusion.py`.
