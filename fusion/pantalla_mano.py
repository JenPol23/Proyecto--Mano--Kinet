"""
pantalla_mano.py  -  CORRE EN EL PC (py -3.11)
Pantalla sincronizada con la mano SIN tocar el firmware.

- RelojMano: carga de firmware_mano/main.py SOLO la parte de la mano (todo lo que esta antes de
  "# ---------------- BUCLE PRINCIPAL") con machine y time falsos, y ejecuta sus propias funciones
  (reset_all, las letras, deletrear) en tiempo virtual. Asi los tiempos salen de la misma logica de la placa:
  PAUSA_DEDO solo por cada dedo que de verdad se mueve (mover_a salta los que ya estan en su lugar),
  PAUSA_LETRA mostrando cada letra y reset_all en el orden del firmware. No hay tablas copiadas a mano.
- Seguimiento: recibe los eventos de Mano.deletrear() (al_evento, desde el hilo BLE) y dice en cada instante que
  esta haciendo la mano: 'formando', 'mostrando', 'abriendo', 'movimiento', 'espacio', 'hablando'... El reloj
  arranca al enviar cada tramo y se corrige con cada letra_actual:x (o gesto_x_ok) y con deletreo_completo.
- VentanaMano: ventana OpenCV sencilla: estado arriba, letra actual en grande, la palabra con la letra resaltada y
  las letras con movimiento marcadas. Esc o q la cierran.

Uso: la abre voz.py --texto "Tatiana Maldonado" --deletrear.
"""

import os
import sys
import threading
import time
import types
from dataclasses import dataclass, field

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)

from reconocer import LETRAS_ESTATICAS   # noqa: E402

RUTA_FIRMWARE = os.path.join(RAIZ, "firmware_mano", "main.py")
MARCA_FIN = "# ---------------- BUCLE PRINCIPAL"      # lo de la mano termina aqui (despues: Bluetooth y bucle)
LATENCIA = 0.05         # s estimados del PC a la placa por BLE (se corrige con cada letra)

NOMBRES_ESTADO = {
    "listo": "listo",
    "formando": "formando",
    "mostrando": "mostrando",
    "abriendo": "abriendo mano",
    "abierta": "mano abierta",
    "movimiento": "letra con movimiento (mano abierta)",
    "espacio": "espacio",
    "hablando": "hablando",
    "terminado": "terminado",
    "error": "error",
}


# ---------------- Reloj virtual con la logica del firmware ----------------
class _TiempoVirtual:
    """Hace de modulo 'time' para el firmware: sleep avanza un reloj virtual y anota en que fase iba."""

    def __init__(self):
        self.t = 0.0
        self.fase = ("listo", None, None)
        self.pasos = []                          # (t0, t1, fase)

    def sleep(self, segundos):
        t0 = self.t
        self.t += segundos
        self.pasos.append((t0, self.t, self.fase))

    def sleep_ms(self, ms):
        self.sleep(ms / 1000)

    def ticks_ms(self):
        return int(self.t * 1000)

    def ticks_diff(self, a, b):
        return a - b


class _PWM:
    def __init__(self, pin=None, freq=None):
        pass

    def duty_ns(self, ns):
        pass


@dataclass
class Linea:
    """Lo que hace la mano con una orden, en segundos desde que la placa la recibe."""
    segmentos: list                     # (t0, t1, estado, letra, indice de la letra en el tramo)
    marcas: list                        # instante de cada letra formada (letra_actual:x o gesto_x_ok)
    t_completo: float = None            # instante de deletreo_completo (solo palabras)
    total: float = 0.0
    despues: tuple = ("abierta", None, None)

    def en(self, t):
        """(estado, letra, indice) en el instante virtual t."""
        if t >= self.total:
            return self.despues
        for t0, t1, estado, letra, indice in self.segmentos:
            if t0 <= t < t1:
                return estado, letra, indice
        if self.segmentos:
            primero = self.segmentos[0]
            return primero[2], primero[3], primero[4]
        return self.despues


