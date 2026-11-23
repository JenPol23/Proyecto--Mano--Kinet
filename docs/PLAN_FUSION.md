# Plan de fusión: Kinect → mano → voz

Proyecto nuevo: se dibuja en el aire con el Kinect el nombre, el apellido o el nombre y apellido de un
integrante. La mano robótica lo deletrea letra por letra en lengua de señas colombiana (LSC) y, al terminar,
un MAX98357 conectado a la **misma ESP32 de la mano** lo dice con la **voz original grabada** de esa persona.
Todo corre local, sin APIs en la nube, y **todo va por Bluetooth BLE: nada por WiFi**.

Estado: **propuesta aprobada con correcciones (punto A, versión 2)**. Sin código todavía. Las decisiones
abiertas están en la §9.

---

## 1. Reglas de trabajo (acordadas)

1. **La carpeta es autosuficiente:** nada del proyecto importa ni lee `Dibujar/`, `proyectoDoby/` ni rutas de
   fuera (salvo la caché de Hugging Face de TrOCR y ffmpeg en el PATH). Lo que hacía falta de esas carpetas se
   **copió** (los originales no se tocan hasta la limpieza): los audios a `voces/`, `dibujar.py` a
   `fusion/referencia/dibujar_original.py`, `palabra.png` a `fusion/pruebas/`, la guía de gráficas a
   `guia_graficas/`, y `normalizar`, `_pulir` y el I2S de Doby dentro del código.
2. Estructura: `voces/` (entrada única de audios), `fusion/` (programa del PC; `audios_placa/` = salida,
   `cache_audio/`, `registros/`, `pruebas/`, `referencia/`), `firmware_mano/` (firmware oficial), `guia_graficas/`,
   `docs/` (este plan, `LISTA_GRABACION.md`, `pruebas_dedos.md`). `main.py`, `consola_pc.py` y `prueba.py` de la
   raíz son los originales de la mano y no se modifican.
3. Los audios originales de `voces/` solo se leen. Las conversiones van a `fusion/cache_audio/` y
   `fusion/audios_placa/`.
4. **No se sube nada a ninguna ESP32**: el usuario sube con Thonny el firmware y los WAV. El firmware oficial de
   la mano es `firmware_mano/main.py` (pines nuevos, pulgar2 700/2300, `reset_all` desde el pulgar y la orden
   `voz`); el `main.py` de la raíz queda como el original.
5. Antes de crear o tocar cada archivo, se avisa cuál es y se espera el visto bueno.
6. La limpieza (borrar `Dibujar/` y `proyectoDoby/`) se hace **al final**, cuando el usuario haya probado el
   programa completo (punto D), y después de confirmar que `C:\Users\miran\proyectoDoby` existe completo.
7. **No se clona ninguna voz ni se usa VITS para los nombres.** Solo suenan grabaciones originales.

## 2. Arquitectura

Un solo programa en **Python 3.11 del sistema** (`py -3.11`), que ya tiene mediapipe, opencv,
transformers, bleak y numpy. Se usan hilos para no congelar la ventana del Kinect. **Una sola placa**, la
ESP32-S3 N16R8 de la mano, con BLE (servicio UART de Nordic) y firmware `firmware_mano/main.py`:

- **Servos:** índice 1, meñique 2, medio 42, anular 4, pulgar 40, pulgar2 39 (PWM).
- **MAX98357 (I2S):** DIN → GPIO 7, BCLK → GPIO 15, LRC → GPIO 16 (los mismos pines con los que funcionaba en
  Doby), GAIN y SD sin conectar, el parlante solo a + y −. No chocan con los servos (1, 2, 4, 39, 40, 42) ni con
  nada más del firmware. El GPIO 48 (LED RGB) ya no se usa.
