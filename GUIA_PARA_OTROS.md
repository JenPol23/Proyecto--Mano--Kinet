# Guía para otro grupo: de cero a funcionando

Esta guía es para alguien que **no conoce el proyecto** y solo tiene el repositorio clonado y su propio hardware.
Sigue los pasos **en orden**: cada paso usa lo que se preparó en los anteriores. Todo sale del código del
repositorio. Lo que no se pudo comprobar está marcado **POR VERIFICAR**, junto con lo que hay que hacer para
comprobarlo.

> [!IMPORTANT]
> El repositorio **no trae ninguna grabación de voz**. Cada grupo graba las suyas (paso 6). Sin grabaciones, la mano
> deletrea igual, pero no suena nada.

**Convención de esta guía:** todos los comandos se ejecutan en una terminal **abierta en la carpeta del
repositorio** y **con el entorno virtual activado** (paso 3.1), escribiendo `python`. Cada vez que abran una
terminal nueva, actívenlo otra vez con `.venv\Scripts\activate`. No usen `py -3.11` con el entorno activado:
`py -3.11` usa el Python general de Windows, que no tiene los paquetes del proyecto. La única excepción es la
clonación de voz (paso 12), que usa su propio entorno, `venv_f5`.

**Resumen del orden:**

| Paso | Qué | Dónde | ¿Hardware? |
|---|---|---|---|
| 1–2 | Requisitos y circuito | — | Sí |
| 3 | Preparar el PC | PC | No |
| 4 | Crear los archivos de configuración (Bluetooth y WiFi) | PC | No |
| 5 | Poner sus integrantes | PC | No |
| 6 | Grabar los nombres y convertirlos | PC | No |
| 7 | MicroPython y subir todo a la placa | Placa por **USB** | Sí |
| 8 | Primera prueba de la mano | Placa con **12 V** | Sí |
| 9 | Calibrar la mano | 12 V ↔ USB | Sí |
| 10 | Rutas e IP | PC | No |
| 11 | Programa completo | Todo | Sí |
| 12 | *(Opcional)* Voces clonadas para el botón Hora | PC con GPU | No |
| 13 | Problemas comunes | — | — |

---

## Paso 1. Requisitos

### Hardware

| Componente | Detalle |
|---|---|
| Placa | **ESP32-S3 N16R8** tipo **YD-ESP32-S3** (USB CH343, LED RGB en GPIO 48) |
| Mano | Una mano robótica con **6 servos**: índice, medio, anular, meñique, pulgar y pulgar2 (ver la nota) |
| Alimentación | Jack de **12 V** + regulador **LM2596** (12 V → 5 V) en una placa de expansión |
| Audio | Amplificador **MAX98357** (I2S) + parlante **8 Ω, 1,5 W** |
| Cámara | **Kinect** (vía OBS) **o cualquier webcam** |
| PC | **Windows** con **Bluetooth** (el plan B de voz usa `winsound`, que solo existe en Windows) |
| WiFi | Solo para el botón Hora: un punto de acceso de **2,4 GHz** (en el proyecto, un celular) |
| Cable USB | Para subir archivos a la placa con Thonny |

> [!NOTE]
> **El repositorio no incluye cómo construir la mano:** no hay piezas, planos ni montaje. Solo trae el firmware y el
> programa. Cada grupo usa su propia mano con 6 servos y la calibra en el paso 9.

**Datos del hardware que no están en el repositorio (POR VERIFICAR):**
- **Modelo de los servos:** no está documentado. Usen servos de hobby que acepten pulsos de 500 a 2500 µs a 50 Hz
  (por ejemplo, del tipo SG90 o MG90S), que es lo que manda el firmware.
- **Adaptador de 12 V:**
  - El amperaje no está documentado. Calculen **al menos 1 A por servo en movimiento**.
  - El firmware mueve **un dedo a la vez**: espera `PAUSA_DEDO = 0,4 s` entre uno y otro (`firmware_mano/main.py:7`).
    Los demás quedan sosteniendo su posición, que también consume.
  - Un LM2596 típico entrega hasta 3 A.
  - **Si la placa se reinicia al mover la mano, la fuente es insuficiente.**
- **Condensador a la salida del LM2596:** el valor no está documentado. Si hay ruido, ver [CONEXIONES.md](CONEXIONES.md).
- **Qué mueve «pulgar2»:** el código solo dice que es un sexto servo del pulgar (GPIO 39), distinto de «pulgar»
  (GPIO 40), y que al abrir la mano se mueve primero. Qué movimiento hace cada uno depende de cómo está armada la
  mano. **Compruébenlo en el paso 8**: con `!b` cierran los dos y con `!e` se abren los dos (`main.py:96-117`).

### Software

| Programa | Versión | Para qué | Si no la conocen |
|---|---|---|---|
| Python | **3.11** (3.11.9) | Todo el programa del PC | — |
| Paquetes de `requirements.txt` | torch 2.11.0, transformers 4.57.6, opencv-python 5.0.0.93, mediapipe 0.10.9, numpy 2.4.6, scipy 1.17.1, pillow 12.3.0, bleak 3.0.2 | Visión, OCR y Bluetooth | — |
| ffmpeg y ffprobe | POR VERIFICAR la mínima | Convertir las grabaciones | Usen una reciente y comprueben que `ffmpeg -version` responda |
| Thonny | POR VERIFICAR | Subir archivos a la ESP32 | Usen la última y comprueben que abajo a la derecha aparezca la placa como **MicroPython (ESP32)** |
| MicroPython | **v1.28.0**, *Generic ESP32S3* | Firmware de la placa | — |
| OBS Studio | POR VERIFICAR | Solo con el Kinect | Usen la última y comprueben que el Kinect aparezca como fuente y que exista «Iniciar cámara virtual» |
| Driver del Kinect | POR VERIFICAR | Que Windows vea el Kinect | Comprueben que el Kinect aparezca en el **Administrador de dispositivos** de Windows y como fuente en OBS **antes de seguir** |

---

## Paso 2. Armar el circuito

Seguir **[CONEXIONES.md](CONEXIONES.md)**. Lo esencial:

1. **Ajustar el LM2596 a 5,0 V con el multímetro ANTES de conectarle nada.**
2. Servos: la señal va a los GPIO **1** (índice), **2** (meñique), **42** (medio), **4** (anular), **40** (pulgar) y
   **39** (pulgar2). La alimentación sale del **LM2596**, nunca del pin de 5 V de la ESP32.
