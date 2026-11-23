"""
hora.py  -  CORRE EN EL PC
"¿Que hora es?": la hora del reloj del PC en America/Bogota, como se dice en Colombia (12 horas, minutos
exactos): "Son las nueve y veintitres de la noche.", "Es la una en punto de la tarde.".
Cada hora del dia (1440) es una frase entera pregenerada (gTTS en voz_cache/hora/, F5 en
<CARPETA_VOZ_CLONADA>/<persona>/hora/; entrenamiento/generar_hora.py). Doby nunca genera voz en vivo.

Momento del dia: madrugada 1:00-5:59, manana 6:00-11:59, mediodia 12:00-12:59, tarde 13:00-18:59,
noche 19:00-0:59. Minuto 1: "y uno".
Archivo: <carpeta>/hora/hora_HHMM_<md5 del texto>.wav (si cambia el texto, cambia el archivo).
"""

import hashlib
import os
import wave
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

import config
import tts

ZONA = ZoneInfo("America/Bogota")
SUBCARPETA = "hora"
HORAS = ["doce", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once"]
UNIDADES = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]
ESPECIALES = {10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince", 16: "dieciséis",
              17: "diecisiete", 18: "dieciocho", 19: "diecinueve", 20: "veinte", 21: "veintiuno", 22: "veintidós",
              23: "veintitrés", 24: "veinticuatro", 25: "veinticinco", 26: "veintiséis", 27: "veintisiete",
              28: "veintiocho", 29: "veintinueve"}
DECENAS = {3: "treinta", 4: "cuarenta", 5: "cincuenta"}


def ahora():
    """Hora actual en Colombia (las pruebas reemplazan esta funcion por un reloj simulado)."""
    return datetime.now(ZONA)


def numero(n):
    """1..59 en palabras: 23 -> 'veintitrés', 45 -> 'cuarenta y cinco'."""
    if n < 10:
        return UNIDADES[n]
    if n in ESPECIALES:
        return ESPECIALES[n]
    return DECENAS[n // 10] + ("" if n % 10 == 0 else " y " + UNIDADES[n % 10])


def momento(h):
    if 1 <= h <= 5:
        return "de la madrugada"
    if 6 <= h <= 11:
        return "de la mañana"
    if h == 12:
        return "del mediodía"
    if 13 <= h <= 18:
        return "de la tarde"
    return "de la noche"                       # 19-23 y 0 (00:01 -> "las doce y uno de la noche")


def texto(h, m):
    """texto(21, 23) -> 'Son las nueve y veintitrés de la noche.'"""
    inicio = "Es la una" if h % 12 == 1 else "Son las " + HORAS[h % 12]
    minutos = "en punto" if m == 0 else "y " + numero(m)
    return "{} {} {}.".format(inicio, minutos, momento(h))


def clave(h, m):
    return "hora_{:02d}{:02d}".format(h, m)


def todas():
    """Las 1440 (hora, minuto) del dia."""
    return [(h, m) for h in range(24) for m in range(60)]


def nombre_archivo(h, m):
    return "{}_{}.wav".format(clave(h, m), hashlib.md5(texto(h, m).encode("utf-8")).hexdigest()[:8])


def ruta_normal(h, m):
    """voz_cache/hora/hora_HHMM_<md5>.wav (voz normal, gTTS)."""
    return os.path.join(tts.CARPETA_CACHE, SUBCARPETA, nombre_archivo(h, m))


def leer(ruta):
    """int16 mono 16 kHz, o None si falta, no abre o tiene otro formato (sin generar nada)."""
    try:
        with wave.open(ruta, "rb") as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, config.TASA):
                return None
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    except (OSError, EOFError, wave.Error):
        return None
    return pcm if len(pcm) > config.TASA * (tts.SILENCIO_FINAL + 0.3) and np.any(pcm) else None
