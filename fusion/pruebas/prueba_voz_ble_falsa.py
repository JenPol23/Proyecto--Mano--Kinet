"""
Prueba de fusion/voz.py + Mano.hablar() con un bleak FALSO que imita el firmware (deletreo + orden "voz").
No necesita la placa ni Bluetooth, y NO depende de lo que haya en voces/: crea sus propios audios de prueba
(tonos de 1,2 s) en una carpeta temporal; caché, WAV y CSV de la prueba también van a esa carpeta.

Uso (desde la carpeta del proyecto):  py -3.11 fusion/pruebas/prueba_voz_ble_falsa.py
"""
import asyncio, json, os, sys, tempfile, threading, time, types, wave
import numpy as np

FUSION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FUSION)
sys.stdout.reconfigure(encoding="utf-8")
TEMP = tempfile.mkdtemp(prefix="prueba_voz_")

ACCIONES = set("abcdefiklmnopqrtuvwxy")
EST = {"ordenes": [], "placa": None, "firmware": "voz"}       # firmware: "voz" o "viejo" (sin voz)


class Cliente:
    def __init__(self, dispositivo, disconnected_callback=None):
        self.buf, self.auth = b"", False

    async def connect(self, timeout=None):
        pass

    async def disconnect(self):
        pass

    async def start_notify(self, uuid, cb):
        self.notif = cb

    async def write_gatt_char(self, uuid, datos, response=True):
        assert len(datos) <= 20
        self.buf += datos
        while b"\n" in self.buf:
            linea, self.buf = self.buf.split(b"\n", 1)
            asyncio.get_running_loop().create_task(self._atender(linea.decode()))

    async def _resp(self, t):
        await asyncio.sleep(0.001)
        d = (t + "\n").encode()
        for k in range(0, len(d), 20):
            self.notif(None, bytearray(d[k:k + 20]))

    async def _atender(self, cmd):
        if not self.auth:
            self.auth = True
            await self._resp("ok:auth")
            return
        EST["ordenes"].append(cmd)
        cmd = cmd.strip().lower()
        nuevo = EST["firmware"] == "voz"
        if cmd in ("reset", "1"):
            await self._resp("reset_ok")
        elif nuevo and cmd in ("version", "?"):
            await self._resp("version:voz-2")
        elif nuevo and cmd.startswith("voz "):    # la "placa" tiene lo que se preparó (como si se hubiera subido)
            nombres = cmd.split()[1:]
            if nombres == ["cuelga"]:
                return                            # no responde nunca (para probar esperas y cerrar())
            if nombres == ["falla"]:
                await self._resp("voz_error:i2s")
                return
            faltan = [n for n in nombres if not os.path.exists(os.path.join(EST["placa"], n + ".wav"))]
            await self._resp("voz_falta:" + ",".join(faltan) if faltan else "voz_ok")
        elif cmd in ACCIONES:
            await self._resp("gesto_" + cmd + "_ok")
        elif len(cmd) > 1:
            for l in cmd:
                await self._resp("gesto_" + l + "_ok")
                await self._resp("letra_actual:" + l)
            await self._resp("deletreo_completo")
        else:
            await self._resp("comando_no_reconocido")


class Escaner:
    @staticmethod
    async def find_device_by_name(nombre, timeout=None):
        return object()


sys.modules["bleak"] = types.SimpleNamespace(BleakScanner=Escaner, BleakClient=Cliente)

import consola_mano as cm                       # noqa: E402
import voz as V                                 # noqa: E402
from reconocer import Integrantes, interpretar  # noqa: E402

cm.PAUSA_LETRA_SUELTA = cm.PAUSA_MOVIMIENTO = cm.PAUSA_ESPACIO = 0.0
cfg = os.path.join(TEMP, "config_ble_falso.py")             # token falso: nunca se usa config_ble.py real
with open(cfg, "w", encoding="utf-8") as f:
    f.write('NOMBRE = "Mano-LSC"\nTOKEN = "' + "x" * 32 + '"\n')