class RelojMano:
    """Ejecuta en el PC las funciones de la mano de firmware_mano/main.py en tiempo virtual."""

    def __init__(self, ruta_firmware=RUTA_FIRMWARE):
        with open(ruta_firmware, encoding="utf-8") as f:
            codigo = f.read()
        if MARCA_FIN not in codigo:
            raise ValueError("No encuentro '{}' en {}".format(MARCA_FIN, ruta_firmware))
        self.tiempo = _TiempoVirtual()
        self.mensajes = []                       # (t, texto) de lo que imprime el firmware
        self.k = -1                              # indice de la letra que se esta formando en el tramo
        maquina = types.SimpleNamespace(Pin=lambda *a, **k: None, PWM=_PWM, I2S=None)
        ns = {"__name__": "firmware_simulado", "print": self._print}
        guardados = {m: sys.modules.get(m) for m in ("machine", "time")}
        sys.modules["machine"] = maquina
        sys.modules["time"] = self.tiempo        # solo mientras se carga: el firmware hace "import time"
        try:
            exec(compile(codigo[:codigo.index(MARCA_FIN)], ruta_firmware, "exec"), ns)
        finally:
            for m, v in guardados.items():
                if v is None:
                    sys.modules.pop(m, None)
                else:
                    sys.modules[m] = v
        self.ns = ns
        self.pausa_letra = ns["PAUSA_LETRA"]
        self.pausa_dedo = ns["PAUSA_DEDO"]
        # Se envuelven (sin cambiarlas) reset_all y cada letra para saber en que fase va el reloj
        reset_original = ns["reset_all"]

        def reset_all():
            self.tiempo.fase = ("abriendo", None, self.k if self.k >= 0 else None)
            reset_original()

        ns["reset_all"] = reset_all
        for letra, funcion in list(ns["acciones"].items()):
            ns["acciones"][letra] = self._envolver(letra, funcion)

    def _envolver(self, letra, funcion):
        def formar():
            self.k += 1
            self.tiempo.fase = ("formando", letra, self.k)
            funcion()
        return formar

    def _print(self, *partes, **_):
        texto = " ".join(str(p) for p in partes)
        self.mensajes.append((self.tiempo.t, texto))
        if texto.startswith("letra_actual:"):
            self.tiempo.fase = ("mostrando", texto.split(":", 1)[1], self.k)

    def _preparar(self):
        for cfg in self.ns["dedos_config"].values():     # la mano empieza abierta (el PC manda reset antes)
            cfg["pos"] = cfg["abierto"]
        self.tiempo.t = 0.0
        self.tiempo.pasos = []
        self.tiempo.fase = ("abriendo", None, None)
        self.mensajes = []
        self.k = -1

    def _segmentos(self):
        segmentos = []
        for t0, t1, (estado, letra, indice) in self.tiempo.pasos:
            if segmentos and segmentos[-1][2:] == (estado, letra, indice) and abs(segmentos[-1][1] - t0) < 1e-9:
                segmentos[-1] = (segmentos[-1][0], t1, estado, letra, indice)
            else:
                segmentos.append((t0, t1, estado, letra, indice))
        return segmentos

    def simular_palabra(self, letras):
        """Tramo de 2+ letras: lo que hace deletrear(letras) del firmware."""
        self._preparar()
        self.ns["deletrear"](letras)
        marcas = [t for t, m in self.mensajes if m.startswith("letra_actual:")]
        completo = next((t for t, m in self.mensajes if m == "deletreo_completo"), None)
        return Linea(self._segmentos(), marcas, completo, self.tiempo.t, ("abierta", None, None))

    def simular_letra(self, letra):
        """Tramo de 1 letra: lo que hace atender_orden(letra) del firmware (reset_all + la letra, y gesto_x_ok).
        Despues la letra queda puesta hasta que el PC manda reset."""
        self._preparar()
        self.ns["reset_all"]()
        self.ns["acciones"][letra]()
        t = self.tiempo.t
        return Linea(self._segmentos(), [t], None, t, ("mostrando", letra, 0))


