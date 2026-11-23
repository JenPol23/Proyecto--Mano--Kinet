"""
Prueba de fusion/dibujar_fusion.py SIN Kinect, sin TrOCR y sin placa: gestos simulados en tiempo virtual, un OCR
falso con respuestas fijas y un bleak FALSO que atiende las ordenes en orden, como el firmware (una a la vez).
Usa la Mano y la Voz reales. Sus archivos (txt, png, CSV, WAV) van a una carpeta temporal del sistema.

Uso (desde la carpeta del proyecto):  py -3.11 fusion/pruebas/prueba_dibujar_falsa.py
"""
import asyncio, os, sys, tempfile, threading, time, types

FUSION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FUSION)
sys.stdout.reconfigure(encoding="utf-8")
TEMP = tempfile.mkdtemp(prefix="prueba_dibujar_")

ACCIONES = set("abcdefiklmnopqrtuvwxy")
ESTADO = {"modo": "normal", "ordenes": [], "retardo": 0.0}


class Cliente:
    """Como el firmware: las ordenes se atienden una detras de otra; una palabra tarda 'retardo' s por letra."""

    def __init__(self, dispositivo, disconnected_callback=None):
        self.notif = None
        self.buf = b""
        self.auth = False
        self.cola = None

    async def connect(self, timeout=None):
        self.cola = asyncio.Queue()
        self.tarea = asyncio.get_running_loop().create_task(self._atender_cola())

    async def disconnect(self):
        self.tarea.cancel()
        await asyncio.gather(self.tarea, return_exceptions=True)

    async def start_notify(self, uuid, cb):
        self.notif = cb

    async def write_gatt_char(self, uuid, datos, response=True):
        assert len(datos) <= 20
        self.buf += datos
        while b"\n" in self.buf:
            linea, self.buf = self.buf.split(b"\n", 1)
            self.cola.put_nowait(linea.decode())

    async def _resp(self, t):
        await asyncio.sleep(0.001)
        d = (t + "\n").encode()
        for k in range(0, len(d), 20):
            self.notif(None, bytearray(d[k:k + 20]))

    async def _atender_cola(self):
        while True:
            await self._atender(await self.cola.get())

    async def _atender(self, cmd):
        if not self.auth:
            self.auth = cmd == "auth " + "x" * 32
            await self._resp("ok:auth" if self.auth else "error:auth")
            return
        ESTADO["ordenes"].append(cmd)
        cmd = cmd.strip().lower()
        if cmd == "?":
            await self._resp("version:voz-2")
        elif cmd.startswith("voz "):
            await self._resp("voz_ok")
        elif cmd in ("reset", "1"):
            await self._resp("reset_ok")
        elif cmd in ACCIONES:
            await self._resp("gesto_" + cmd + "_ok")
        elif len(cmd) > 1:
            for l in cmd:
                await asyncio.sleep(ESTADO["retardo"])
                await self._resp("gesto_" + l + "_ok")
                await self._resp("letra_actual:" + l)
            await self._resp("deletreo_completo")
        else:
            await self._resp("comando_no_reconocido")


class Escaner:
    @staticmethod
    async def find_device_by_name(nombre, timeout=None):
        return None if ESTADO["modo"] == "sin_placa" else object()


sys.modules["bleak"] = types.SimpleNamespace(BleakScanner=Escaner, BleakClient=Cliente)

import consola_mano as cm  # noqa: E402
import dibujar_fusion as df  # noqa: E402
from reconocer import Integrantes, interpretar  # noqa: E402
from voz import Voz  # noqa: E402

cm.PAUSA_LETRA_SUELTA = cm.PAUSA_MOVIMIENTO = cm.PAUSA_ESPACIO = 0.0
cfg = os.path.join(TEMP, "config_ble_falso.py")             # token falso: nunca se usa config_ble.py real
with open(cfg, "w", encoding="utf-8") as f:
    f.write('NOMBRE = "Mano-LSC"\nTOKEN = "' + "x" * 32 + '"\n')