# integrantes.json de prueba: el real, pero buscando solo en una carpeta temporal con estos audios de prueba.
# Faltan a proposito Maldonado y los de Harry (para probar "Falta audio"). Lina va con extension de WhatsApp.
voces_prueba = os.path.join(TEMP, "voces")
os.makedirs(voces_prueba)
# (JEAN.mp4.wav y no JEAN.wav: "Jean.wav" esta en no_usar sin importar mayusculas)
for k, archivo in enumerate(["JEAN.mp4.wav", "Paul.wav", "Lina.mp3.wav", "Tatiana.wav", "Lina_Maldonado.wav"]):
    with wave.open(os.path.join(voces_prueba, archivo), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
        t = np.arange(int(44100 * 1.2)) / 44100
        w.writeframes((np.sin(2 * np.pi * (300 + 50 * k) * t) * 8000 * (t > 0.2) * (t < 1.0)).astype("<i2").tobytes())
with open(os.path.join(FUSION, "integrantes.json"), encoding="utf-8") as f:
    datos = json.load(f)
datos["carpetas_audio"] = [voces_prueba]
ruta_ints = os.path.join(TEMP, "integrantes_prueba.json")
with open(ruta_ints, "w", encoding="utf-8") as f:
    json.dump(datos, f, ensure_ascii=False)
ints = Integrantes(ruta_ints)

cache, placa_pc = os.path.join(TEMP, "cache"), os.path.join(TEMP, "audios_placa")
EST["placa"] = placa_pc
csv_falso = os.path.join(TEMP, "tiempos_voz_falso.csv")

mano = cm.Mano(cfg, ruta_tiempos=os.path.join(TEMP, "tiempos_mano_falso.csv"))
voz = V.Voz(mano, ints, ruta_tiempos=csv_falso, carpeta_cache=cache, carpeta_placa=placa_pc)
print("conectar:", mano.conectar())
fallas = 0


def caso(nombre, texto, ok_esp, msg_esp, voz_esp, deletrear=False):
    global fallas
    EST["ordenes"] = []
    r = interpretar(texto, ints)
    if deletrear:
        mano.deletrear(r)
    ok, msg = voz.hablar(r)
    enviadas = [o for o in EST["ordenes"] if o.startswith("voz")]
    bien = ok == ok_esp and msg == msg_esp and enviadas == voz_esp
    fallas += not bien
    print("{}  {:24} ok={} msg={!r}\n       órdenes: {}".format("PASA " if bien else "FALLA", nombre, ok, msg,
                                                            EST["ordenes"]))
    return bien


caso("Lina", "Lina", True, "Sonó: Lina", ["voz lina"])
caso("frase grabada", "Lina Maldonado", True, "Sonó: Lina Maldonado", ["voz lina_maldonado"])
caso("frase sin grabar", "Tatiana Maldonado", False, "Falta audio: Maldonado", [])
caso("palabras sueltas", "Lina Tatiana", True, "Sonó: Lina Tatiana", ["voz lina tatiana"])
caso("Jean (de Jean Paul)", "Jean Paul", True, "Sonó: Jean Paul", ["voz jean paul"])
caso("Harry falta", "Harry Raigozo", False, "Falta audio: Harry, Raigozo", [])

# El PC tiene el archivo pero la placa no (no se subió): se quita de la "placa" justo después de prepararlo
original = voz.preparar_placa


def preparar_y_quitar(base):
    res = original(base)
    if base == "Tatiana":
        os.remove(res[0])                          # solo el WAV temporal de esta prueba
    return res


voz.preparar_placa = preparar_y_quitar
caso("no está en la placa", "Lina Tatiana", False,
     "Falta audio: Tatiana (no está en la placa: súbelo a /voz con Thonny)", ["voz lina tatiana"])
voz.preparar_placa = original

caso("deletrear y después voz", "Lina", True, "Sonó: Lina", ["voz lina"], deletrear=True)
despues = EST["ordenes"][-2:] == ["reset", "voz lina"]
fallas += not despues
print("{}  la voz va después del reset final".format("PASA " if despues else "FALLA"))
caso("no reconocido", "Pedro", False, "No coincide con un integrante", [])


def chequeo(nombre, cond, extra=""):
    global fallas
    fallas += not cond
    print("{}  {}{}".format("PASA " if cond else "FALLA", nombre, "  " + extra if extra else ""))


# Versión del firmware: "?" no mueve la mano en el firmware viejo
EST["ordenes"] = []
chequeo("versión con el firmware con voz", voz.comprobar_placa() == (True, "voz-2") and EST["ordenes"] == ["?"])
EST["firmware"] = "viejo"
ok, msg = voz.comprobar_placa()
chequeo("firmware sin voz: lo avisa sin deletrear nada", not ok and msg == cm.MSG_SIN_VOZ and EST["ordenes"][-1] == "?",
        msg)
EST["firmware"] = "voz"

# voz_error de la placa
original_hablar = mano.hablar
mano.hablar = lambda nombres, espera=20: original_hablar(["falla"], espera)
ok, msg = voz.hablar(interpretar("Lina", ints))
chequeo("voz_error:i2s -> mensaje claro", not ok and msg == "La placa no pudo reproducir el audio (i2s)", msg)

# La espera de voz_ok es la duración del audio + 0,93 s + 5 s
capturado = {}
mano.hablar = lambda nombres, espera=20: (capturado.update(espera=espera), original_hablar(nombres, espera))[1]
r = interpretar("Jean Paul", ints)
voz.hablar(r)
listos, _ = voz.preparar(r)
audio = sum(s for _, _, s in listos) + 0.25
chequeo("espera de la voz = audio ({:.2f} s) + 0,93 + 5 = {:.2f} s (no 20 ni 60)".format(audio, capturado["espera"]),
        abs(capturado["espera"] - (audio + 0.93 + 5)) < 1e-6)
mano.hablar = original_hablar

# Si la placa no responde: se rinde a los 'espera' s
t = time.perf_counter()
ok, msg = mano.hablar(["cuelga"], espera=0.6)
chequeo("placa que no responde: se rinde en la espera pedida ({:.1f} s)".format(time.perf_counter() - t),
        not ok and msg == cm.MSG_TIEMPO and time.perf_counter() - t < 2)

# !orden (modo directo)
vistos = []
chequeo("!version", mano.orden_directa("version") == (True, "version:voz-2"))
chequeo("!voz xyz", mano.orden_directa("voz xyz") == (True, "voz_falta:xyz"))
chequeo("!lina (respuestas intermedias y final)",
        mano.orden_directa("lina", vistos.append) == (True, "deletreo_completo") and len(vistos) == 8, str(len(vistos)))
EST["firmware"] = "viejo"
chequeo("!g en el firmware viejo: comando_no_reconocido (sin error)", mano.orden_directa("g") ==
        (True, "comando_no_reconocido"))
EST["firmware"] = "voz"

# cerrar() con una orden colgada: suelta todo en menos de SEG_CIERRE y la orden termina con error
mano2 = cm.Mano(cfg, ruta_tiempos=os.path.join(TEMP, "tiempos_mano_falso2.csv"))
mano2.conectar()
resultado_hilo = {}
hilo = threading.Thread(target=lambda: resultado_hilo.update(r=mano2.hablar(["cuelga"], espera=30)))
hilo.start()
time.sleep(0.4)
t = time.perf_counter()
mano2.cerrar()
hilo.join(3)
chequeo("cerrar() con una voz colgada: vuelve en {:.2f} s y la orden termina con error".format(time.perf_counter() - t),
        not hilo.is_alive() and resultado_hilo.get("r", (True,))[0] is False and time.perf_counter() - t < 3.5,
        str(resultado_hilo))
chequeo("cerrar() dos veces no falla y después no se puede mandar nada",
        (mano2.cerrar() is None) and mano2.hablar(["lina"])[0] is False)

# Ctrl+C mientras se espera: corta enseguida (se simula un KeyboardInterrupt en el hilo principal)
import _thread
mano3 = cm.Mano(cfg, ruta_tiempos=os.path.join(TEMP, "tiempos_mano_falso3.csv"))
mano3.conectar()
threading.Timer(0.5, _thread.interrupt_main).start()
t = time.perf_counter()
try:
    mano3.hablar(["cuelga"], espera=30)
    cortado = False
except KeyboardInterrupt:
    cortado = True
chequeo("Ctrl+C durante una espera de 30 s corta en {:.2f} s".format(time.perf_counter() - t),
        cortado and time.perf_counter() - t < 1.5)
mano3.cerrar()
mano.cerrar()

with wave.open(os.path.join(placa_pc, "lina.wav")) as w:
    formato = (w.getframerate(), w.getnchannels(), 8 * w.getsampwidth(),
               os.path.getsize(os.path.join(placa_pc, "lina.wav")) - 2 * w.getnframes())
bien = formato == (16000, 1, 16, 44)
fallas += not bien
print("{}  formato de los WAV para la placa: {} Hz, {} canal, {} bits, cabecera de {} bytes".format(
    "PASA " if bien else "FALLA", *formato))
print("\n{} fallas".format(fallas))
sys.exit(1 if fallas else 0)
