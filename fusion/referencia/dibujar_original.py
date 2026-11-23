import cv2
import mediapipe as mp
import numpy as np
import os
import time
import warnings
import threading
import subprocess
from PIL import Image, ImageOps

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
warnings.filterwarnings("ignore")

from transformers import TrOCRProcessor, VisionEncoderDecoderModel
from TTS.utils.synthesizer import Synthesizer
import pygame

# ================== CONFIGURACIÓN ==================
SAVE_DIR = r"C:\Users\miran\Dibujar\dibujos"
os.makedirs(SAVE_DIR, exist_ok=True)

TTS_CACHE_DIR = os.path.join(SAVE_DIR, "tts_cache")
os.makedirs(TTS_CACHE_DIR, exist_ok=True)
EXTENSIONES_AUDIO = (".mp4", ".mp3", ".ogg", ".wav")

ANCHO, ALTO = 1920, 1080
SUAVIZADO = 3

MARGEN_INFERIOR = 200
LIMITE_INFERIOR = ALTO - MARGEN_INFERIOR

FRAMES_GUARDAR  = 8
FRAMES_COLOR    = 10
FRAMES_LIMPIAR  = 10
FRAMES_BOTON    = 20
FRAMES_GRACIA   = 5

BTN_CX, BTN_CY = 480, 170
BTN_RADIO = 65

COLORES = [(0, 255, 0), (255, 0, 0), (0, 0, 255)]
NOMBRES_COLORES = ["VERDE", "AZUL", "ROJO"]
color_idx = 0

COLOR_ACTIVO_UI   = (230, 200, 60)
COLOR_INACTIVO_UI = (30, 150, 255)
COLOR_BARRA       = (55, 40, 15)
COLOR_FLASH       = (60, 130, 190)

# ================== ESTADO ==================
activo = False
prev_x, prev_y = None, None
cnt_guardar = cnt_color = cnt_limpiar = cnt_boton = 0
gesto_anterior = None
tiempo_ultimo_gesto = 0
COOLDOWN = 1.5
frames_sin_deteccion = 0

flash_msg = ""
flash_time = 0.0
FLASH_DURACION = 1.4

# ================== CÁMARA ==================
cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)

# ================== MEDIAPIPE ==================
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
mp_drawing = mp.solutions.drawing_utils
mp_styles = mp.solutions.drawing_styles

# ================== CARGA DE IA ==================
print(" Cargando modelo TrOCR...")
ocr_processor = TrOCRProcessor.from_pretrained('microsoft/trocr-large-handwritten')
ocr_model = VisionEncoderDecoderModel.from_pretrained('microsoft/trocr-large-handwritten')
print(" Modelo TrOCR listo")

print(" Cargando modelo TTS...")
TTS_MODEL_PATH = r"C:\tts_model_espanol"

tts_model = Synthesizer(
    tts_checkpoint=os.path.join(TTS_MODEL_PATH, "model_file.pth.tar"),
    tts_config_path=os.path.join(TTS_MODEL_PATH, "config.json"),
    use_cuda=False
)
pygame.mixer.init()
print(" Modelo TTS listo")

drawing_canvas = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)

# ================== DETECCIÓN DE GESTOS ==================

def dedo_extendido(l, tip_id, pip_id, mcp_id=None):
    if mcp_id:
        return l[tip_id].y < l[pip_id].y - 0.02 and l[tip_id].y < l[mcp_id].y - 0.04
    return l[tip_id].y < l[pip_id].y - 0.02

def pulgar_extendido(l):
    return (l[mp_hands.HandLandmark.THUMB_TIP].y < l[mp_hands.HandLandmark.THUMB_IP].y - 0.02
            and l[mp_hands.HandLandmark.THUMB_TIP].y < l[mp_hands.HandLandmark.THUMB_MCP].y - 0.04)

