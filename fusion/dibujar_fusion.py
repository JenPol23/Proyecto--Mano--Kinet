"""
dibujar_fusion.py  -  CORRE EN EL PC (py -3.11)
C4: todo junto. Se dibuja en el aire con el Kinect el nombre de un integrante -> OCR -> confirmacion en pantalla ->
la mano deletrea por BLE (con el panel sincronizado de pantalla_mano.py) -> suena la voz original por la placa.

- Base: fusion/referencia/dibujar_original.py (gestos, lienzo y suavizado copiados de ahi; sin TTS ni pygame).
- TrOCR se carga una sola vez (reconocer.Ocr). La mano se conecta por BLE en segundo plano al arrancar; si no
  conecta, se puede dibujar igual: al confirmar se guarda el .txt y no se manda nada (r = reintentar).
- Gestos (MediaPipe):
    indice = dibuja · mano abierta = levanta el lapiz · pulgar abajo 1 s = siguiente palabra (se lee en segundo
    plano y se limpia el lienzo) · pulgar arriba = terminar · shaka = borrar la palabra actual · 3 dedos = color ·
    indice + medio (dos) 1 s = quitar la ultima palabra.
  Maximo MAX_PALABRAS palabras. Los gestos que se sostienen muestran un anillo de carga.
- Despues de cada accion o cambio de estado hay que SOLTAR el gesto (otro gesto o sin mano durante FRAMES_SOLTAR
  cuadros) antes de que cuente el siguiente: el pulgar arriba que termina no confirma y el shaka no borra.
- Estados: DIBUJANDO -> LEYENDO (espera la cola del OCR, en orden) -> CONFIRMAR ("Lei -> Entendi"; pulgar arriba
  1,5 s confirma, shaka vuelve) o RECHAZADO (3 s, no se manda nada) -> DELETREANDO (mano + voz en un hilo; Esc =
  DETENIENDO: detener(), reset y vuelve a DIBUJANDO) -> DIBUJANDO.
- La cola del OCR es UN hilo con las tareas en orden (leer, deshacer, terminar): si terminar o deshacer llegan
  mientras se lee una palabra, esperan a que termine.
- Un solo hilo usa la Mano a la vez (ControlMano.candado): el deletreo espera a que termine el intento de conexion.
- Cada dibujo es UNA palabra: TrOCR (max 12 tokens, sin repetir pares) a veces inventa algo en el blanco que
  sobra ("Jean Jean", "Jean F."). una_palabra() se queda con la palabra que mas se parece a un nombre o apellido
  de integrantes.json (o, si ninguna pasa el UMBRAL de reconocer.py, con la mas larga, como dibujar_original.py).
- Registros: fusion/salidas/<fecha>_<persona>.txt al confirmar (haya mano o no); por cada palabra, en
  fusion/registros/ocr_imagenes/, <fecha>_<n>.png (el lienzo que se manda) y <fecha>_<n>_trocr.png (lo que recibe
  TrOCR); fusion/registros/ocr.csv (una fila por palabra, con el texto CRUDO de TrOCR en 'leido'; nunca borra las
  anteriores); tiempos_mano.csv y tiempos_voz.csv los siguen escribiendo Mano.deletrear() y Voz.hablar().
- Teclas: r = reintentar la conexion BLE · d = modo diagnostico (gesto que ve MediaPipe) · Esc/q = salir (durante
  el deletreo: detener; un segundo Esc sale). Ctrl+C sale enseguida. Siempre se suelta el Bluetooth.
- Boton Hora (arriba a la derecha, dentro de la imagen del Kinect; dentro de el no se dibuja; o tecla h), solo en DIBUJANDO: indice sobre el boton 1 s ->
  MENU_HORA (4 voces: indice 1 s sobre una, o teclas 1-4; shaka o Esc cierra; se cierra solo tras SEG_MENU_HORA s)
  -> HORA: hora.decir() en un hilo, con el candado de la mano (nunca a la vez que el deletreo, la voz o la conexion
  BLE). La fecha y la hora van por WiFi (mano_wifi.py -> firmware_mano/wifi_hora.py) con la voz CLONADA; al terminar
  vuelve a DIBUJANDO sin borrar el lienzo. Si no se usa el boton, nada cambia.

Uso (desde la carpeta del proyecto; Thonny y cualquier otro programa conectado a la mano cerrados; 12 V, sin USB):
  py -3.11 fusion/dibujar_fusion.py                 (--camara N: indice de la camara, 1 = Kinect)
  py -3.11 fusion/dibujar_fusion.py --diagnostico
  py -3.11 fusion/dibujar_fusion.py --voz-pc       PLAN B: voces (nombres, fecha y hora) por los parlantes del PC
"""

import argparse
import asyncio
import concurrent.futures
import csv
import math
import os
import queue
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)

import torch  # noqa: E402,F401  PRIMERO: con cv2/mediapipe/PIL/bleak antes, c10.dll falla (WinError 1114)
import cv2                                              # noqa: E402
import numpy as np                                      # noqa: E402
from PIL import Image, ImageDraw, ImageFont             # noqa: E402

from consola_mano import MSG_DETENIDO, ErrorMano, Mano, leer_config, texto_tramos   # noqa: E402
from reconocer import UMBRAL, Integrantes, interpretar, palabras_de   # noqa: E402

CARPETA_SALIDAS = os.path.join(AQUI, "salidas")
CARPETA_IMAGENES = os.path.join(AQUI, "registros", "ocr_imagenes")
RUTA_OCR = os.path.join(AQUI, "registros", "ocr.csv")
TOKENS_PALABRA = 12                     # max_new_tokens de TrOCR para UNA palabra (reconocer.py usa 40)
COLUMNAS_OCR = ["intento", "fecha", "leido", "tiempo_ocr", "entendido", "coincidio"]

