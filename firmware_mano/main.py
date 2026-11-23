from machine import Pin, PWM, I2S
import time
import sys
import os

# ---------------- CONFIGURACION ----------------
PAUSA_DEDO = 0.4     # segundos que espera cada dedo antes de mover el siguiente
PAUSA_LETRA = 1.0    # pausa entre letras al deletrear
US_MIN = 500         # pulso minimo permitido (microsegundos)
US_MAX = 2500        # pulso maximo permitido (microsegundos)

# ---------------- VOZ (MAX98357 por I2S) ----------------
PIN_BCLK = 15        # los mismos pines con los que el MAX98357 funcionaba en Doby
PIN_LRC = 16
PIN_DIN = 7
TASA_VOZ = 16000
CARPETA_VOZ = "/voz" # un WAV por palabra o frase: /voz/lina.wav, /voz/lina_maldonado.wav ...
PAUSA_VOZ_MS = 250   # entre archivos de una misma orden "voz"
VERSION = "voz-2"    # orden "version" (o "?") -> "version:voz-2"

dedos_config = {
    "indice":   {"pin": 1,  "abierto": 500,  "cerrado": 2000, "mitad": 1000},
    "menique":  {"pin": 2,  "abierto": 500,  "cerrado": 2000, "mitad": 1200},
    "medio":    {"pin": 42, "abierto": 500,  "cerrado": 2000, "mitad": 1000},
    "anular":   {"pin": 4,  "abierto": 2200, "cerrado": 500,  "mitad": 1700},
    "pulgar":   {"pin": 40,  "abierto": 1500, "cerrado": 500,  "mitad": 1000},  # antes abierto era 10: calibrar
    "pulgar2":  {"pin": 39,  "abierto": 700,  "cerrado": 2300, "mitad": 1600},
}

# ---------------- INICIO DE SERVOS ----------------
print("Iniciando motores...")
for dedo, cfg in dedos_config.items():
    s = PWM(Pin(cfg["pin"]), freq=50)
    s.duty_ns(int(cfg["abierto"] * 1000))
    cfg["servo"] = s
    cfg["pos"] = cfg["abierto"]
    time.sleep(0.5)
print("Mano lista.")

# ---------------- MOVIMIENTO BASICO ----------------
def mover_a(nombre, us):
    cfg = dedos_config.get(nombre)
    if not cfg:
        return
    us = int(us)
    if us < US_MIN:
        us = US_MIN
    if us > US_MAX:
        us = US_MAX
    if cfg["pos"] == us:
        return                      # ya esta en esa posicion, no espera
    cfg["servo"].duty_ns(us * 1000)
    cfg["pos"] = us
    time.sleep(PAUSA_DEDO)          # espera a que este dedo termine

def mover_dedo(nombre, estado):
    cfg = dedos_config.get(nombre)
    if not cfg:
        return
    mover_a(nombre, cfg["cerrado"] if estado == 1 else cfg["abierto"])

def mover_mitad(nombre):
    cfg = dedos_config.get(nombre)
    if not cfg:
        return
    mover_a(nombre, cfg["mitad"])

def mover_cuarto(nombre):
    cfg = dedos_config.get(nombre)
    if not cfg:
        return
    mover_a(nombre, (cfg["abierto"] + cfg["mitad"]) / 2)

def mover_cuarto_mas(nombre):
    cfg = dedos_config.get(nombre)
    if not cfg:
        return
    cuarto = (cfg["abierto"] + cfg["mitad"]) / 2
    mover_a(nombre, (cuarto + cfg["mitad"]) / 2)

# Orden para abrir la mano: primero el pulgar completo (pulgar2 y pulgar),
# despues los demas dedos. Asi ningun dedo choca con el pulgar al subir.
ORDEN_ABRIR = ["pulgar2", "pulgar", "indice", "medio", "anular", "menique"]

def reset_all():
    # Abre toda la mano empezando por el pulgar.
    # Se usa antes de cada letra, al terminar cada palabra y con "reset".
    for nombre in ORDEN_ABRIR:
        mover_dedo(nombre, 0)