# ---------------- Seguimiento de un deletreo real ----------------
class Seguimiento:
    """Junta los eventos de Mano.deletrear() con el RelojMano. Se usa desde dos hilos (BLE y ventana)."""

    def __init__(self, reloj, resultado, ahora=time.monotonic):
        self.reloj = reloj
        self.ahora = ahora
        self.palabras = [p.upper() for p in resultado.palabras_mano]
        self.orden = []                          # (palabra, posicion de inicio, tipo, letras) de cada tramo
        for n, tramos in enumerate(resultado.tramos):
            posicion = 0
            for tipo, letras in tramos:
                self.orden.append((n, posicion, tipo, letras))
                posicion += len(letras)
        self.k = -1                              # tramo actual en self.orden
        self.candado = threading.Lock()
        self.linea = None
        self.base = None                         # instante real que corresponde al 0 virtual de la linea
        self.vistas = 0                          # letras formadas ya vistas en el tramo actual
        self.tramo = (None, None)                # (palabra, posicion de inicio) del tramo actual
        self.fijo = ("listo", None, None, None)  # (estado, letra, palabra, posicion) cuando no hay linea
        self.detalle = ""

    def _siguiente(self, tipo, letras):
        for j in range(self.k + 1, len(self.orden)):
            if self.orden[j][2] == tipo and self.orden[j][3] == letras:
                self.k = j
                return self.orden[j]
        return None

    def evento(self, tipo, dato=""):
        """al_evento de Mano.deletrear()."""
        with self.candado:
            ahora = self.ahora()
            if tipo == "envio":
                tramo = self._siguiente("mano", dato)
                n, inicio = (tramo[0], tramo[1]) if tramo else (None, None)
                self.linea = self.reloj.simular_palabra(dato) if len(dato) > 1 else self.reloj.simular_letra(dato)
                self.base = ahora + LATENCIA
                self.vistas = 0
                self.tramo = (n, inicio)
            elif tipo == "letra" and self.linea is not None:
                if self.vistas < len(self.linea.marcas):        # corrige el reloj con la letra que llego
                    self.base = ahora - self.linea.marcas[self.vistas]
                    self.vistas += 1
            elif tipo == "deletreo_completo" and self.linea is not None and self.linea.t_completo is not None:
                self.base = ahora - self.linea.t_completo
            elif tipo == "reset":
                if self.linea is not None and self.linea.t_completo is None:   # letra suelta: ahora se abre
                    self.linea = None
                    self.fijo = ("abriendo", None, None, None)
                elif self.linea is None:
                    self.fijo = ("abriendo", None, None, None)
            elif tipo == "reset_ok":
                self.linea = None
                self.fijo = ("abierta", None, None, None)
            elif tipo == "movimiento":
                tramo = self._siguiente("movimiento", dato)
                self.linea = None
                self.fijo = ("movimiento", dato, tramo[0] if tramo else None, tramo[1] if tramo else None)
            elif tipo == "espacio":
                self.linea = None
                self.fijo = ("espacio", None, None, None)
            elif tipo == "fin":
                self.linea = None
                self.fijo = ("abierta", None, None, None)

    def hablando(self):
        with self.candado:
            self.linea = None
            self.fijo = ("hablando", None, None, None)

    def terminado(self, ok, mensaje):
        with self.candado:
            self.linea = None
            self.fijo = ("terminado" if ok else "error", None, None, None)
            self.detalle = mensaje

    def estado(self):
        """dict(estado, letra, palabra, posicion, detalle) en este instante."""
        with self.candado:
            if self.linea is not None:
                estado, letra, indice = self.linea.en(self.ahora() - self.base)
                n, inicio = self.tramo
                posicion = inicio + indice if (inicio is not None and indice is not None) else None
                if estado == "abierta":
                    posicion = None
                return dict(estado=estado, letra=letra, palabra=n, posicion=posicion, detalle=self.detalle)
            estado, letra, n, posicion = self.fijo
            return dict(estado=estado, letra=letra, palabra=n, posicion=posicion, detalle=self.detalle)


