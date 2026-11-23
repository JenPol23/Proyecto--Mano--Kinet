"""
prueba_boton_hora_falsa.py  -  CORRE EN EL PC (py -3.11), SIN KINECT, SIN TrOCR Y SIN PLACA
Prueba el boton Hora de fusion/dibujar_fusion.py con gestos simulados en tiempo virtual y un hora.decir() falso:
abrir el menu (indice 1 s sobre el boton o tecla h), elegir voz (indice 1 s o teclas 1-4), cerrar (shaka, Esc,
5 s), el candado de la mano (nunca a la vez que el deletreo o la conexion), errores, y que el lienzo y las
palabras quedan intactos. Nada de esto toca el secretos.py real, la red ni la placa.

Uso: py -3.11 fusion/pruebas/prueba_boton_hora_falsa.py
"""
import os
import sys
import threading
import time
import types

FUSION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FUSION)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


class _BleakNada:                       # bleak falso: aqui nunca se conecta nada por Bluetooth
    pass


sys.modules["bleak"] = types.SimpleNamespace(BleakScanner=_BleakNada, BleakClient=_BleakNada)

import numpy as np  # noqa: E402

import dibujar_fusion as df  # noqa: E402
from reconocer import Integrantes  # noqa: E402

fallas = []


def chequeo(nombre, ok, detalle=""):
    print("{}   {}{}".format("PASA " if ok else "FALLA", nombre, "  " + detalle if detalle else ""))
    if not ok:
        fallas.append(nombre)


hora_cargado_al_empezar = "hora" in sys.modules
ints = Integrantes()
FPS = 1 / 30
FRAME = np.zeros((df.ALTO, df.ANCHO, 3), np.uint8)


class OcrFalso:
    def leer(self, ruta, max_tokens=None, guardar_vista=None):
        return "lina"


class DecirFalso:
    """hora.decir() falso: anota la voz; si 'esperar' es un Event, no termina hasta que se suelte."""

    def __init__(self):
        self.llamadas = []
        self.esperar = None
        self.error = None

    def __call__(self, persona):
        self.llamadas.append(persona)
        if self.esperar is not None:
            self.esperar.wait(5)
        if self.error is not None:
            raise self.error
        return {"resultado": "ok", "mensaje": "{}: Hoy es jueves doce de noviembre.".format(persona)}


class Escena:
    def __init__(self, decir=None):
        self.decir = decir if decir is not None else DecirFalso()
        self.control = df.ControlMano(ints, crear_mano=lambda: None, crear_voz=lambda m: None,
                                      decir_hora=self.decir)
        self.control.estado, self.control.detalle, self.control.con_voz = "conectada", "version:voz-2", True
        self.s = df.Sesion(OcrFalso(), self.control, ints)
        self.t = 100.0

    def cuadros(self, gesto, punto, segundos):
        for _ in range(max(1, int(round(segundos / FPS)))):
            self.t += FPS
            self.s.cuadro(gesto, punto, self.t)

    def esperar_hora(self, limite=3.0):
        fin = time.monotonic() + limite
        while self.control.hora_en_curso and time.monotonic() < fin:
            time.sleep(0.01)
        self.cuadros(None, None, FPS)           # un cuadro para que la Sesion vea que termino

    def trazo(self):
        for x in range(300, 700, 20):
            self.cuadros("indice", (x, 400), FPS)
        self.cuadros("abierta", None, 0.2)


x1, y1, x2, y2 = df.BOTON_HORA
EN_BOTON = ((x1 + x2) // 2, (y1 + y2) // 2)


def en_voz(i):
    r = df.botones_voces(4)[i]
    return ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)


print("1. Abrir el menú")
e = Escena()
e.trazo()
lienzo = e.s.lienzo.copy()
chequeo("antes de usar el botón no se carga hora.py", not hora_cargado_al_empezar and "hora" not in sys.modules)
e.cuadros("indice", EN_BOTON, 0.5)
e.cuadros("abierta", None, 0.3)
chequeo("índice 0,5 s sobre el botón: no abre nada", e.s.estado == df.DIBUJANDO)
e.cuadros("indice", EN_BOTON, 1.1)
chequeo("índice 1 s sobre el botón: abre el menú", e.s.estado == df.MENU_HORA)
chequeo("el índice sobre el botón no dibuja", np.array_equal(e.s.lienzo, lienzo))