3. MAX98357: **DIN → GPIO 7, BCLK → GPIO 15, LRC → GPIO 16, VIN → 3V3 de la ESP32, GND → GND de la ESP32.**
   Con VIN en 5Vin no suena.
4. **Todas las tierras unidas:** LM2596, ESP32, servos y MAX98357.
5. **Nunca USB y 12 V a la vez.**

> [!IMPORTANT]
> **Con solo el USB, la mano NO se mueve.** Los servos reciben corriente únicamente del LM2596, que necesita los
> 12 V. Por USB la placa arranca, responde, se conecta al WiFi e incluso suena (el MAX98357 va al 3V3), pero los
> dedos no se mueven.

---

## Paso 3. Preparar el PC

### 3.1 Python, el entorno virtual y los paquetes

1. Instalar **Python 3.11** desde python.org, con la opción «Add python.exe to PATH».
2. Crear y activar el entorno virtual en la carpeta del repositorio:
   ```
   py -3.11 -m venv .venv
   .venv\Scripts\activate
   python -m pip install --upgrade pip
   ```
   Si PowerShell no deja activarlo, ejecutar `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y volver a
   activar. Desde aquí, siempre `python`.
3. **Primero torch** (una de las dos líneas):
   ```
   python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
   python -m pip install torch==2.11.0
   ```
   - La primera es para PC **con GPU NVIDIA** (CUDA 12.8, la que usó el proyecto).
   - La segunda es para PC **sin GPU**. TrOCR funciona con los dos, solo que más lento sin GPU.
4. **Después, el resto**:
   ```
   python -m pip install -r requirements.txt
   ```
   Como torch ya está instalado en la versión 2.11.0, este paso no lo reemplaza.

   > **No se probó una instalación limpia desde cero.** Las versiones son las del PC original.
   > Si `pip` no encuentra una versión o hay un conflicto, anoten el mensaje y prueben con la versión más cercana
   > de ese paquete.
5. **Descargar TrOCR una vez, con internet.** Es `microsoft/trocr-large-handwritten`, de unos 2,4 GB. Después el
   programa lo carga **sin internet**, porque `fusion/reconocer.py` pone `HF_HUB_OFFLINE=1`:
   ```
   python -c "from transformers import TrOCRProcessor, VisionEncoderDecoderModel as M; n='microsoft/trocr-large-handwritten'; TrOCRProcessor.from_pretrained(n); M.from_pretrained(n)"
   ```
6. Comprobar (no necesita Kinect ni placa):
   ```
   python fusion/reconocer.py --pruebas
   ```
   Debe decir `23 de 23 pruebas pasan.` con los nombres del grupo original. En el paso 5 se cambian.

### 3.2 ffmpeg

1. Descargar ffmpeg para Windows (versión *essentials*) y descomprimirlo.
2. Agregar su carpeta `bin` al **PATH** de Windows.
3. Abrir una terminal **nueva** y comprobar `ffmpeg -version` y `ffprobe -version`.

### 3.3 Cámara: Kinect u otra webcam

El programa **no usa el SDK del Kinect**. Abre una cámara normal con OpenCV
(`cv2.VideoCapture(N, cv2.CAP_DSHOW)`, `fusion/dibujar_fusion.py:1131`), y por defecto es la **cámara 1**
(`--camara`, `fusion/dibujar_fusion.py:1179`). El camino del proyecto es:

```
Kinect ──► OBS (fuente «Dispositivo de captura de video») ──► «Iniciar cámara virtual» ──► OpenCV, cámara 1
```

1. Instalar el driver del Kinect (POR VERIFICAR cuál: depende del modelo). **Antes de seguir, comprueben que el
   Kinect aparezca en el Administrador de dispositivos de Windows.**
2. En OBS: agregar el Kinect como fuente de video. **Comprueben que se vea la imagen en OBS** y presionen
   **«Iniciar cámara virtual»**.
3. Ver qué número de cámara ve OpenCV:
   ```
   python -c "import cv2; [print(i, cv2.VideoCapture(i, cv2.CAP_DSHOW).read()[0]) for i in range(4)]"
   ```
   Los números que dicen `True` funcionan.

**Sin Kinect: cualquier webcam, sin OBS.** Se usa `--camara 0` (normalmente la del portátil), o `1`, `2`… Si el
número no sirve, el programa dice «No se abrió la cámara N (prueba con --camara 0)».

---

## Paso 4. Crear los archivos de configuración (en el PC)

Se crean **ahora**, antes de tocar la placa, porque en el paso 7 se suben. Ninguno se sube al repositorio: están
en `.gitignore`.

Primero, generar un TOKEN para el Bluetooth y otro para el WiFi. Pueden ser distintos. Ejecutar este comando dos
veces:

```
python -c "import secrets; print(secrets.token_hex(16))"
```

### 4.1 Bluetooth: `config_ble.py` (obligatorio)

El PC busca la placa **por su nombre**, no por su dirección MAC (`BleakScanner.find_device_by_name`,
`fusion/consola_mano.py:301`). Copiar `config_ble.ejemplo.py` → **`config_ble.py`**, en la raíz del repositorio:

```python
# antes (plantilla)            # después (ejemplo)
NOMBRE = "Mano-LSC"            NOMBRE = "Mano-LSC"        (cámbienlo si hay varias manos cerca)
TOKEN = "CAMBIAR_AQUI"         TOKEN = "3f9a...el primer token generado..."
```

- El TOKEN debe tener **al menos 16 caracteres**. Con `CAMBIAR_AQUI` la placa lo rechaza a propósito.
- **El mismo archivo** va en el PC (raíz del repositorio) y en la placa (paso 7).
- No hace falta emparejar la placa en Windows: basta con tener el Bluetooth del PC activado.

### 4.2 WiFi: `config_wifi.py` y `secretos.py` (solo para el botón Hora)

Son **dos** archivos que deben coincidir:

1. **Para la placa:** copiar `config_wifi.ejemplo.py` → **`config_wifi.py`**:
   ```python
   # antes (plantilla)                        # después (ejemplo)
   RED = "TU_RED"                             RED = "CelularDeAna"
   CLAVE = "TU_CLAVE"                         CLAVE = "clave-del-celular"
   TOKEN = "PEGAR_AQUI_EL_TOKEN_GENERADO"     TOKEN = "b71c...el segundo token generado..."
   PUERTO = 5001                              PUERTO = 5001
   NOMBRE = "mano"                            NOMBRE = "mano"
   ```
   La red debe ser de **2,4 GHz**: el ESP32-S3 no ve redes de 5 GHz.
2. **Para el PC:** copiar `secretos.ejemplo.py` → **`secretos.py`** (raíz del repositorio), con el **mismo
   TOKEN, PUERTO y NOMBRE** de `config_wifi.py`. Por ahora dejen **`IP_FIJA = None`**: la IP de la placa se conoce
   en el paso 7.4 y se completa ahí.

El PC busca la placa como `mano.local` (el `NOMBRE` + `.local`) y, si no responde, en `IP_FIJA`. Si después
cambian el TOKEN, cámbienlo en los dos archivos y vuelvan a subir `config_wifi.py` a la placa.

---

## Paso 5. Poner sus integrantes

### 5.1 `fusion/integrantes.json`: qué se reconoce y qué audio suena

Cada persona es una entrada en `"personas"`. Ejemplo, para cambiar a Lina por «Ana María Gómez»:

```json
// ANTES
"lina": {
  "nombre_completo": "Lina Tatiana Maldonado",
  "palabras": [
    {"texto": "Lina",      "tipo": "nombre",   "audio": "Lina"},
    {"texto": "Tatiana",   "tipo": "nombre",   "audio": "Tatiana"},
    {"texto": "Maldonado", "tipo": "apellido", "audio": "Maldonado"}
  ],
  "frases": [
    {"palabras": ["Lina", "Maldonado"],            "audio": "Lina_Maldonado"},
    {"palabras": ["Lina", "Tatiana", "Maldonado"], "audio": "Lina_Tatiana_Maldonado"}
  ]
}

