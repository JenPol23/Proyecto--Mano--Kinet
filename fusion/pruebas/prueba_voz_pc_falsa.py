"""
prueba_voz_pc_falsa.py  -  CORRE EN EL PC (py -3.11), SIN PLACA, SIN KINECT Y SIN SONIDO
Prueba el PLAN B de audio (dibujar_fusion.py --voz-pc): nombres, fecha y hora por los parlantes del PC.
  - VozPC: la misma regla que la placa (frase grabada si existe; si no, palabras sueltas con 250 ms), con los WAV
    de fusion/audios_placa/; nunca manda "voz" a la placa; Falta audio; detener; fila en tiempos_voz.csv (temporal).
  - voz_pc.sonar(): WAV temporal valido y winsound asincrono (winsound FALSO: no suena nada); Esc lo corta.
  - hora.decir(en_pc=True): los mismos WAV, sin WiFi (mano_wifi no se usa). Sin en_pc, sigue yendo por WiFi.
  - ControlMano: sin voz_pc usa Voz (la placa) como hoy; con voz_pc usa VozPC; la mano deletrea igual.

Uso: py -3.11 fusion/pruebas/prueba_voz_pc_falsa.py
"""
import json
import os
import sys
import tempfile
import threading
import time
import types
import wave
from datetime import datetime

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
import hora  # noqa: E402
import mano_wifi  # noqa: E402
import voz_pc  # noqa: E402
from reconocer import Integrantes, interpretar  # noqa: E402
from voz import CARPETA_PLACA, Voz, leer_wav  # noqa: E402

fallas = []
TMP = tempfile.mkdtemp(prefix="prueba_voz_pc_")


def chequeo(nombre, ok, detalle=""):
    print("{}   {}{}".format("PASA " if ok else "FALLA", nombre, "  " + detalle if detalle else ""))
    if not ok:
        fallas.append(nombre)


ints = Integrantes()


class ManoFalsa:
    """Deletrea 'bien' al instante. Si alguien manda 'voz' a la placa, se anota (no deberia con --voz-pc)."""

    def __init__(self):
        self.cerrada, self.conectada = False, True
        self.deletreos, self.voces, self.resets = [], [], 0
        self.aviso_tiempos = ""
        self.version_falla = False

    def conectar(self):
        return True, ""

    def version(self):
        if self.version_falla:
            raise OSError("sin respuesta")
        return True, "voz-2"

    def deletrear(self, r, al_evento=None):
        self.deletreos.append(r.mostrar)
        return True, "ok"

    def hablar(self, nombres, espera=0):
        self.voces.append(nombres)
        return True, "voz_ok"

    def detener(self):
        pass

    def reset(self):
        self.resets += 1
        return True, "reset_ok"

    def cerrar(self):
        self.cerrada = True


class SonarFalso:
    """Anota lo que 'sonaria'. bloquear=True: espera a 'parar' (como un audio largo) hasta 3 s."""

    def __init__(self, bloquear=False):
        self.sonado = []
        self.bloquear = bloquear

    def __call__(self, pcm, parar=None):
        self.sonado.append(np.frombuffer(pcm.tobytes() if hasattr(pcm, "tobytes") else bytes(pcm), "<i2").copy())
        if self.bloquear and parar is not None:
            return not parar.wait(3)
        return True


def placa(base):
    return leer_wav(os.path.join(CARPETA_PLACA, base + ".wav"))


def nueva_voz(sonar, mano=None):
    return voz_pc.VozPC(mano or ManoFalsa(), ints, sonar=sonar, ruta_tiempos=os.path.join(TMP, "tiempos_voz.csv"))


print("1. VozPC: nombres por el PC con la misma regla")
mano = ManoFalsa()
s = SonarFalso()
v = nueva_voz(s, mano)
chequeo("comprobar_placa: siempre True y lo dice", v.comprobar_placa() == (True, "voz-2 · voz por el PC"))
mano.version_falla = True
chequeo("si la mano no responde la versión, la voz del PC sigue disponible", v.comprobar_placa() == (True, "voz por el PC"))
mano.version_falla = False

r = interpretar("Lina Maldonado", ints)
ok, mensaje = v.hablar(r)
chequeo("frase grabada (Lina Maldonado): suena SOLO lina_maldonado.wav de audios_placa",
        ok and len(s.sonado) == 1 and np.array_equal(s.sonado[0], placa("lina_maldonado")), mensaje)