print("\n2. Elegir una voz con el índice")
e.cuadros("indice", en_voz(2), 0.5)
e.cuadros("indice", en_voz(1), 0.5)
chequeo("cambiar de voz antes de 1 s reinicia la cuenta", e.s.estado == df.MENU_HORA and not e.decir.llamadas)
e.cuadros("indice", en_voz(2), 1.1)
chequeo("índice 1 s sobre Lina: suena con la voz de Lina", e.s.estado in (df.HORA, df.DIBUJANDO)
        and e.decir.llamadas == ["lina"], str(e.decir.llamadas))
e.esperar_hora()
chequeo("al terminar vuelve a DIBUJANDO con el mensaje", e.s.estado == df.DIBUJANDO
        and e.s.aviso == "lina: Hoy es jueves doce de noviembre.", e.s.aviso)
chequeo("el lienzo queda intacto", np.array_equal(e.s.lienzo, lienzo))
e.cuadros("indice", (800, 300), 0.3)
chequeo("el índice que quedó levantado no dibuja hasta soltarlo", np.array_equal(e.s.lienzo, lienzo))
e.cuadros("abierta", None, 0.3)
e.cuadros("indice", (800, 300), 0.3)
chequeo("después de soltarlo se dibuja como siempre", not np.array_equal(e.s.lienzo, lienzo))

print("\n3. Cerrar el menú sin elegir")
for nombre, accion in (("shaka", lambda: e.cuadros("shaka", None, 0.8)), ("Esc", lambda: e.s.tecla(27)),
                       ("5 s sin elegir", lambda: e.cuadros("abierta", None, df.SEG_MENU_HORA + 0.2))):
    e = Escena()
    e.s.tecla(ord("h"))
    abierto = e.s.estado == df.MENU_HORA
    accion()
    chequeo("{} cierra el menú (sin salir ni sonar)".format(nombre), abierto and e.s.estado == df.DIBUJANDO
            and not e.s.salir and not e.decir.llamadas)
e = Escena()
e.s.tecla(ord("h"))
e.cuadros("indice", en_voz(0), 0.6)
e.cuadros("abierta", None, df.SEG_MENU_HORA - 0.5)
e.cuadros("indice", en_voz(0), 0.4)
chequeo("señalar una voz reinicia los 5 s", e.s.estado == df.MENU_HORA)

print("\n4. Teclas")
e = Escena()
for k in "1234":
    e.s.tecla(ord(k))
chequeo("1-4 fuera del menú no hacen nada", e.s.estado == df.DIBUJANDO and not e.decir.llamadas)
e.s.tecla(ord("h"))
e.s.tecla(ord("4"))
e.esperar_hora()
chequeo("h + 4 = Paula", e.decir.llamadas == ["paula"] and e.s.estado == df.DIBUJANDO, str(e.decir.llamadas))
e.s._cambiar(df.CONFIRMAR)
e.s.tecla(ord("h"))
chequeo("h en otro estado (CONFIRMAR): no abre el menú, avisa", e.s.estado == df.CONFIRMAR and "dibuja" in e.s.aviso)
e.s._cambiar(df.DIBUJANDO)
e.s.tecla(ord("h"))
e.s.tecla(ord("q"))
chequeo("q sigue saliendo del programa (como hoy)", e.s.salir)

print("\n5. El candado de la mano")
e = Escena()
e.control.ocupada = True                          # deletreo en curso
e.s.tecla(ord("h"))
chequeo("con el deletreo en curso: no abre, avisa 'ocupada'", e.s.estado == df.DIBUJANDO and "ocupada" in e.s.aviso)
chequeo("decir_hora() devuelve False con el deletreo en curso", e.control.decir_hora("lina") is False)
e.control.ocupada = False

