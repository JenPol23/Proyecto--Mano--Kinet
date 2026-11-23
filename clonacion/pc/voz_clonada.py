"""
voz_clonada.py  -  CORRE EN EL PC
Frases de Doby con la voz de cada integrante (F5-TTS), generadas por entrenamiento/generar_voces_f5.py
en <config.CARPETA_VOZ_CLONADA>/<persona>/ (voz_cache_f5/; voz_cache_clonada/ es la de XTTS, descartada).

- Mismas claves que tts.FRASES + 'generica' ("Listo.", solo como respaldo). El texto clonado es el mismo,
  salvo TEXTOS_CLONADOS: NINGUNA frase clonada contiene "Doby" (su eco, con Doby dormido, podria parecer
  un llamado).
- Archivo: <carpeta>/<persona>/<clave>_<md5 del texto>.wav (16 kHz int16 mono, mismo procesado que
  tts._pulir): si cambia el texto, cambia el archivo. Otras versiones aprobadas: _alternativas/.
- obtener_seguro(): voz de UNA persona, nunca otra voz. Si falta el audio: otra version aprobada suya,
  su frase generica o silencio, y queda registrado en logs/voz_<fecha>.csv.
- normal(): la voz de siempre (gTTS), SOLO de los WAV que ya existen en voz_cache/ (usa tts._ruta);
  nunca genera nada ni llama a gTTS.
- cobertura(): comprueba que no falte ningun audio (lo usan Doby al arrancar y pruebas/verificar_cobertura.py).
- Hora ("¿que hora es?", pc/hora.py): 1440 frases enteras por voz en <carpeta>/<persona>/hora/ y voz_cache/hora/.
  obtener_hora(): si a la persona le falta la frase, la hora COMPLETA con la voz normal (decidido por el usuario
  solo para la hora: nunca se mezclan voces) y queda en el log. En cobertura(): falta en un integrante -> AVISO;
  falta en la voz normal -> FALLA (sonaria en silencio).
"""

import csv
import glob
import hashlib
import json
import os
import wave
from datetime import datetime

import numpy as np

import config
import hora
import tts
from texto import normalizar

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA_LOGS = os.path.join(RAIZ, "logs")
RUTA_HABLANTES = os.path.join(RAIZ, "modelos", "hablantes", "hablantes.json")
SEG_MINIMO = 0.3                     # un audio mas corto (sin el silencio final) se considera danado

# Frases cuyo texto cambia en la version clonada (quitar "Hola Doby")
TEXTOS_CLONADOS = {
    "descansar": "Está bien, me voy a descansar. Llámame cuando me necesites.",
}
GENERICA = "generica"
TEXTO_GENERICA = "Listo."            # respaldo corto si en ejecucion falla un audio de una persona


def claves():
    """Todas las frases clonadas: las de tts.FRASES y la generica."""
    return list(tts.FRASES) + [GENERICA]


def texto(clave):
    if clave == GENERICA:
        return TEXTO_GENERICA
    return TEXTOS_CLONADOS.get(clave, tts.FRASES[clave])


def _comprobar_textos():
    malas = [c for c in claves() if "doby" in normalizar(texto(c)).split()]
    if malas:
        raise ValueError("frases clonadas con 'Doby' en el texto: {}".format(", ".join(malas)))


_comprobar_textos()


def carpeta():
    """Se lee de config cada vez (las pruebas la cambian)."""
    return os.path.join(RAIZ, config.CARPETA_VOZ_CLONADA)


def _base(clave):
    return "{}_{}".format(clave, hashlib.md5(texto(clave).encode("utf-8")).hexdigest()[:8])


def ruta(persona, clave):
    return os.path.join(carpeta(), persona, _base(clave) + ".wav")


def alternativas(persona, clave):
    return sorted(glob.glob(os.path.join(carpeta(), persona, "_alternativas", _base(clave) + "_v*.wav")))