r = interpretar("Lina Tatiana", ints)
s.sonado.clear()
ok, mensaje = v.hablar(r)
pausa = np.zeros(int(ints.pausa_ms / 1000 * 16000), np.int16)
chequeo("sin frase grabada (Lina Tatiana): lina + 250 ms + tatiana",
        ok and len(s.sonado) == 1 and np.array_equal(s.sonado[0], np.concatenate([placa("lina"), pausa, placa("tatiana")])),
        "pausa {} ms".format(ints.pausa_ms))
chequeo("nunca manda 'voz' a la placa", mano.voces == [])
chequeo("mensaje", mensaje == "Sonó (PC): Lina Tatiana", mensaje)

sin_audio = next((p for p in ("Paula", "Camila", "Enriquez") if ints.buscar_audio(p) is None), None)
if sin_audio:
    s.sonado.clear()
    ok, mensaje = v.hablar(interpretar(sin_audio, ints))
    chequeo("sin grabación ({}): 'Falta audio' y no suena nada".format(sin_audio),
            not ok and mensaje.startswith("Falta audio") and not s.sonado, mensaje)
else:
    print("  (todas las grabaciones existen: se salta 'Falta audio')")

with open(os.path.join(TMP, "tiempos_voz.csv"), encoding="utf-8-sig") as f:
    texto = f.read()
chequeo("tiempos_voz.csv: filas marcadas 'pc:' (en una carpeta temporal)", "pc: lina_maldonado" in texto
        and "pc: lina tatiana" in texto)

s = SonarFalso(bloquear=True)
v = nueva_voz(s)
resultado = {}
hilo = threading.Thread(target=lambda: resultado.update(r=v.hablar(interpretar("Lina Tatiana", ints))))
t0 = time.monotonic()
hilo.start()
time.sleep(0.2)
v.detener()
hilo.join(3)
chequeo("detener corta la voz del PC enseguida", resultado.get("r") == (False, "Voz detenida")
        and time.monotonic() - t0 < 1.5, str(resultado.get("r")))

print("\n2. voz_pc.sonar() con un winsound falso (no suena nada)")
llamadas = []
falso = types.SimpleNamespace(SND_FILENAME=0x20000, SND_ASYNC=0x1, SND_NODEFAULT=0x2, SND_PURGE=0x40)


def play(ruta, flags):
    info = None
    if ruta:
        with wave.open(ruta, "rb") as w:
            info = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
    llamadas.append((ruta, flags, info))


falso.PlaySound = play
sys.modules["winsound"] = falso
pcm = np.full(1600, 1000, np.int16)                 # 0,1 s
voz_pc.PASO = 0.01
ok = voz_pc.sonar(pcm)
ruta, flags, info = llamadas[0]
chequeo("WAV temporal de 16 kHz, mono, 16 bits con todo el audio", info == (1, 2, 16000, 1600), str(info))
chequeo("asíncrono (se puede cortar)", flags & falso.SND_ASYNC and flags & falso.SND_FILENAME)
chequeo("espera a que termine y borra el temporal", ok is True and not os.path.exists(ruta))
chequeo("el temporal no va dentro del proyecto", not os.path.abspath(ruta).startswith(os.path.dirname(FUSION)))
llamadas.clear()
parar = threading.Event()
threading.Timer(0.05, parar.set).start()
t0 = time.monotonic()
ok = voz_pc.sonar(np.zeros(16000 * 5, np.int16), parar)
chequeo("con 'parar': corta (PlaySound None + PURGE) sin esperar los 5 s",
        ok is False and llamadas[-1][0] is None and llamadas[-1][1] == falso.SND_PURGE and time.monotonic() - t0 < 1)

print("\n3. hora.decir(en_pc=True): los mismos WAV, sin WiFi")
cfg = json.load(open(hora.RUTA_CONFIG, encoding="utf-8"))
cfg["doby"] = os.path.join(TMP, "doby")
cfg["fechas"] = os.path.join(TMP, "fechas", "{persona}")
json.dump(cfg, open(os.path.join(TMP, "hora.json"), "w", encoding="utf-8"))
config = hora.Config(os.path.join(TMP, "hora.json"))
ahora = datetime(2026, 11, 12, 15, 35)


def wav(ruta, n, valor):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    datos = np.full(n, valor, np.int16)
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(datos.tobytes())
    return datos


p_hora = wav(os.path.join(cfg["doby"], "voz_cache_f5", "lina", "hora",
                          "hora_1535_{}.wav".format(hora.huella(hora.texto_hora(15, 35)))), 800, 7)