- **Alimentación del MAX98357: VIN → pin 3V3 de la ESP32, GND → GND de la ESP32, siempre (con USB y con 12 V).
  Nunca al pin 5Vin si la placa va por USB.** Por qué: en esta placa (tipo YD-ESP32-S3, USB con CH343 y LED RGB en
  el GPIO 48) el pin 5Vin está separado del USB por unos pads rotulados **«IN-OUT»**. Con los pads separados (como
  vienen), el pin 5Vin no entrega los 5 V del USB: sirve solo como *entrada* de una fuente externa. Por eso, con VIN
  en 5Vin, la placa respondía `voz_ok` (el I2S sí sacaba el audio, con los tiempos correctos) pero el amplificador
  no tenía corriente y no sonaba nada. Diagnóstico del 2026-10-28 con mpremote: tono de 440 Hz con la
  configuración de Doby → mudo con VIN en 5Vin, suena con VIN en 3V3; después jean.wav con `reproducir_voz()` del
  firmware `voz-2` → suena completo (confirmado de oído). El firmware `voz-2` no necesitó cambios. A 3,3 V el MAX98357 da menos potencia que a 5 V, pero alcanza para el parlante.
  Recomendado: condensador de 220–470 µF entre VIN y GND pegado al módulo.
- Sin micrófono ni reconocimiento de voz. La ESP32 de Doby (WiFi) no se usa: `esp32_voz.py` y `VozWifi` quedan
  fuera del flujo.

```
 Kinect (webcam 1, MediaPipe)                                   fusion/dibujar_fusion.py
   │ mano abierta = levantar el lápiz (solo deja de dibujar)     (copia de dibujar.py)
   │ pulgar abajo 1 s = siguiente palabra (se lee sola y se
   │             agrega a la lista «Jean | …»; el lienzo se limpia)
   │ pulgar arriba = terminar (se lee la última y se unen todas)
   ▼
 una imagen por palabra ──► TrOCR ──► "Jean" + "Miranda" ──► "Jean Miranda"   fusion/reconocer.py
                                                   │
                         normalizar + coincidencia aproximada
                         contra fusion/integrantes.json
                                                   ▼
                 resultado: persona + palabras canónicas + tipo (nombre / apellido / nombre+apellido)
                                                   │
                     CONFIRMACIÓN EN PANTALLA ("Leí: … → Entendí: …")
                     pulgar arriba = sí · shaka = cancelar
                                                   ▼
 Mano por BLE ◄── deletrea por tramos de letras estáticas         fusion/consola_mano.py (clase Mano)
   letras con movimiento: en grande en pantalla + mano abierta
   respuestas: gesto_x_ok · letra_actual:x · deletreo_completo · reset_ok
                                                   │  (espera el cierre del ÚLTIMO tramo)
                                                   ▼
 Voz original: frase grabada o palabras sueltas                            fusion/voz.py
   BLE "voz lina_maldonado" / "voz tatiana maldonado"                     Mano.hablar()
   la placa suena /voz/*.wav (250 ms entre archivos) → voz_ok / voz_falta
                                                   ▼
                                     vuelve a DIBUJANDO
```

### Estados del programa

`DIBUJANDO → RECONOCIENDO → CONFIRMANDO → DELETREANDO → HABLANDO → DIBUJANDO`

- Mientras no esté en `DIBUJANDO`, se ignoran el gesto de guardar y el dibujo, para no lanzar dos flujos a la vez.
- La barra superior muestra el estado, el texto entendido y la **letra actual** en grande.
- Cualquier error (BLE caído, audio que falta en el PC o en la placa, OCR vacío) se muestra en
  pantalla y el programa vuelve a `DIBUJANDO`. **Nunca se cae.**

### Archivos nuevos propuestos (se piden uno por uno)

