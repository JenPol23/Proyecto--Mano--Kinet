"""
tts.py  -  CORRE EN EL PC
Voz de Doby: genera cada frase con gTTS UNA sola vez, la procesa para el
parlante de la ESP32 y la guarda en voz_cache/. Despues funciona sin internet.

Procesamiento (igual que pruebas/pc_prueba_voz.py):
  MP3 de gTTS -> pygame a su frecuencia nativa (24 kHz) -> resample_poly a 16 kHz
  -> pasa-altos Butterworth orden 2 a 200 Hz -> normalizar al pico x VOLUMEN
  -> rampas de 10 ms -> 0.3 s de silencio al final.

Ejecutar con:  py pc/tts.py   (pregenera todas las frases)
"""

import hashlib
import os
import wave
from itertools import combinations
from math import gcd

os.environ["SDL_AUDIODRIVER"] = "dummy"          # pygame sin usar los parlantes del PC
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import numpy as np
from scipy.signal import butter, resample_poly, sosfilt

import config

CARPETA_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "voz_cache")
TASA_GTTS = 24000       # frecuencia original de gTTS
CORTE_GRAVES = 200      # Hz: por debajo de esto el parlante solo distorsiona
SILENCIO_FINAL = 0.3    # segundos


# ---------------- Frases de Doby ----------------
NOMBRES = {"cautin": "cautín"}      # como se dice cada aparato (la clave de config.APARATOS va sin tilde)
FEMENINOS = {"plancha"}             # "la plancha", "encendida"


def _el(aparato):
    """'el bombillo', 'el cautín', 'la plancha'."""
    return ("la " if aparato in FEMENINOS else "el ") + NOMBRES.get(aparato, aparato)


def _o(aparato):
    """Terminacion que concuerda con el aparato: encendid-o / encendid-a."""
    return "a" if aparato in FEMENINOS else "o"


def _unir(partes):
    """['el bombillo', 'la plancha'] -> 'el bombillo y la plancha'."""
    if len(partes) == 1:
        return partes[0]
    return ", ".join(partes[:-1]) + " y " + partes[-1]


def clave_estado(encendidos):
    """Clave de la frase de estado para una lista de aparatos encendidos."""
    orden = [a for a in config.APARATOS if a in encendidos]
    if not orden:
        return "todo_apagado"
    return "estado_" + "_".join(orden)


def _crear_frases():
    frases = {
        "saludo_1": "Hola amo, ¿qué vamos a hacer hoy?",
        "saludo_2": "¿Qué quieres que haga por ti?",
    }
    for aparato in config.APARATOS:        # con su genero: "el cautín", "la plancha"
        el, o = _el(aparato), _o(aparato)
        frases["encendi_" + aparato] = "Listo, encendí {}.".format(el)
        frases["ya_encendido_" + aparato] = "{} ya estaba encendid{}.".format(el.capitalize(), o)
        frases["apague_" + aparato] = "Listo, apagué {}.".format(el)
        frases["ya_apagado_" + aparato] = "{} ya estaba apagad{}.".format(el.capitalize(), o)
    for aparato in config.CALIENTES:       # apagado automatico (config.APAGADO_AUTOMATICO)
        frases["auto_apagado_" + aparato] = "Por seguridad, apagué {}.".format(_el(aparato))

    frases["apagar_todo"] = "Listo, apagué todo. Me voy a descansar."
    frases["descansar"] = "Está bien, me voy a descansar. Dime Hola Doby cuando me necesites."
    frases["agradecer"] = "Con gusto."
    frases["no_entendi"] = "No te entendí, ¿me lo repites?"
    frases["cual_encender"] = "¿Cuál quieres que encienda?"
    frases["cual_apagar"] = "¿Cuál quieres que apague?"
    frases["no_reconozco"] = "No reconozco tu voz."
    frases["repite_hola"] = "No te reconocí bien, llámame otra vez."   # sin "Hola Doby": su eco no es un llamado

    # Estado: "Todo está apagado." y las combinaciones de aparatos encendidos (15 con 4 aparatos)
    frases["todo_apagado"] = "Todo está apagado."
    aparatos = list(config.APARATOS)
    for cantidad in range(1, len(aparatos) + 1):
        for grupo in combinations(aparatos, cantidad):
            lista = _unir([_el(a) for a in grupo])
            if cantidad == 1:
                texto = "Está encendid{} {}.".format(_o(grupo[0]), lista)
            else:                          # femenino plural solo si todos son femeninos
                texto = "Están encendid{}s {}.".format("a" if all(a in FEMENINOS for a in grupo) else "o", lista)
            frases[clave_estado(grupo)] = texto
    return frases