def is_drawing(l):
    indice = dedo_extendido(l,
        mp_hands.HandLandmark.INDEX_FINGER_TIP,
        mp_hands.HandLandmark.INDEX_FINGER_PIP,
        mp_hands.HandLandmark.INDEX_FINGER_MCP)
    medio  = l[mp_hands.HandLandmark.MIDDLE_FINGER_TIP].y > l[mp_hands.HandLandmark.MIDDLE_FINGER_PIP].y
    anular = l[mp_hands.HandLandmark.RING_FINGER_TIP].y   > l[mp_hands.HandLandmark.RING_FINGER_PIP].y
    meniq  = l[mp_hands.HandLandmark.PINKY_TIP].y         > l[mp_hands.HandLandmark.PINKY_PIP].y
    return indice and medio and anular and meniq

def is_pulgar_arriba(l):
    pulgar = pulgar_extendido(l)
    indice = l[mp_hands.HandLandmark.INDEX_FINGER_TIP].y  > l[mp_hands.HandLandmark.INDEX_FINGER_PIP].y
    medio  = l[mp_hands.HandLandmark.MIDDLE_FINGER_TIP].y > l[mp_hands.HandLandmark.MIDDLE_FINGER_PIP].y
    anular = l[mp_hands.HandLandmark.RING_FINGER_TIP].y   > l[mp_hands.HandLandmark.RING_FINGER_PIP].y
    meniq  = l[mp_hands.HandLandmark.PINKY_TIP].y         > l[mp_hands.HandLandmark.PINKY_PIP].y
    return pulgar and indice and medio and anular and meniq

def is_tres_dedos(l):
    indice = dedo_extendido(l, mp_hands.HandLandmark.INDEX_FINGER_TIP,  mp_hands.HandLandmark.INDEX_FINGER_PIP)
    medio  = dedo_extendido(l, mp_hands.HandLandmark.MIDDLE_FINGER_TIP, mp_hands.HandLandmark.MIDDLE_FINGER_PIP)
    anular = dedo_extendido(l, mp_hands.HandLandmark.RING_FINGER_TIP,   mp_hands.HandLandmark.RING_FINGER_PIP)
    meniq  = l[mp_hands.HandLandmark.PINKY_TIP].y > l[mp_hands.HandLandmark.PINKY_PIP].y
    return indice and medio and anular and meniq

def is_shaka(l):
    pulgar = pulgar_extendido(l)
    indice = l[mp_hands.HandLandmark.INDEX_FINGER_TIP].y  > l[mp_hands.HandLandmark.INDEX_FINGER_PIP].y
    medio  = l[mp_hands.HandLandmark.MIDDLE_FINGER_TIP].y > l[mp_hands.HandLandmark.MIDDLE_FINGER_PIP].y
    anular = l[mp_hands.HandLandmark.RING_FINGER_TIP].y   > l[mp_hands.HandLandmark.RING_FINGER_PIP].y
    meniq  = dedo_extendido(l, mp_hands.HandLandmark.PINKY_TIP, mp_hands.HandLandmark.PINKY_PIP)
    return pulgar and indice and medio and anular and meniq

def dedo_en_boton(l):
    tip = l[mp_hands.HandLandmark.INDEX_FINGER_TIP]
    ix, iy = int(tip.x * ANCHO), int(tip.y * ALTO)
    dx, dy = ix - BTN_CX, iy - BTN_CY
    return (dx * dx + dy * dy) <= BTN_RADIO * BTN_RADIO

# ================== TTS ==================

def reproducir_audio(ruta_audio):
    pygame.mixer.music.load(ruta_audio)
    pygame.mixer.music.play()

    # 1. Esperamos a que el audio termine de reproducirse por completo
    while pygame.mixer.music.get_busy():
        time.sleep(0.1)

    # 2. SOLUCIÓN: Obligamos a Pygame a soltar el archivo en cuanto termina
    pygame.mixer.music.unload()

def hablar_texto(texto, nombre_archivo="output"):
    """Sintetiza el texto con el TTS en español y lo reproduce."""
    try:
        texto_procesado = texto.lower().strip()
        if not texto_procesado.endswith('.'):
            texto_procesado += '.'

        ruta_audio = os.path.join(TTS_CACHE_DIR, f"{nombre_archivo}.wav")

        wav = tts_model.tts(texto_procesado)
        tts_model.save_wav(wav, ruta_audio)

        reproducir_audio(ruta_audio)

        print(f" Voz reproducida: '{texto_procesado}'")
    except Exception as e:
        print(f" Error en TTS: {e}")