| Archivo | Qué hace | Base |
|---|---|---|
| `docs/LISTA_GRABACION.md` | Qué audios faltan y con qué nombre de archivo ponerlos en `voces/` | nuevo (punto B) |
| `fusion/integrantes.json` | Mapeo palabra → persona → archivo de audio | nuevo |
| `fusion/reconocer.py` | TrOCR con todas las palabras, normalización y coincidencia aproximada | `ocr_a_txt()` de `dibujar.py` + `normalizar()` de `texto.py` (copiada) |
| `fusion/consola_mano.py` | Clase `Mano` (cliente BLE persistente: auth, deletreo por tramos, espera de respuestas) + prueba por consola. Un solo archivo; reemplaza al `mano_ble.py` de la versión anterior del plan | lógica copiada de `consola_pc.py`, corregida |
| `fusion/config_fusion.py` | Tasa, volumen, procesado y recorte de silencio (la IP de Doby queda sin usar) | valores de la configuración de Doby (copiados) |
| `fusion/esp32_voz.py` | Cliente TCP del parlante de Doby. **Fuera del flujo** (no se usa) | copia recortada de `esp32_cliente.py` |
| `fusion/voz.py` | Convierte los audios, prepara `fusion/audios_placa/`, elige frase o palabras y manda `voz` por BLE | nuevo + `_pulir()` de `tts.py` (copiada) |
| `firmware_mano/main.py` | Firmware oficial de la mano: letras + orden `voz` por I2S | copia de `main.py` con los cambios del usuario |
| `fusion/pruebas/` | Pruebas simuladas (mano, firmware con voz, voz por BLE) y `palabra.png` | nuevo |
| `fusion/referencia/dibujar_original.py` | Copia de `dibujar.py`, base de `dibujar_fusion.py` (no se ejecuta) | copia |
| `fusion/dibujar_fusion.py` | Ventana del Kinect, gestos, estados y orquestación | copia de `dibujar.py` |

**Credenciales:** el PC no necesita `secretos.py` ni ninguna IP: todo va por BLE con el TOKEN de `config_ble.py`.

## 3. Reconocimiento (OCR + coincidencia aproximada)

1. Se usa el mismo preprocesado de `dibujar.py` (fondo blanco, trazo negro, erosión) y TrOCR
   `microsoft/trocr-large-handwritten` desde la caché local de Hugging Face.
2. **Se conservan todas las palabras**: se elimina `max(palabras, key=len)`.
3. `normalizar()`: minúsculas, sin tildes, conserva la ñ, solo letras. Ejemplo: `"Enríquez."` → `enriquez`.
4. Cada palabra se compara con el vocabulario del grupo (todos los nombres y apellidos) usando
   `difflib.SequenceMatcher`, de la librería estándar, sin instalar nada:
   - **Primero se busca la coincidencia exacta.** Solo si no la hay se usa la aproximada.
   - Se acepta si la similitud es **≥ 0,75–0,80** (por ajustar con pruebas reales) **y** si supera a la segunda
     opción por **≥ 0,10**. Si no, la palabra queda *dudosa* y la pantalla muestra las dos opciones.
     Comprobado con `difflib`: `paul`/`paula` = 0,89, `jaen`/`jean` = 0,75, `juan`/`jean` = 0,75,
     `luna`/`lina` = 0,75, `mirnda`/`miranda` = 0,92. Sin el margen, una "Paula" mal leída podría ir a Jean Paul.
   - TrOCR a veces une dos palabras ("JeanPaul"). En ese caso también se prueba partir la palabra en dos.
5. **Persona:** todas las palabras deben pertenecer a **una misma persona** y estar en el orden de su nombre
   completo. Ejemplos válidos: "Lina", "Tatiana Maldonado", "Paul Miranda", "Jean Paul Miranda". Solo se usa el
   primer apellido: el segundo apellido ya no es una palabra del grupo.
6. **Tipo:** solo nombres → *nombre*; solo apellidos → *apellido*; ambos → *nombre y apellido*.
7. **"Jean" dibujado solo** («Jean» es solo de Jean Paul; Harry nunca usa «Jean»): se deletrea "Jean" y suena
   `voces/JEAN.mp4` (voz de Jean Paul), así que se muestra como Jean Paul.
   "Jean Paul" no es ambiguo, y "Jean Harry" se rechaza por ser una mezcla de dos personas.
8. **Sin coincidencia** (o palabras de personas distintas): en pantalla aparece
   "No reconocí un integrante: '<texto crudo>'"; no se envía nada a la mano ni al parlante.
9. **Confirmación:** antes de mandar a la mano, la pantalla muestra
   `Leí: "Jaen Mirnda"  →  Entendí: "Jean Miranda" (Jean Paul)  ·  👍 sí  /  🤙 cancelar`.
   Lo que se deletrea es la **forma corregida** (canónica) del texto, no el texto crudo del OCR.