def leer(r):
    """int16 mono 16 kHz, o None si falta, no abre, tiene otro formato o es demasiado corto/silencio."""
    try:
        with wave.open(r, "rb") as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, config.TASA):
                return None
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    except (OSError, EOFError, wave.Error):
        return None
    if len(pcm) < (SEG_MINIMO + tts.SILENCIO_FINAL) * config.TASA or not np.any(pcm):
        return None
    return pcm


def obtener(persona, clave):
    """Version principal de la frase con la voz de 'persona', o None si no existe."""
    if not persona:
        return None
    return leer(ruta(persona, clave))


def obtener_seguro(persona, clave):
    """
    (pcm, texto, origen) SIEMPRE con la voz de 'persona'. origen: 'principal', 'alternativa',
    'generica' o 'silencio' (pcm vacio). Todo lo que no sea 'principal' queda en el log como error.
    """
    pcm = obtener(persona, clave)
    if pcm is not None:
        return pcm, texto(clave), "principal"
    for r in alternativas(persona, clave):
        pcm = leer(r)
        if pcm is not None:
            registrar(persona, clave, "falta la principal", "alternativa " + os.path.basename(r))
            return pcm, texto(clave), "alternativa"
    pcm = obtener(persona, GENERICA)
    if pcm is not None and clave != GENERICA:
        registrar(persona, clave, "falta la principal y no hay alternativas", "generica")
        return pcm, texto(GENERICA), "generica"
    registrar(persona, clave, "falta la principal, las alternativas y la generica", "silencio")
    return np.zeros(0, dtype=np.int16), "", "silencio"


def normal(clave):
    """(pcm, texto) de la voz de siempre, SOLO si su WAV ya existe en voz_cache/ (nunca genera)."""
    pcm = leer(tts._ruta(clave))
    if pcm is None:
        registrar("", clave, "falta en voz_cache/ (no se genera: todo local)", "silencio")
        return np.zeros(0, dtype=np.int16), ""
    return pcm, tts.FRASES[clave]


def ruta_hora(persona, h, m):
    return os.path.join(carpeta(), persona, hora.SUBCARPETA, hora.nombre_archivo(h, m))


def obtener_hora(persona, h, m):
    """
    (pcm, texto, voz) de la hora COMPLETA. Con persona: su frase; si le falta o esta danada, la hora completa
    con la voz normal (nunca mezcla voces) y queda en el log. Si tampoco esta la de la voz normal: silencio
    y log (nunca se genera nada).
    """
    texto = hora.texto(h, m)
    if persona:
        pcm = hora.leer(ruta_hora(persona, h, m))
        if pcm is not None:
            return pcm, texto, persona
        registrar(persona, hora.clave(h, m), "falta la frase de la hora", "la hora completa con la voz normal")
    pcm = hora.leer(hora.ruta_normal(h, m))
    if pcm is None:
        registrar("", hora.clave(h, m), "falta en voz_cache/hora/ (no se genera: todo local)", "silencio")
        return np.zeros(0, dtype=np.int16), "", None
    return pcm, texto, None


def _hay_hora(ruta):
    """Comprobacion rapida (1440 archivos por voz): existe y no es demasiado corto."""
    try:
        return os.path.getsize(ruta) > 44 + int(2 * config.TASA * (tts.SILENCIO_FINAL + 0.3))
    except OSError:
        return False


def cobertura_hora(nombres):
    """(lineas, faltan_normal). Un integrante sin alguna frase: AVISO (esa hora suena con la voz normal)."""
    todas = hora.todas()
    lineas = []
    for voz in list(nombres) + ["normal"]:
        malas = [hora.clave(h, m)[5:] for h, m in todas
                 if not _hay_hora(hora.ruta_normal(h, m) if voz == "normal" else ruta_hora(voz, h, m))]
        estado = "OK" if not malas else "{} {} (p. ej. {}){}".format(
            "FALLA: faltan" if voz == "normal" else "AVISO: faltan", len(malas), ", ".join(malas[:5]),
            "" if voz == "normal" else ": esas horas suenan con la voz normal")
        lineas.append("  {:7} hora {:4}/{} {}".format(voz, len(todas) - len(malas), len(todas), estado))
        if voz == "normal":
            return lineas, len(malas)