# ---------------- Pantalla (como dibujar_original.py) ----------------
ANCHO, ALTO = 1920, 1080
VENTANA = "Dibujar - mano LSC"
SUAVIZADO = 3
LIMITE_INFERIOR = ALTO - 200            # no se dibuja debajo (ahi va la guia)
FRAMES_GRACIA = 5                       # cuadros sin mano antes de levantar el lapiz
COLORES = [(0, 255, 0), (255, 0, 0), (0, 0, 255)]
NOMBRES_COLORES = ["verde", "azul", "rojo"]
COLOR_BARRA = (55, 40, 15)
COLOR_FLASH = (60, 130, 190)
VERDE, AMARILLO, ROJO, BLANCO, GRIS = (60, 180, 60), (0, 200, 230), (60, 60, 220), (255, 255, 255), (170, 170, 170)
RUTAS_FUENTE = [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"]   # con tildes (cv2 no las tiene)

# ---------------- Gestos y tiempos ----------------
MAX_PALABRAS = 4
FRAMES_SOLTAR = 5                       # cuadros con otro gesto (o sin mano) para soltar el gesto bloqueado
TOLERANCIA = 3                          # cuadros sueltos de otro gesto que no reinician un anillo
SEG_SOSTENER = {"pulgar_abajo": 1.0, "pulgar_arriba": 0.6, "shaka": 0.6, "tres": 0.6, "dos": 1.0,
                "confirmar": 1.5, "volver": 0.6, "hora": 1.0, "voz_hora": 1.0}
ETIQUETAS = {"pulgar_abajo": "Siguiente palabra", "pulgar_arriba": "Terminar", "shaka": "Borrar", "tres": "Color",
             "dos": "Deshacer", "confirmar": "Confirmar", "volver": "Volver a dibujar"}
SEG_AVISO = 2.5
SEG_RECHAZO = 3.0                       # RECHAZADO se ve este tiempo y vuelve a DIBUJANDO
SEG_PANEL_FINAL = 2.0                   # el panel de la mano queda este tiempo despues de terminar
PASO = 0.2                              # esperas en pasos cortos (Ctrl+C corta enseguida)

DIBUJANDO, LEYENDO, CONFIRMAR, RECHAZADO, DELETREANDO, DETENIENDO = (
    "DIBUJANDO", "LEYENDO", "CONFIRMAR", "RECHAZADO", "DELETREANDO", "DETENIENDO")

# ---------------- Boton Hora ----------------
MENU_HORA, HORA = "MENU_HORA", "HORA"
# La imagen del Kinect ocupa x ~250-1690 de las 1920 (franjas negras a los lados): el boton y el menu van dentro.
# Arriba a la derecha, bajo los avisos (y 125-185); dentro del boton no se dibuja.
BOTON_HORA = (1360, 190, 1640, 300)     # x1, y1, x2, y2
SEG_MENU_HORA = 5.0                     # el menu se cierra solo si nadie senala una voz este tiempo
SEG_ESPERA_HORA = 10.0                  # espera del candado (p. ej. mientras se conecta el Bluetooth)


def dentro(punto, rect):
    return punto is not None and rect[0] <= punto[0] <= rect[2] and rect[1] <= punto[1] <= rect[3]


def botones_voces(n):
    """Rectangulos de los n botones del menu de la hora, en fila y centrados."""
    ancho, sep = 300, 30                # 4 botones: x 315-1605, dentro de la imagen del Kinect
    x0 = (ANCHO - (n * ancho + (n - 1) * sep)) // 2
    return [(x0 + i * (ancho + sep), 430, x0 + i * (ancho + sep) + ancho, 590) for i in range(n)]


# ---------------- Deteccion de gestos (copiada de dibujar_original.py) ----------------
class HL:
    """Indices de los puntos de MediaPipe Hands (= mp.solutions.hands.HandLandmark)."""
    WRIST = 0
    THUMB_IP, THUMB_MCP, THUMB_TIP = 3, 2, 4
    INDEX_FINGER_MCP, INDEX_FINGER_PIP, INDEX_FINGER_TIP = 5, 6, 8
    MIDDLE_FINGER_MCP, MIDDLE_FINGER_PIP, MIDDLE_FINGER_TIP = 9, 10, 12
    RING_FINGER_MCP, RING_FINGER_PIP, RING_FINGER_TIP = 13, 14, 16
    PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20


def dedo_extendido(l, tip_id, pip_id, mcp_id=None):
    if mcp_id:
        return l[tip_id].y < l[pip_id].y - 0.02 and l[tip_id].y < l[mcp_id].y - 0.04
    return l[tip_id].y < l[pip_id].y - 0.02


def pulgar_extendido(l):
    return (l[HL.THUMB_TIP].y < l[HL.THUMB_IP].y - 0.02
            and l[HL.THUMB_TIP].y < l[HL.THUMB_MCP].y - 0.04)


def is_drawing(l):
    indice = dedo_extendido(l, HL.INDEX_FINGER_TIP, HL.INDEX_FINGER_PIP, HL.INDEX_FINGER_MCP)
    medio = l[HL.MIDDLE_FINGER_TIP].y > l[HL.MIDDLE_FINGER_PIP].y
    anular = l[HL.RING_FINGER_TIP].y > l[HL.RING_FINGER_PIP].y
    meniq = l[HL.PINKY_TIP].y > l[HL.PINKY_PIP].y
    return indice and medio and anular and meniq


def is_pulgar_arriba(l):
    pulgar = pulgar_extendido(l)
    indice = l[HL.INDEX_FINGER_TIP].y > l[HL.INDEX_FINGER_PIP].y
    medio = l[HL.MIDDLE_FINGER_TIP].y > l[HL.MIDDLE_FINGER_PIP].y
    anular = l[HL.RING_FINGER_TIP].y > l[HL.RING_FINGER_PIP].y
    meniq = l[HL.PINKY_TIP].y > l[HL.PINKY_PIP].y
    return pulgar and indice and medio and anular and meniq


def is_tres_dedos(l):
    indice = dedo_extendido(l, HL.INDEX_FINGER_TIP, HL.INDEX_FINGER_PIP)
    medio = dedo_extendido(l, HL.MIDDLE_FINGER_TIP, HL.MIDDLE_FINGER_PIP)
    anular = dedo_extendido(l, HL.RING_FINGER_TIP, HL.RING_FINGER_PIP)
    meniq = l[HL.PINKY_TIP].y > l[HL.PINKY_PIP].y
    return indice and medio and anular and meniq


def is_dos(l):
    """Nuevo: indice y medio extendidos, anular y meñique doblados (el pulgar no importa). Con 'tres' el anular va
    arriba y con 'indice' el medio va doblado: no se confunden."""
    indice = dedo_extendido(l, HL.INDEX_FINGER_TIP, HL.INDEX_FINGER_PIP)
    medio = dedo_extendido(l, HL.MIDDLE_FINGER_TIP, HL.MIDDLE_FINGER_PIP)
    anular = l[HL.RING_FINGER_TIP].y > l[HL.RING_FINGER_PIP].y
    meniq = l[HL.PINKY_TIP].y > l[HL.PINKY_PIP].y
    return indice and medio and anular and meniq


def is_shaka(l):
    pulgar = pulgar_extendido(l)
    indice = l[HL.INDEX_FINGER_TIP].y > l[HL.INDEX_FINGER_PIP].y
    medio = l[HL.MIDDLE_FINGER_TIP].y > l[HL.MIDDLE_FINGER_PIP].y
    anular = l[HL.RING_FINGER_TIP].y > l[HL.RING_FINGER_PIP].y
    meniq = dedo_extendido(l, HL.PINKY_TIP, HL.PINKY_PIP)
    return pulgar and indice and medio and anular and meniq


def _doblado(l, tip_id, pip_id):
    """Dedo doblado sin importar como este girada la mano: la punta queda mas cerca de la muñeca que el nudillo."""
    w = l[HL.WRIST]
    return math.hypot(l[tip_id].x - w.x, l[tip_id].y - w.y) < math.hypot(l[pip_id].x - w.x, l[pip_id].y - w.y)


def is_pulgar_abajo(l):
    """Nuevo: puño con el pulgar hacia abajo (la punta del pulgar bajo su nudillo y bajo los nudillos de la mano)."""
    pulgar = (l[HL.THUMB_TIP].y > l[HL.THUMB_IP].y + 0.02 and l[HL.THUMB_TIP].y > l[HL.THUMB_MCP].y + 0.04
              and l[HL.THUMB_TIP].y > l[HL.INDEX_FINGER_MCP].y)
    dedos = all(_doblado(l, t, p) for t, p in ((HL.INDEX_FINGER_TIP, HL.INDEX_FINGER_PIP),
                                              (HL.MIDDLE_FINGER_TIP, HL.MIDDLE_FINGER_PIP),
                                              (HL.RING_FINGER_TIP, HL.RING_FINGER_PIP),
                                              (HL.PINKY_TIP, HL.PINKY_PIP)))
    return pulgar and dedos


def is_mano_abierta(l):
    """Nuevo: los cuatro dedos extendidos (el pulgar no importa)."""
    return all(dedo_extendido(l, t, p, m) for t, p, m in (
        (HL.INDEX_FINGER_TIP, HL.INDEX_FINGER_PIP, HL.INDEX_FINGER_MCP),
        (HL.MIDDLE_FINGER_TIP, HL.MIDDLE_FINGER_PIP, HL.MIDDLE_FINGER_MCP),
        (HL.RING_FINGER_TIP, HL.RING_FINGER_PIP, HL.RING_FINGER_MCP),
        (HL.PINKY_TIP, HL.PINKY_PIP, HL.PINKY_MCP)))


def clasificar(l):
    """'pulgar_abajo' | 'shaka' | 'pulgar_arriba' | 'tres' | 'dos' | 'abierta' | 'indice' | 'nada' (en ese orden)."""
    if is_pulgar_abajo(l):
        return "pulgar_abajo"
    if is_shaka(l):
        return "shaka"
    if is_pulgar_arriba(l):
        return "pulgar_arriba"
    if is_tres_dedos(l):
        return "tres"
    if is_dos(l):
        return "dos"
    if is_mano_abierta(l):
        return "abierta"
    if is_drawing(l):
        return "indice"
    return "nada"


class Sostener:
    """Un gesto sostenido 'segundos'. Unos pocos cuadros de otro gesto (TOLERANCIA) no lo reinician."""

    def __init__(self, segundos):
        self.segundos = segundos
        self.desde = None
        self.fuera = 0

    def actualizar(self, activo, t):
        if activo:
            self.fuera = 0
            if self.desde is None:
                self.desde = t
        elif self.desde is not None:
            self.fuera += 1
            if self.fuera > TOLERANCIA:
                self.desde = None
        return activo and self.desde is not None and t - self.desde >= self.segundos

    def progreso(self, t):
        return 0.0 if self.desde is None else min(1.0, (t - self.desde) / self.segundos)

    def reiniciar(self):
        self.desde = None
        self.fuera = 0


# ---------------- OCR en orden ----------------
def una_palabra(crudo, vocabulario):
    """Lo que leyo TrOCR de UN dibujo -> una sola palabra (normalizada, con mayuscula inicial; '' si nada).
    Candidatos: cada palabra (sin signos, en minusculas; repetidas una vez) y todas unidas ("mal donado" ->
    "maldonado"). Gana la que mas se parece a una palabra del vocabulario (SequenceMatcher, como reconocer.py) si
    pasa el UMBRAL; si ninguna lo pasa, la mas larga (regla de dibujar_original.py) e interpretar() decide."""
    palabras = list(dict.fromkeys(palabras_de(crudo)))
    if not palabras:
        return ""
    candidatos = palabras + (["".join(palabras)] if len(palabras) > 1 else [])

    def parecido(c):
        return max(1.0 if c == v else SequenceMatcher(None, c, v).ratio() for v in vocabulario)

    mejor = max(candidatos, key=parecido)
    if parecido(mejor) < UMBRAL:
        mejor = max(palabras, key=len)
    return mejor.capitalize()


@dataclass
class Palabra:
    leido: str                                   # la palabra elegida (pantalla, interpretar y .txt)
    seg: float
    fecha: str
    crudo: str = ""                              # lo que devolvio TrOCR (ocr.csv)


class ColaOcr:
    """UN hilo y una cola FIFO: ('leer', png), ('deshacer',), ('terminar',), ('vaciar',). Asi terminar y deshacer
    esperan a la lectura en curso y todo se aplica en el orden en que se pidio."""

    def __init__(self, ocr, vocabulario=()):
        self.ocr = ocr
        self.vocabulario = vocabulario
        self.tareas = queue.Queue()
        self.candado = threading.Lock()
        self.palabras = []
        self.pendientes = 0                      # lecturas sin terminar
        self.listo = None                        # al procesar 'terminar': copia de las palabras
        self.errores = []
        threading.Thread(target=self._trabajar, daemon=True).start()

    def leer(self, ruta_png):
        with self.candado:
            self.pendientes += 1
        self.tareas.put(("leer", ruta_png))

    def deshacer(self):
        self.tareas.put(("deshacer",))

    def terminar(self):
        with self.candado:
            self.listo = None
        self.tareas.put(("terminar",))

    def vaciar(self):
        self.tareas.put(("vaciar",))

    def tomar_listo(self):
        with self.candado:
            listo, self.listo = self.listo, None
            return listo

    def vista(self):
        with self.candado:
            return [p.leido for p in self.palabras], self.pendientes

    def _trabajar(self):
        while True:
            tarea = self.tareas.get()
            if tarea[0] == "leer":
                inicio = time.perf_counter()
                vista = tarea[1][:-len(".png")] + "_trocr.png"
                try:
                    crudo = (self.ocr.leer(tarea[1], max_tokens=TOKENS_PALABRA, guardar_vista=vista) or "").strip()
                except Exception as e:                   # el programa no se cae por el OCR
                    crudo = ""
                    self.errores.append("Error en el OCR ({})".format(type(e).__name__))
                palabra = Palabra(una_palabra(crudo, self.vocabulario), time.perf_counter() - inicio,
                                  datetime.now().isoformat(sep=" ", timespec="milliseconds"), crudo)
                with self.candado:
                    self.palabras.append(palabra)
                    self.pendientes -= 1
                    n = len(self.palabras)
                print("  palabra {}: '{}' -> '{}' ({:.1f} s)".format(n, crudo, palabra.leido, palabra.seg))
            elif tarea[0] == "deshacer":
                with self.candado:
                    if self.palabras:
                        self.palabras.pop()
            elif tarea[0] == "terminar":
                with self.candado:
                    self.listo = list(self.palabras)
            elif tarea[0] == "vaciar":
                with self.candado:
                    self.palabras = []


# ---------------- Mano (un solo hilo a la vez) ----------------
class ControlMano:
    """Mano + Voz. Conexion, deletreo+voz y reset van cada uno en su hilo, siempre con el candado tomado."""

    def __init__(self, integrantes, crear_mano=None, crear_voz=None, decir_hora=None, voz_pc=False):
        self.crear_mano = crear_mano or Mano
        self.decir_hora_fn = decir_hora          # None = hora.decir() (se importa solo al usar el boton)
        self.hora_en_curso = False
        self.hora_final = None                   # dict de hora.decir(): 'resultado' y 'mensaje'
        self.voz_pc = voz_pc                     # plan B (--voz-pc): nombres y hora por los parlantes del PC
        if crear_voz is None and voz_pc:
            from voz_pc import VozPC

            def crear_voz(mano):
                return VozPC(mano, integrantes)
        if crear_voz is None:
            from voz import Voz

            def crear_voz(mano):
                return Voz(mano, integrantes)
        self.crear_voz = crear_voz
        self.candado = threading.Lock()
        self.mano = None
        self.voz = None
        self.estado = "sin mano"                 # 'conectando' | 'conectada' | 'sin mano'
        self.detalle = ""
        self.con_voz = False
        self.ocupada = False                     # deletreo + voz en curso
        self.deteniendo = False                  # reset despues de Esc en curso
        self.final = None                        # (ok, mensaje) del ultimo deletreo
        self.cerrado = False
        self._parar = False
        self.noticias = []                       # mensajes para la pantalla (los toma Sesion)

    def _noticia(self, texto):
        print("  " + texto)
        self.noticias.append(texto)

    # --- conexion ---
    def conectar_fondo(self):
        if self.cerrado or self.estado == "conectando" or self.ocupada or self.deteniendo:
            return False
        self.estado = "conectando"
        threading.Thread(target=self._conectar, daemon=True).start()
        return True

    def reintentar(self):
        """Tecla r. Devuelve el mensaje para la pantalla."""
        if self.ocupada or self.deteniendo:
            return "Espera a que termine el deletreo"
        if self.estado == "conectando":
            return "Ya se está conectando con la mano"
        self.conectar_fondo()
        return "Reintentando la conexión con la mano…"

    def _conectar(self):
        with self.candado:
            try:
                if self.cerrado:
                    return
                if self.mano is None or self.mano.cerrada:
                    self.mano = self.crear_mano()
                    self.voz = self.crear_voz(self.mano)
                ok, mensaje = self.mano.conectar()
                if not ok:
                    self.estado, self.detalle = "sin mano", mensaje
                    self._noticia("Sin mano: {}. r = reintentar".format(mensaje))
                    return
                self.con_voz, version = self.voz.comprobar_placa()
                self.estado, self.detalle = "conectada", version
                self._noticia("Mano conectada ({})".format(version) if self.con_voz
                              else "Mano conectada, pero sin voz: {}".format(version))
            except Exception as e:
                self.estado, self.detalle = "sin mano", "error ({})".format(type(e).__name__)
                self._noticia("Sin mano: {}. r = reintentar".format(self.detalle))

    def puede_deletrear(self):
        return not self.cerrado and self.estado in ("conectada", "conectando")

    def texto_estado(self):
        """(texto, color) para la barra de arriba."""
        if self.estado == "conectando":
            return "Mano: conectando…", AMARILLO
        if self.estado == "conectada":
            if self.mano is not None and not self.mano.conectada and not self.ocupada:
                return "Mano: desconectada (r = reintentar)", AMARILLO
            return "Mano: conectada ({})".format(self.detalle if self.con_voz else "sin voz"), VERDE
        return "Mano: sin conexión (r = reintentar)", ROJO

    # --- deletreo + voz ---
    def deletrear_y_hablar(self, resultado, seguimiento=None):
        self.ocupada = True
        self._parar = False
        self.final = None
        threading.Thread(target=self._trabajo, args=(resultado, seguimiento), daemon=True).start()

    def _trabajo(self, r, seguimiento):
        final = (False, MSG_DETENIDO)
        self.candado.acquire()                   # espera a que termine el intento de conexion
        try:
            if self._parar or self.cerrado:
                final = (False, MSG_DETENIDO)
            elif self.estado != "conectada":
                final = (False, "Sin mano: {} (no se mandó nada)".format(self.detalle))
            else:
                print("  Deletreando:  {}".format("  |  ".join(texto_tramos(t) for t in r.tramos)))
                ok, mensaje = self.mano.deletrear(r, seguimiento.evento if seguimiento else None)
                if self._parar:
                    final = (False, MSG_DETENIDO)
                elif not ok:
                    final = (False, mensaje + "  (no se hace sonar la voz)")
                elif not self.con_voz:
                    final = (False, "Deletreo completo; no suena: {}".format(self.detalle))
                else:
                    if seguimiento is not None:
                        seguimiento.hablando()
                    final = self.voz.hablar(r)
                for aviso in (self.mano.aviso_tiempos, self.voz.aviso_tiempos):
                    if aviso:
                        self._noticia(aviso)
        except (concurrent.futures.CancelledError, asyncio.CancelledError):
            final = (False, MSG_DETENIDO)
        except ErrorMano as e:
            final = (False, str(e))
        except Exception as e:                   # la ventana nunca se cae por la mano
            final = (False, "Error con la mano ({})".format(type(e).__name__))
        finally:
            self.candado.release()               # siempre: el reset de detener() no queda bloqueado
            self.final = final
            if seguimiento is not None:
                seguimiento.terminado(*final)
            print("  {} {}".format("✔" if final[0] else "✗", final[1]))
            self.ocupada = False

    def detener(self):
        """Esc durante el deletreo: corta la orden en curso, espera a que suelte el candado y manda reset."""
        if not self.ocupada or self.deteniendo:
            return
        self.deteniendo = True
        self._parar = True
        if self.mano is not None:
            self.mano.detener()
        if self.voz_pc and self.voz is not None:
            self.voz.detener()                   # plan B: corta el sonido del PC
        threading.Thread(target=self._resetear, daemon=True).start()

    def _resetear(self):
        try:
            while not self.candado.acquire(timeout=PASO):
                if self.cerrado:
                    return
                if self.mano is not None:
                    self.mano.detener()          # por si la orden empezo justo despues del primer detener()
            try:
                if not self.cerrado and self.mano is not None and self.mano.conectada:
                    ok, mensaje = self.mano.reset()
                    self._noticia("Detenido: mano abierta" if ok else "Detenido; reset: {}".format(mensaje))
                else:
                    self._noticia("Detenido")
            finally:
                self.candado.release()
        finally:
            self.deteniendo = False

    # --- boton Hora (WiFi; con el mismo candado: nunca a la vez que el deletreo, la voz o la conexion) ---
    def decir_hora(self, persona):
        """Empieza a decir la fecha y la hora con la voz de 'persona' en un hilo. False si la mano esta ocupada."""
        if self.cerrado or self.ocupada or self.deteniendo or self.hora_en_curso:
            return False
        self.hora_en_curso = True
        self.hora_final = None
        threading.Thread(target=self._hora, args=(persona,), daemon=True).start()
        return True

    def _hora(self, persona):
        final = {"resultado": "error", "mensaje": "Error con la hora"}
        try:
            if not self.candado.acquire(timeout=SEG_ESPERA_HORA):
                final = {"resultado": "ocupada", "mensaje": "La mano está ocupada; pide la hora otra vez"}
                return
            try:
                if self.cerrado:
                    return
                if self.decir_hora_fn is None:
                    import hora
                    config = hora.Config()
                    if self.voz_pc:
                        self.decir_hora_fn = lambda p: hora.decir(config, p, en_pc=True)
                    else:
                        self.decir_hora_fn = lambda p: hora.decir(config, p)
                final = self.decir_hora_fn(persona)
            finally:
                self.candado.release()
        except Exception as e:                   # la ventana nunca se cae por la hora
            final = {"resultado": "error", "mensaje": "Error con la hora ({})".format(type(e).__name__)}
        finally:
            self.hora_final = final
            print("  {} {}".format("✔" if final.get("resultado") == "ok" else "✗", final.get("mensaje", "")))
            self.hora_en_curso = False

    def cerrar(self):
        """Corta todo y suelta el Bluetooth (sin reset). Se puede llamar varias veces."""
        self.cerrado = True
        self._parar = True
        if self.mano is not None:
            self.mano.cerrar()


# ---------------- Registros ----------------
def guardar_txt(r, palabras, estado_mano, carpeta=CARPETA_SALIDAS, ahora=None):
    """fusion/salidas/<fecha>_<persona>.txt con lo leido y lo entendido. Devuelve la ruta."""
    ahora = ahora or datetime.now()
    os.makedirs(carpeta, exist_ok=True)
    base = os.path.join(carpeta, "{}_{}".format(ahora.strftime("%Y-%m-%d_%H-%M-%S"), r.persona))
    ruta, n = base + ".txt", 1
    while os.path.exists(ruta):
        n += 1
        ruta = "{}_{}.txt".format(base, n)
    lineas = ["fecha: {}".format(ahora.isoformat(sep=" ", timespec="seconds")),
              "leído: {}".format(r.leido),
              "palabras leídas: {}".format(" | ".join(p.leido for p in palabras)),
              "OCR crudo: {}".format(" | ".join(p.crudo for p in palabras)),
              "entendido: {}".format(r.mostrar),
              "persona: {} ({})".format(r.persona, r.tipo),
              "mano: {}".format("  |  ".join(texto_tramos(t) for t in r.tramos)),
              "audios: {}".format(" ".join(r.audios)),
              "estado de la mano: {}".format(estado_mano)]
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    return ruta


def guardar_ocr(filas, ruta=RUTA_OCR):
    """Agrega las filas de un intento a ocr.csv. Devuelve un aviso si no se pudo (o '' si todo bien)."""
    if not filas:
        return ""
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        nuevo = not os.path.exists(ruta)
        with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS_OCR)
            if nuevo:
                w.writeheader()
            w.writerows(filas)
        return ""
    except OSError as e:
        return "No se pudo guardar ocr.csv ({}): ¿está abierto en Excel?".format(e.strerror or e)