10. Se escribe el `.txt` **solo después de confirmar**, con el texto que se muestra (p. ej. «Jean Miranda»), en
    `fusion/salidas/`.

### Varias palabras en un mismo dibujo (en `dibujar_fusion.py`, C4)

Se dibuja **una palabra a la vez**. Cada palabra se lee sola con TrOCR, lo que además le facilita el trabajo al OCR.

| Gesto (estado `DIBUJANDO`) | Qué hace |
|---|---|
| Índice | Dibuja |
| **Mano abierta** | **Levantar el lápiz:** solo deja de dibujar, para mover el trazo a donde empieza la siguiente letra (como en `dibujar.py`). **No hace nada más**: ni siguiente palabra, ni limpiar, ni confirmar |
| **Pulgar abajo sostenido 1 s** (anillo de carga) | **Siguiente palabra:** lee el lienzo con TrOCR (mientras tanto muestra «Leyendo…» e ignora los gestos), agrega lo leído a la lista de arriba («Jean \| ») y limpia el lienzo. Si el lienzo está vacío: «No hay nada dibujado». Si TrOCR no lee nada: «No leí nada, dibuja de nuevo» y el lienzo se conserva |
| **Pulgar arriba** | **Terminar:** si hay algo en el lienzo, lo lee y lo agrega; une la lista en orden («Jean Miranda») y llama a `interpretar()` como si fuera un solo texto (mismas reglas: una persona, en orden, sin mezclas) → `CONFIRMANDO`. Lista y lienzo vacíos: «No hay nada dibujado» |
| **Shaka** | Limpia **solo la palabra que se está dibujando** (el lienzo); la lista no cambia |
| **Botón «↶ Deshacer»** en pantalla, abajo a la derecha (índice sostenido 20 cuadros, con anillo de carga, como el ON/OFF) | Quita la última palabra de la lista |
| Tres dedos | Cambia el color (como antes) |

- **Botón «↶ Deshacer», lejos del dibujo:** va en la esquina inferior derecha, centro en (1760, 970) con radio de
  65 px, **dentro de la «zona segura»** (debajo de la línea `LIMITE_INFERIOR` = 880 px, donde `dibujar.py` ya no
  dibuja). Para llegar ahí hay que bajar la mano a propósito, y el trazo de una letra nunca pasa por encima.
- **Máximo 4 palabras.** Con 3 en la lista, el pulgar abajo ya no agrega: muestra «Esta es la última palabra:
  termina con 👍», y el pulgar arriba agrega la cuarta. (Sin el segundo apellido, el nombre más largo del grupo tiene 3.)
- Cada palabra de la lista se muestra con lo que **leyó** TrOCR, más una marca: ✓ si se parece a algún nombre del
  grupo, ? si no. Es un aviso temprano; la decisión final es la de `interpretar()` sobre el texto unido.
- **Confirmación:** se muestra «Leí: … → Entendí: …». En `CONFIRMANDO`, el pulgar arriba **solo cuenta después de
  bajar la mano** (al menos 0,5 s sin pulgar arriba), para que el mismo gesto de «terminar» no confirme solo. Shaka
  = cancelar: se borran la lista y el lienzo.
- Rechazos («No coincide con un integrante», «¿Paul o Paula? Dibuja de nuevo») → se muestran, se borran la lista
  y el lienzo, y se vuelve a `DIBUJANDO`.
- **Pulgar abajo frente a los demás gestos** (revisado con las funciones de `dibujar.py`):
  - **Frente a pulgar arriba:** el original exige la punta del pulgar *más arriba* que sus articulaciones IP y
    MCP; el pulgar abajo exige que esté *más abajo* que las dos, con margen. Las condiciones son opuestas y no
    pueden cumplirse a la vez.
  - **Frente a la mano abierta:** el pulgar abajo exige los 4 dedos doblados.
  - **Dedos doblados:** con el puño girado hacia abajo, la prueba original por altura (`punta.y > pip.y`) no es
    fiable. Para el pulgar abajo, un dedo cuenta como doblado si su punta está **más cerca de la muñeca** que su
    articulación PIP, lo que no depende de la orientación.
  - **Margen del pulgar:** es relativo al tamaño de la mano (distancia de la muñeca a la base del dedo medio), así
    funciona igual cerca y lejos del Kinect.
  - **Puño normal:** no se confunde. Con la mano hacia arriba, la punta del pulgar queda por encima de su base.
  - **Contra activaciones sin querer:** sostenerlo 1 s, con anillo de carga.