# ---------------- LETRAS ----------------
def a():
    for d in ["indice", "medio", "anular", "menique", "pulgar", "pulgar2"]:
        mover_dedo(d, 1)

def b():
    for d in ["indice", "medio", "anular", "menique"]:
        mover_dedo(d, 0)
    mover_dedo("pulgar", 1)
    mover_dedo("pulgar2", 1)

def c():
    mover_dedo("pulgar2", 0)
    for d in ["medio", "anular", "menique", "pulgar", "indice"]:
        mover_mitad(d)

def d():
    mover_dedo("indice", 0)
    for n_ in ["medio", "anular", "menique", "pulgar", "pulgar2"]:
        mover_mitad(n_)

def e():
    for d in ["indice", "medio", "anular", "menique"]:
        mover_dedo(d, 1)
    mover_dedo("pulgar", 0)
    mover_dedo("pulgar2", 0)

def f():
    mover_dedo("indice", 0)
    for d in ["medio", "anular", "menique", "pulgar", "pulgar2"]:
        mover_dedo(d, 1)

def i():
    for d in ["indice", "medio", "anular", "pulgar", "pulgar2"]:
        mover_dedo(d, 1)
    mover_dedo("menique", 0)

def k():
    mover_dedo("indice", 0)
    mover_cuarto_mas("medio")
    mover_mitad("pulgar")
    mover_mitad("pulgar2")
    mover_dedo("anular", 1)
    mover_dedo("menique", 1)

def l():
    mover_dedo("pulgar2", 0)
    mover_dedo("pulgar", 0)
    mover_dedo("indice", 0)
    for d in ["medio", "anular", "menique"]:
        mover_dedo(d, 1)

def m():
    mover_mitad("medio")
    mover_mitad("indice")
    mover_mitad("anular")
    mover_dedo("menique", 1)
    mover_dedo("pulgar", 1)
    mover_dedo("pulgar2", 1)

def n():
    mover_mitad("indice")
    mover_mitad("medio")
    mover_dedo("anular", 1)
    mover_dedo("menique", 1)
    mover_dedo("pulgar", 1)
    mover_dedo("pulgar2", 1)

def o():
    for d in ["indice", "medio", "anular", "menique", "pulgar2"]:
        mover_mitad(d)
    mover_dedo("pulgar", 0)

def p():
    mover_cuarto_mas("indice")
    mover_mitad("medio")
    mover_dedo("anular", 1)
    mover_dedo("menique", 1)
    mover_dedo("pulgar", 1)
    mover_dedo("pulgar2", 1)

def q():
    for d in ["indice", "medio", "anular", "menique"]:
        mover_dedo(d, 0)
    mover_mitad("pulgar")
    mover_dedo("pulgar2", 1)

def r():
    mover_cuarto("indice")
    mover_dedo("medio", 0)
    for d in ["anular", "menique", "pulgar", "pulgar2"]:
        mover_dedo(d, 1)

def t():
    for d in ["medio", "anular", "menique", "pulgar", "pulgar2"]:
        mover_dedo(d, 0)
    mover_mitad("indice")

def u():
    mover_dedo("indice", 0)
    mover_dedo("menique", 0)
    for d in ["medio", "anular", "pulgar", "pulgar2"]:
        mover_dedo(d, 1)

def v():
    mover_dedo("indice", 0)
    mover_dedo("medio", 0)
    for d in ["anular", "menique", "pulgar", "pulgar2"]:
        mover_dedo(d, 1)

def w():
    for d in ["indice", "medio", "anular"]:
        mover_dedo(d, 0)
    for d in ["menique", "pulgar", "pulgar2"]:
        mover_dedo(d, 1)

def x():
    mover_cuarto("indice")
    for d in ["medio", "anular", "menique", "pulgar", "pulgar2"]:
        mover_dedo(d, 1)

def y():
    mover_dedo("pulgar", 0)
    mover_dedo("pulgar2", 0)
    mover_dedo("menique", 0)
    for d in ["indice", "medio", "anular"]:
        mover_dedo(d, 1)