# ---------------- Ventana ----------------
class VentanaMano:
    """Ventana OpenCV. dibujar() devuelve la imagen (sirve para probar sin abrir la ventana)."""

    ANCHO, ALTO = 960, 540
    FONDO = (250, 250, 250)
    TEXTO = (30, 30, 30)
    GRIS = (150, 150, 150)
    RESALTE = (0, 215, 255)                   # amarillo (BGR)
    MOVIMIENTO = (0, 120, 255)                # naranja (BGR)
    COLORES = {"formando": (200, 120, 0), "mostrando": (0, 150, 0), "abriendo": (120, 120, 120),
               "movimiento": (0, 120, 255), "hablando": (180, 0, 180), "error": (0, 0, 220)}

    def __init__(self, seguimiento, titulo="Mano LSC"):
        self.seguimiento = seguimiento
        self.titulo = titulo

    def dibujar(self):
        import cv2
        import numpy as np

        e = self.seguimiento.estado()
        img = np.full((self.ALTO, self.ANCHO, 3), self.FONDO, np.uint8)
        fuente = cv2.FONT_HERSHEY_DUPLEX
        color = self.COLORES.get(e["estado"], self.TEXTO)

        # Estado arriba
        cv2.putText(img, NOMBRES_ESTADO.get(e["estado"], e["estado"]), (30, 55), fuente, 1.3, color, 2, cv2.LINE_AA)
        if e["detalle"]:
            cv2.putText(img, e["detalle"][:70], (30, 95), fuente, 0.7, self.GRIS, 1, cv2.LINE_AA)

        # Letra actual en grande
        if e["letra"]:
            letra = e["letra"].upper()
            con_movimiento = e["letra"] not in LETRAS_ESTATICAS
            tam = cv2.getTextSize(letra, fuente, 9, 18)[0]
            x = (self.ANCHO - tam[0]) // 2
            cv2.putText(img, letra, (x, 330), fuente, 9, self.MOVIMIENTO if con_movimiento else self.TEXTO, 18,
                        cv2.LINE_AA)
            if con_movimiento:
                nota = "(con movimiento)"
                tam = cv2.getTextSize(nota, fuente, 0.9, 2)[0]
                cv2.putText(img, nota, ((self.ANCHO - tam[0]) // 2, 375), fuente, 0.9, self.MOVIMIENTO, 2,
                            cv2.LINE_AA)

        # La palabra (o palabras) con la letra actual resaltada y las letras con movimiento marcadas
        escala, grosor = 1.4, 2
        paso = cv2.getTextSize("W", fuente, escala, grosor)[0][0] + 6
        total = sum(len(p) for p in self.seguimiento.palabras) + len(self.seguimiento.palabras) - 1
        paso = min(paso, (self.ANCHO - 60) // max(total, 1))
        x = (self.ANCHO - paso * total) // 2
        y = 480
        for n, palabra in enumerate(self.seguimiento.palabras):
            for j, c in enumerate(palabra):
                actual = e["palabra"] == n and e["posicion"] == j
                movimiento = c.lower() not in LETRAS_ESTATICAS
                if actual:
                    cv2.rectangle(img, (x - 4, y - 40), (x + paso - 6, y + 12), self.RESALTE, -1)
                tam = cv2.getTextSize(c, fuente, escala, grosor)[0]
                cx = x + (paso - 6 - tam[0]) // 2
                cv2.putText(img, c, (cx, y), fuente, escala, self.MOVIMIENTO if movimiento else self.TEXTO, grosor,
                            cv2.LINE_AA)
                if movimiento:
                    cv2.line(img, (x, y + 8), (x + paso - 10, y + 8), self.MOVIMIENTO, 3)
                x += paso
            x += paso                              # espacio entre palabras
        cv2.putText(img, "Esc / q: salir", (self.ANCHO - 190, self.ALTO - 12), fuente, 0.55, self.GRIS, 1,
                    cv2.LINE_AA)
        return img

    def mostrar(self, terminado, segundos_al_final=2.0):
        """Muestra la ventana hasta que terminado() sea True (y unos segundos mas). False si el usuario la cerro."""
        import cv2

        cv2.namedWindow(self.titulo, cv2.WINDOW_AUTOSIZE)
        fin = None
        try:
            while True:
                cv2.imshow(self.titulo, self.dibujar())
                tecla = cv2.waitKey(30) & 0xFF
                if tecla in (27, ord("q")):
                    return False
                if cv2.getWindowProperty(self.titulo, cv2.WND_PROP_VISIBLE) < 1:
                    return False
                if terminado():
                    fin = fin or time.monotonic()
                    if time.monotonic() - fin >= segundos_al_final:
                        return True
        finally:
            cv2.destroyWindow(self.titulo)
            cv2.waitKey(1)