e = Escena()
e.control.candado.acquire()                       # p. ej. conectando por Bluetooth
e.s.tecla(ord("h"))
e.s.tecla(ord("3"))
time.sleep(0.3)
chequeo("si el candado está tomado, la hora espera (no suena aún)", e.s.estado == df.HORA and not e.decir.llamadas)
e.control.candado.release()
e.esperar_hora()
chequeo("al soltarse el candado, suena", e.decir.llamadas == ["lina"] and e.s.estado == df.DIBUJANDO)

e = Escena()
e.decir.esperar = threading.Event()
e.s.tecla(ord("h"))
e.s.tecla(ord("1"))
time.sleep(0.2)
chequeo("mientras suena, el candado de la mano está tomado (el deletreo esperaría)",
        e.control.candado.locked() and e.control.hora_en_curso)
e.cuadros("pulgar_arriba", None, 2.0)
e.s.tecla(ord("h"))
chequeo("mientras suena, los gestos y h no cambian nada", e.s.estado == df.HORA)
chequeo("no se puede pedir otra hora a la vez", e.control.decir_hora("harry") is False)
e.decir.esperar.set()
e.esperar_hora()
chequeo("al terminar suelta el candado", not e.control.candado.locked() and e.s.estado == df.DIBUJANDO)

df_espera = df.SEG_ESPERA_HORA
df.SEG_ESPERA_HORA = 0.2
e = Escena()
e.control.candado.acquire()
e.s.tecla(ord("h"))
e.s.tecla(ord("2"))
e.esperar_hora()
e.control.candado.release()
df.SEG_ESPERA_HORA = df_espera
chequeo("candado tomado más de SEG_ESPERA_HORA: avisa y no suena",
        not e.decir.llamadas and e.s.estado == df.DIBUJANDO and "ocupada" in e.s.aviso, e.s.aviso)

print("\n6. Errores (la ventana nunca se cae)")
e = Escena()
e.decir.error = RuntimeError("fallo de prueba")
e.trazo()
lienzo = e.s.lienzo.copy()
e.s.tecla(ord("h"))
e.s.tecla(ord("1"))
e.esperar_hora()
chequeo("error dentro de hora.decir(): vuelve a DIBUJANDO con aviso", e.s.estado == df.DIBUJANDO
        and "Error con la hora (RuntimeError)" in e.s.aviso and not e.control.candado.locked(), e.s.aviso)
chequeo("el lienzo queda intacto tras el error", np.array_equal(e.s.lienzo, lienzo))
e = Escena(decir=lambda p: {"resultado": "sin_wifi", "mensaje": "Sin WiFi en la mano: no responde"})
e.s.tecla(ord("h"))
e.s.tecla(ord("1"))
e.esperar_hora()
chequeo("'Sin WiFi en la mano' se muestra tal cual", e.s.aviso == "Sin WiFi en la mano: no responde", e.s.aviso)

print("\n7. Pantalla y conexión con hora.py")
e = Escena()
e.decir.esperar = threading.Event()
ok = True
for paso in (lambda: None, lambda: e.s.tecla(ord("h")), lambda: e.cuadros("indice", en_voz(1), 0.5),
             lambda: e.s.tecla(ord("2"))):
    paso()
    try:
        img = e.s.dibujar(FRAME.copy())
        ok = ok and img.shape == FRAME.shape
    except Exception as error:                    # noqa: BLE001
        ok = False
        print("   ", e.s.estado, error)
chequeo("se dibujan DIBUJANDO, MENU_HORA y HORA sin errores", ok and e.s.estado == df.HORA)
e.decir.esperar.set()
e.esperar_hora()

import hora  # noqa: E402

llamadas = []
decir_real = hora.decir
hora.decir = lambda config, persona: llamadas.append((type(config).__name__, persona)) or {"resultado": "ok",
                                                                                         "mensaje": "ok"}
try:
    control = df.ControlMano(ints, crear_mano=lambda: None, crear_voz=lambda m: None)
    control.decir_hora("harry")
    fin = time.monotonic() + 3
    while control.hora_en_curso and time.monotonic() < fin:
        time.sleep(0.01)
finally:
    hora.decir = decir_real
chequeo("sin decir_hora: usa hora.decir(hora.Config(), persona)", llamadas == [("Config", "harry")], str(llamadas))

print("\n{} fallas".format(len(fallas)))
sys.exit(1 if fallas else 0)