- **Gestos que no cambian:** pulgar arriba, shaka, tres dedos y el botón ON/OFF se detectan igual que en
  `dibujar.py`, que ya funciona.
- **Modo diagnóstico:** muestra en pantalla qué gesto detecta MediaPipe en cada momento, para confirmar con el
  Kinect que pulgar abajo, pulgar arriba y mano abierta se distinguen antes de usarlos.

### `fusion/integrantes.json`

Integrantes (solo el primer apellido):

| Clave | Nombres | Apellido |
|---|---|---|
| `jeanpaul` | Jean, Paul | Miranda |
| `harry` | Jean, Harry | Raigozo |
| `lina` | Lina, Tatiana | Maldonado |
| `paula` | Paula, Camila | Enríquez |

Cada palabra apunta a un **nombre base de archivo**. El programa lo busca solo en `voces/` (raíz del proyecto),
sin distinguir mayúsculas, con cualquiera de estas extensiones: `.mp3 .mp4 .m4a .wav .ogg .mpeg`, también con la
extensión doble de WhatsApp (`Maldonado.mp3.mpeg` cuenta como `Maldonado`). Para agregar un audio
que falta **basta con poner el archivo en `voces/`** con el nombre de `LISTA_GRABACION.md`; no hay que tocar el
JSON. Cada persona tiene además 2 `frases` grabadas («primer nombre + apellido» y el nombre completo, p. ej.
`Lina_Maldonado` y `Lina_Tatiana_Maldonado`); las demás combinaciones se arman uniendo las palabras sueltas.
`no_usar` evita que `Jean.wav`, `0-000.wav` u `output.wav` se tomen por error (p. ej. `JEAN` → `JEAN.mp4`,
nunca `Jean.wav`). "Jean" dibujado solo se asigna a Jean Paul, porque `JEAN.mp4` es su voz.

## 4. Mano por BLE y sincronización

### Protocolo real del firmware (`main.py`, versión BLE)

| El PC envía | La placa responde |
|---|---|
| `auth <TOKEN>` (en los primeros 3 s) | `ok:auth` o `error:auth` y desconecta |
| `reset` o `1` | `reset_ok` (mano abierta) |
| una letra (`a`) | `gesto_a_ok` (sin pausa posterior, la mano queda en la letra) |
| una palabra (`lina`) | por letra: `gesto_x_ok` + `letra_actual:x` (luego espera 1 s); si no existe: `letra_x_no_disponible` (sin abrir la mano ni esperar); al final: `deletreo_completo` y abre la mano |
| `voz <a> [<b> ...]` | suena `/voz/<a>.wav`, 250 ms, `/voz/<b>.wav`… y responde `voz_ok`; si falta alguno (o no es un WAV válido): `voz_falta:<a>,<b>` sin sonar nada; si falla el I2S o la lectura: `voz_error:<i2s\|lectura>` (nunca se cuelga ni detiene la mano) |
| `version` o `?` | `version:voz-2` (pines 7/15/16). El PC usa `?`: el firmware sin voz responde `comando_no_reconocido` sin mover la mano (con `version` la deletrearía) |
| otra cosa | `comando_no_reconocido` |

**Desfase de `consola_pc.py` que se corrige en la copia:** la consola espera la línea `listo`, que el firmware
nunca envía. En la copia, la autenticación termina con `ok:auth`, y cada orden termina con
`deletreo_completo` (palabra), `gesto_x_ok` (letra sola), `reset_ok`, `voz_ok`/`voz_falta:…` o
`comando_no_reconocido`.