def buscar_audio_existente(nombre):
    """Busca en SAVE_DIR un audio cuyo nombre de archivo (sin extension) coincida
    con el nombre reconocido, sin importar mayusculas/minusculas. Si hay varias
    extensiones para el mismo nombre, se prefiere en el orden de EXTENSIONES_AUDIO."""
    nombre_lower = nombre.lower()
    try:
        archivos = os.listdir(SAVE_DIR)
    except OSError:
        return None
    candidatos = {}
    for f in archivos:
        base, ext = os.path.splitext(f)
        ext = ext.lower()
        if base.lower() == nombre_lower and ext in EXTENSIONES_AUDIO:
            candidatos[ext] = os.path.join(SAVE_DIR, f)
    for ext in EXTENSIONES_AUDIO:
        if ext in candidatos:
            return candidatos[ext]
    return None

def preparar_para_pygame(ruta):
    """pygame no reproduce .mp4 directamente; lo convierte a .wav con ffmpeg
    y guarda una copia en cache para no reconvertir cada vez."""
    ext = os.path.splitext(ruta)[1].lower()
    if ext in (".wav", ".mp3", ".ogg"):
        return ruta
    ruta_wav = os.path.join(TTS_CACHE_DIR, os.path.basename(os.path.splitext(ruta)[0]) + ".wav")
    if not os.path.exists(ruta_wav) or os.path.getmtime(ruta_wav) < os.path.getmtime(ruta):
        subprocess.run(
            ["ffmpeg", "-y", "-i", ruta, ruta_wav],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
    return ruta_wav

def hablar_o_reproducir_audio(texto_limpio, nombre):
    """Si ya existe un audio guardado con ese nombre lo reproduce tal cual;
    si no, cae de vuelta al TTS sintetico en espanol."""
    ruta_existente = buscar_audio_existente(nombre)
    if ruta_existente:
        try:
            ruta_reproducible = preparar_para_pygame(ruta_existente)
            reproducir_audio(ruta_reproducible)
            print(f" Voz reproducida: {os.path.basename(ruta_existente)}")
        except Exception as e:
            print(f" Error reproduciendo audio: {e}")
    else:
        hablar_texto(texto_limpio, nombre)
# ================== OCR ==================

def nombre_archivo_seguro(texto):
    limpio = "".join(c for c in texto if c.isalnum() or c in ("-", "_")).strip()
    return limpio if limpio else "palabra_" + time.strftime("%Y%m%d_%H%M%S")

def ocr_a_txt(ruta_png):
    try:
        imagen = cv2.imread(ruta_png)
        imagen = cv2.resize(imagen, (640, 480))
        fondo_blanco = np.ones_like(imagen) * 255
        gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        mascara = gris > 0
        fondo_blanco[mascara] = (0, 0, 0)
        kernel = np.ones((5, 5), np.uint8)
        fondo_blanco = cv2.erode(fondo_blanco, kernel, iterations=2)

        pil_img = Image.fromarray(fondo_blanco).convert("RGB")
        pixel_values = ocr_processor(images=pil_img, return_tensors="pt").pixel_values
        generated_ids = ocr_model.generate(pixel_values, max_new_tokens=30)
        texto = ocr_processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

        palabras = texto.split()
        texto_limpio = max(palabras, key=len) if palabras else ""
        print(f" Texto reconocido: '{texto_limpio}'")

        nombre = nombre_archivo_seguro(texto_limpio)
        ruta_txt = os.path.join(SAVE_DIR, f"{nombre}.txt")
        with open(ruta_txt, "w", encoding="utf-8") as f:
            f.write(texto_limpio)
        print(f" Texto guardado en {ruta_txt}")

        if texto_limpio:
            hablar_o_reproducir_audio(texto_limpio, nombre)

    except Exception as e:
        print(f" Error en OCR: {e}")

# ================== ACCIONES ==================

def mostrar_flash(msg):
    global flash_msg, flash_time
    flash_msg = msg
    flash_time = time.time()

def accion_guardar_palabra():
    global drawing_canvas
    if np.any(drawing_canvas > 0):
        ruta_png = os.path.join(SAVE_DIR, "palabra.png")
        cv2.imwrite(ruta_png, drawing_canvas)
        print(f" Palabra guardada en {ruta_png}")
        mostrar_flash("Leyendo y hablando...")

        drawing_canvas = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)

        threading.Thread(target=ocr_a_txt, args=(ruta_png,), daemon=True).start()
    else:
        print(" No hay nada dibujado")
        mostrar_flash("No hay nada dibujado")

