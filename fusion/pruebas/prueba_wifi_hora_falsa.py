"""
prueba_wifi_hora_falsa.py  -  CORRE EN EL PC (py -3.11), SIN PLACA
Carga firmware_mano/wifi_hora.py (el de la placa) en el PC con imitaciones de machine, network, socket,
select, time, gc, esp32 y config_wifi, y comprueba que:
  - sin config_wifi.py, sin TOKEN, sin red, sin memoria o con cualquier error, atender() NUNCA lanza un error
    hacia main.py (la mano sigue igual); solo Ctrl+C pasa, como hoy;
  - el protocolo: auth, ping, mem, wav (suena lo recibido + silencio), fin, tamano, corte, i2s;
  - nunca usa PWM (no mueve la mano) y nunca imprime la red, la clave ni el TOKEN.

Uso: py -3.11 fusion/pruebas/prueba_wifi_hora_falsa.py
"""

import contextlib
import importlib.util
import io
import os
import random
import re
import sys
import types

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
RUTA = os.path.join(RAIZ, "firmware_mano", "wifi_hora.py")

RED, CLAVE, TOKEN = "RedDePrueba-XYZ", "ClaveDePrueba-123", "TokenDePrueba-0123456789abcdef"
fallas = []


def chequeo(nombre, ok, detalle=""):
    print("{}   {}{}".format("PASA " if ok else "FALLA", nombre, "  " + detalle if detalle else ""))
    if not ok:
        fallas.append(nombre)


# ---------------- Imitaciones ----------------
class E:
    """Estado del mundo falso (se reinicia en cada escenario)."""

    def reiniciar(self):
        self.ms = 0
        self.conectado = False
        self.connects = 0
        self.wlan_activo = None
        self.servidores = []
        self.pendientes = []
        self.i2s_creados = []
        self.i2s_falla_crear = False
        self.i2s_falla_escribir = None      # excepcion a lanzar al escribir
        self.sin_memoria = False
        self.bind_falla = False


e = E()


class Tiempo:
    @staticmethod
    def ticks_ms():
        return e.ms

    @staticmethod
    def ticks_diff(a, b):
        return a - b

    @staticmethod
    def ticks_add(a, b):
        return a + b

    @staticmethod
    def sleep_ms(n):
        e.ms += n


class GC:
    @staticmethod
    def collect():
        pass

    @staticmethod
    def mem_free():
        return 96 * 1024


class Pin:
    def __init__(self, n):
        self.n = n


class I2S:
    TX, MONO = 1, 2

    def __init__(self, ident, sck, ws, sd, mode, bits, format, rate, ibuf):
        if e.i2s_falla_crear:
            raise OSError("sin DMA")
        self.pines = (sck.n, ws.n, sd.n)
        self.config = (ident, bits, rate, ibuf)
        self.datos = bytearray()
        self.cerrado = False
        e.i2s_creados.append(self)

    def write(self, buf):
        if e.i2s_falla_escribir:
            raise e.i2s_falla_escribir
        self.datos += bytes(buf)
        e.ms += len(buf) // 32                  # suena en tiempo real
        return len(buf)

    def deinit(self):
        self.cerrado = True


class WLAN:
    def __init__(self, modo):
        pass

    def active(self, v=None):
        if v is not None:
            e.wlan_activo = v
        return e.wlan_activo

    def connect(self, red, clave):
        e.connects += 1

    def disconnect(self):
        pass

    def isconnected(self):
        return e.conectado

    def ifconfig(self):
        return ("192.168.43.228", "255.255.255.0", "192.168.43.1", "192.168.43.1")