# ---------------- Texto con tildes (cv2.putText no las tiene) ----------------
_fuentes = {}


def fuente(tam):
    if tam not in _fuentes:
        _fuentes[tam] = None
        for ruta in RUTAS_FUENTE:
            try:
                _fuentes[tam] = ImageFont.truetype(ruta, tam)
                break
            except OSError:
                pass
    return _fuentes[tam]


def sin_tildes(texto):
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").encode("ascii", "replace").decode()


class Rotulos:
    """Junta los textos de un cuadro y los pinta de una vez con PIL (y = linea base)."""

    def __init__(self):
        self.items = []

    def poner(self, texto, x, y, tam, color=BLANCO, centro=False):
        self.items.append((texto, int(x), int(y), tam, color, centro))

    @staticmethod
    def ancho(texto, tam):
        f = fuente(tam)
        if f is None:
            return cv2.getTextSize(sin_tildes(texto), cv2.FONT_HERSHEY_SIMPLEX, tam / 32, 2)[0][0]
        return int(f.getlength(texto))

    def pintar(self, img):
        if not self.items:
            return img
        if fuente(20) is None:
            for texto, x, y, tam, color, centro in self.items:
                if centro:
                    x -= self.ancho(texto, tam) // 2
                cv2.putText(img, sin_tildes(texto), (x, y), cv2.FONT_HERSHEY_SIMPLEX, tam / 32, color, 2)
            return img
        pil = Image.fromarray(img)               # la imagen es BGR: el color se pasa tal cual (BGR)
        d = ImageDraw.Draw(pil)
        for texto, x, y, tam, color, centro in self.items:
            d.text((x, y), texto, font=fuente(tam), fill=tuple(color), anchor="ms" if centro else "ls")
        return np.array(pil)