### Cómo se deletrea (sin cambiar el firmware)

- La conexión BLE se abre **una vez al arrancar**, en un hilo con su propio bucle asyncio, y se mantiene
  abierta. Si se cae, se reconecta y se avisa en pantalla.
- El texto canónico se normaliza para la mano: minúsculas, sin tildes (`í`→`i`), conserva la `ñ`.
- El PC parte cada palabra en **tramos de letras estáticas**, separados por las letras con movimiento (§6).
  Ejemplo: `harry` → [h] + `arry` · `raigozo` → `raigo` + [z] + `o` · `jean` → [j] + `ean`.
  - **Tramo de 2 o más letras:** se envía y se espera `deletreo_completo` (la mano queda abierta).
  - **Tramo de 1 letra:** se envía, se espera `gesto_x_ok`, se esperan 1 s y se envía `reset` (espera `reset_ok`).
    Así se comporta igual que dentro de una palabra.
  - **Letra con movimiento:** se envía `reset` (espera `reset_ok`, así la mano ya terminó de abrirse); la letra
    aparece **en grande** en pantalla con la nota "(con movimiento)" durante 1,5 s, y se sigue con el tramo
    siguiente.
  - **Entre palabras:** `reset` + 1 s de pausa, para que se note el espacio.
  - **Al final:** `reset` y se espera `reset_ok`. `main.py` envía `deletreo_completo` *antes* de abrir la mano;
    como atiende una orden a la vez, el `reset_ok` final llega con la mano ya abierta y quieta. Los dedos que ya
    están abiertos no se mueven, así que no gasta tiempo.
- La pantalla muestra la letra actual (de `letra_actual:x`, o la letra con movimiento que pone el PC).
  **Sincronizada sin tocar el firmware** (`fusion/pantalla_mano.py`): el PC ejecuta las funciones de la mano del
  propio firmware en tiempo virtual para saber cuándo la mano está *formando*, *mostrando* o *abriendo*, y corrige
  el reloj con cada `letra_actual:x` y `deletreo_completo` (comparado con el deletreo real: ±0,09 s por letra).
- **Solo después del cierre del último tramo** se pasa a `HABLANDO`.
- Tiempo de espera por respuesta: 20 s (cada letra tarda entre 2 y 6 s: hasta 12 movimientos de 0,4 s, más
  1 s de pausa). Si se agota, aparece "La mano no respondió", **no se habla** y se vuelve a `DIBUJANDO`.

### `config_ble.py`

Está en la **raíz del proyecto** (`config_ble.py`, puesto por el usuario) con `NOMBRE = "Mano-LSC"` y el mismo
TOKEN de la placa (32 caracteres). `consola_mano.py` lo lee desde ahí con `ast.literal_eval`, sin ejecutarlo. No
se copia, no se modifica y el token nunca se muestra. Está en el `.gitignore` de la raíz. Los UUID no van en ese
archivo: están fijos en `main.py` (servicio UART de Nordic, `6E400001/2/3-…`).

## 5. Voz (grabaciones originales por el MAX98357 de la placa de la mano)

- **20 audios** (5 por persona, lista en `docs/LISTA_GRABACION.md`): sus dos nombres, su apellido, «primer
  nombre + apellido» y el nombre completo, todos en `voces/`. **Cada audio dura al menos 1 s**, con un poco de
  silencio antes y después (los de menos de 1 s se oían cortados y se retiraron). **Válidos hoy (5):** `JEAN.mp4`
  y `Paul.mp4` (voz de Jean Paul), `Lina.mp3.mpeg`, `Tatiana.mp3` y `Maldonado.mp3`.
- **No se usan:** `Jean.wav`, `0-000.wav`, `output.wav`, ni ningún segundo apellido.
- **Sin clonación ni VITS.** Si falta un audio, la pantalla muestra **«Falta audio: <palabra>»** y no suena nada
  (para no decir un nombre a medias). La mano ya deletreó y el programa vuelve a `DIBUJANDO` sin caerse.