def accion_cambiar_color():
    global color_idx
    color_idx = (color_idx + 1) % len(COLORES)
    print(f"Color: {NOMBRES_COLORES[color_idx]}")
    mostrar_flash(f"Color: {NOMBRES_COLORES[color_idx]}")

def accion_limpiar_canvas():
    global drawing_canvas
    drawing_canvas = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)
    print(" Canvas limpiado")
    mostrar_flash("Canvas limpiado")

def accion_toggle():
    global activo, drawing_canvas, prev_x, prev_y
    activo = not activo
    print("▶️ ACTIVADO" if activo else "⏹️ DESACTIVADO")
    drawing_canvas = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)
    prev_x, prev_y = None, None

def cooldown_ok(gesto, cd=None):
    global gesto_anterior, tiempo_ultimo_gesto
    if cd is None:
        cd = COOLDOWN
    ahora = time.time()
    if gesto != gesto_anterior or (ahora - tiempo_ultimo_gesto) > cd:
        gesto_anterior, tiempo_ultimo_gesto = gesto, ahora
        return True
    return False

# ================== UI ==================

def rect_redondeado(frame, pt1, pt2, color, radio, grosor=-1):
    x1, y1 = pt1
    x2, y2 = pt2
    cv2.rectangle(frame, (x1 + radio, y1), (x2 - radio, y2), color, grosor)
    cv2.rectangle(frame, (x1, y1 + radio), (x2, y2 - radio), color, grosor)
    for cx, cy in [(x1 + radio, y1 + radio), (x2 - radio, y1 + radio),
                   (x1 + radio, y2 - radio), (x2 - radio, y2 - radio)]:
        cv2.circle(frame, (cx, cy), radio, color, grosor)