FRASES = _crear_frases()


# ---------------- Generacion y procesamiento ----------------
def _ruta(clave):
    """voz_cache/<clave>_<md5 del texto>.wav: si cambia el texto, cambia el archivo."""
    huella = hashlib.md5(FRASES[clave].encode("utf-8")).hexdigest()[:8]
    return os.path.join(CARPETA_CACHE, "{}_{}.wav".format(clave, huella))


def _generar_voz(texto, ruta_mp3):
    """Genera la voz con gTTS y la entrega a 16 kHz con buena calidad."""
    from gtts import gTTS
    import pygame

    gTTS(texto, lang="es", tld="com.mx").save(ruta_mp3)

    # Decodificar el MP3 en su frecuencia original (sin que pygame la cambie)
    pygame.mixer.init(frequency=TASA_GTTS, size=-16, channels=1)
    tasa_real = pygame.mixer.get_init()[0]
    muestras = pygame.sndarray.array(pygame.mixer.Sound(ruta_mp3)).astype(np.float32)
    pygame.mixer.quit()

    if muestras.ndim > 1:
        muestras = muestras.mean(axis=1)

    # Remuestreo de calidad a 16 kHz (con filtro antialiasing)
    g = gcd(config.TASA, tasa_real)
    return resample_poly(muestras, config.TASA // g, tasa_real // g)


def _pulir(audio):
    """Quita graves, normaliza el volumen, suaviza inicio y final y agrega silencio."""
    audio = audio.astype(np.float32)
    audio -= audio.mean()

    filtro = butter(2, CORTE_GRAVES, btype="highpass", fs=config.TASA, output="sos")
    audio = sosfilt(filtro, audio)

    pico = np.max(np.abs(audio))
    if pico > 0:
        audio = audio / pico * config.VOLUMEN * 32767

    n = int(0.01 * config.TASA)                  # 10 ms de rampa para evitar "clics"
    rampa = np.linspace(0, 1, n)
    audio[:n] *= rampa
    audio[-n:] *= rampa[::-1]

    silencio = np.zeros(int(SILENCIO_FINAL * config.TASA), dtype=np.float32)
    return np.concatenate([audio, silencio]).astype(np.int16)


def _generar(clave):
    os.makedirs(CARPETA_CACHE, exist_ok=True)
    ruta_mp3 = os.path.join(CARPETA_CACHE, "_temporal.mp3")
    try:
        audio = _pulir(_generar_voz(FRASES[clave], ruta_mp3))
    finally:
        if os.path.exists(ruta_mp3):
            os.remove(ruta_mp3)
    with wave.open(_ruta(clave), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(config.TASA)
        wav.writeframes(audio.astype("<i2").tobytes())


# ---------------- Uso desde Doby ----------------
def pregenerar():
    """Genera solo las frases que faltan en voz_cache/ (necesita internet la primera vez)."""
    for clave, texto in FRASES.items():
        if os.path.exists(_ruta(clave)):
            origen = "cache"
        else:
            _generar(clave)
            origen = "GENERADA"
        segundos = len(obtener(clave)) / config.TASA
        print("  [{:8}] {:28} {:4.1f} s  {}".format(origen, clave, segundos, texto))


def obtener(clave):
    """Devuelve la frase como array int16 a 16 kHz (la genera si no esta en cache)."""
    ruta = _ruta(clave)
    if not os.path.exists(ruta):
        _generar(clave)
    with wave.open(ruta, "rb") as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")


if __name__ == "__main__":
    print("Pregenerando {} frases de Doby en {}".format(len(FRASES), os.path.abspath(CARPETA_CACHE)))
    pregenerar()
    print("Listo.")