def rect_redondeado(frame, pt1, pt2, color, radio, grosor=-1):
    x1, y1 = pt1
    x2, y2 = pt2
    cv2.rectangle(frame, (x1 + radio, y1), (x2 - radio, y2), color, grosor)
    cv2.rectangle(frame, (x1, y1 + radio), (x2, y2 - radio), color, grosor)
    for cx, cy in [(x1 + radio, y1 + radio), (x2 - radio, y1 + radio),
                   (x1 + radio, y2 - radio), (x2 - radio, y2 - radio)]:
        cv2.circle(frame, (cx, cy), radio, color, grosor)


def panel(frame, pt1, pt2, color=(30, 30, 30), alfa=0.8):
    capa = frame.copy()
    rect_redondeado(capa, pt1, pt2, color, 24)
    return cv2.addWeighted(capa, alfa, frame, 1 - alfa, 0)


def anillo(frame, centro, radio, progreso, color=BLANCO):
    if progreso > 0:
        cv2.ellipse(frame, centro, (radio, radio), -90, 0, int(360 * progreso), color, 8)


# ---------------- La sesion (toda la logica; no conoce la camara) ----------------
class Sesion:
    def __init__(self, ocr, control, integrantes, carpeta_salidas=CARPETA_SALIDAS, ruta_ocr=RUTA_OCR,
                 diagnostico=False, carpeta_imagenes=CARPETA_IMAGENES):
        self.cola = ColaOcr(ocr, integrantes.vocabulario)
        self.control = control
        self.integrantes = integrantes
        self.carpeta_salidas = carpeta_salidas
        self.carpeta_png = carpeta_imagenes
        self.ruta_ocr = ruta_ocr
        self.diagnostico = diagnostico
        self.lienzo = np.zeros((ALTO, ANCHO, 3), np.uint8)
        self.color_idx = 0
        self.prev = None
        self.sin_mano = 0
        self.estado = DIBUJANDO
        self.desde = 0.0
        self.t = 0.0
        self.gesto = None
        self.punto = None
        self.bloqueado = None                    # gesto que hay que soltar antes de contar el siguiente
        self.distinto = 0
        self.sost = {n: Sostener(s) for n, s in SEG_SOSTENER.items()}
        self.cuenta = 0                          # palabras pedidas (leidas + en cola - deshechas)
        self.n_png = 0
        self.palabras = []                       # palabras del intento en curso (al terminar)
        self.resultado = None
        self.ruta_txt = None
        self.reloj = None
        self.seguimiento = None
        self.ventana_mano = None
        self.fin_t = None
        self.aviso = ""
        self.aviso_hasta = 0.0
        self.salir = False
        self.voces_hora = None                   # [(persona, nombre)] de hora.json, al abrir el menu la 1a vez
        self.voz_apuntada = None                 # boton del menu que senala el indice
        self.menu_actividad = 0.0
        self.voz_elegida = ""

    # --- entrada ---
    def cuadro(self, gesto, punto, t):
        """Un cuadro de la camara: gesto de clasificar() (None = sin mano) y punta del indice en pixeles."""
        self.t, self.gesto, self.punto = t, gesto, punto
        self._soltar(gesto)
        self._noticias()
        self._avanzar(t)
        g = None if self.bloqueado else gesto
        if self.estado == DIBUJANDO:
            self._dibujando(g, punto, t)
        elif self.estado == CONFIRMAR:
            if self.sost["confirmar"].actualizar(g == "pulgar_arriba", t):
                self._confirmar()
            elif self.sost["volver"].actualizar(g == "shaka", t):
                self._cambiar(DIBUJANDO)
                self._avisar("Vuelve a dibujar (índice + medio 1 s quita la última palabra)")
        elif self.estado == MENU_HORA:
            self._menu_hora(g, punto, t)

    def tecla(self, k):
        if self.estado == MENU_HORA and (k == 27 or ord("1") <= k <= ord("4")):
            if k == 27:
                self._cerrar_menu_hora("Menú de la hora cerrado")
            elif k - ord("1") < len(self.voces_hora):
                self._decir_hora(k - ord("1"))
            return
        if k == ord("h"):
            if self.estado == DIBUJANDO:
                self._abrir_menu_hora()
            elif self.estado != MENU_HORA:
                self._avisar("La hora se pide mientras se dibuja")
            return
        if k in (27, ord("q")):
            if self.estado == DELETREANDO:
                self.control.detener()
                self._cambiar(DETENIENDO)
            else:
                self.salir = True                # tambien con un segundo Esc mientras se detiene
        elif k == ord("r"):
            self._avisar(self.control.reintentar())
        elif k == ord("d"):
            self.diagnostico = not self.diagnostico

    # --- estados ---
    def _cambiar(self, estado):
        print("  [{}]".format(estado))
        self.estado = estado
        self.desde = self.t
        self._bloquear()

    def _bloquear(self):
        self.bloqueado = self.gesto if self.gesto not in (None, "nada") else None
        self.distinto = 0
        self.prev = None
        for s in self.sost.values():
            s.reiniciar()

    def _soltar(self, gesto):
        if self.bloqueado is None:
            return
        if gesto == self.bloqueado:
            self.distinto = 0
        else:
            self.distinto += 1
            if self.distinto >= FRAMES_SOLTAR:
                self.bloqueado = None
                self.distinto = 0

    def _avisar(self, texto, segundos=SEG_AVISO):
        self.aviso = texto
        self.aviso_hasta = self.t + segundos

    def _noticias(self):
        while self.control.noticias:
            self._avisar(self.control.noticias.pop(0), 4.0)
        while self.cola.errores:
            self._avisar(self.cola.errores.pop(0), 4.0)

    def _avanzar(self, t):
        if self.estado == LEYENDO:
            listo = self.cola.tomar_listo()
            if listo is not None:
                self._interpretar(listo)
        elif self.estado == RECHAZADO:
            if t - self.desde >= SEG_RECHAZO:
                self._cambiar(DIBUJANDO)
        elif self.estado == DELETREANDO:
            if not self.control.ocupada:
                if self.fin_t is None:
                    self.fin_t = t
                    ok, mensaje = self.control.final or (False, "")
                    self._avisar(mensaje, 4.0)
                elif t - self.fin_t >= SEG_PANEL_FINAL:
                    self._fin_intento()
        elif self.estado == DETENIENDO:
            if not self.control.ocupada and not self.control.deteniendo:
                self._fin_intento()
        elif self.estado == HORA:
            if not self.control.hora_en_curso:
                r = self.control.hora_final or {}
                self._cambiar(DIBUJANDO)         # sin borrar el lienzo ni las palabras
                self._avisar(r.get("mensaje") or "Listo", 5.0)

    def _fin_intento(self):
        self.cola.vaciar()
        self.cuenta = 0
        self.lienzo[:] = 0
        self.resultado = self.seguimiento = self.ventana_mano = None
        self._cambiar(DIBUJANDO)

    # --- DIBUJANDO ---
    def _dibujando(self, g, punto, t):
        if self.sost["hora"].actualizar(g == "indice" and dentro(punto, BOTON_HORA), t):
            self._abrir_menu_hora()
            return
        for nombre, accion in (("pulgar_abajo", self._siguiente), ("pulgar_arriba", self._terminar),
                               ("shaka", self._limpiar), ("tres", self._color), ("dos", self._deshacer)):
            if self.sost[nombre].actualizar(g == nombre, t):
                accion()
                self._bloquear()
                return
        if g is None and self.gesto is None:
            self.sin_mano += 1
            if self.sin_mano >= FRAMES_GRACIA:
                self.prev = None
            return
        self.sin_mano = 0
        if g == "indice" and punto is not None and punto[1] < LIMITE_INFERIOR and not dentro(punto, BOTON_HORA):
            x, y = punto
            if self.prev is not None:
                x = int(self.prev[0] + (x - self.prev[0]) / SUAVIZADO)
                y = int(self.prev[1] + (y - self.prev[1]) / SUAVIZADO)
                cv2.line(self.lienzo, self.prev, (x, y), COLORES[self.color_idx], 20)
            cv2.circle(self.lienzo, (x, y), 10, COLORES[self.color_idx], -1)
            self.prev = (x, y)
        else:
            self.prev = None                     # mano abierta (o cualquier otro gesto): lapiz arriba

    def hay_trazo(self):
        return bool(np.any(self.lienzo))

    def _encolar_trazo(self):
        os.makedirs(self.carpeta_png, exist_ok=True)
        self.n_png += 1
        ruta = os.path.join(self.carpeta_png, "{}_{}.png".format(datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
                                                                 self.n_png))
        cv2.imwrite(ruta, self.lienzo)
        self.cola.leer(ruta)
        self.cuenta += 1
        self.lienzo[:] = 0
        self.prev = None

    def _siguiente(self):
        if not self.hay_trazo():
            self._avisar("No hay nada dibujado")
        elif self.cuenta >= MAX_PALABRAS:
            self._avisar("Máximo {} palabras: pulgar arriba para terminar o índice + medio para deshacer".format(
                MAX_PALABRAS))
        else:
            self._encolar_trazo()
            self._avisar("Leyendo la palabra {}…".format(self.cuenta))

    def _terminar(self):
        if self.hay_trazo():
            if self.cuenta >= MAX_PALABRAS:
                self.lienzo[:] = 0
                self._avisar("Máximo {} palabras: el último trazo no se lee".format(MAX_PALABRAS), 4.0)
            else:
                self._encolar_trazo()
        if self.cuenta == 0:
            self._avisar("No hay nada dibujado")
            return
        self.cola.terminar()
        self._cambiar(LEYENDO)

    def _deshacer(self):
        if self.cuenta == 0:
            self._avisar("No hay palabras para deshacer")
            return
        self.cola.deshacer()
        self.cuenta -= 1
        self._avisar("Se quitó la última palabra")

    def _limpiar(self):
        self.lienzo[:] = 0
        self.prev = None
        self._avisar("Palabra borrada")

    def _color(self):
        self.color_idx = (self.color_idx + 1) % len(COLORES)
        self._avisar("Color: {}".format(NOMBRES_COLORES[self.color_idx]))

    # --- Boton Hora: DIBUJANDO -> MENU_HORA -> HORA -> DIBUJANDO (el lienzo no se toca) ---
    def _abrir_menu_hora(self):
        if self.control.ocupada or self.control.deteniendo or self.control.hora_en_curso:
            self._avisar("La mano está ocupada")
            return
        if self.voces_hora is None:
            try:
                import hora
                config = hora.Config()
                self.voces_hora = [(p, config.mostrar(p)) for p in config.orden][:4]
            except Exception as e:
                self._avisar("Botón Hora no disponible ({})".format(type(e).__name__), 4.0)
                return
        self._cambiar(MENU_HORA)
        self.voz_apuntada = None
        self.menu_actividad = self.t

    def _menu_hora(self, g, punto, t):
        if self.sost["volver"].actualizar(g == "shaka", t):
            self._cerrar_menu_hora("Menú de la hora cerrado")
            return
        # Para senalar se usa el gesto tal cual (el indice con que se abrio el menu no hay que soltarlo):
        # los botones estan lejos del boton Hora y hay que sostener 1 s.
        i = next((k for k, r in enumerate(botones_voces(len(self.voces_hora)))
                  if self.gesto == "indice" and dentro(punto, r)), None)
        if i != self.voz_apuntada:
            self.voz_apuntada = i
            self.sost["voz_hora"].reiniciar()
        if i is not None:
            self.menu_actividad = t
            if self.sost["voz_hora"].actualizar(True, t):
                self._decir_hora(i)
        elif t - self.menu_actividad >= SEG_MENU_HORA:
            self._cerrar_menu_hora("Menú de la hora cerrado")

    def _cerrar_menu_hora(self, texto):
        self._cambiar(DIBUJANDO)
        self._avisar(texto)

    def _decir_hora(self, i):
        persona, self.voz_elegida = self.voces_hora[i]
        if not self.control.decir_hora(persona):
            self._cerrar_menu_hora("La mano está ocupada")
            return
        self._cambiar(HORA)

    # --- LEYENDO -> CONFIRMAR / RECHAZADO ---
    def _interpretar(self, palabras):
        self.palabras = palabras
        texto = " ".join(p.leido for p in palabras if p.leido)
        r = interpretar(texto, self.integrantes)
        self.resultado = r
        intento = datetime.now().isoformat(sep=" ", timespec="seconds")
        filas = [{"intento": intento, "fecha": p.fecha, "leido": p.crudo, "tiempo_ocr": "{:.2f}".format(p.seg),
                  "entendido": r.mostrar if r.ok else "", "coincidio": "sí" if r.ok else "no"} for p in palabras]
        aviso = guardar_ocr(filas, self.ruta_ocr)
        if r.ok:
            print("  Leí: '{}' -> Entendí: {} ({})".format(texto, r.mostrar, r.persona))
            self._cambiar(CONFIRMAR)
        else:
            print("  Leí: '{}' -> ✗ {}  {}".format(texto, r.motivo, r.detalle))
            self._cambiar(RECHAZADO)
        if aviso:
            self._avisar(aviso, 4.0)

    def _confirmar(self):
        r = self.resultado
        texto_mano, _ = self.control.texto_estado()
        try:
            self.ruta_txt = guardar_txt(r, self.palabras, texto_mano, self.carpeta_salidas)
            print("  Guardado: {}".format(os.path.relpath(self.ruta_txt, RAIZ)))
        except OSError as e:
            self.ruta_txt = None
            self._avisar("No se pudo guardar el .txt ({})".format(e.strerror or e), 4.0)
        if not self.control.puede_deletrear():
            nombre = os.path.basename(self.ruta_txt) if self.ruta_txt else "(sin .txt)"
            self._avisar("Sin mano: guardado {}. r = reintentar".format(nombre), 5.0)
            self._fin_intento()
            return
        self.seguimiento = self._crear_seguimiento(r)
        if self.seguimiento is not None:
            from pantalla_mano import VentanaMano
            self.ventana_mano = VentanaMano(self.seguimiento)
        self.fin_t = None
        self.control.deletrear_y_hablar(r, self.seguimiento)
        self._cambiar(DELETREANDO)

    def _crear_seguimiento(self, r):
        try:
            from pantalla_mano import RelojMano, Seguimiento
            if self.reloj is None:
                self.reloj = RelojMano()
            return Seguimiento(self.reloj, r)
        except Exception as e:                   # sin panel, pero la mano deletrea igual
            print("  Sin panel sincronizado ({}: {})".format(type(e).__name__, e))
            return None

    # --- pantalla ---
    def dibujar(self, frame):
        img = cv2.addWeighted(frame, 1, self.lienzo, 1, 0)
        rot = Rotulos()
        t = self.t

        # Barra de arriba: estado de la mano, palabras y colores
        capa = img.copy()
        cv2.rectangle(capa, (0, 0), (ANCHO, 110), COLOR_BARRA, -1)
        img = cv2.addWeighted(capa, 0.65, img, 0.35, 0)
        texto_mano, color_mano = self.control.texto_estado()
        cv2.circle(img, (40, 55), 14, color_mano, -1)
        rot.poner(texto_mano, 66, 66, 30, BLANCO)
        leidas, pendientes = self.cola.vista()
        lista = leidas + ["…"] * pendientes
        rot.poner("Palabras ({}/{}): {}".format(self.cuenta, MAX_PALABRAS, "  ·  ".join(lista) if lista else "—"),
                  620, 66, 30, BLANCO)
        for i, col in enumerate(COLORES):
            cx = ANCHO - 220 + i * 65
            elegido = i == self.color_idx
            cv2.circle(img, (cx, 55), 26 if elegido else 20, col, -1)
            cv2.circle(img, (cx, 55), 26 if elegido else 20, BLANCO if elegido else (110, 110, 110),
                       3 if elegido else 1)

        if self.estado == DIBUJANDO:
            cv2.line(img, (0, LIMITE_INFERIOR), (ANCHO, LIMITE_INFERIOR), (0, 200, 255), 2)
            rot.poner("índice = dibujar · mano abierta = levantar · pulgar abajo 1 s = siguiente palabra · "
                      "pulgar arriba = terminar", 20, ALTO - 120, 26, GRIS)
            rot.poner("shaka = borrar · 3 dedos = color · índice + medio 1 s = quitar la última palabra",
                      20, ALTO - 80, 26, GRIS)
            nombre, progreso = max(((n, self.sost[n].progreso(t)) for n in ("pulgar_abajo", "pulgar_arriba",
                                    "shaka", "tres", "dos")), key=lambda x: x[1])
            if progreso > 0:
                cv2.circle(img, (ANCHO // 2, 270), 50, (40, 40, 40), -1)     # debajo del aviso
                anillo(img, (ANCHO // 2, 270), 44, progreso)
                rot.poner(ETIQUETAS[nombre], ANCHO // 2, 355, 30, BLANCO, centro=True)
            x1, y1, x2, y2 = BOTON_HORA
            prog = self.sost["hora"].progreso(t)
            rect_redondeado(img, (x1, y1), (x2, y2), (110, 80, 30) if prog > 0 else (60, 60, 60), 20)
            rot.poner("Hora", x1 + 30, y1 + 60, 44, BLANCO)
            rot.poner("índice 1 s · tecla h", x1 + 30, y1 + 95, 22, GRIS)
            anillo(img, (x2 - 55, (y1 + y2) // 2), 30, prog)
        elif self.estado == MENU_HORA:
            img = panel(img, (200, 280), (ANCHO - 200, 760))
            rot.poner("¿Con qué voz digo la fecha y la hora?", ANCHO // 2, 370, 46, BLANCO, centro=True)
            prog = self.sost["voz_hora"].progreso(t)
            for k, ((_, nombre), (x1, y1, x2, y2)) in enumerate(zip(self.voces_hora,
                                                                    botones_voces(len(self.voces_hora)))):
                apuntado = k == self.voz_apuntada
                rect_redondeado(img, (x1, y1), (x2, y2), (110, 80, 30) if apuntado else (70, 70, 70), 20)
                rot.poner(nombre, (x1 + x2) // 2, (y1 + y2) // 2 + 15, 44, BLANCO, centro=True)
                rot.poner(str(k + 1), x1 + 24, y1 + 40, 26, GRIS)
                if apuntado and prog > 0:
                    cv2.rectangle(img, (x1 + 20, y2 - 24), (x1 + 20 + int((x2 - x1 - 40) * prog), y2 - 14), VERDE, -1)
            rot.poner("Señala una voz 1 s (o teclas 1–4)  ·  shaka o Esc = cerrar  ·  se cierra sola a los {:.0f} s"
                      .format(SEG_MENU_HORA), ANCHO // 2, 700, 28, AMARILLO, centro=True)
        elif self.estado == HORA:
            img = panel(img, (ANCHO // 2 - 600, 320), (ANCHO // 2 + 600, 500))
            rot.poner("Diciendo la fecha y la hora con la voz de {}…".format(self.voz_elegida), ANCHO // 2, 405, 42,
                      BLANCO, centro=True)
            rot.poner("(suena en la mano por WiFi)", ANCHO // 2, 460, 28, GRIS, centro=True)
        elif self.estado == LEYENDO:
            img = panel(img, (ANCHO // 2 - 400, 300), (ANCHO // 2 + 400, 460))
            rot.poner("Leyendo {} palabra{}…".format(self.cuenta, "s" if self.cuenta != 1 else ""),
                      ANCHO // 2, 395, 44, BLANCO, centro=True)
        elif self.estado == CONFIRMAR and self.resultado is not None:
            r = self.resultado
            img = panel(img, (260, 220), (ANCHO - 260, 700))
            rot.poner("Leí:  {}".format(r.leido), ANCHO // 2, 320, 36, GRIS, centro=True)
            rot.poner("Entendí:  {}".format(r.mostrar), ANCHO // 2, 420, 64, BLANCO, centro=True)
            rot.poner("({}, {})".format(self.integrantes.nombre_completo(r.persona), r.tipo), ANCHO // 2, 480, 30,
                      GRIS, centro=True)
            rot.poner("Pulgar arriba 1,5 s = confirmar   ·   shaka = volver a dibujar", ANCHO // 2, 650, 30,
                      AMARILLO, centro=True)
            cv2.circle(img, (ANCHO // 2, 560), 40, (60, 60, 60), -1)
            anillo(img, (ANCHO // 2, 560), 36, max(self.sost["confirmar"].progreso(t),
                                                   self.sost["volver"].progreso(t)))
        elif self.estado == RECHAZADO and self.resultado is not None:
            r = self.resultado
            img = panel(img, (260, 260), (ANCHO - 260, 620), (40, 40, 140))
            rot.poner(r.motivo, ANCHO // 2, 380, 56, BLANCO, centro=True)
            rot.poner("Leí:  {}".format(r.leido or "—"), ANCHO // 2, 460, 34, BLANCO, centro=True)
            rot.poner("Vuelve a dibujar (índice + medio 1 s quita la última palabra)", ANCHO // 2, 560, 30, BLANCO,
                      centro=True)
        elif self.estado in (DELETREANDO, DETENIENDO):
            if self.ventana_mano is not None:
                mano = self.ventana_mano.dibujar()
                h, w = mano.shape[:2]
                x, y = (ANCHO - w) // 2, 150
                img[y:y + h, x:x + w] = mano
                cv2.rectangle(img, (x - 2, y - 2), (x + w + 1, y + h + 1), BLANCO, 2)
            if self.estado == DELETREANDO:
                rot.poner("Esc = detener la mano", ANCHO // 2, ALTO - 60, 30, GRIS, centro=True)
            else:
                rot.poner("Deteniendo: la mano termina el tramo y se abre…  (Esc otra vez = salir)", ANCHO // 2,
                          ALTO - 60, 30, AMARILLO, centro=True)

        if self.aviso and t < self.aviso_hasta:
            tam = 34
            ancho = rot.ancho(self.aviso, tam)
            x1, x2 = ANCHO // 2 - ancho // 2 - 24, ANCHO // 2 + ancho // 2 + 24
            rect_redondeado(img, (x1, 125), (x2, 185), COLOR_FLASH, 16)
            rot.poner(self.aviso, ANCHO // 2, 167, tam, BLANCO, centro=True)

        if self.diagnostico:
            rot.poner("gesto: {}   bloqueado: {}   estado: {}".format(self.gesto or "sin mano",
                                                                     self.bloqueado or "—", self.estado),
                      20, 160 if not (self.aviso and t < self.aviso_hasta) else 230, 28, AMARILLO)
            if self.punto is not None:
                cv2.circle(img, self.punto, 8, AMARILLO, 2)
        rot.poner("r = reconectar mano · d = diagnóstico · h = hora · Esc/q = salir", 20, ALTO - 30, 22, GRIS)
        return rot.pintar(img)


# ---------------- Programa ----------------
def bucle_camara(sesion, camara):
    import mediapipe as mp

    cap = cv2.VideoCapture(camara, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
    if not cap.isOpened():
        print("  ✗ No se abrió la cámara {} (prueba con --camara 0)".format(camara))
        return
    mp_hands = mp.solutions.hands
    manos = mp_hands.Hands(static_image_mode=False, max_num_hands=1, model_complexity=1,
                           min_detection_confidence=0.5, min_tracking_confidence=0.5)
    dibujo, estilos = mp.solutions.drawing_utils, mp.solutions.drawing_styles
    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENTANA, 1280, 720)
    try:
        while not sesion.salir:
            ok, frame = cap.read()
            if not ok:
                print("  ✗ La cámara dejó de responder")
                break
            frame = cv2.resize(cv2.convertScaleAbs(frame), (ANCHO, ALTO))
            resultado = manos.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            gesto = punto = None
            if resultado.multi_hand_landmarks:
                hl = resultado.multi_hand_landmarks[0]
                dibujo.draw_landmarks(frame, hl, mp_hands.HAND_CONNECTIONS,
                                      estilos.get_default_hand_landmarks_style(),
                                      estilos.get_default_hand_connections_style())
                gesto = clasificar(hl.landmark)
                punta = hl.landmark[HL.INDEX_FINGER_TIP]
                punto = (int(punta.x * ANCHO), int(punta.y * ALTO))
            sesion.cuadro(gesto, punto, time.monotonic())
            cv2.imshow(VENTANA, sesion.dibujar(frame))
            tecla = cv2.waitKey(1) & 0xFF
            if tecla != 255:
                sesion.tecla(tecla)
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break                            # cerrada con la X
    finally:
        cap.release()
        manos.close()
        cv2.destroyAllWindows()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Dibujar con el Kinect -> mano LSC -> voz (C4)")
    parser.add_argument("--camara", type=int, default=1, help="índice de la cámara (1 = Kinect)")
    parser.add_argument("--diagnostico", action="store_true", help="mostrar el gesto que detecta MediaPipe")
    parser.add_argument("--voz-pc", action="store_true",
                        help="plan B: nombres, fecha y hora por los parlantes del PC (la mano deletrea igual por BLE)")
    args = parser.parse_args()

    print("=" * 50)
    print("  DIBUJAR -> MANO LSC -> VOZ")
    print("=" * 50)
    integrantes = Integrantes()
    control = ControlMano(integrantes, voz_pc=args.voz_pc)
    if args.voz_pc:
        print("  PLAN B: las voces suenan por los parlantes del PC (la mano deletrea igual por Bluetooth)")
    try:
        print("  Cargando TrOCR (una sola vez)...")             # antes del Bluetooth en segundo plano
        from reconocer import Ocr
        ocr = Ocr()
        print("  TrOCR listo.")
        try:
            nombre, token = leer_config()
            print("  Buscando '{}' por Bluetooth en segundo plano (token cargado: {} caracteres)".format(
                nombre, len(token)))
        except ErrorMano as e:
            print("  ✗ {}".format(e))
        control.conectar_fondo()
        print("  Esc/q = salir")
        sesion = Sesion(ocr, control, integrantes, diagnostico=args.diagnostico)
        bucle_camara(sesion, args.camara)
        return 0
    except KeyboardInterrupt:
        print("\nSaliste (Ctrl+C).")
        return 0
    finally:
        control.cerrar()                         # siempre suelta el Bluetooth (sin reset)
        print("  Bluetooth suelto.")


if __name__ == "__main__":
    sys.exit(main())