def dibujar_ui(frame):
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (ANCHO, 110), COLOR_BARRA, -1)
    frame = cv2.addWeighted(overlay, 0.65, frame, 0.35, 0)

    color_estado = COLOR_ACTIVO_UI if activo else COLOR_INACTIVO_UI
    rect_redondeado(frame, (20, 20), (330, 90), color_estado, 18)
    cv2.circle(frame, (55, 55), 10, (255, 255, 255), -1)
    cv2.putText(frame, "ACTIVO" if activo else "INACTIVO", (85, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 3)

    for i, col in enumerate(COLORES):
        cx = 430 + i * 65
        seleccionado = (i == color_idx)
        radio = 26 if seleccionado else 20
        cv2.circle(frame, (cx, 55), radio, col, -1)
        borde = (255, 255, 255) if seleccionado else (110, 110, 110)
        cv2.circle(frame, (cx, 55), radio, borde, 3 if seleccionado else 1)

    btn_color = COLOR_ACTIVO_UI if activo else COLOR_INACTIVO_UI
    cv2.circle(frame, (BTN_CX, BTN_CY), BTN_RADIO, btn_color, -1)
    cv2.circle(frame, (BTN_CX, BTN_CY), BTN_RADIO, (255, 255, 255), 2)
    angulo = int(360 * (cnt_boton / FRAMES_BOTON))
    if angulo > 0:
        cv2.ellipse(frame, (BTN_CX, BTN_CY), (BTN_RADIO - 8, BTN_RADIO - 8),
                    -90, 0, angulo, (255, 255, 255), 6)
    cv2.putText(frame, "ON" if activo else "OFF",
                (BTN_CX - 42, BTN_CY + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 3)

    if activo:
        cv2.line(frame, (0, LIMITE_INFERIOR), (ANCHO, LIMITE_INFERIOR), (0, 200, 255), 2)
        cv2.putText(frame, "zona segura", (ANCHO - 300, LIMITE_INFERIOR - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)

    guia = "pulgar arriba=guardar | 3 dedos=color | shaka=limpiar" if activo else "lleva el dedo al circulo para activar"
    cv2.putText(frame, guia, (20, ALTO - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 180, 180), 2)

    if flash_msg and (time.time() - flash_time) < FLASH_DURACION:
        (tw, th), _ = cv2.getTextSize(flash_msg, cv2.FONT_HERSHEY_SIMPLEX, 1.1, 2)
        cx = ANCHO // 2
        x1, y1 = cx - tw // 2 - 24, 130
        x2, y2 = cx + tw // 2 + 24, 130 + th + 34
        rect_redondeado(frame, (x1, y1), (x2, y2), COLOR_FLASH, 16)
        cv2.putText(frame, flash_msg, (cx - tw // 2, y1 + th + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)

    return frame

# ================== LOOP PRINCIPAL ==================
print("=" * 50)
print("  DIBUJO CON KINECT")
print("=" * 50)
print("  Q                → Salir")
print("=" * 50)

cv2.namedWindow("Dibujar", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Dibujar", 1280, 720)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.convertScaleAbs(frame)
    frame = cv2.resize(frame, (ANCHO, ALTO))

    rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = hands.process(rgb)

    if result.multi_hand_landmarks:
        frames_sin_deteccion = 0
        for hl in result.multi_hand_landmarks:
            mp_drawing.draw_landmarks(
                frame, hl, mp_hands.HAND_CONNECTIONS,
                mp_styles.get_default_hand_landmarks_style(),
                mp_styles.get_default_hand_connections_style()
            )
            l = hl.landmark

            pulgar_det  = is_pulgar_arriba(l)
            tres_det    = is_tres_dedos(l)
            shaka_det   = is_shaka(l)
            drawing_det = is_drawing(l)
            boton_det   = dedo_en_boton(l)

            cnt_boton = cnt_boton + 1 if boton_det else 0
            if cnt_boton >= FRAMES_BOTON and cooldown_ok("boton"):
                accion_toggle()
                cnt_boton = 0

            if not activo:
                prev_x, prev_y = None, None
                continue

            cnt_guardar = cnt_guardar + 1 if pulgar_det and not shaka_det else 0
            cnt_color   = cnt_color + 1   if tres_det                     else 0
            cnt_limpiar = cnt_limpiar + 1 if shaka_det                    else 0

            if cnt_guardar >= FRAMES_GUARDAR and cooldown_ok("guardar"):
                accion_guardar_palabra()
                cnt_guardar = 0
                prev_x, prev_y = None, None

            elif cnt_color >= FRAMES_COLOR and cooldown_ok("color"):
                accion_cambiar_color()
                cnt_color = 0

            elif cnt_limpiar >= FRAMES_LIMPIAR and cooldown_ok("limpiar"):
                accion_limpiar_canvas()
                cnt_limpiar = 0

            elif drawing_det and not pulgar_det and not boton_det:
                tip    = l[mp_hands.HandLandmark.INDEX_FINGER_TIP]
                ix_raw = int(tip.x * ANCHO)
                iy_raw = int(tip.y * ALTO)

                if iy_raw < LIMITE_INFERIOR:
                    if prev_x is not None:
                        ix = int(prev_x + (ix_raw - prev_x) / SUAVIZADO)
                        iy = int(prev_y + (iy_raw - prev_y) / SUAVIZADO)
                        cv2.line(drawing_canvas, (prev_x, prev_y), (ix, iy), COLORES[color_idx], 20)
                    else:
                        ix, iy = ix_raw, iy_raw
                    cv2.circle(drawing_canvas, (ix, iy), 10, COLORES[color_idx], -1)
                    cv2.circle(frame,          (ix, iy), 12, COLORES[color_idx], -1)
                    prev_x, prev_y = ix, iy
                else:
                    pass

            else:
                prev_x, prev_y = None, None

    else:
        frames_sin_deteccion += 1
        cnt_boton = 0
        if frames_sin_deteccion >= FRAMES_GRACIA:
            cnt_guardar = cnt_color = cnt_limpiar = 0
            prev_x, prev_y = None, None

    combined = cv2.addWeighted(frame, 1, drawing_canvas, 1, 0)
    combined = dibujar_ui(combined)
    cv2.imshow("Dibujar", combined)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