acciones = {
    "a": a, "b": b, "c": c, "d": d, "e": e,
    "f": f, "i": i, "k": k, "l": l, "m": m,
    "n": n, "o": o, "p": p, "q": q, "r": r,
    "t": t, "u": u, "v": v, "w": w, "x": x,
    "y": y,
}

# ---------------- DELETREO ----------------
def deletrear(palabra):
    for letra in palabra.lower():
        if letra in acciones:
            reset_all()
            acciones[letra]()
            print("gesto_" + letra + "_ok")
            print("letra_actual:" + letra)
            time.sleep(PAUSA_LETRA)
        else:
            print("letra_" + letra + "_no_disponible")
    print("deletreo_completo")
    reset_all()

# ---------------- VOZ ----------------
# Orden "voz <archivo> [<archivo> ...]": suena /voz/<archivo>.wav (16 kHz, mono, 16 bits) en orden,
# con PAUSA_VOZ_MS entre ellos. Responde SIEMPRE una de: "voz_ok" al terminar, "voz_falta:<a>,<b>" (sin sonar
# nada) o "voz_error:<i2s|lectura>" si algo falla. Nunca lanza: un error de la voz no detiene la mano.
# El I2S solo existe mientras suena (los servos usan PWM, que es otro periferico).
_buf_voz = bytearray(4096)
_ceros = bytearray(1600)                        # 50 ms de silencio

def _ruta_voz(nombre):
    return CARPETA_VOZ + "/" + nombre + ".wav"

def _inicio_datos(f):
    """Deja el archivo al comienzo del audio (bloque 'data') y devuelve cuantos bytes tiene."""
    cab = f.read(12)
    if cab[0:4] != b"RIFF" or cab[8:12] != b"WAVE":
        raise ValueError("no es WAV")
    while True:
        h = f.read(8)
        if len(h) < 8:
            raise ValueError("WAV sin datos")
        n = int.from_bytes(h[4:8], "little")
        if h[0:4] == b"data":
            return n
        f.seek(n + (n & 1), 1)

def _silencio(i2s, ms):
    for _ in range(ms // 50):
        i2s.write(_ceros)

def reproducir_voz(nombres):
    """Suena /voz/<nombre>.wav en orden. Devuelve la respuesta para el PC."""
    faltan = []
    for nombre in nombres:                      # se revisan TODOS antes de sonar
        try:
            if not all(c.isalpha() or c == "_" for c in nombre):
                raise ValueError("nombre no valido")
            with open(_ruta_voz(nombre), "rb") as f:
                _inicio_datos(f)
        except (OSError, ValueError):
            faltan.append(nombre)
    if faltan:
        return "voz_falta:" + ",".join(faltan)  # no suena nada
    i2s = None
    paso = "i2s"
    try:
        i2s = I2S(0, sck=Pin(PIN_BCLK), ws=Pin(PIN_LRC), sd=Pin(PIN_DIN), mode=I2S.TX,
                  bits=16, format=I2S.MONO, rate=TASA_VOZ, ibuf=20000)   # igual que Doby
        mv = memoryview(_buf_voz)
        for k, nombre in enumerate(nombres):
            if k:
                _silencio(i2s, PAUSA_VOZ_MS)
            paso = "lectura"
            with open(_ruta_voz(nombre), "rb") as f:
                restante = _inicio_datos(f)
                while restante > 0:
                    n = f.readinto(mv[:min(len(_buf_voz), restante)])
                    if not n:
                        break
                    paso = "i2s"
                    i2s.write(mv[:n])           # a 16 kHz: cada bloque tarda como mucho 128 ms, nunca se queda
                    paso = "lectura"
                    restante -= n
        paso = "i2s"
        _silencio(i2s, 300)                     # los 0,3 s finales de Doby
        time.sleep_ms(630)                      # lo que tarda en vaciarse ibuf=20000 (como Doby)
        respuesta = "voz_ok"
    except Exception:
        respuesta = "voz_error:" + paso
    finally:
        if i2s is not None:
            try:
                i2s.deinit()                    # suelta los pines; sin reloj el MAX98357 se apaga solo
            except Exception:
                pass
    return respuesta

# ---------------- BUCLE PRINCIPAL ----------------
# =============================================================================
# >>> INICIO DE LO AGREGADO: este bloque reemplaza el BUCLE PRINCIPAL original.
# Recibe las MISMAS órdenes por USB y, si existe config_ble.py, también por
# Bluetooth (BLE, servicio "UART" de Nordic, con token), y responde con los
# MISMOS textos del código original.
# Arriba de este bloque está el código original, más la sección VOZ (orden "voz").
# =============================================================================
import bluetooth
from micropython import const

try:
    import uselect as select
except ImportError:
    import select

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_FLAG_READ = const(0x0002)
_FLAG_WRITE_NO_RESPONSE = const(0x0004)
_FLAG_WRITE = const(0x0008)
_FLAG_NOTIFY = const(0x0010)
_UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), _FLAG_READ | _FLAG_NOTIFY)
_UART_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), _FLAG_WRITE | _FLAG_WRITE_NO_RESPONSE)