- **Conversión** (`voz.py --preparar`; los originales no se tocan): ffmpeg decodifica a su frecuencia original →
  mono → `resample_poly` a 16 kHz → pasa-altos suave de 100 Hz (Doby: 200) → pico 0,35 igual para todos →
  rampas de 2 ms (Doby: 10) contra el «clic». **No se recorta nada:** los audios ya vienen cortados y el WAV dura
  exactamente lo mismo que el original (comprobado al milisegundo). Intermedio en
  `fusion/cache_audio/<Base>_<huella>.wav`; para la placa, `fusion/audios_placa/<base en minúsculas>.wav`
  (16 kHz, mono, 16 bits, cabecera de 44 bytes). Con los 6 actuales: 132 KB; con los 20, unos 440 KB (la flash
  de la N16R8 tiene varios MB libres).
- **Qué suena:** si lo reconocido es exactamente una frase grabada → solo ese archivo (`voz lina_maldonado`); si
  no → las palabras sueltas (`voz tatiana maldonado`) y la placa pone **250 ms** entre ellas y 0,3 s al final.
- **Envío:** por la misma conexión BLE de la mano (`Mano.hablar()`), **después** de `deletreo_completo` y del
  `reset` final. La placa responde `voz_ok` al terminar de sonar, o `voz_falta:<archivos>` si no los tiene
  («Falta audio: … (no está en la placa: súbelo a /voz con Thonny)»).
- **Firmware:** el I2S (16 bits, mono, 16 kHz, `ibuf=20000`, como Doby) se crea solo durante cada `voz` y se
  suelta al terminar. El PWM de los servos es otro periférico y no se
  mueve ningún servo mientras suena. Mientras suena, la placa no atiende otra orden (el PC espera `voz_ok`).
- Cada intento queda en `fusion/registros/tiempos_voz.csv` (texto, archivos, segundos de audio, segundos hasta
  `voz_ok`, resultado), que servirá para las gráficas reales (§8).
- **Si la placa se reinicia al sonar:** caída de voltaje. Revisar que el LM2596 dé 5,0 V (con multímetro, sonando),
  que el condensador esté pegado al módulo y bien polarizado, y probar con `VOLUMEN` más bajo (0,25) en
  `config_fusion.py` (se vuelve a correr `--preparar` y a subir los WAV).
- **Si se oye ruido o zumbido:** GND del MAX98357 a la regleta de la placa (no a la de los servos), cables de I2S
  cortos (< 15 cm) y lejos de los cables de los servos, y los cables del parlante trenzados. Si el ruido es un
  pitido constante cuando no suena nada, es la fuente del LM2596: un condensador cerámico de 100 nF en paralelo
  con el electrolítico ayuda.

## 6. Letras

### Lista final (abecedario LSC)

Según el artículo de Unillanos (*Orinoquia*, 2021), las letras **estáticas** (sin movimiento) del abecedario
LSC son exactamente 21: **a b c d e f i k l m n o p q r t u v w x y**. Son las mismas 21 que ya tiene el
firmware de la mano. Por lo tanto llevan movimiento, y **no se hacen con la mano**:

| Con movimiento | Aparece en los nombres del grupo |
|---|---|
| **g** | Rai**g**ozo |
| **h** | **H**arry |
| **j** | **J**ean |
| **ñ** | — |
| **s** | — |
| **z** | Raigo**z**o, Enríque**z** |
**ll** y **rr** (letras propias de la LSC, con movimiento) **no se usan**: se deletrean como dos letras
estáticas, `l` + `l` y `r` + `r` (decidido). Ejemplo: `harry` → [H en pantalla] + `arry`.

**Consecuencia:** no se agrega ninguna letra al firmware. La propuesta anterior de posiciones para g, h y s queda
descartada. (El único agregado al firmware es la orden `voz`, §5.)

> Fuente: el artículo menciona estas 21 letras como «señas estáticas». El usuario lo confirmará con el
> abecedario que usó el grupo.

### Qué se hace con una letra con movimiento

Se muestra **en grande** en pantalla con la nota "(con movimiento)", la mano **se abre** y se sigue con la
siguiente letra (detalle en §4).

## 7. Orden de trabajo y pruebas