ints = Integrantes()
FPS = 1 / 30
FRAME = __import__("numpy").zeros((df.ALTO, df.ANCHO, 3), "uint8")


class OcrFalso:
    """Devuelve las respuestas en orden. bloquear = {n: Event}: la lectura n espera a que se suelte el Event."""

    def __init__(self, respuestas, bloquear=None):
        self.respuestas = list(respuestas)
        self.bloquear = bloquear or {}
        self.llamadas = 0

    def leer(self, ruta, max_tokens=None, guardar_vista=None):
        assert os.path.exists(ruta), "no se guardó el PNG"
        assert max_tokens == df.TOKENS_PALABRA, "max_tokens = {}".format(max_tokens)
        assert guardar_vista == ruta[:-4] + "_trocr.png", "guardar_vista = {}".format(guardar_vista)
        self.vistas = getattr(self, "vistas", []) + [guardar_vista]
        n = self.llamadas
        self.llamadas += 1
        if n in self.bloquear:
            self.bloquear[n].wait(5)
        return self.respuestas[n]


class Caso:
    def __init__(self, nombre, respuestas, modo="normal", retardo=0.0, bloquear=None):
        ESTADO.update(modo=modo, ordenes=[], retardo=retardo)
        self.nombre = nombre
        self.dir = os.path.join(TEMP, nombre.replace(" ", "_"))
        os.makedirs(self.dir)
        self.ocr = OcrFalso(respuestas, bloquear)
        self.ruta_ocr = os.path.join(self.dir, "ocr.csv")
        self.control = df.ControlMano(
            ints, crear_mano=lambda: cm.Mano(cfg, ruta_tiempos=os.path.join(self.dir, "tiempos_mano.csv")),
            crear_voz=lambda m: Voz(m, ints, ruta_tiempos=os.path.join(self.dir, "tiempos_voz.csv"),
                                    carpeta_placa=os.path.join(self.dir, "audios_placa")))
        self.s = df.Sesion(self.ocr, self.control, ints, carpeta_salidas=os.path.join(self.dir, "salidas"),
                           ruta_ocr=self.ruta_ocr, carpeta_imagenes=os.path.join(self.dir, "ocr_imagenes"))
        self.t = 0.0
        self.fallas = []
        self.control.conectar_fondo()

    # --- gestos ---
    def gesto(self, g, segundos, punto=None):
        for _ in range(max(1, round(segundos / FPS))):
            self.t += FPS
            self.s.cuadro(g, punto, self.t)

    def trazar(self):
        for k in range(20):
            self.t += FPS
            self.s.cuadro("indice", (300 + 20 * k, 400), self.t)

    def soltar(self):
        self.gesto("nada", 0.3)

    def esperar(self, cond, g=None, limite=8.0):
        """Avanza el tiempo (real y virtual) hasta cond() o 'limite' s reales."""
        fin = time.monotonic() + limite
        while not cond():
            if time.monotonic() > fin:
                return False
            time.sleep(0.01)
            self.t += 0.01
            self.s.cuadro(g, None, self.t)
        return True

    def pantalla(self):
        img = self.s.dibujar(FRAME.copy())
        self.revisar(img.shape == FRAME.shape, "dibujar() en {}".format(self.s.estado))

    def revisar(self, ok, texto):
        if not ok:
            self.fallas.append(texto)

    def ordenes_mano(self):
        return [o for o in ESTADO["ordenes"] if o != "?"]

    def filas_ocr(self):
        if not os.path.exists(self.ruta_ocr):
            return []
        import csv
        with open(self.ruta_ocr, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def txts(self):
        carpeta = os.path.join(self.dir, "salidas")
        return [n for n in os.listdir(carpeta) if n.endswith(".txt")] if os.path.isdir(carpeta) else []

    def palabra(self, g_fin="pulgar_abajo"):
        """Traza y la manda con pulgar abajo 1 s (o termina con pulgar arriba)."""
        self.trazar()
        self.gesto(g_fin, 1.1 if g_fin == "pulgar_abajo" else 0.7)
        self.soltar()

    def confirmar(self):
        self.soltar()
        self.gesto("pulgar_arriba", 1.6)

    def cerrar(self):
        self.control.cerrar()
        bien = not self.fallas
        print("{}  {}".format("PASA " if bien else "FALLA", self.nombre))
        for f in self.fallas:
            print("       ✗ " + f)
        return bien


resultados = []

# 0. una_palabra(): lo que inventa TrOCR en el blanco que sobra
fallas_una = []
for crudo, esperado, ok_esp in (("Jean Jean", "Jean", True), ("Jean F.", "Jean", True),
                                ("Mal donado", "Maldonado", True), ("2021 22 May", None, False),
                                ("Lina", "Lina", True), ("", "", False)):
    elegida = df.una_palabra(crudo, ints.vocabulario)
    r = interpretar(elegida, ints)
    if (esperado is not None and elegida != esperado) or r.ok != ok_esp:
        fallas_una.append("'{}' -> '{}' (ok={}); esperado '{}' (ok={})".format(crudo, elegida, r.ok, esperado,
                                                                              ok_esp))
print("{}  una_palabra(): Jean Jean / Jean F. / Mal donado / 2021 22 May".format("FALLA" if fallas_una
                                                                                else "PASA "))
for f in fallas_una:
    print("       ✗ " + f)
resultados.append(not fallas_una)


def mano_sintetica(extendidos, pulgar):
    """21 puntos de una mano derecha vertical. extendidos: {'indice','medio','anular','menique'}; pulgar: 'arriba'
    | 'doblado'."""
    p = [types.SimpleNamespace(x=0.5, y=0.9) for _ in range(21)]
    pulgares = {"arriba": [(0.40, 0.75), (0.38, 0.65), (0.37, 0.55)], "doblado": [(0.42, 0.72), (0.45, 0.70),
                                                                                  (0.48, 0.71)]}
    for i, (x, y) in zip((2, 3, 4), pulgares[pulgar]):
        p[i] = types.SimpleNamespace(x=x, y=y)
    for nombre, mcp, x in (("indice", 5, 0.44), ("medio", 9, 0.50), ("anular", 13, 0.56), ("menique", 17, 0.62)):
        ys = (0.60, 0.50, 0.40, 0.30) if nombre in extendidos else (0.60, 0.55, 0.60, 0.65)
        for k, y in enumerate(ys):
            p[mcp + k] = types.SimpleNamespace(x=x, y=y)
    return p


fallas_gestos = []
for extendidos, pulgar, esperado in ((("indice", "medio"), "doblado", "dos"), (("indice", "medio"), "arriba", "dos"),
                                     (("indice", "medio", "anular"), "doblado", "tres"),
                                     (("indice",), "doblado", "indice"),
                                     (("indice", "medio", "anular", "menique"), "doblado", "abierta")):
    obtenido = df.clasificar(mano_sintetica(set(extendidos), pulgar))
    if obtenido != esperado:
        fallas_gestos.append("{} + pulgar {}: '{}' (esperado '{}')".format("+".join(extendidos), pulgar, obtenido,
                                                                          esperado))
print("{}  clasificar(): dos / tres / indice / abierta".format("FALLA" if fallas_gestos else "PASA "))
for f in fallas_gestos:
    print("       ✗ " + f)
resultados.append(not fallas_gestos)


# 1. Normal + soltar el gesto: «Lina» + «Maldonado»
c = Caso("normal Lina Maldonado", ["Lina", "Maldonado"])
c.revisar(c.esperar(lambda: c.control.estado == "conectada"), "no conectó")
c.palabra()
c.trazar()
c.pantalla()
c.gesto("pulgar_arriba", 0.7)                           # termina: lee el trazo que queda
c.revisar(c.esperar(lambda: c.s.estado == df.CONFIRMAR, g="pulgar_arriba"), "no llegó a CONFIRMAR")
c.pantalla()
c.gesto("pulgar_arriba", 2.5)                           # el mismo pulgar que terminó: NO confirma
c.revisar(c.s.estado == df.CONFIRMAR, "el pulgar que terminó confirmó solo")
c.confirmar()
c.revisar(c.s.estado == df.DELETREANDO, "no pasó a DELETREANDO (está en {})".format(c.s.estado))
c.pantalla()
c.revisar(c.esperar(lambda: c.s.estado == df.DIBUJANDO), "no volvió a DIBUJANDO")
archivos = [b.lower() for b, _ in Voz(None, ints).elegir(interpretar("Lina Maldonado", ints))]   # frase o sueltas
esperado = ["reset", "lina", "reset", "maldonado", "reset", "voz " + " ".join(archivos)]
c.revisar(c.ordenes_mano() == esperado, "órdenes {} != {}".format(c.ordenes_mano(), esperado))
c.revisar(c.control.final == (True, "Sonó: Lina Maldonado"), "final {}".format(c.control.final))
c.revisar(len(c.txts()) == 1, "txt: {}".format(c.txts()))
if c.txts():
    with open(os.path.join(c.dir, "salidas", c.txts()[0]), encoding="utf-8") as f:
        contenido = f.read()
    c.revisar("entendido: Lina Maldonado" in contenido and "leído: Lina Maldonado" in contenido, "contenido del txt")
filas = c.filas_ocr()
c.revisar([(x["leido"], x["entendido"], x["coincidio"]) for x in filas]
          == [("Lina", "Lina Maldonado", "sí"), ("Maldonado", "Lina Maldonado", "sí")], "ocr.csv {}".format(filas))
c.revisar(len({x["intento"] for x in filas}) == 1, "intento distinto en las filas")
c.revisar(os.path.exists(os.path.join(c.dir, "tiempos_mano.csv")), "falta tiempos_mano.csv")
c.revisar(os.path.exists(os.path.join(c.dir, "tiempos_voz.csv")), "falta tiempos_voz.csv")
c.revisar(c.s.cuenta == 0 and c.s.cola.vista() == ([], 0), "no se vació la lista al terminar")
resultados.append(c.cerrar())

# 1b. OCR con basura: «Lina» + «Mal donado», «Jean F.» + «Paul» y «2021 22 May»
for respuestas, mostrar in ((["Lina", "Mal donado"], "Lina Maldonado"), (["Jean F.", "Paul"], "Jean Paul")):
    c = Caso("ocr crudo " + mostrar, respuestas)
    c.palabra()
    c.palabra("pulgar_arriba")
    c.revisar(c.esperar(lambda: c.s.estado == df.CONFIRMAR, g="pulgar_arriba"),
              "no llegó a CONFIRMAR (está en {})".format(c.s.estado))
    c.revisar(c.s.resultado is not None and c.s.resultado.mostrar == mostrar,
              "entendido {}".format(c.s.resultado and c.s.resultado.mostrar))
    filas = c.filas_ocr()
    c.revisar([x["leido"] for x in filas] == respuestas, "ocr.csv no tiene el texto crudo: {}".format(filas))
    pngs = sorted(os.listdir(os.path.join(c.dir, "ocr_imagenes")))
    c.revisar(len(pngs) == 2 and all(os.path.join(c.dir, "ocr_imagenes", p) in [v[:-10] + ".png" for v in c.ocr.vistas]
                                     for p in pngs), "PNG en ocr_imagenes: {}".format(pngs))
    resultados.append(c.cerrar())

c = Caso("ocr crudo 2021 22 May", ["2021 22 May"])
c.palabra("pulgar_arriba")
c.revisar(c.esperar(lambda: c.s.estado == df.RECHAZADO), "no llegó a RECHAZADO (está en {})".format(c.s.estado))
c.revisar([x["leido"] for x in c.filas_ocr()] == ["2021 22 May"], "ocr.csv {}".format(c.filas_ocr()))
resultados.append(c.cerrar())

# 2. Sin coincidencia: «Pedro»
c = Caso("sin coincidencia", ["Pedro"])
c.esperar(lambda: c.control.estado == "conectada")
c.palabra("pulgar_arriba")
c.revisar(c.esperar(lambda: c.s.estado == df.RECHAZADO), "no llegó a RECHAZADO (está en {})".format(c.s.estado))
c.pantalla()
c.gesto("pulgar_arriba", 2.0)                           # en RECHAZADO no se confirma nada
c.revisar(c.esperar(lambda: c.s.estado == df.DIBUJANDO, limite=5), "no volvió a DIBUJANDO")
c.revisar(c.ordenes_mano() == [], "se mandó algo a la mano: {}".format(c.ordenes_mano()))
c.revisar(c.txts() == [], "se guardó un txt")
filas = c.filas_ocr()
c.revisar([(x["leido"], x["entendido"], x["coincidio"]) for x in filas] == [("Pedro", "", "no")],
          "ocr.csv {}".format(filas))
c.revisar(c.s.cuenta == 1, "la palabra rechazada no se conserva para deshacer")
resultados.append(c.cerrar())

# 3. Cuatro palabras + trazo en el lienzo: no se lee una quinta
c = Caso("4 palabras + trazo", ["Lina", "Tatiana", "Maldonado", "Jean", "NO"])
for _ in range(4):
    c.palabra()
c.revisar(c.esperar(lambda: c.s.cola.vista()[1] == 0), "no terminó de leer")
c.trazar()
c.gesto("pulgar_abajo", 1.1)
c.revisar("Máximo" in c.s.aviso, "sin aviso con pulgar abajo: '{}'".format(c.s.aviso))
c.revisar(c.s.hay_trazo(), "el trazo se borró con pulgar abajo")
c.soltar()
c.gesto("pulgar_arriba", 0.7)
c.revisar("Máximo" in c.s.aviso, "sin aviso al terminar: '{}'".format(c.s.aviso))
c.revisar(c.esperar(lambda: c.s.estado in (df.RECHAZADO, df.CONFIRMAR), g="pulgar_arriba"), "no interpretó")
c.revisar(c.ocr.llamadas == 4, "OCR llamado {} veces".format(c.ocr.llamadas))
filas = c.filas_ocr()
c.revisar([x["leido"] for x in filas] == ["Lina", "Tatiana", "Maldonado", "Jean"]
          and len({x["intento"] for x in filas}) == 1, "ocr.csv {}".format(filas))
c.revisar(not c.s.hay_trazo(), "el trazo de más quedó en el lienzo")
resultados.append(c.cerrar())

# 4. Orden de la cola: deshacer y terminar esperan a la lectura en curso
suelta = threading.Event()
c = Caso("orden de la cola", ["Lina", "Pedro", "Maldonado"], bloquear={1: suelta})
c.esperar(lambda: c.control.estado == "conectada")
c.palabra()                                             # Lina
c.palabra()                                             # Pedro (se queda leyendo)
c.revisar(c.esperar(lambda: c.ocr.llamadas == 2), "no empezó la segunda lectura")
c.trazar()
c.soltar()
c.gesto("dos", 2.5)                                     # Deshacer (quita Pedro cuando termine de leerlo);
c.revisar(c.s.cuenta == 1, "'dos' sostenido deshizo {} veces".format(2 - c.s.cuenta))   # sostenido: solo una vez
c.soltar()
c.palabra("pulgar_arriba")                              # Maldonado + terminar
c.revisar(c.s.estado == df.LEYENDO, "no está en LEYENDO")
c.revisar(c.s.cola.vista()[0] == ["Lina"], "se aplicó algo antes de terminar la lectura")
suelta.set()
c.revisar(c.esperar(lambda: c.s.estado == df.CONFIRMAR), "no llegó a CONFIRMAR (está en {})".format(c.s.estado))
c.revisar([p.leido for p in c.s.palabras] == ["Lina", "Maldonado"],
          "palabras {}".format([p.leido for p in c.s.palabras]))
resultados.append(c.cerrar())

# 5. Sin mano: el txt se guarda igual; r reintenta
c = Caso("sin mano", ["Lina"], modo="sin_placa")
c.revisar(c.esperar(lambda: c.control.estado == "sin mano", limite=15), "no terminó el intento de conexión")
c.palabra("pulgar_arriba")
c.revisar(c.esperar(lambda: c.s.estado == df.CONFIRMAR, g="pulgar_arriba"), "no llegó a CONFIRMAR")
c.confirmar()
c.revisar(c.s.estado == df.DIBUJANDO and "Sin mano" in c.s.aviso, "estado {} aviso '{}'".format(c.s.estado,
                                                                                              c.s.aviso))
c.revisar(len(c.txts()) == 1, "txt: {}".format(c.txts()))
c.revisar(c.ordenes_mano() == [], "se mandó algo: {}".format(c.ordenes_mano()))
ESTADO["modo"] = "normal"
c.s.tecla(ord("r"))
c.revisar(c.esperar(lambda: c.control.estado == "conectada"), "r no reconectó")
c.pantalla()
resultados.append(c.cerrar())

# 6. Esc durante el deletreo: detener a mitad de «Raigozo» (rai | g | o | z | o)
c = Caso("Esc a mitad de Raigozo", ["Raigozo"], retardo=0.15)
c.esperar(lambda: c.control.estado == "conectada")
c.palabra("pulgar_arriba")
c.revisar(c.esperar(lambda: c.s.estado == df.CONFIRMAR, g="pulgar_arriba"), "no llegó a CONFIRMAR")
c.confirmar()
c.revisar(c.esperar(lambda: "rai" in ESTADO["ordenes"]), "no se mandó 'rai'")
time.sleep(0.1)                                         # a mitad del tramo
c.s.tecla(27)
c.revisar(c.s.estado == df.DETENIENDO, "Esc no pasó a DETENIENDO")
c.pantalla()
c.revisar(c.esperar(lambda: c.s.estado == df.DIBUJANDO), "no volvió a DIBUJANDO")
c.revisar(c.ordenes_mano() == ["reset", "rai", "reset"], "órdenes {}".format(c.ordenes_mano()))
c.revisar(c.control.final == (False, cm.MSG_DETENIDO), "final {}".format(c.control.final))
c.revisar(not c.control.mano.cerrada and not c.s.salir, "se cerró en vez de volver a dibujar")
c.revisar("Detenido: mano abierta" in c.s.aviso, "aviso '{}'".format(c.s.aviso))
time.sleep(0.5)
c.revisar(c.ordenes_mano() == ["reset", "rai", "reset"], "llegó algo después: {}".format(c.ordenes_mano()))
c.s.tecla(27)                                           # Esc en DIBUJANDO: salir
c.revisar(c.s.salir, "Esc en DIBUJANDO no sale")
resultados.append(c.cerrar())

# 7. Dos Esc: el segundo sale enseguida con cerrar()
c = Caso("dos Esc", ["Raigozo"], retardo=0.3)
c.esperar(lambda: c.control.estado == "conectada")
c.palabra("pulgar_arriba")
c.esperar(lambda: c.s.estado == df.CONFIRMAR, g="pulgar_arriba")
c.confirmar()
c.esperar(lambda: "rai" in ESTADO["ordenes"])
c.s.tecla(27)
c.s.tecla(27)
c.revisar(c.s.salir, "el segundo Esc no sale")
inicio = time.monotonic()
c.control.cerrar()
c.revisar(time.monotonic() - inicio < 3.5 and c.control.mano.cerrada, "cerrar() tardó o no soltó")
c.revisar(c.esperar(lambda: not c.control.ocupada and not c.control.deteniendo, limite=4),
          "quedaron hilos de la mano vivos")
resultados.append(c.cerrar())

fallas = resultados.count(False)
print("\n{} fallas".format(fallas))
sys.exit(1 if fallas else 0)