p_fecha = wav(os.path.join(config.carpeta_fechas("lina"), hora.nombre_fecha(ahora.date())), 600, -3)
conectar_real = mano_wifi.conectar


def sin_wifi(*a, **k):
    raise mano_wifi.ErrorWifi("Sin WiFi en la mano: prueba")


mano_wifi.conectar = sin_wifi
hora.PAUSA_PC = 0.0
s = SonarFalso()
r = hora.decir(config, "lina", ahora, ruta_csv=os.path.join(TMP, "tiempos_hora.csv"), en_pc=True, sonar=s)
chequeo("suena la fecha y luego la hora, por el PC", r["resultado"] == "ok" and len(s.sonado) == 2
        and np.array_equal(s.sonado[0], p_fecha) and np.array_equal(s.sonado[1], p_hora), r["mensaje"])
chequeo("no usa el WiFi (como = 'pc')", r.get("como") == "pc")
r = hora.decir(config, "lina", ahora, ruta_csv=os.path.join(TMP, "tiempos_hora.csv"))
chequeo("sin en_pc sigue yendo por WiFi, igual que antes", r["resultado"] == "sin_wifi", r["mensaje"])
mano_wifi.conectar = conectar_real

print("\n4. dibujar_fusion: ControlMano con y sin --voz-pc")


def conectar_control(**kw):
    c = df.ControlMano(ints, crear_mano=ManoFalsa, **kw)
    c._conectar()
    return c


c = conectar_control()
chequeo("sin --voz-pc: la voz es la de la placa (Voz), como hoy",
        type(c.voz) is Voz and c.estado == "conectada" and c.texto_estado()[0] == "Mano: conectada (voz-2)",
        c.texto_estado()[0])
c = conectar_control(voz_pc=True)
chequeo("con --voz-pc: VozPC y la barra lo dice", isinstance(c.voz, voz_pc.VozPC)
        and "voz por el PC" in c.texto_estado()[0], c.texto_estado()[0])
s = SonarFalso()
c.voz.sonar = s
c.voz.ruta_tiempos = os.path.join(TMP, "tiempos_voz.csv")
c.deletrear_y_hablar(interpretar("Lina Maldonado", ints))
fin = time.monotonic() + 5
while c.ocupada and time.monotonic() < fin:
    time.sleep(0.01)
chequeo("la mano deletrea igual y la voz suena en el PC", c.final == (True, "Sonó (PC): Lina Maldonado")
        and c.mano.deletreos == ["Lina Maldonado"] and c.mano.voces == [] and len(s.sonado) == 1, str(c.final))

s = SonarFalso(bloquear=True)
c.voz.sonar = s
c.deletrear_y_hablar(interpretar("Lina Tatiana", ints))
time.sleep(0.2)
c.detener()
fin = time.monotonic() + 3
while (c.ocupada or c.deteniendo) and time.monotonic() < fin:
    time.sleep(0.01)
chequeo("Esc (detener) corta la voz del PC y abre la mano", c.final in ((False, df.MSG_DETENIDO),
                                                                       (False, "Voz detenida"))
        and c.mano.resets == 1 and not c.ocupada, str(c.final))

llamadas = []
decir_real = hora.decir
hora.decir = lambda config, persona, **kw: llamadas.append((persona, kw)) or {"resultado": "ok", "mensaje": "ok"}
try:
    for kw in ({}, {"voz_pc": True}):
        c = df.ControlMano(ints, crear_mano=ManoFalsa, crear_voz=lambda m: None, **kw)
        c.decir_hora("lina")
        fin = time.monotonic() + 3
        while c.hora_en_curso and time.monotonic() < fin:
            time.sleep(0.01)
finally:
    hora.decir = decir_real
chequeo("botón Hora: sin --voz-pc por WiFi (como hoy); con --voz-pc en el PC",
        llamadas == [("lina", {}), ("lina", {"en_pc": True})], str(llamadas))

fuente = open(os.path.join(FUSION, "dibujar_fusion.py"), encoding="utf-8").read()
chequeo("dibujar_fusion.py tiene la opción --voz-pc y se la pasa a ControlMano",
        'add_argument("--voz-pc"' in fuente and "ControlMano(integrantes, voz_pc=args.voz_pc)" in fuente)

print("\n{} fallas".format(len(fallas)))
sys.exit(1 if fallas else 0)