def _ble_aviso(texto):
    print("# " + texto)            # avisos del Bluetooth: se ven en Thonny, el PC los ignora


def atender_orden(cmd, responder):
    """Lo mismo que hacía el bucle original con cada orden. Devuelve False con 'salir'."""
    cmd = cmd.strip().lower()
    if not cmd:
        return True
    if cmd == "salir":
        return False
    elif cmd == "reset" or cmd == "1":
        reset_all()
        responder("reset_ok")
    elif cmd == "version" or cmd == "?":   # antes de len(cmd) > 1: si no, "version" se deletrearia
        responder("version:" + VERSION)
    elif cmd == "voz" or cmd.startswith("voz "):
        nombres = cmd.split()[1:]
        responder(reproducir_voz(nombres) if nombres else "comando_no_reconocido")
    elif cmd in acciones:
        reset_all()
        acciones[cmd]()
        responder("gesto_" + cmd + "_ok")
    elif len(cmd) > 1:
        if responder is print:
            deletrear(cmd)          # por USB: la función original tal cual
        else:
            # por Bluetooth: los mismos pasos y textos de deletrear(), enviados al PC
            for letra in cmd:
                if letra in acciones:
                    reset_all()
                    acciones[letra]()
                    responder("gesto_" + letra + "_ok")
                    responder("letra_actual:" + letra)
                    time.sleep(PAUSA_LETRA)
                else:
                    responder("letra_" + letra + "_no_disponible")
            responder("deletreo_completo")
            reset_all()
    else:
        responder("comando_no_reconocido")
    return True


class LectorUSB:
    """Lee órdenes por USB sin quedarse esperando (para poder atender también el Bluetooth)."""

    def __init__(self):
        self.poll = select.poll()
        self.poll.register(sys.stdin, select.POLLIN)
        self.buffer = ""

    def leer(self):
        while self.poll.poll(0):
            c = sys.stdin.read(1)
            if c in ("\n", "\r", ""):
                if self.buffer:
                    linea, self.buffer = self.buffer, ""
                    return linea
                if c == "":
                    return None
                continue
            if len(self.buffer) < 64:
                self.buffer += c
        return None


