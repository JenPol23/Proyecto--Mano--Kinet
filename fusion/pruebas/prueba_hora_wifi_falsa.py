"""
prueba_hora_wifi_falsa.py  -  CORRE EN EL PC (py -3.11), SIN PLACA
Levanta el firmware_mano/wifi_hora.py REAL como placa falsa en 127.0.0.1 (sockets de verdad; solo se imitan el
I2S, la red WiFi y lo propio de MicroPython) y llama a hora.decir() + mano_wifi.py como lo haria el boton Hora.
Asi se prueba que el PC y la placa hablan el mismo protocolo. Nunca lee el secretos.py real ni el TOKEN real.

Uso: py -3.11 fusion/pruebas/prueba_hora_wifi_falsa.py
"""

import csv
import importlib.util
import io
import json
import os
import select as select_real
import socket as socket_real
import sys
import tempfile
import threading
import time as time_real
import types
import wave
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
FUSION = os.path.dirname(AQUI)
RAIZ = os.path.dirname(FUSION)
sys.path.insert(0, FUSION)

import hora  # noqa: E402
import mano_wifi  # noqa: E402

TOKEN = "TokenDePrueba-0123456789abcdef"
fallas = []


def chequeo(nombre, ok, detalle=""):
    print("{}   {}{}".format("PASA " if ok else "FALLA", nombre, "  " + detalle if detalle else ""))
    if not ok:
        fallas.append(nombre)


def puerto_libre():
    with socket_real.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------- Placa falsa: wifi_hora.py real con imitaciones de MicroPython ----------------
class I2S:
    TX, MONO = 1, 2
    creados = []
    colgar = False                      # True = la placa se queda pegada sonando (no responde mas)

    def __init__(self, ident, sck, ws, sd, mode, bits, format, rate, ibuf):
        self.datos = bytearray()
        self.cerrado = False
        I2S.creados.append(self)

    def write(self, buf):
        while I2S.colgar:
            time_real.sleep(0.05)
        self.datos += bytes(buf)

    def deinit(self):
        self.cerrado = True


class WLAN:
    def __init__(self, modo):
        pass

    def active(self, v=None):
        return True

    def connect(self, red, clave):
        pass

    def disconnect(self):
        pass

    def isconnected(self):
        return True

    def ifconfig(self):
        return ("127.0.0.1", "255.0.0.0", "127.0.0.1", "127.0.0.1")


class ClienteReal:
    """Un socket de verdad con la interfaz de MicroPython (readline, readinto, write)."""
    conexiones = 0

    def __init__(self, sock):
        ClienteReal.conexiones += 1
        self.sock = sock
        self.lector = sock.makefile("rb")

    def settimeout(self, s):
        self.sock.settimeout(s)

    def readline(self):
        return self.lector.readline()

    def readinto(self, mv):
        return self.lector.readinto1(mv)

    def write(self, b):
        self.sock.sendall(b)

    def close(self):
        self.lector.close()
        self.sock.close()


class ServidorReal:
    def __init__(self):
        self.sock = socket_real.socket()

    def setsockopt(self, *a):
        self.sock.setsockopt(*a)

    def bind(self, direccion):
        self.sock.bind(("127.0.0.1", direccion[1]))

    def listen(self, n):
        self.sock.listen(n)

    def accept(self):
        c, direccion = self.sock.accept()
        c.setblocking(True)
        return ClienteReal(c), direccion

    def close(self):
        self.sock.close()


class Poll:
    def register(self, s, flags):
        self.s = s

    def ipoll(self, timeout):
        listos, _, _ = select_real.select([self.s.sock], [], [], 0)
        if listos:
            yield (self.s, 1)


tiempo_falso = types.SimpleNamespace(
    ticks_ms=lambda: int(time_real.monotonic() * 1000), ticks_diff=lambda a, b: a - b,
    ticks_add=lambda a, b: a + b, sleep_ms=lambda ms: time_real.sleep(ms / 10000))   # 10x mas rapido