class Cliente:
    """Lo que manda el PC (bytes) y como termina: 'timeout' (OSError) o 'cerrado' (b'')."""

    def __init__(self, datos, fin="timeout"):
        self.entrada = bytearray(datos)
        self.fin = fin
        self.salida = b""
        self.cerrado = False
        self.timeouts = []

    def _agotado(self):
        if self.fin == "timeout":
            raise OSError(116, "ETIMEDOUT")
        return b""

    def settimeout(self, s):
        self.timeouts.append(s)

    def readline(self):
        if e.sin_memoria:
            raise MemoryError()
        if not self.entrada:
            return self._agotado()
        i = self.entrada.find(b"\n")
        i = len(self.entrada) if i < 0 else i + 1
        linea, self.entrada = bytes(self.entrada[:i]), self.entrada[i:]
        return linea

    def readinto(self, mv):
        if not self.entrada:
            return self._agotado() or 0
        k = min(len(mv), len(self.entrada), 1460)     # trozos como los de TCP
        mv[:k] = self.entrada[:k]
        del self.entrada[:k]
        return k

    def write(self, b):
        self.salida += b

    def close(self):
        self.cerrado = True

    def respuestas(self):
        return self.salida.decode().split()


class Servidor:
    def __init__(self):
        self.cerrado = False
        self.puerto = None
        e.servidores.append(self)

    def setsockopt(self, *a):
        pass

    def bind(self, direccion):
        if e.bind_falla:
            raise OSError(112, "EADDRINUSE")
        self.puerto = direccion[1]

    def listen(self, n):
        pass

    def accept(self):
        return e.pendientes.pop(0), ("192.168.43.10", 50000)

    def close(self):
        self.cerrado = True


class Poll:
    def register(self, s, flags):
        self.s = s

    def ipoll(self, timeout):
        if e.pendientes and not self.s.cerrado:
            yield (self.s, 1)


socket_falso = types.SimpleNamespace(socket=lambda: Servidor(), SOL_SOCKET=1, SO_REUSEADDR=2)
select_falso = types.SimpleNamespace(poll=Poll, POLLIN=1)
network_falso = types.SimpleNamespace(WLAN=WLAN, STA_IF=0, hostname=lambda n: None)
esp32_falso = types.SimpleNamespace(HEAP_DATA=4, idf_heap_info=lambda t: [(300000, 60 * 1024, 30000, 50000),
                                                                          (100000, 20 * 1024, 10000, 9000)])
sys.modules["machine"] = types.SimpleNamespace(Pin=Pin, I2S=I2S)       # sin PWM: si lo usara, fallaria


def poner_config(**valores):
    if valores is None or valores.get("_ninguno"):
        sys.modules.pop("config_wifi", None)
        return
    cfg = dict(RED=RED, CLAVE=CLAVE, TOKEN=TOKEN, PUERTO=5001, NOMBRE="mano")
    cfg.update(valores)
    sys.modules["config_wifi"] = types.SimpleNamespace(**{k: v for k, v in cfg.items() if v is not None})


def cargar():
    sys.modules["network"] = network_falso
    sys.modules["esp32"] = esp32_falso
    spec = importlib.util.spec_from_file_location("wifi_hora", RUTA)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.time, m.gc, m.socket, m.select = Tiempo, GC, socket_falso, select_falso
    return m


salida_total = io.StringIO()


def nuevo(conectar=True, **config):
    """Escenario nuevo: Wifi() creado y, si conectar, con la red y el servidor listos."""
    e.reiniciar()
    poner_config(**config)
    with contextlib.redirect_stdout(salida_total):
        w = wh.Wifi()
        if conectar and w.activo:
            e.conectado = True
            w.atender()
    return w


def pasada(w, *clientes):
    """El PC se conecta con cada cliente y main.py da una vuelta por cada uno. Devuelve el error, si hubo."""
    e.pendientes.extend(clientes)
    try:
        with contextlib.redirect_stdout(salida_total):
            for _ in clientes:
                w.atender()
        return None
    except BaseException as error:              # noqa: B036  (justo lo que se quiere ver: que no pase nada)
        return error


def pcm(n_bytes):
    return bytes(random.randrange(256) for _ in range(n_bytes))


try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass
random.seed(7)
wh = cargar()

print("1. Arranque sin poder usar el WiFi (la mano sigue igual)")
w = nuevo(_ninguno=True)
chequeo("sin config_wifi.py: no lanza, WiFi desactivado", not w.activo)
chequeo("sin config_wifi.py: atender() no hace nada", pasada(w) is None and not e.servidores)
w = nuevo(TOKEN=None)
chequeo("sin TOKEN: desactivado y el WiFi ni se enciende", not w.activo and e.wlan_activo is None)
w = nuevo(RED="")
chequeo("sin RED: desactivado", not w.activo)