class ServidorBLE:
    """La mano como periférico BLE con el servicio UART de Nordic. Nunca bloquea el bucle.

    Un solo PC a la vez (al conectarse uno, la placa deja de anunciarse). La primera
    línea debe ser "auth <TOKEN>" en 3 s; si no, la placa lo desconecta.
    """

    def __init__(self, cfg):
        self.nombre = getattr(cfg, "NOMBRE", "Mano-LSC")
        self.token = cfg.TOKEN
        if not self.token or len(self.token) < 16:
            raise ValueError("TOKEN de config_ble.py muy corto (minimo 16 caracteres)")
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        try:
            self.ble.config(gap_name=self.nombre)
        except Exception:
            pass
        self.ble.irq(self._irq)
        ((self.h_tx, self.h_rx),) = self.ble.gatts_register_services(((_UART_UUID, (_UART_TX, _UART_RX)),))
        self.ble.gatts_set_buffer(self.h_rx, 256, True)
        self.conexion = None
        self.autenticado = False
        self.desde = time.ticks_ms()
        self.trozos = []            # lo que llega por Bluetooth (lo llena _irq)
        self.buffer = b""
        self.eventos = []           # avisos de conexión/desconexión para imprimirlos fuera de _irq
        nombre = self.nombre.encode()
        self.anuncio = b"\x02\x01\x06" + bytes((len(nombre) + 1, 0x09)) + nombre
        self.respuesta = bytes((17, 0x07)) + bytes(_UART_UUID)
        self._anunciar()
        _ble_aviso("Bluetooth listo: se anuncia como {}".format(self.nombre))

    def _anunciar(self):
        self.ble.gap_advertise(100000, adv_data=self.anuncio, resp_data=self.respuesta)

    def _irq(self, evento, datos):
        if evento == _IRQ_CENTRAL_CONNECT:
            self.conexion = datos[0]
            self.autenticado = False
            self.desde = time.ticks_ms()
            self.trozos = []
            self.buffer = b""
            self.eventos.append("PC conectado por Bluetooth")
        elif evento == _IRQ_CENTRAL_DISCONNECT:
            self.conexion = None
            self.autenticado = False
            self.eventos.append("PC desconectado; anunciando de nuevo")
            self._anunciar()
        elif evento == _IRQ_GATTS_WRITE:
            if datos[1] == self.h_rx:
                self.trozos.append(self.ble.gatts_read(self.h_rx))

    def _enviar(self, texto):
        datos = (texto + "\n").encode()
        for k in range(0, len(datos), 20):             # paquetes de 20 bytes: sirve con cualquier MTU
            try:
                self.ble.gatts_notify(self.conexion, self.h_tx, datos[k:k + 20])
            except Exception:
                return

    def _desconectar(self):
        try:
            self.ble.gap_disconnect(self.conexion)
        except Exception:
            pass

    def atender(self, atender_orden):
        """Una pasada: avisos, token y órdenes recibidas. Devuelve False con 'salir'."""
        while self.eventos:
            _ble_aviso(self.eventos.pop(0))
        if self.conexion is None:
            return True
        while self.trozos:
            self.buffer += self.trozos.pop(0)
        if len(self.buffer) > 256:
            self.buffer = b""
        lineas = []
        while b"\n" in self.buffer:
            linea, self.buffer = self.buffer.split(b"\n", 1)
            lineas.append(linea.decode("utf-8", "ignore").strip("\r"))
        if not self.autenticado:
            if lineas and lineas[0].strip() == "auth " + self.token:
                self.autenticado = True
                lineas = lineas[1:]
                self._enviar("ok:auth")
            elif lineas:
                self._enviar("error:auth")
                _ble_aviso("Conexion rechazada (token incorrecto)")
                self._desconectar()
                return True
            elif time.ticks_diff(time.ticks_ms(), self.desde) > 3000:
                self._desconectar()                    # no se presentó a tiempo
                return True
        for linea in lineas:
            if not atender_orden(linea, self._enviar):
                return False
        return True


usb = LectorUSB()
ble = None
try:
    import config_ble
    ble = ServidorBLE(config_ble)
except ImportError:
    pass                            # sin config_ble.py: solo USB, igual que el original
except Exception as error:
    _ble_aviso("Bluetooth desactivado: {}".format(error))

print("Listo. Esperando comandos...")
seguir = True
while seguir:
    try:
        linea = usb.leer()
        if linea is not None:
            seguir = atender_orden(linea, print)
        if seguir and ble is not None:
            seguir = ble.atender(atender_orden)
        time.sleep_ms(5)
    except KeyboardInterrupt:
        break

reset_all()
print("Programa terminado.")
# =============================================================================
# <<< FIN DE LO AGREGADO
# =============================================================================