// DESPUÉS
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

(Los `//` son solo para esta guía: el archivo JSON real no admite comentarios.)

- **`"audio"` es lo que asocia cada palabra con su grabación:** `"audio": "Gomez"` hace que se busque `voces/Gomez.*`.
- **`"palabras"`** es lo único que se puede escribir, y en ese orden.
- **`"frases"`** son combinaciones con su propia grabación. Si no existe la grabación de la frase, suenan las
  palabras sueltas con 250 ms entre ellas.
- **`"nombre_completo"`** solo se muestra entre paréntesis en la confirmación.
- **Solo el primer apellido.** Mezclar palabras de dos personas → «No coincide con un integrante».
- **`"ambiguos"`** decide a quién va una palabra que tienen dos personas: `{"ana": "ana"}`.
  - **Atención:** hoy trae `"ambiguos": {"jean": "jeanpaul"}`, del grupo original. Si ya no tienen a Jean Paul,
    **borren esa entrada** o cámbienla por la suya. No rompe nada, pero confunde.
- Si el grupo tiene más o menos de 4 personas, no hay problema: el reconocimiento recorre todas las que haya.
- Más casos comprobados: [GUIA_CAMBIAR_VOCES.md](GUIA_CAMBIAR_VOCES.md).

**Probar sin Kinect:**

```
python fusion/reconocer.py --texto "Ana Gomez"
```

Muestra qué entendió, cómo lo deletrea la mano y si encuentra cada audio.

**Pruebas:** los casos de `PRUEBAS` en `fusion/reconocer.py` y varias pruebas de `fusion/pruebas/` usan los
nombres del grupo original. Van a fallar hasta que los cambien por los suyos.

### 5.2 `fusion/hora.json` (solo para el botón Hora)

```json
// ANTES
"orden_menu": ["jeanpaul", "harry", "lina", "paula"],
"personas": {
  "lina": {"mostrar": "Lina", "voz_doby": "lina"}, ...
},
"piloto": {"persona": "jeanpaul", ...}

// DESPUÉS
"orden_menu": ["ana", "..."],
"personas": {
  "ana": {"mostrar": "Ana", "voz_doby": "ana"}, ...
},
"piloto": {"persona": "ana", ...}
```

- **`"orden_menu"`:** **hasta 4 voces**.
  - Las teclas del menú solo llegan al `4` (`fusion/dibujar_fusion.py:744`).
  - Con 5 botones, la fila (x = 150 a 1770) es más ancha que la imagen del Kinect (x ≈ 250 a 1690,
    `fusion/dibujar_fusion.py:107`).
  - Con menos de 4 voces, los botones se centran solos.
- **La clave** (`"ana"`) es el nombre de la carpeta de las fechas: `voces_clonadas/fecha/ana/`.
- **`"mostrar"`** es el texto del botón.
- **`"piloto"` → `"persona"`** tiene que ser una de sus claves. Si queda `"jeanpaul"` y esa persona ya no existe,
  `generar_fechas.py --piloto` falla. Las fechas de `"piloto"` deben caer dentro de `"rango_fechas"`.
- **`"voz_doby"`** es el nombre de la voz clonada, y **debe ser exactamente el mismo en tres lugares**:
  1. `"voz_doby"` en `fusion/hora.json`;
  2. la clave en `clonacion/entrenamiento/referencias_voz_f5.json`;
  3. la carpeta `clonacion/voz_comparacion_f5/referencias/<voz>/`.

---

## Paso 6. Grabar los nombres y convertirlos (en el PC)

1. **Lista exacta de archivos:** uno por cada `"audio"` de `integrantes.json`, tanto en `palabras` como en
   `frases`. El programa la imprime con ✔ o ✗:
   ```
   python fusion/voz.py --preparar
   ```
   Para cada uno que falta dice `✗ <palabra>  FALTA  (grabar como voces/<Audio>.*)`.
2. **Nombre del archivo:** exactamente el `"audio"`, **sin tildes ni ñ**, con `_` entre palabras y solo letras:
   `Ana.m4a`, `Gomez.mp3`, `Ana_Gomez.m4a`. Cuidado con:
   - `Ana (1).m4a` (descargado dos veces);
   - un espacio antes del punto;
   - las tildes.

   El programa no los encuentra.
3. **Formato:** `.mp3 .mp4 .m4a .wav .ogg .mpeg`, cualquier frecuencia, mono o estéreo. Las notas de voz de
   WhatsApp (`.opus`) hay que convertirlas: `ffmpeg -i "nota.opus" Ana.m4a`.
4. **Duración:** **al menos 1 s**, con unos 0,3–0,5 s de silencio **antes y después**, porque no se recorta nada.
   Graben en un lugar silencioso, a 20–30 cm del celular y sin saturar.
5. **Dónde van:** en **`voces/`** (ver `voces/LEEME.md`).
6. **Convertir para la placa** (necesita ffmpeg):
   ```
   python fusion/voz.py --preparar
   ```
   Deja en `fusion/audios_placa/` un WAV por audio: **16 000 Hz, mono, 16 bits**, con el nombre en minúsculas
   (`ana_gomez.wav`). El volumen se iguala solo. Esos WAV se suben a la placa en el paso 7.

