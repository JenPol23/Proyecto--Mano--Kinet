"""
Simula firmware_mano/main.py (letras + orden "voz") en el PC con machine/I2S/neopixel/USB falsos.
No necesita la placa. Los WAV de prueba van a una carpeta temporal del sistema (hace de /voz).

Uso (desde la carpeta del proyecto):  py -3.11 fusion/pruebas/prueba_firmware_voz.py
"""
import io, os, sys, tempfile, types, time, wave
import numpy as np

PROYECTO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIRMWARE = os.path.join(PROYECTO, "firmware_mano", "main.py")
PLACA_VOZ = tempfile.mkdtemp(prefix="prueba_placa_voz_")
T = [0]
EVENTOS = []           # ('pwm', pin, us) | ('i2s_init', pines) | ('i2s', bytes) | ('i2s_deinit',) | ('led', valor)
ENTRADA = []
SALIDA = []


def wav(nombre, muestras):
    with wave.open(os.path.join(PLACA_VOZ, nombre + ".wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(np.asarray(muestras, "<i2").tobytes())


LINA = (np.arange(9216) % 200 + 1).astype(np.int16)
JEAN = np.full(12960, 7, np.int16)
PAUL = np.full(19040, -5, np.int16)
wav("lina", LINA); wav("jean", JEAN); wav("paul", PAUL)
with open(os.path.join(PLACA_VOZ, "danado.wav"), "wb") as f:
    f.write(b"esto no es un wav")


PINES_USADOS = set()                   # todos los GPIO que el firmware llega a usar


class Pin:
    OUT = 1
    def __init__(s, n, modo=None, value=None):
        s.n = n
        PINES_USADOS.add(n)


class PWM:
    def __init__(s, pin, freq):
        s.p = pin.n
    def duty_ns(s, ns):
        EVENTOS.append(("pwm", s.p, ns // 1000))


I2S_CREADOS = [0]
I2S_FALLA = {3: "init", 4: "write"}         # el 3.er I2S no se puede crear; el 4.º falla al escribir


class I2S:
    TX, MONO = 0, 1
    def __init__(s, n, sck, ws, sd, mode, bits, format, rate, ibuf):
        I2S_CREADOS[0] += 1
        s.falla = I2S_FALLA.get(I2S_CREADOS[0])
        if s.falla == "init":
            raise OSError("I2S ocupado")
        EVENTOS.append(("i2s_init", (sck.n, ws.n, sd.n, bits, rate, ibuf)))
    def write(s, b):
        if s.falla == "write":
            raise OSError("DMA")
        EVENTOS.append(("i2s", bytes(b)))
        T[0] += len(b) // 32               # 32 bytes por ms a 16 kHz
        return len(b)
    def deinit(s):
        EVENTOS.append(("i2s_deinit",))


class NeoPixel:
    def __init__(s, pin, n):
        s.pin, s.v = pin.n, [None] * n
    def __setitem__(s, i, v):
        s.v[i] = v
    def write(s):
        EVENTOS.append(("led", s.pin, s.v[0]))


buf = []
class Stdin:
    def read(s, n):
        return buf.pop(0)
class Poll:
    def register(s, *a): pass
    def poll(s, t):
        while ENTRADA and ENTRADA[0][0] <= T[0]:
            buf.extend(ENTRADA.pop(0)[1] + "\n")
        return bool(buf)


def avanzar(seg):
    T[0] += int(seg * 1000)


sys.modules["machine"] = types.SimpleNamespace(Pin=Pin, PWM=PWM, I2S=I2S)
sys.modules["neopixel"] = types.SimpleNamespace(NeoPixel=NeoPixel)
sys.modules["bluetooth"] = types.SimpleNamespace(UUID=lambda x: x, BLE=None)
sys.modules["micropython"] = types.SimpleNamespace(const=lambda x: x)
sys.modules["uselect"] = types.SimpleNamespace(poll=Poll, POLLIN=1)
sys.modules["config_ble"] = None
time.sleep = avanzar
time.sleep_ms = lambda ms: avanzar(ms / 1000)
time.ticks_ms = lambda: T[0]
time.ticks_diff = lambda a, b: a - b
real_stdin, real_stdout = sys.stdin, sys.stdout
sys.stdin = Stdin()


class Captura(io.StringIO):
    def write(s, t):
        SALIDA.extend(l for l in t.split("\n") if l)
        return len(t)


ORDENES = ["lina", "voz lina", "voz jean paul", "voz lina_maldonado", "voz lina maldonado danado",
           "voz ../main", "voz", "version", "?",
           "voz lina",          # el I2S no se puede crear -> voz_error:i2s (y la placa sigue)
           "voz lina",          # el I2S falla al escribir -> voz_error:i2s
           "a", "reset", "voz lina", "salir"]
for k, o in enumerate(ORDENES):
    ENTRADA.append((k * 60000, o))
codigo = open(FIRMWARE, encoding="utf-8").read()
assert codigo.count('CARPETA_VOZ = "/voz"') == 1
codigo = codigo.replace('CARPETA_VOZ = "/voz"', "CARPETA_VOZ = " + repr(PLACA_VOZ.replace("\\", "/")))
sys.stdout = Captura()
try:
    exec(compile(codigo, FIRMWARE, "exec"), {"__name__": "__main__"})
finally:
    sys.stdout, sys.stdin = real_stdout, real_stdin
sys.stdout.reconfigure(encoding="utf-8")

fallas = 0
def chequeo(nombre, cond, extra=""):
    global fallas
    fallas += not cond
    print("{}  {}{}".format("PASA " if cond else "FALLA", nombre, "  " + extra if extra else ""))

resp = [l for l in SALIDA if not l.startswith(("Iniciando", "Mano lista", "Listo.", "Programa"))]
print("Respuestas:", resp)
esperado = (["gesto_l_ok", "letra_actual:l", "gesto_i_ok", "letra_actual:i", "gesto_n_ok", "letra_actual:n",
             "gesto_a_ok", "letra_actual:a", "deletreo_completo"]
            + ["voz_ok", "voz_ok", "voz_falta:lina_maldonado", "voz_falta:maldonado,danado", "voz_falta:../main",
               "comando_no_reconocido", "version:voz-2", "version:voz-2", "voz_error:i2s", "voz_error:i2s",
               "gesto_a_ok", "reset_ok", "voz_ok"])
chequeo("respuestas exactas (mano sin cambios + version + voz_ok / voz_falta / voz_error)", resp == esperado)
if resp != esperado:
    print("       esperado:", esperado)
chequeo("después de dos voz_error la mano y la voz siguen funcionando", resp[-3:] == ["gesto_a_ok", "reset_ok", "voz_ok"])

# Audio enviado por cada voz
bloques, actual = [], None
for e in EVENTOS:
    if e[0] == "i2s_init":
        actual = [e[1], b""]
    elif e[0] == "i2s":
        actual[1] += e[1]
    elif e[0] == "i2s_deinit":
        bloques.append(actual); actual = None
# I2S creados: voz lina, voz jean paul, (el 3.º no se crea), el 4.º falla al escribir, voz lina final
chequeo("4 I2S abiertos y cerrados (las voz_falta no suenan; el que no se creó no queda abierto)",
        len(bloques) == 4 and actual is None, str(len(bloques)))
chequeo("pines I2S como en Doby (BCLK 15, LRC 16, DIN 7) y formato 16 bits / 16 kHz",
        all(b[0] == (15, 16, 7, 16, 16000, 20000) for b in bloques), str(bloques[0][0]))
MANO = {1, 2, 42, 4, 40, 39}
chequeo("los pines de la voz no chocan con los de la mano", not ({15, 16, 7} & MANO))
chequeo("el firmware solo usa los pines de la mano y los de la voz (nada en el 48 ni en el 47)",
        PINES_USADOS <= MANO | {15, 16, 7}, str(sorted(PINES_USADOS)))
lina_ok = np.concatenate([LINA, np.zeros(4800, np.int16)])
a = np.frombuffer(bloques[0][1], "<i2")
chequeo("voz lina = lina + 0,3 s", np.array_equal(a, lina_ok), "{} muestras".format(len(a)))
b = np.frombuffer(bloques[1][1], "<i2")
chequeo("voz jean paul = jean + 250 ms + paul + 0,3 s",
        np.array_equal(b, np.concatenate([JEAN, np.zeros(4000, np.int16), PAUL, np.zeros(4800, np.int16)])))
chequeo("la voz que falló al escribir no mandó audio", bloques[2][1] == b"")
chequeo("después del error, voz lina vuelve a sonar completa", np.array_equal(np.frombuffer(bloques[3][1], "<i2"), lina_ok))
chequeo("ya no se toca el LED (sin neopixel)", not [e for e in EVENTOS if e[0] == "led"])
pwm_en_voz = []
dentro = False
for e in EVENTOS:
    if e[0] == "i2s_init": dentro = True
    if e[0] == "i2s_deinit": dentro = False
    if dentro and e[0] == "pwm": pwm_en_voz.append(e)
chequeo("ningún servo se mueve mientras suena", not pwm_en_voz)
p39 = sorted({e[2] for e in EVENTOS if e[0] == "pwm" and e[1] == 39})
chequeo("pulgar2 (GPIO 39) solo 700/1600/2300", set(p39) <= {700, 1600, 2300}, str(p39))
print("\n{} fallas".format(fallas))
sys.exit(1 if fallas else 0)