print("\n2. Red")
w = nuevo(conectar=False)
chequeo("con config: activo y conectando sin esperar", w.activo and e.connects == 1 and e.ms == 0)
pasada(w)
w.atender()
chequeo("sin red: no abre el puerto", not e.servidores)
e.ms += 31000
w.atender()
chequeo("sin red 30 s: reintenta conectar", e.connects == 2)
e.conectado = True
e.ms += 1001
w.atender()
chequeo("con red: abre el puerto 5001", len(e.servidores) == 1 and e.servidores[0].puerto == 5001)
e.conectado = False
e.ms += 1001
w.atender()
chequeo("se pierde la red: cierra el puerto", e.servidores[0].cerrado and w.servidor is None and w.activo)
e.conectado = True
e.ms += 1001
w.atender()
chequeo("vuelve la red: abre el puerto otra vez", len(e.servidores) == 2 and w.servidor is not None)
w = nuevo(conectar=False)
e.conectado, e.bind_falla = True, True
chequeo("puerto ocupado: no lanza y sigue activo", pasada(w) is None and w.atender() is None and w.activo)
e.bind_falla = False
e.ms += 1001
w.atender()
chequeo("puerto libre otra vez: lo abre", w.servidor is not None)

print("\n3. Protocolo")
w = nuevo()
c = Cliente(b"auth malo\nping\n")
pasada(w, c)
chequeo("token incorrecto: error:auth y cierra (no atiende 'ping')", c.respuestas() == ["error:auth"] and c.cerrado)
c = Cliente("auth {}\nping\nmem\nfin\nping\n".format(TOKEN).encode())
pasada(w, c)
chequeo("ping, mem (MicroPython:ESP-IDF), fin", c.respuestas() == ["ok:auth", "pong", "mem:96:80", "chao"], str(c.respuestas()))
chequeo("tras 'fin' cierra y no lee mas", c.cerrado and c.entrada == b"ping\n")
chequeo("las esperas nunca pasan de 2 s", max(c.timeouts) <= 2, str(sorted(set(c.timeouts))))