**Espacio en la placa:**
- Cada segundo de audio ocupa unos **32 KB** (16 000 muestras × 2 bytes). Los 17 WAV del grupo original sumaban
  unos 1 477 KB.
- Cuánto espacio libre tiene la placa: POR VERIFICAR. **Compruébenlo en el paso 7.4** con el comando de ese paso.

**Qué falla si falta uno:**
- **Falta en el PC:** «Falta audio: Ana». La mano deletrea, pero **no suena nada**; si falta una palabra, no suena
  ninguna.
- **No se subió a la placa:** la placa responde `voz_falta:ana` y en pantalla sale «Falta audio: Ana (no está en
  la placa: súbelo a /voz con Thonny)».

Conversión manual a 16 kHz, mono y 16 bits (no hace falta, porque `voz.py` la hace solo):
- **ffmpeg:** `ffmpeg -i entrada.m4a -ac 1 -ar 16000 -sample_fmt s16 salida.wav`.
- **Audacity:** *Pistas → Mezclar → Mezclar estéreo a mono*, frecuencia del proyecto 16000 Hz,
  *Exportar → WAV, PCM con signo de 16 bits*.

---

## Paso 7. Preparar la ESP32 (solo USB, SIN los 12 V)

En este paso la placa va **solo por USB**. La mano no se moverá, y es normal (ver el paso 2).

### 7.1 Instalar MicroPython

**Qué archivo bajar:**
- Ir a https://micropython.org/download/ESP32_GENERIC_S3/ y bajar, de la sección de firmware, el archivo
  **`ESP32_GENERIC_S3-<fecha>-v1.28.0.bin`**: la versión **v1.28.0 de la variante genérica**, sin `SPIRAM_OCT` ni
  `FLASH_4M` en el nombre.
- Esa variante **no usa la PSRAM** de la N16R8, y el proyecto funciona igual.
- La fecha exacta del archivo: POR VERIFICAR.

**Cómo instalarlo:**
- Cómo se instaló en el proyecto: POR VERIFICAR.
- Una forma habitual es con Thonny: *Herramientas → Opciones → Intérprete → MicroPython (ESP32) → «Instalar o
  actualizar MicroPython (esptool)»*, eligiendo el puerto COM de la placa. Los nombres exactos de los menús: POR
  VERIFICAR.

**Comprobar:** al conectar, la consola de Thonny debe mostrar algo como
`MicroPython v1.28.0 … Generic ESP32S3 module with ESP32S3`. Si no dice `v1.28.0`, reinstalen.

El **puerto COM** solo lo usa Thonny, y se elige en esa pantalla o abajo a la derecha. El programa del PC no usa
ningún puerto COM.

### 7.2 Subir los archivos

En Thonny: *Ver → Archivos*. Arriba se ve el PC y abajo la placa. Para subir: clic derecho sobre el archivo del PC
→ **«Subir a /»**. Si Thonny no deja subir porque la placa está ocupada, presionen **Detener** (Stop).

Ya tienen todo: `config_ble.py` y `config_wifi.py` del paso 4, y los WAV del paso 6.

| Orden | Archivo del PC | Ruta en la placa | ¿Obligatorio? |
|---|---|---|---|
| 1 | `config_ble.py` (paso 4.1) | `/config_ble.py` | **Sí**: sin él, la placa solo atiende por USB |
| 2 | Los `.wav` de `fusion/audios_placa/` (paso 6) | carpeta **`/voz`** (crearla en el panel de la placa: clic derecho → nueva carpeta) | Para que suenen los nombres |
| 3 | `config_wifi.py` (paso 4.2) | `/config_wifi.py` | Solo para el botón Hora |
| 4 | `firmware_mano/wifi_hora.py` | `/wifi_hora.py` | Solo para el botón Hora |
| 5 | `firmware_mano/main.py` | `/main.py` | **Sí**: arranca solo al encender |

`main.py` va al final: es el que arranca solo, y conviene que lo demás ya esté en la placa.

### 7.3 Activar el WiFi del botón Hora: pegar 2 líneas en `/main.py`

El `firmware_mano/main.py` del repositorio **no trae** estas 2 líneas; en la placa original se pegaron a mano.
Sin ellas, la mano y la voz por Bluetooth funcionan, pero el botón Hora no. Si no van a usar el botón Hora, salten
este paso.

En Thonny: **Detener**, abrir **`/main.py` de la placa** (doble clic en el panel de la placa), pegar las 2 líneas
y guardar con Ctrl+S.

**Línea 1**, en la **columna 0** (sin espacios delante), justo **antes** de
`print("Listo. Esperando comandos...")` (`firmware_mano/main.py:522` en el repositorio):

```python
exec("try:\n import wifi_hora\n _wifi = wifi_hora.Wifi()\nexcept Exception as e:\n _wifi = None\n print('# WiFi desactivado:', e)")
```

**Línea 2**, con **8 espacios** delante, justo **antes** de `time.sleep_ms(5)` (`firmware_mano/main.py:531`):

```python
        if _wifi: _wifi.atender()
```

Antes → después:

```python
# ANTES                                          # DESPUÉS
print("Listo. Esperando comandos...")            exec("try:\n import wifi_hora\n _wifi = ...")   <- línea 1
seguir = True                                    print("Listo. Esperando comandos...")
while seguir:                                    seguir = True
    try:                                         while seguir:
        linea = usb.leer()                           try:
        if linea is not None:                            linea = usb.leer()
            seguir = atender_orden(linea, print)         if linea is not None:
        if seguir and ble is not None:                       seguir = atender_orden(linea, print)
            seguir = ble.atender(atender_orden)          if seguir and ble is not None:
        time.sleep_ms(5)                                     seguir = ble.atender(atender_orden)
                                                         if _wifi: _wifi.atender()              <- línea 2
                                                         time.sleep_ms(5)
```

Si algo del WiFi falla (no hay `config_wifi.py`, no hay red o falta memoria), la placa escribe
`# WiFi desactivado: …` y **la mano sigue funcionando igual**.

### 7.4 Comprobar la placa, ver su IP y el espacio libre (USB + Thonny + Ctrl+D)

**Mientras Thonny está conectado, `main.py` queda en pausa.** Para que arranque, hay que pulsar **Ctrl+D** en la
consola de Thonny (reinicio suave). Entonces se ve el arranque:

```
Iniciando motores...
Mano lista.
# WiFi: conectando (red cargada, N caracteres; TOKEN cargado, N caracteres)
Listo. Esperando comandos...
# WiFi listo: 192.168.x.x puerto 5001  RAM ... KB  ESP-IDF ... KB
```

1. **Su IP:** la de la línea `# WiFi listo: …`. Si ven `# WiFi desactivado: …`, revisen `config_wifi.py` y que
   el punto de acceso esté encendido. Pónganla en **`secretos.py`** del PC: `IP_FIJA = "192.168.x.x"`. Es el plan
   B por si `mano.local` no responde.
2. **El firmware:** escribir `version` en la consola → debe responder `version:voz-2`.
3. **La voz** (suena también por USB): escribir `voz ana` (un archivo de `/voz`, sin `.wav`) → se oye y responde
   `voz_ok`.
4. **Las letras:** escribir `a` responde `gesto_a_ok`, pero **los dedos no se mueven** con solo USB. Se prueban en
   el paso 8.
5. **Espacio libre:** presionen **Detener** y escriban en la consola:
   ```python
   import os; s = os.statvfs('/'); print(s[0] * s[3] // 1024, 'KB libres')
   ```

Para terminar: **cerrar Thonny** y **quitar el USB**.

---

## Paso 8. Primera prueba de la mano (12 V, sin USB)

1. Conectar los **12 V** (sin USB). Thonny **cerrado**. Bluetooth del PC activado.
2. En el PC:
   ```
   python fusion/consola_mano.py
   ```
   Dentro de la consola:
   - `!version` → `version:voz-2`;
   - `!a`, `!b`, `!e` → la mano hace esas letras;
   - `!reset` → se abre;
   - `!voz ana` → suena;
   - escribir `Ana Gomez` → la mano deletrea;
   - `salir` termina.
3. Con `!b` (pulgar y pulgar2 cerrados) y `!e` (los dos abiertos) vean **qué movimiento hace cada servo del
   pulgar** en su mano.

Si algo no se mueve bien, calibren (paso 9).

---

## Paso 9. Calibrar la mano (ciclo 12 V ↔ USB)

Los pulsos se calibran **para cada mano**. Están en **`firmware_mano/main.py:21-28`** (`dedos_config`), en
microsegundos, entre 500 y 2500:

```python
dedos_config = {
    "indice":   {"pin": 1,  "abierto": 500,  "cerrado": 2000, "mitad": 1000},
    "menique":  {"pin": 2,  "abierto": 500,  "cerrado": 2000, "mitad": 1200},
    "medio":    {"pin": 42, "abierto": 500,  "cerrado": 2000, "mitad": 1000},
    "anular":   {"pin": 4,  "abierto": 2200, "cerrado": 500,  "mitad": 1700},
    "pulgar":   {"pin": 40,  "abierto": 1500, "cerrado": 500,  "mitad": 1000},
    "pulgar2":  {"pin": 39,  "abierto": 700,  "cerrado": 2300, "mitad": 1600},
}
```

- **Ejemplo real:** en la mano del grupo original, el **anular** quedó con `"mitad": 1300` en la placa, mientras
  el repositorio tiene **1700**. Cada mano se calibra distinto.
- `"abierto"`, `"cerrado"` y `"mitad"` son posiciones de cada dedo. Algunas letras usan además un «cuarto»
  calculado entre abierto y mitad.
- **Las letras** son las funciones `a()` … `y()` (`main.py:92-217`). La tabla `acciones` (`main.py:219-225`) une
  cada letra con su función. Por ejemplo, `b()` abre índice, medio, anular y meñique (`mover_dedo(d, 0)`) y cierra
  pulgar y pulgar2 (`mover_dedo(..., 1)`).
- **Tiempos:** `PAUSA_DEDO = 0.4` s entre dedos y `PAUSA_LETRA = 1.0` s por letra (`main.py:7-8`).

**El ciclo de calibración.** Ver la letra necesita los 12 V; cambiar el pulso necesita el USB. Nunca los dos a la
vez:

```
 ┌─► 1. VER   12 V, sin USB, Thonny cerrado:  python fusion/consola_mano.py  →  !b  →  mirar el dedo  →  !reset  →  salir
 │   2. Desconectar los 12 V.
 │   3. CAMBIAR  USB + Thonny  →  Detener  →  abrir /main.py de la placa  →  cambiar el valor en dedos_config  →  Ctrl+S
 │   4. Cerrar Thonny y quitar el USB.
 └── 5. Volver a 1 hasta que la letra salga bien.
```

Al terminar:
1. **Copien los mismos valores** al `firmware_mano/main.py` del repositorio. El panel de la pantalla
   (`fusion/pantalla_mano.py`) lee los tiempos de ese archivo.
2. **No borren** las 2 líneas del WiFi (paso 7.3).
3. `fusion/pruebas/comparar_firmware.py` compara la parte de la mano de `main.py` con el respaldo
   `main_funciona_sin_voz.py`. Si cambian solo `main.py`, mostrará la diferencia, y es lo esperado. Para que vuelva a
   pasar, copien los mismos valores al respaldo.

---

## Paso 10. Ajustar rutas e IP a su computador

**Puerto COM:** el programa del PC no usa ninguno; solo Thonny (paso 7.1).

Estos archivos tienen rutas o la IP del PC original. **El único obligatorio es `fusion/hora.json:4`**, y solo
para el botón Hora:

| Archivo:línea | Qué tiene | Qué poner | ¿Obligatorio? |
|---|---|---|---|
| `fusion/hora.json:4` | `"doby": "C:/Users/miran/proyectoDoby"` | Ruta **absoluta** de su carpeta `clonacion`, con `/`: `"C:/Users/ana/Proyecto--Mano--Kinet/clonacion"` | **Sí**, para el botón Hora |
| `secretos.py` (`IP_FIJA`) | Lo crean ustedes (paso 4.2) | La IP de **su** placa (paso 7.4) | Recomendado |
| `fusion/pruebas/prueba_wifi_envio.py:46` | `DOBY_VOCES = r"C:\Users\miran\proyectoDoby\voz_cache_f5"` | `r"C:\Users\ana\Proyecto--Mano--Kinet\clonacion\voz_cache_f5"` | Solo si ejecutan esa prueba |
| `clonacion/entrenamiento/experimentos_voz/referencias_f5.py:7` | `RAIZ = r"C:\Users\miran\proyectoDoby"` | Ruta de su carpeta `clonacion` | Solo si usan ese script para recortar referencias |
| `clonacion/entrenamiento/experimentos_voz/referencia_ef.py:5` | igual | igual | igual |
| `clonacion/entrenamiento/experimentos_voz/f5_prueba_minima.py:20` | `R = r"C:\Users\miran\proyectoDoby"` | igual | Solo si ejecutan esa prueba |
| `clonacion/pc/config.py:4` | `IP_ESP32 = "192.168.43.228"` | — | No: es del proyecto anterior (Doby); la clonación no se conecta a la placa |
| `fusion/hora.py:21` | IP de ejemplo en un comentario | — | No |
| `fusion/herramientas/generar_fechas.py:8` | Ruta de ejemplo en un comentario | — | No |
| `fusion/referencia/dibujar_original.py:19` | `SAVE_DIR = r"C:\Users\miran\Dibujar\dibujos"` | — | No (copia vieja que no se ejecuta) |
| `docs/SUSTENTACION.md`, `docs/PLAN_FUSION.md`, `INFORME_PROYECTO.md`, `GUIA_CAMBIAR_VOCES.md`, `GUIA_VOZ_CLONADA_Y_HORA.md` | Rutas e IP del grupo original | — | No (son documentos) |

**Por qué la ruta absoluta en `hora.json`:** `"doby"` y `"horas"` se usan tal cual. Una ruta relativa se resolvería
desde la carpeta donde se ejecuta el comando, no desde la del repositorio.

---

## Paso 11. Ejecutar el programa completo

**Antes:**
- Placa con **12 V** y **sin USB**.
- **Thonny cerrado.**
- Bluetooth del PC activado.
- OBS con la **cámara virtual iniciada** (o una webcam).
- Entorno activado.
- Para el botón Hora: punto de acceso encendido y el PC conectado a él.

```
python fusion/dibujar_fusion.py
python fusion/dibujar_fusion.py --camara 0        otra cámara o webcam
python fusion/dibujar_fusion.py --voz-pc          plan B: todas las voces por los parlantes del PC
python fusion/dibujar_fusion.py --diagnostico     muestra el gesto que detecta MediaPipe
```

**Qué deberían ver y oír:**
1. En la consola, «Cargando TrOCR (microsoft/trocr-large-handwritten)…». La primera vez tarda.
2. La ventana con la imagen de la cámara. La mano se conecta por Bluetooth en segundo plano; si no conecta, se
   puede dibujar igual, y la tecla `r` reintenta.
3. **Índice:** escribe en el aire. **Mano abierta:** levanta el lápiz. **Pulgar abajo 1 s:** siguiente palabra
   (máximo 4).
4. **Pulgar arriba** → «Leí … → Entendí …». **Pulgar arriba 1,5 s** confirma y el **shaka** vuelve a dibujar.
5. **La mano deletrea** y la pantalla muestra cada letra. Las letras con movimiento (g h j ñ s z) salen en grande
   con la mano abierta. Al final **suena el nombre**.
6. **Botón «Hora»** (arriba a la derecha) o tecla `h` → menú con **hasta 4 voces** (índice 1 s, o teclas 1 a 4)
   → «Hoy es … Son las …». Necesita el paso 12.
7. Salir: `Esc` o `q`. Durante el deletreo, `Esc` detiene la mano y la abre.

**Pruebas sin hardware** (12 suites):

```
python fusion/reconocer.py --pruebas
python fusion/pruebas/prueba_mano_falsa.py
python fusion/pruebas/prueba_firmware_voz.py
python fusion/pruebas/prueba_voz_ble_falsa.py
python fusion/pruebas/prueba_reloj.py
python fusion/pruebas/comparar_firmware.py
python fusion/pruebas/prueba_wifi_hora_falsa.py
python fusion/pruebas/prueba_hora_wifi_falsa.py
python fusion/pruebas/prueba_boton_hora_falsa.py
python fusion/pruebas/prueba_hora.py
python fusion/pruebas/prueba_dibujar_falsa.py
python fusion/pruebas/prueba_voz_pc_falsa.py
```

Con el repositorio recién clonado y **sin grabaciones**, las 10 primeras pasan. Las 2 últimas fallan con «Falta
audio: Lina, Maldonado», porque usan las grabaciones del grupo original. Con los nombres de ustedes, también hay
que adaptar las pruebas (paso 5.1).

---

## Paso 12. (Opcional) Voces clonadas para el botón Hora

> [!WARNING]
> **Es la parte más difícil y es OPCIONAL: solo la usa el botón Hora.** Sin estos audios, todo lo demás funciona.
> **Los scripts de `clonacion/` se copiaron del proyecto anterior del grupo (Doby) y NO se probaron ejecutándolos
> desde este repositorio.** Las instrucciones siguen el código, pero pueden aparecer errores de rutas o archivos
> que falten. Necesita una GPU NVIDIA (el proyecto usó una RTX 5050 Laptop de 8 GB) y varias horas.
> Detalle técnico: [GUIA_VOZ_CLONADA_Y_HORA.md](GUIA_VOZ_CLONADA_Y_HORA.md).

### 12.1 Qué audios necesita el botón

Por cada voz del menú, **todo en WAV PCM de 16 000 Hz, mono y 16 bits** (`fusion/hora.py` rechaza otro formato):

| Qué | Cuántos | Nombre y carpeta | Ejemplo |
|---|---|---|---|
| Horas | **1440** (cada minuto) | `clonacion/voz_cache_f5/<voz_doby>/hora/hora_HHMM_<md5>.wav` | «Son las nueve y veintitrés de la noche.» |
| Fechas | Una por día de `"rango_fechas"` | `voces_clonadas/fecha/<persona>/fecha_AAAAMMDD_<md5>.wav` | «Hoy es viernes veinte de noviembre.» |

- El `<md5>` lo calculan los generadores a partir del texto; **no se escribe a mano**.
- **Si falta la fecha**, el botón dice **solo la hora**.
- **Si falta la hora**, no dice nada y aparece «Falta audio de la hora HH:MM».

### 12.2 Grabar y registrar las referencias

1. **Grabar:**
   - Cada persona lee en voz alta varias frases normales.
   - De ahí se recortan **3 clips de 6 a 12 s** por persona (una principal y dos respaldos), con voz clara y sin
     pausas largas. Se pueden recortar con Audacity.
   - Cada clip va con un `.txt` que dice **exactamente** lo que se oye:
     ```
     clonacion/voz_comparacion_f5/referencias/ana/ana_ref1.wav
     clonacion/voz_comparacion_f5/referencias/ana/ana_ref1.txt     <- Hola, me llamo Ana y estudio ingeniería.
     ```
   - **Formato:** las del proyecto original eran WAV de 48 kHz; otro formato está POR VERIFICAR. **Usen WAV mono
     de 48 kHz, como el original.**