class Placa:
    def __init__(self, token=TOKEN):
        self.puerto = puerto_libre()
        sys.modules["machine"] = types.SimpleNamespace(Pin=lambda n: n, I2S=I2S)
        sys.modules["network"] = types.SimpleNamespace(WLAN=WLAN, STA_IF=0, hostname=lambda n: None)
        sys.modules["esp32"] = types.SimpleNamespace(HEAP_DATA=4, idf_heap_info=lambda t: [(0, 80 * 1024, 0, 0)])
        sys.modules["config_wifi"] = types.SimpleNamespace(RED="red", CLAVE="clave", TOKEN=token, PUERTO=self.puerto)
        spec = importlib.util.spec_from_file_location("wifi_hora_falsa", os.path.join(RAIZ, "firmware_mano",
                                                                                    "wifi_hora.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.time = tiempo_falso
        m.gc = types.SimpleNamespace(collect=lambda: None, mem_free=lambda: 96 * 1024)
        m.socket = types.SimpleNamespace(socket=ServidorReal, SOL_SOCKET=socket_real.SOL_SOCKET,
                                         SO_REUSEADDR=socket_real.SO_REUSEADDR)
        m.select = types.SimpleNamespace(poll=Poll, POLLIN=1)
        self.salida = io.StringIO()
        m.print = lambda *a: self.salida.write(" ".join(str(x) for x in a) + "\n")   # solo los avisos de la placa
        self.wifi = m.Wifi()
        self.wifi.atender()                     # abre el puerto
        self.seguir = True
        self.error = None
        self.hilo = threading.Thread(target=self._bucle, daemon=True)
        self.hilo.start()

    def _bucle(self):                           # = el bucle de main.py: una pasada cada 5 ms
        try:
            while self.seguir:
                self.wifi.atender()
                time_real.sleep(0.005)
        except BaseException as e:              # noqa: B036  (no deberia pasar nunca)
            self.error = e

    def parar(self):
        self.seguir = False
        self.hilo.join(2)
        self.wifi.apagar("fin de la prueba")


# ---------------- Frases de prueba ----------------
def wav(ruta, segundos, valor):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    pcm = int(valor).to_bytes(2, "little", signed=True) * int(segundos * 16000)
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return pcm


def secretos(puerto, ip_fija="127.0.0.1", token=TOKEN):
    return {"TOKEN": token, "PUERTO": puerto, "IP_FIJA": ip_fija, "NOMBRE": "mano"}


try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

tmp = tempfile.TemporaryDirectory()
cfg = json.load(open(hora.RUTA_CONFIG, encoding="utf-8"))
cfg["doby"] = os.path.join(tmp.name, "doby")
cfg["fechas"] = os.path.join(tmp.name, "fechas", "{persona}")
ruta_cfg = os.path.join(tmp.name, "hora.json")
json.dump(cfg, open(ruta_cfg, "w", encoding="utf-8"))
config = hora.Config(ruta_cfg)
ruta_csv = os.path.join(tmp.name, "tiempos_hora.csv")
ahora = datetime(2026, 11, 12, 15, 35)
pcm_hora = wav(os.path.join(cfg["doby"], "voz_cache_f5", "lina", "hora",
                            "hora_1535_{}.wav".format(hora.huella(hora.texto_hora(15, 35)))), 0.25, 1000)
pcm_fecha = wav(os.path.join(config.carpeta_fechas("lina"), hora.nombre_fecha(ahora.date())), 0.2, -2000)
SILENCIO = bytes(9600)
llamadas = 0


def decir(persona="lina", cuando=ahora, **k):
    global llamadas
    llamadas += 1
    return hora.decir(config, persona, cuando, ruta_csv=ruta_csv, **k)


resolver_real = mano_wifi.resolver
placa = Placa()

print("1. Fecha y hora en la mano (wifi_hora.py real en 127.0.0.1)")
mano_wifi.resolver = lambda nombre: None                     # mano.local no resuelve -> IP_FIJA
I2S.creados.clear()
r = decir(secretos=secretos(placa.puerto))
chequeo("resultado ok", r["resultado"] == "ok", r["mensaje"])
chequeo("mano.local no resuelve -> usa IP_FIJA", r.get("como") == "IP_FIJA", str(r.get("como")))
chequeo("la placa recibe exactamente la fecha y luego la hora (+ 0,3 s de silencio cada una)",
        [bytes(i.datos) for i in I2S.creados] == [pcm_fecha + SILENCIO, pcm_hora + SILENCIO])
chequeo("el I2S se suelta despues de cada frase", all(i.cerrado for i in I2S.creados))
chequeo("mensaje con lo que sonó", r["mensaje"] == "Lina: Hoy es jueves doce de noviembre. Son las tres y treinta "
        "y cinco de la tarde.", r["mensaje"])
chequeo("tiempos de cada frase", r.get("seg_fecha") == 0.2 and r.get("seg_hora") == 0.25 and r.get("ms_fecha", 0) > 0
        and r.get("ms_hora", 0) > 0 and r["ms_total"] >= r["ms_fecha"] + r["ms_hora"], str(r))

mano_wifi.resolver = lambda nombre: "127.0.0.1"
r = decir(secretos=secretos(placa.puerto))
chequeo("mano.local resuelve -> la usa primero", r["resultado"] == "ok" and r.get("como") == "mano.local", str(r.get("como")))
r = decir(secretos=secretos(placa.puerto, ip_fija=None), ip="127.0.0.1")
chequeo("--ip: va directo a esa IP", r["resultado"] == "ok" and r.get("como") == "ip")

print("\n2. Falta audio")
I2S.creados.clear()
r = decir(cuando=datetime(2027, 3, 3, 15, 35), secretos=secretos(placa.puerto))
chequeo("sin la fecha: suena solo la hora, con aviso", r["resultado"] == "ok" and "Falta audio de la fecha" in r["mensaje"]
        and [bytes(i.datos) for i in I2S.creados] == [pcm_hora + SILENCIO], r["mensaje"])
antes = ClienteReal.conexiones
r = decir(cuando=ahora.replace(minute=36), secretos=secretos(placa.puerto))
chequeo("sin la hora: falta_audio y ni se conecta a la mano",
        r["resultado"] == "falta_audio" and "15:36" in r["mensaje"] and ClienteReal.conexiones == antes, r["mensaje"])

print("\n3. Sin WiFi o la placa no responde (mensaje claro, nunca un error)")
r = decir(secretos=secretos(placa.puerto, token="OtroToken-0123456789"))
chequeo("TOKEN distinto: lo dice", r["resultado"] == "error" and "rechazó el TOKEN" in r["mensaje"], r["mensaje"])
mano_wifi.resolver = lambda nombre: None
t = time_real.perf_counter()
r = decir(secretos=secretos(puerto_libre()))
seg = time_real.perf_counter() - t
chequeo("nadie escucha: 'Sin WiFi en la mano' en menos de 2 s",
        r["resultado"] == "sin_wifi" and r["mensaje"].startswith("Sin WiFi en la mano") and seg < 2,
        "{} ({:.2f} s)".format(r["mensaje"], seg))
r = decir(secretos=secretos(placa.puerto, ip_fija=None))
chequeo("ni mano.local ni IP_FIJA: lo dice", r["resultado"] == "sin_wifi" and "no hay IP_FIJA" in r["mensaje"],
        r["mensaje"])
I2S.colgar = True
t = time_real.perf_counter()
r = decir(secretos=secretos(placa.puerto))
seg = time_real.perf_counter() - t
I2S.colgar = False
chequeo("la placa se queda pegada sonando: error claro y sin colgar el PC (< 5 s)",
        r["resultado"] == "error" and "no respondió" in r["mensaje"] and seg < 5, "{} ({:.1f} s)".format(r["mensaje"], seg))
time_real.sleep(0.3)
r = decir(secretos=secretos(placa.puerto))
chequeo("despues la placa sigue atendiendo", r["resultado"] == "ok", r["mensaje"])
chequeo("la placa nunca le pasó un error a main.py", placa.error is None and placa.wifi.activo, str(placa.error))

print("\n4. secretos.py (archivos de prueba; el real no se lee)")
for texto, debe in (('raise SystemExit("no se ejecuta")\nTOKEN = "abc"\nPUERTO = 5001\nIP_FIJA = "10.0.0.9"\n', None),
                    ('PUERTO = 5001\n', "falta TOKEN"), ('TOKEN = "abc"\nPUERTO = "x"\n', "PUERTO"),
                    ('TOKEN = (\n', "error de sintaxis")):
    ruta = os.path.join(tmp.name, "secretos.py")
    open(ruta, "w", encoding="utf-8").write(texto)
    try:
        s = mano_wifi.leer_secretos(ruta)
        ok = debe is None and s == {"TOKEN": "abc", "PUERTO": 5001, "IP_FIJA": "10.0.0.9", "NOMBRE": "mano"}
        detalle = "leído sin ejecutarlo"
    except mano_wifi.ErrorWifi as e:
        ok = debe is not None and debe in str(e) and str(e).startswith("Sin WiFi en la mano")
        detalle = str(e)
    chequeo("secretos.py: {}".format(debe or "lee TOKEN, PUERTO, IP_FIJA sin ejecutarlo"), ok, detalle)
try:
    mano_wifi.leer_secretos(os.path.join(tmp.name, "no_existe.py"))
    mensaje = ""
except mano_wifi.ErrorWifi as e:
    mensaje = str(e)
chequeo("sin secretos.py: lo dice", mensaje == "Sin WiFi en la mano: no existe secretos.py", mensaje)

print("\n5. Registro y alcance")
with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
    filas = list(csv.DictReader(f))
chequeo("una fila por cada vez (también cuando falla)", len(filas) == llamadas, "{} filas".format(len(filas)))
chequeo("columnas de tiempos_hora.csv", list(filas[0].keys()) == hora.COLUMNAS)
chequeo("resultados anotados", [f["resultado"] for f in filas] ==
        ["ok", "ok", "ok", "ok", "falta_audio", "error", "sin_wifi", "sin_wifi", "error", "ok"],
        str([f["resultado"] for f in filas]))
chequeo("el TOKEN no aparece en el CSV ni en lo que imprime la placa",
        TOKEN not in open(ruta_csv, encoding="utf-8-sig").read() and TOKEN not in placa.salida.getvalue())
chequeo("hora.py y mano_wifi.py no cargan bleak, torch ni cv2",
        not any(m in sys.modules for m in ("bleak", "torch", "cv2")))

mano_wifi.resolver = resolver_real
placa.parar()
print("\n{} fallas".format(len(fallas)))
sys.exit(1 if fallas else 0)