fecha, hora = pcm(6400), pcm(12001 // 2 * 2)
c = Cliente("auth {}\nwav {}\n".format(TOKEN, len(fecha)).encode() + fecha +
            "wav {}\n".format(len(hora)).encode() + hora + b"fin\n")
t0 = e.ms
pasada(w, c)
r = c.respuestas()
chequeo("fecha y hora en una conexion: listo/voz_ok x2, chao", [x.split(":")[0] for x in r] ==
        ["ok", "listo", "voz_ok", "listo", "voz_ok", "chao"], str(r))
chequeo("I2S 0, pines BCLK 15 / LRC 16 / DIN 7, 16 bits, 16 kHz, ibuf 20000",
        all(i.pines == (15, 16, 7) and i.config == (0, 16, 16000, 20000) for i in e.i2s_creados))
chequeo("suena exactamente lo recibido + 0,3 s de silencio",
        [bytes(i.datos) for i in e.i2s_creados] == [fecha + bytes(9600), hora + bytes(9600)])
chequeo("el I2S se suelta despues de cada frase", len(e.i2s_creados) == 2 and all(i.cerrado for i in e.i2s_creados))
ms_ok = int(r[2].split(":")[1])
chequeo("voz_ok:<ms> = audio + silencio + vaciado del colchon", ms_ok == 200 + 300 + 630, str(ms_ok))

c = Cliente("auth {}\nwav 0\nwav 7\nwav {}\nwav x\nhola\nping\n".format(TOKEN, 15 * 32000 + 2).encode())
pasada(w, c)
chequeo("tamaños malos (0, impar, > 15 s, texto): voz_error:tamano y sigue",
        c.respuestas() == ["ok:auth"] + ["voz_error:tamano"] * 4 + ["comando_no_reconocido", "pong"], str(c.respuestas()))

print("\n4. Fallas a mitad (la mano sigue igual)")
for fin in ("timeout", "cerrado"):
    w = nuevo()
    c = Cliente("auth {}\nwav 6400\n".format(TOKEN).encode() + pcm(3000), fin=fin)
    error = pasada(w, c)
    chequeo("el PC deja de mandar ({}): voz_error:corte, cierra, suelta el I2S".format(fin),
            error is None and c.respuestas()[-1] == "voz_error:corte" and c.cerrado and e.i2s_creados[0].cerrado
            and w.activo, str(c.respuestas()))
w = nuevo()
c = Cliente("auth {}\n".format(TOKEN).encode())
chequeo("PC conectado que no manda nada: cierra sin error", pasada(w, c) is None and c.cerrado and w.activo)
c = Cliente(b"", fin="timeout")
chequeo("PC que no se presenta: cierra sin error", pasada(w, c) is None and c.cerrado)
c = Cliente(b"auth \xff\xfe\n")
chequeo("bytes que no son texto: cierra sin error", pasada(w, c) is None and c.cerrado and w.activo)

w = nuevo()
e.i2s_falla_crear = True
c = Cliente("auth {}\nwav 6400\nping\n".format(TOKEN).encode())
error = pasada(w, c)
chequeo("I2S no se puede crear: voz_error:i2s y la conexion sigue (pong)",
        error is None and c.respuestas() == ["ok:auth", "voz_error:i2s", "pong"], str(c.respuestas()))
w = nuevo()
e.i2s_falla_escribir = OSError("i2s")
c = Cliente("auth {}\nwav 6400\n".format(TOKEN).encode() + pcm(6400) + b"ping\n")
error = pasada(w, c)
chequeo("falla al escribir en el I2S: voz_error:i2s, cierra, suelta el I2S",
        error is None and c.respuestas()[-1] == "voz_error:i2s" and c.cerrado and e.i2s_creados[0].cerrado)

w = nuevo()
e.sin_memoria = True
c = Cliente("auth {}\n".format(TOKEN).encode())
error = pasada(w, c)
chequeo("sin memoria: no lanza, WiFi apagado y desactivado para siempre",
        error is None and not w.activo and e.wlan_activo is False and w.servidor is None)
chequeo("desactivado: atender() ya no hace nada", pasada(w, Cliente(b"x")) is None and len(e.pendientes) == 1)

w = nuevo()
e.i2s_falla_escribir = KeyboardInterrupt()
error = pasada(w, Cliente("auth {}\nwav 6400\n".format(TOKEN).encode() + pcm(6400)))
chequeo("Ctrl+C de Thonny SI pasa a main.py (como hoy) y suelta el I2S",
        isinstance(error, KeyboardInterrupt) and e.i2s_creados[0].cerrado)

w = nuevo()
errores = 0
for n in range(300):
    basura = bytes(random.choice(b"aw vpingmeauthfn0123456789 \n\xff") for _ in range(random.randrange(80)))
    if random.random() < 0.5:
        basura = "auth {}\n".format(TOKEN).encode() + basura
    e.i2s_falla_crear = random.random() < 0.1
    if pasada(w, Cliente(basura, fin=random.choice(("timeout", "cerrado")))) is not None:
        errores += 1
chequeo("300 conexiones con basura: atender() nunca lanza", errores == 0 and w.activo, "{} errores".format(errores))

print("\n5. No toca la mano ni muestra secretos")
fuente = open(RUTA, encoding="utf-8").read()
codigo = re.sub(r'"""[\s\S]*?"""', "", fuente)
chequeo("de machine solo usa Pin e I2S (sin PWM: no mueve servos)",
        re.findall(r"^[ \t]*(?:from machine import .*|import machine.*)$", codigo, re.M) == ["from machine import Pin, I2S"]
        and "PWM" not in codigo)
chequeo("no importa main.py ni nada de la mano", not re.search(r"import\s+main\b|reset_all|acciones|deletrear", codigo))
impreso = salida_total.getvalue()
chequeo("nunca imprime la red, la clave ni el TOKEN", RED not in impreso and CLAVE not in impreso and TOKEN not in impreso)
chequeo("dice cuantos caracteres tienen", "{} caracteres".format(len(TOKEN)) in impreso)
chequeo("sus avisos empiezan con '# ' (el PC los ignora)",
        all(l.startswith("# ") for l in impreso.splitlines() if l.strip()))

print("\n{} fallas".format(len(fallas)))
sys.exit(1 if fallas else 0)
