"""
Prueba de fusion/consola_mano.py con un bleak FALSO que imita atender_orden() del firmware (via BLE).
No necesita la mano ni Bluetooth. Sus archivos temporales van a una carpeta temporal del sistema.

Uso (desde la carpeta del proyecto):  py -3.11 fusion/pruebas/prueba_mano_falsa.py
"""
import asyncio, os, sys, tempfile, types

FUSION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FUSION)
sys.stdout.reconfigure(encoding="utf-8")
TEMP = tempfile.mkdtemp(prefix="prueba_mano_")

ACCIONES = set("abcdefiklmnopqrtuvwxy")
ESTADO = {"modo": "normal", "ordenes": []}


class Cliente:
    def __init__(self, dispositivo, disconnected_callback=None):
        self.cb_corte = disconnected_callback
        self.notif = None
        self.buf = b""
        self.auth = False
        self.n = 0

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
            ok = cmd == "auth " + "x" * 32 and ESTADO["modo"] != "token_malo"
            self.auth = ok
            await self._resp("ok:auth" if ok else "error:auth")
            return
        ESTADO["ordenes"].append(cmd)
        self.n += 1
        if ESTADO["modo"] == "corte" and self.n == 4:
            self.cb_corte(self)
            return
        cmd = cmd.strip().lower()
        if cmd in ("reset", "1"):
            await self._resp("reset_ok")
        elif cmd in ACCIONES:
            await self._resp("gesto_" + cmd + "_ok")
        elif len(cmd) > 1:
            for l in cmd:
                if l in ACCIONES:
                    await self._resp("gesto_" + l + "_ok")
                    await self._resp("letra_actual:" + l)
                else:
                    await self._resp("letra_" + l + "_no_disponible")
            await self._resp("deletreo_completo")
        else:
            await self._resp("comando_no_reconocido")


class Escaner:
    @staticmethod
    async def find_device_by_name(nombre, timeout=None):
        return None if ESTADO["modo"] == "sin_placa" else object()


sys.modules["bleak"] = types.SimpleNamespace(BleakScanner=Escaner, BleakClient=Cliente)

import consola_mano as cm  # noqa: E402
from reconocer import Integrantes, interpretar  # noqa: E402

cm.PAUSA_LETRA_SUELTA = cm.PAUSA_MOVIMIENTO = cm.PAUSA_ESPACIO = 0.0
cfg = os.path.join(TEMP, "config_ble_falso.py")             # token falso: nunca se usa config_ble.py real
with open(cfg, "w", encoding="utf-8") as f:
    f.write('NOMBRE = "Mano-LSC"\nTOKEN = "' + "x" * 32 + '"\n')

ints = Integrantes()
fallas = 0


def caso(nombre, texto, modo, ok_esp, ordenes_esp=None, msg_esp=None):
    global fallas
    ESTADO.update(modo=modo, ordenes=[])
    mano = cm.Mano(cfg, ruta_tiempos=os.path.join(TEMP, "tiempos_falso.csv"))
    eventos = []
    ok, msg = mano.conectar()
    if ok:
        ok, msg = mano.deletrear(interpretar(texto, ints), lambda t, d: eventos.append((t, d)))
    mano.cerrar()
    bien = ok == ok_esp and (ordenes_esp is None or ESTADO["ordenes"] == ordenes_esp) and (msg_esp is None or msg == msg_esp)
    fallas += not bien
    print("{}  {:22} ok={} msg={!r}".format("PASA " if bien else "FALLA", nombre, ok, msg))
    print("       ordenes: {}".format(ESTADO["ordenes"]))
    if not bien and ordenes_esp is not None:
        print("       esperado: {}".format(ordenes_esp))


caso("Raigozo", "Raigozo", "normal", True,
     ["reset", "rai", "reset", "o", "reset", "reset", "o", "reset", "reset"])
caso("Harry Raigozo", "Harry Raigozo", "normal", True,
     ["reset", "reset", "arry", "reset", "rai", "reset", "o", "reset", "reset", "o", "reset", "reset"])
caso("Lina", "Lina", "normal", True, ["reset", "lina", "reset"])
caso("token malo", "Lina", "token_malo", False, msg_esp=cm.MSG_TOKEN)
caso("sin placa", "Lina", "sin_placa", False, msg_esp=cm.MSG_NO_RESPONDE)
caso("corte a mitad", "Jean Paul Miranda", "corte", False, msg_esp=cm.MSG_CORTE)
print("\n{} fallas".format(fallas))
sys.exit(1 if fallas else 0)