2. **Registrar** en `clonacion/entrenamiento/referencias_voz_f5.json`. **Borren las voces del grupo original**
   (`camila`, `harry`, `jenpol`, `lina`): sus clips no vienen en el repositorio, y dejarlas puede hacer fallar los
   scripts que recorren todas las voces. El nombre de la voz debe ser igual al de la carpeta y al `"voz_doby"`
   (paso 5.2):
   ```json
   // antes:   "camila": [...], "harry": [...], "jenpol": [...], "lina": ["lina_refC2", "lina_refC1", "lina_refC3"]
   // después: "ana": ["ana_ref1", "ana_ref2", "ana_ref3"]
   ```
   El campo `"_nota"` puede quedarse.

### 12.3 Entorno `venv_f5` y modelos

1. **Crear el entorno** aparte del principal, porque F5 necesita otra versión de transformers:
   ```
   py -3.11 -m venv venv_f5
   venv_f5\Scripts\python.exe -m pip install -r clonacion\requirements_clonacion.txt
   ```
   Que esta instalación limpia quede igual a la original está POR VERIFICAR: la original heredaba paquetes del
   sistema. **Lo comprueban en el punto 12.4.1** con `--muestra`, antes de generar las 1440.
2. **Descargar los modelos** (con internet, una vez). Van a `clonacion/modelos/`; ver `clonacion/modelos/LEEME.md`.
   - **F5-Spanish** (`jpgallegoar/F5-Spanish`, el modelo y el vocabulario):
     ```
     venv_f5\Scripts\python.exe -c "from huggingface_hub import hf_hub_download as d; [d('jpgallegoar/F5-Spanish', f, local_dir='clonacion/modelos/f5-spanish') for f in ('model_1200000.safetensors', 'vocab.txt')]"
     ```
   - **Vocoder** `vocos-mel-24khz`:
     ```
     venv_f5\Scripts\python.exe -c "from huggingface_hub import snapshot_download as s; s('charactr/vocos-mel-24khz', local_dir='clonacion/modelos/f5-spanish/vocos-mel-24khz')"
     ```
     El repositorio de origen, `charactr/vocos-mel-24khz`, es POR VERIFICAR: es el que usa f5-tts por defecto.
     **Comprueben** que en esa carpeta queden `config.yaml` y `pytorch_model.bin` (52 MB).
   - **Whisper `medium`** (faster-whisper). Va a la caché de Hugging Face, porque `clonacion/pc/stt.py` lo carga con
     `WhisperModel("medium")`:
     ```
     venv_f5\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')"
     ```
   - Estos tres comandos salen de los nombres que usa el código, pero **no se probaron**. Si uno falla, busquen
     en la página de Hugging Face de cada modelo los archivos de la tabla de `clonacion/modelos/LEEME.md` y pónganlos
     en esas carpetas.
3. **Riesgo, POR VERIFICAR:** `clonacion/pc/voz_clonada.py:210` lee `clonacion/modelos/hablantes/hablantes.json`
   (la lista de integrantes del proyecto Doby), que **no está en el repositorio**. Si un script falla con
   `FileNotFoundError: …hablantes.json`, creen ese archivo con sus voces y vuelvan a ejecutar:
   ```json
   {"nombres": ["ana"]}
   ```

### 12.4 Generar y comprobar

1. **Las horas**, desde la carpeta `clonacion`:
   ```
   cd clonacion
   ..\venv_f5\Scripts\python.exe entrenamiento\generar_hora.py --persona ana --muestra    (60 horas de prueba)
   ..\venv_f5\Scripts\python.exe entrenamiento\generar_hora.py --persona ana              (las 1440)
   cd ..
   ```
   - Cada frase se revisa con Whisper. Se acepta si la similitud es ≥ 0,95 y la hora y los minutos son exactos.
   - Las dudosas van a `_revisar_de_oido/` y se aprueban con `--aprobar ana 2123` o se regeneran con
     `--rechazar ana 2123`.
   - Se puede cortar y retomar: salta lo que ya existe.
   - `generar_hora_noche.py` (todas las voces seguidas) tiene **fijas las voces del grupo original**: con otras
     voces, usen `generar_hora.py` para cada una.
   - **Tiempo:** con la RTX 5050 Laptop, de **50 a 92 min por voz** (~3,4 s por frase). Sin GPU NVIDIA: POR
     VERIFICAR. **Mídanlo con `--muestra`** (60 frases) antes de lanzar las 1440.
2. **Apuntar `hora.json`** a su carpeta `clonacion`, con ruta absoluta (paso 10):
   `"doby": "C:/Users/ana/Proyecto--Mano--Kinet/clonacion"`.
3. **Las fechas**, desde la carpeta del repositorio:
   ```
   venv_f5\Scripts\python.exe fusion/herramientas/generar_fechas.py --piloto           (las fechas de "piloto")
   venv_f5\Scripts\python.exe fusion/herramientas/generar_fechas.py --estimar          (cuánto tardará el total)
   venv_f5\Scripts\python.exe fusion/herramientas/generar_fechas.py --persona ana      (todo "rango_fechas")
   ```
   - Para cambiar los días que cubre, editen `"rango_fechas"` en `hora.json` antes de generar.
   - **Tiempo:** las 200 del proyecto original (50 fechas × 4 voces) tardaron 9,5 min con la RTX.
4. **Comprobar** (con el entorno principal):
   ```
   python fusion/hora.py --cobertura
   ```
   Debe decir `horas 1440/1440   fechas N/N` para cada voz.

---