def registrar(persona, clave, problema, sustituto):
    """Una fila por error en logs/voz_<fecha>.csv. Un error aqui no detiene a Doby."""
    print("  ERROR DE VOZ: {} / {}: {} -> {}".format(persona or "voz normal", clave, problema, sustituto))
    ruta_log = os.path.join(CARPETA_LOGS, "voz_{}.csv".format(datetime.now().strftime("%Y-%m-%d")))
    try:
        os.makedirs(CARPETA_LOGS, exist_ok=True)
        nuevo = not os.path.exists(ruta_log)
        with open(ruta_log, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["fecha", "persona", "frase", "problema", "sustituto"])
            w.writerow([datetime.now().isoformat(sep=" ", timespec="seconds"), persona, clave, problema, sustituto])
    except OSError as e:
        print("  AVISO: no se pudo escribir el registro de voz ({}).".format(e))


def personas():
    """Personas con carpeta de voz clonada (sin las de prueba, que empiezan con '_')."""
    c = carpeta()
    if not os.path.isdir(c):
        return []
    return sorted(d for d in os.listdir(c) if not d.startswith("_") and os.path.isdir(os.path.join(c, d)))


def integrantes():
    """Los integrantes enrolados (modelos/hablantes/hablantes.json): son los que pueden quedar verificados."""
    with open(RUTA_HABLANTES, encoding="utf-8") as f:
        return list(json.load(f)["nombres"])


def cobertura(nombres=None):
    """
    (ok, lineas). Falla si falta o esta danado CUALQUIER audio:
    - voz clonada: cada integrante x cada frase (lo que sigue en _revisar_de_oido/ cuenta como faltante),
      con el pico de tts._pulir (config.VOLUMEN);
    - voz normal (voz_cache/): todas las frases de tts.FRASES (suenan sin persona verificada);
    - VOZ_POR_DEFECTO debe ser None o un integrante.
    """
    nombres = integrantes() if nombres is None else nombres
    pico = round(config.VOLUMEN * 32767)
    lineas, faltan = [], 0
    for p in nombres:
        malas = []
        for c in claves():
            pcm = obtener(p, c)
            if pcm is None:
                revision = os.path.exists(os.path.join(carpeta(), p, "_revisar_de_oido", _base(c) + ".wav"))
                malas.append(c + (" (en _revisar_de_oido)" if revision else ""))
            elif abs(int(np.max(np.abs(pcm))) - pico) > 2:
                malas.append(c + " (pico {} != {})".format(int(np.max(np.abs(pcm))), pico))
        faltan += len(malas)
        lineas.append("  {:7} {:3}/{} {}".format(p, len(claves()) - len(malas), len(claves()),
                                                 "OK" if not malas else "FALTAN: " + ", ".join(malas)))
    malas = [c for c in tts.FRASES if leer(tts._ruta(c)) is None]
    faltan += len(malas)
    lineas.append("  {:7} {:3}/{} {}".format("normal", len(tts.FRASES) - len(malas), len(tts.FRASES),
                                             "OK (voz_cache/)" if not malas else "FALTAN en voz_cache/: " + ", ".join(malas)))
    if config.VOZ_POR_DEFECTO is not None and config.VOZ_POR_DEFECTO not in nombres:
        faltan += 1
        lineas.append("  VOZ_POR_DEFECTO = '{}' no es un integrante".format(config.VOZ_POR_DEFECTO))
    total = len(nombres) * len(claves()) + len(tts.FRASES)
    lineas.insert(0, "Cobertura de voz ({}): {:.1f} % ({} de {} audios)".format(
        os.path.relpath(carpeta(), RAIZ), 100 * (total - faltan) / total, total - faltan, total))
    lineas_hora, faltan_normal = cobertura_hora(nombres)
    lineas += ["Hora (\"¿que hora es?\", 1440 frases por voz):"] + lineas_hora
    return faltan == 0 and faltan_normal == 0, lineas