**A. Plan:** este archivo y `CLAUDE.md`. ✔ (versión 2)

**B. Audios**
1. `docs/LISTA_GRABACION.md`: audios que faltan, persona y nombre exacto del archivo. ✔
2. El usuario pone los archivos en `voces/`. La conversión la hace `voz.py` (punto C3), así que no hace falta
   un script de conversión aparte: hay un solo camino para todos los audios.

**C. Implementación, cada parte probada por separado**
1. **OCR**: `reconocer.py` con imágenes guardadas y dibujos nuevos. Prueba: tabla de texto crudo → texto
   entendido → persona, con al menos 3 dibujos por palabra.
2. **Mano** ✔: `consola_mano.py` y `config_ble.py` (raíz, NOMBRE y TOKEN). Probada con la mano real. Prueba
   simulada: `fusion/pruebas/prueba_mano_falsa.py`.
3. **Voz** (en curso): `firmware_mano/main.py` (orden `voz`) + `voz.py` + `Mano.hablar()`. Pruebas simuladas:
   `fusion/pruebas/prueba_firmware_voz.py` y `prueba_voz_ble_falsa.py`. Pruebas reales:
   `voz lina` desde Thonny; `voz.py --texto "Lina"`; `voz.py --texto "Lina" --deletrear`; cada palabra y cada
   frase; y que con un audio faltante aparezca «Falta audio» sin que el programa se caiga.
4. **Todo junto**: `dibujar_fusion.py`. Primero el modo diagnóstico de gestos (pulgar abajo contra pulgar
   arriba y contra la mano abierta). Prueba: un nombre, un apellido y un nombre y apellido de cada integrante,
   dibujados palabra por palabra (pulgar abajo entre palabras, mano abierta entre letras). Además: deshacer, máximo 4 palabras, mezcla de personas, desorden y casos
   de error (sin coincidencia, BLE apagado, audio que falta en el PC o en la placa).

**D. Limpieza:** cuando el usuario confirme que todo funciona y que `C:\Users\miran\proyectoDoby` existe completo,
se borran `Dibujar/` y `proyectoDoby/` de esta carpeta, se revisan los imports y se repite la prueba C4. No se
copiaron (decidido): las grabaciones de Doby, el modelo VITS ni `graficas_entrenamiento/data/` (dataset IAM).
`SUSTENTACION.md` (en `docs/`) se escribe al final de C4.

## 8. Gráficas

`guia_graficas/` (copia de `graficas_entrenamiento/` sin `data/`) se conserva **solo como guía de formato**: su `LEEME.txt` dice que
sus datos son sintéticos. Las gráficas nuevas saldrán **únicamente de datos reales**:
- `fusion/registros/tiempos_voz.csv` y `tiempos_mano.csv`: duración de cada audio, tiempo hasta `voz_ok` y
  tiempos de deletreo;
- los registros de las pruebas del punto C: aciertos del OCR, tiempos de deletreo, tiempo total del flujo.

## 9. Decisiones abiertas

Ya decididas: `Paul.mp4` y `JEAN.mp4` son la voz de Jean Paul · solo el primer apellido · 5 audios por persona
(3 palabras + 2 frases) · si falta un audio no suena nada · todo por BLE, la voz en la placa de la mano · `rr`/`ll` se
deletrean como dos letras estáticas · las letras con movimiento son las que no están entre las 21 estáticas ·
mano abierta = levantar el lápiz, pulgar abajo = siguiente palabra, botón «↶ Deshacer» abajo a la derecha · los
tiempos de la mano se guardan en `fusion/registros/tiempos_mano.csv`.

| # | Decisión | Opciones | Afecta a |
|---|---|---|---|
| 5 | Confirmación en pantalla | gesto 👍/🤙 (propuesto) / automática tras N s | `dibujar_fusion.py` |
| 6 | Umbral de coincidencia aproximada | 0,75–0,80 + margen 0,10 de partida; se ajusta con pruebas | `reconocer.py` |
| 9 | Marca ✓/? por palabra en la lista | sí (propuesto) / no | `dibujar_fusion.py` |