## Paso 13. Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| **La mano no se mueve** al probar por USB | Normal: los servos necesitan los 12 V | Probar las letras con 12 V y `consola_mano.py` (paso 8) |
| En Thonny, `version` da un error de Python | `main.py` está en pausa | Pulsar **Ctrl+D** antes (paso 7.4) |
| **No suena el parlante**, pero la placa responde `voz_ok` | VIN del MAX98357 en 5Vin, o pines equivocados | VIN al **3V3**. Pines **DIN 7, BCLK 15, LRC 16** (no 15/48/47). Revisar el parlante |
| «Falta audio: …» | Falta la grabación en `voces/` o tiene otro nombre | Paso 6: renombrar, `voz.py --preparar` y subir a `/voz` |
| «Falta audio … (no está en la placa …)» | El WAV no está en `/voz` | Subirlo con Thonny (paso 7.2) |
| «La placa no pudo reproducir el audio (i2s)» | Amplificador o cables | Revisar el MAX98357; mientras tanto, `--voz-pc` |
| Voz distorsionada | Volumen alto para 1,5 W | Bajar `VOLUMEN` en `fusion/config_fusion.py` (máximo 0,5), volver a `--preparar` y subir |
| **La ESP32 no aparece por Bluetooth** | Thonny abierto, otro programa conectado, falta `/config_ble.py` o el Bluetooth del PC está apagado | Cerrar Thonny y `consola_mano.py` (un programa a la vez); revisar que `/config_ble.py` exista; en el arranque (Ctrl+D) no debe decir «Bluetooth desactivado» |
| «La mano rechazó el token» | `config_ble.py` distinto en el PC y en la placa | El mismo archivo en los dos lugares (paso 4.1) |
| «Falta config_ble.py en la carpeta del proyecto» | No se creó en el PC | Paso 4.1 |
| **El Kinect no se detecta** («No se abrió la cámara 1») | OBS sin cámara virtual, driver u otro índice | Comprobar en el Administrador de dispositivos y en OBS; iniciar la cámara virtual; probar índices (paso 3.3); o usar una webcam con `--camara 0` |
| **Servos que tiemblan** | Tierras no unidas, fuente débil o pulso fuera de rango | Unir todas las tierras; LM2596 a 5,0 V; calibrar (paso 9) |
| **La placa se reinicia** al mover la mano o al sonar | Fuente insuficiente o caída de voltaje | Medir el LM2596 **mientras se mueve**; adaptador con más amperios; servos nunca desde la ESP32; bajar `VOLUMEN` |
| Zumbido o ruido | Ruido de servos o de la fuente | Ver «Ruido y reinicios» en [CONEXIONES.md](CONEXIONES.md) |
| Botón Hora: «Sin WiFi en la mano …» | La placa no está en la red, faltan las 2 líneas (paso 7.3) o los TOKEN no coinciden | En el arranque (Ctrl+D), buscar `# WiFi listo: <IP>`; revisar los TOKEN de `config_wifi.py` y `secretos.py`; poner `IP_FIJA`; o usar `--voz-pc` |
| Botón Hora: «Falta audio de la hora HH:MM» | No existen las 1440 horas, o `hora.json:4` apunta a otra ruta | Pasos 12 y 10 |
| Botón Hora: dice solo la hora | Falta la fecha de hoy (fuera de `"rango_fechas"`) | Ampliar el rango y generar (paso 12.4) |
| `generar_fechas.py --piloto` falla | `"piloto"` → `"persona"` no existe en `hora.json` | Paso 5.2 |
| `FileNotFoundError: …hablantes.json` | Archivo del proyecto Doby que no viene | Paso 12.3, punto 3 |
| `ffmpeg no pudo leerlo` | ffmpeg no está en el PATH, o el archivo está dañado | Paso 3.2 |
| `ModuleNotFoundError` (cv2, torch…) | Se usó `py -3.11` en vez de `python` con el entorno activado | Activar `.venv` y usar `python` |
| `WinError 1114` al importar `c10.dll` | Orden de importación de torch | No cambiar el orden de los imports de `dibujar_fusion.py` (`import torch` va primero) |
| TrOCR no carga sin internet | No se descargó antes | Paso 3.1, punto 5, con internet |

---

## Lista de verificación final

**Hardware**
- [ ] LM2596 ajustado a **5,0 V** con el multímetro, antes de conectar nada.
- [ ] Servos en los GPIO 1, 2, 42, 4, 40, 39, alimentados desde el LM2596.
- [ ] MAX98357: DIN 7, BCLK 15, LRC 16, **VIN a 3V3**, GND en la tierra de la ESP32; parlante en + y −.
- [ ] **Todas las tierras unidas.**
- [ ] USB y 12 V **nunca** a la vez.

**PC** (entorno `.venv` activado, siempre `python`)
- [ ] torch instalado primero y después `requirements.txt`; TrOCR descargado una vez.
- [ ] `ffmpeg -version` y `ffprobe -version` responden.
- [ ] La cámara abre: Kinect por OBS con `--camara 1`, o webcam con `--camara N`.

**Configuración** (archivos que ustedes crean o cambian)
- [ ] `config_ble.py` con **su** TOKEN, en el PC.
- [ ] `fusion/integrantes.json` con **sus** integrantes, palabras, frases y `"audio"`, y `"ambiguos"` revisado.
- [ ] `PRUEBAS` de `fusion/reconocer.py` adaptada, y `python fusion/reconocer.py --pruebas` pasa.
- [ ] Solo para la Hora: `config_wifi.py` y `secretos.py` con el **mismo** TOKEN, PUERTO y NOMBRE; red de 2,4 GHz;
      `IP_FIJA` con la IP del paso 7.4.
- [ ] Solo para la Hora: `fusion/hora.json` con `"doby"` (línea 4) apuntando a **su** carpeta `clonacion`, y con
      **sus** `personas`, `orden_menu` (hasta 4), `piloto` y `rango_fechas`.

**Audios**
- [ ] Grabaciones en `voces/` con el nombre exacto de cada `"audio"`, al menos 1 s, con silencio antes y después.
- [ ] `python fusion/voz.py --preparar` dice «Listos N de N».
- [ ] Solo para la Hora: `python fusion/hora.py --cobertura` da `horas 1440/1440` y las fechas completas.

**Placa, por USB con Thonny**
- [ ] MicroPython v1.28.0 *Generic ESP32S3* (lo dice la consola de Thonny al conectar).
- [ ] En `/`: `config_ble.py` y `main.py`. Para la Hora, además `config_wifi.py`, `wifi_hora.py` y las **2 líneas**
      en `/main.py`.
- [ ] En `/voz/`: todos los `.wav` de `fusion/audios_placa/`, y espacio libre suficiente.
- [ ] Con **Ctrl+D**: `version` → `version:voz-2` y `voz <nombre>` → `voz_ok`; para la Hora, `# WiFi listo: <IP>`.
- [ ] Thonny cerrado y USB quitado.

**Mano, con 12 V y sin USB**
- [ ] `python fusion/consola_mano.py` → `!version`, `!a`, `!b`, `!e` y `!reset` mueven la mano como se espera.
- [ ] `dedos_config` calibrado con el ciclo del paso 9 y copiado también al `firmware_mano/main.py` del repositorio.
