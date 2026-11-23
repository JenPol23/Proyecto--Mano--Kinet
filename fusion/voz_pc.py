"""
voz_pc.py  -  CORRE EN EL PC (py -3.11). PLAN B DE AUDIO: dibujar_fusion.py --voz-pc
Las voces suenan por los PARLANTES DEL PC en vez del MAX98357 de la placa. La mano sigue deletreando por BLE
igual; solo cambia por donde sale el sonido.

- Nombres: VozPC hereda de voz.Voz y usa la MISMA regla (Voz.elegir/preparar): la frase grabada si existe; si no,
  las palabras sueltas con la pausa de integrantes.json (250 ms). Los audios son los mismos WAV de
  fusion/audios_placa/ (grabaciones originales; preparar() los deja al dia igual que para la placa).
- Fecha y hora: hora.decir(..., en_pc=True) usa los mismos WAV (Doby / voces_clonadas) y sonar() de aqui, sin WiFi.
- sonar(): winsound (biblioteca estandar de Windows), asincrono desde un WAV temporal del sistema, para poder
  cortarlo con Esc (detener). Nada se escribe en el proyecto salvo la fila de tiempos_voz.csv (archivos "pc:...").
"""

import os
import tempfile
import threading
import time
import wave
from datetime import datetime

import numpy as np

import config_fusion as config
from voz import Voz, guardar_tiempos, leer_wav, nombre_placa

PASO = 0.05                 # s entre revisiones de "detener" mientras suena
COLA_PC = 0.15              # s de margen al final (el reproductor de Windows tarda un poco en empezar)


def sonar(pcm, parar=None, tasa=config.TASA):
    """Hace sonar pcm (int16 mono, bytes o array) por los parlantes del PC y espera a que termine.
    'parar': threading.Event; si se activa, corta el sonido enseguida. Devuelve False si se corto."""
    import winsound
    datos = pcm.tobytes() if hasattr(pcm, "tobytes") else bytes(pcm)
    fd, ruta = tempfile.mkstemp(prefix="voz_pc_", suffix=".wav")
    os.close(fd)
    try:
        with wave.open(ruta, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(tasa)
            w.writeframes(datos)
        winsound.PlaySound(ruta, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        fin = time.monotonic() + len(datos) / (2 * tasa) + COLA_PC
        while time.monotonic() < fin:
            if parar is not None and parar.is_set():
                winsound.PlaySound(None, winsound.SND_PURGE)
                return False
            time.sleep(PASO)
        return True
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


class VozPC(Voz):
    """Como Voz, pero suena en el PC. hablar() devuelve (ok, mensaje): nunca lanza."""

    def __init__(self, mano, integrantes=None, sonar=sonar, **kw):
        super().__init__(mano, integrantes, **kw)
        self.sonar = sonar
        self.parar = threading.Event()

    def comprobar_placa(self):
        """La voz no depende de la placa: siempre True. Muestra la version de la mano si responde."""
        try:
            ok, version = self.mano.version()
        except Exception:
            ok, version = False, ""
        return True, "{} · voz por el PC".format(version) if ok else "voz por el PC"

    def detener(self):
        self.parar.set()

    def hablar(self, resultado):
        self.parar.clear()
        fila = {"id_prueba": datetime.now().isoformat(sep=" ", timespec="seconds"),
                "fecha_hora": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                "texto": resultado.leido, "palabras": resultado.mostrar, "archivos": "",
                "seg_audio": "", "seg_hasta_ok": ""}
        try:
            listos, mensaje = self.preparar(resultado)
            if listos is None:
                ok = False
            else:
                pausa = np.zeros(int(round(self.integrantes.pausa_ms / 1000 * config.TASA)), dtype=np.int16)
                partes = []
                for k, (base, _, _) in enumerate(listos):
                    if k:
                        partes.append(pausa)
                    partes.append(leer_wav(os.path.join(self.carpeta_placa, nombre_placa(base) + ".wav")))
                pcm = np.concatenate(partes).astype("<i2")
                fila["archivos"] = "pc: " + " ".join(nombre_placa(b) for b, _, _ in listos)
                fila["seg_audio"] = "{:.3f}".format(len(pcm) / config.TASA)
                inicio = time.perf_counter()
                ok = self.sonar(pcm, self.parar) is not False
                fila["seg_hasta_ok"] = "{:.3f}".format(time.perf_counter() - inicio)
                mensaje = "Sonó (PC): " + resultado.mostrar if ok else "Voz detenida"
        except Exception as e:                      # el programa no se cae por la voz
            ok, mensaje = False, "Error en la voz del PC ({})".format(type(e).__name__)
        fila["resultado"] = "ok" if ok else "error: " + mensaje
        self.aviso_tiempos = guardar_tiempos(fila, self.ruta_tiempos)
        return ok, mensaje
