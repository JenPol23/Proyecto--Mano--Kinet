"""
generar_hora.py  -  CORRE EN EL PC
Las 1440 frases de la hora ("Son las nueve y veintitres de la noche.") para "Doby, ¿que hora es?".
Los textos y las rutas salen de pc/hora.py (unica fuente). Se puede retomar: salta lo que ya existe.

Uso (desde la carpeta del proyecto):
  py entrenamiento/generar_hora.py --normal                         voz normal con gTTS (internet), 1 por segundo
  venv_f5\\Scripts\\python.exe entrenamiento/generar_hora.py --persona jenpol --muestra   60 horas variadas (F5)
  venv_f5\\Scripts\\python.exe entrenamiento/generar_hora.py --persona jenpol            las 1440 (F5)
  venv_f5\\Scripts\\python.exe entrenamiento/generar_hora.py --aprobar jenpol 2123       de _revisar_de_oido/ a la carpeta
  venv_f5\\Scripts\\python.exe entrenamiento/generar_hora.py --rechazar jenpol 2123      borrar y generar otra
  py entrenamiento/generar_hora.py --escuchar normal --al-azar 10   copia para escuchar por el parlante
  py entrenamiento/generar_hora.py --escuchar jenpol --muestra
  py entrenamiento/generar_hora.py --revalidar normal               transcribir de nuevo e informar (no mueve nada)
  (--hora-py RUTA: usar ese hora.py mientras pc/hora.py no exista)

- gTTS: igual que tts.py (tld com.mx, tts._pulir). Una peticion por segundo; si Google falla, 3 reintentos
  (5, 15 y 30 s) y se detiene (se retoma corriendo lo mismo). Whisper solo anota (no rechaza: gTTS da siempre
  el mismo audio).
- F5: el control de siempre: referencia principal (hasta 3 versiones) y luego los respaldos (3 intentos);
  se acepta la primera con similitud Whisper >= 0.95 sobre el audio final Y con la hora y los minutos exactos
  (numeros_ok; confusiones aceptadas: "doce" por "dos" y las 6 horas de HOMOFONOS); si ninguna, la mejor va
  a _revisar_de_oido/. La similitud traduce las cifras de Whisper ("9:23", "23") a palabras.
- Registro: voz_cache/hora/generacion.csv y <CARPETA_VOZ_CLONADA>/<persona>/hora/generacion.csv.

Dependencias (por importacion, sin modificarlas): pc/hora.py, pc/tts.py (_generar_voz, _pulir), pc/stt.py,
pc/texto.py, entrenamiento/generar_voces_f5.py (Motor, semilla, plan_intentos, cargar_referencias; solo F5).
"""

import argparse
import csv
import importlib.util
import os
import random
import re
import shutil
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "pc"))
sys.path.insert(0, os.path.join(RAIZ, "entrenamiento"))

import config                    # noqa: E402
import tts                       # noqa: E402
from texto import normalizar     # noqa: E402

SIMILITUD_MINIMA = 0.95
SEG_ENTRE_PETICIONES = 1.0
ESPERAS_GTTS = (5, 15, 30)
COLUMNAS = ["fecha", "voz", "clave", "texto", "intento", "referencia", "texto_whisper", "similitud",
            "duracion_s", "estado"]
ESCUCHAR = os.path.join(RAIZ, "voz_comparacion_f5", "_prueba_hora")
hora = None


def cargar_hora(ruta):
    global hora
    spec = importlib.util.spec_from_file_location("hora", ruta)
    hora = importlib.util.module_from_spec(spec)
    sys.modules["hora"] = hora
    spec.loader.exec_module(hora)


# ---------------- Que horas ----------------
FIJAS = [(0, 0), (0, 1), (0, 59), (1, 0), (1, 1), (1, 30), (5, 59), (6, 0), (7, 45), (11, 59), (12, 0), (12, 1),
         (12, 30), (12, 59), (13, 0), (13, 1), (13, 5), (18, 59), (19, 0), (21, 23), (23, 59), (2, 52), (3, 57),
         (4, 44), (8, 58), (10, 10), (15, 51), (16, 16), (20, 57), (22, 1)]


def muestra():
    """60 horas: las FIJAS (la una, las doce, en punto, 'y uno', minutos altos, bordes de los 5 momentos) y 30 al azar."""
    resto = [hm for hm in hora.todas() if hm not in FIJAS]
    return FIJAS + random.Random(7).sample(resto, 60 - len(FIJAS))


def hhmm(t):
    return int(t[:2]), int(t[2:])


# ---------------- Similitud (Whisper escribe cifras) ----------------
def sin_cifras(texto):
    t = re.sub(r"(\d{1,2})[:.](\d{2})", lambda x: x.group(1) + (" en punto" if x.group(2) == "00" else " y " + x.group(2)),
               texto)
    palabras = normalizar(t).split()
    salida = []
    for i, p in enumerate(palabras):
        if p.isdigit() and 0 < int(p) < 60:
            p = "una" if p == "1" and i > 0 and palabras[i - 1] == "la" else normalizar(hora.numero(int(p)))
        salida.append(p)
    return " ".join(salida)


# "las diez y seis" suena igual que "las dieciseis": Whisper escribe "Son las 16 de la mañana". Solo en esas 6 horas
# (decidido por el usuario) se lee como "diez y seis"; el resto de la frase debe coincidir como siempre.
HOMOFONOS = {(10, 6): ("dieciseis", "diez y seis"), (10, 7): ("diecisiete", "diez y siete"),
             (10, 9): ("diecinueve", "diez y nueve"), (22, 6): ("dieciseis", "diez y seis"),
             (22, 7): ("diecisiete", "diez y siete"), (22, 9): ("diecinueve", "diez y nueve")}


def canonico(oido, hm=None):
    """Lo que oyo Whisper sin cifras, con las confusiones aceptadas: en las 6 horas de HOMOFONOS 'dieciseis' se
    lee como 'diez y seis', y cuando la hora es 'las dos', 'las doce' se lee como 'las dos'."""
    oido = sin_cifras(oido)
    if hm in HOMOFONOS:
        oido = re.sub(r"\b{}\b".format(HOMOFONOS[hm][0]), HOMOFONOS[hm][1], oido)
    if hm is not None and hm[0] % 12 == 2:
        oido = re.sub(r"\blas doce\b", "las dos", oido)
    return oido


def similitud(oido, esperado, hm=None):
    return SequenceMatcher(None, canonico(oido, hm), sin_cifras(esperado)).ratio()


def numeros_ok(oido, h, m):
    """
    Control estricto (aprobado por el usuario): en lo que oyo Whisper deben estar EXACTAMENTE la hora y los
    minutos esperados ('las dos y siete', 'la una en punto'). Unicas confusiones aceptadas: 'doce' por 'dos'
    cuando la hora es 'las dos' ('las dos y...' suena casi igual a 'las doce...') y las 6 horas de HOMOFONOS.
    """
    esperado = sin_cifras(hora.texto(h, m)).split(" de ")[0].split(" del ")[0].split(" ", 1)[1]
    return re.search(r"\b{}\b".format(re.escape(esperado)), canonico(oido, (h, m))) is not None


def aceptable(oido, h, m):
    """(acepta, similitud): similitud >= SIMILITUD_MINIMA y la hora y los minutos exactos."""
    sim = similitud(oido, hora.texto(h, m), (h, m))
    return sim >= SIMILITUD_MINIMA and numeros_ok(oido, h, m), sim


# ---------------- Archivos ----------------
def guardar_wav(ruta, pcm):
    import wave
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.TASA)
        w.writeframes(pcm.astype("<i2").tobytes())


def anotar(ruta_csv, fila):
    os.makedirs(os.path.dirname(ruta_csv), exist_ok=True)
    nuevo = not os.path.exists(ruta_csv)
    with open(ruta_csv, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        w.writerow(dict(fila, fecha=datetime.now().isoformat(sep=" ", timespec="seconds")))


def carpeta_persona(persona):
    return os.path.join(RAIZ, config.CARPETA_VOZ_CLONADA, persona, hora.SUBCARPETA)


def ruta_persona(persona, h, m):
    return os.path.join(carpeta_persona(persona), hora.nombre_archivo(h, m))


def ruta_revisar(persona, h, m):
    return os.path.join(carpeta_persona(persona), "_revisar_de_oido", hora.nombre_archivo(h, m))


# ---------------- Voz normal (gTTS) ----------------
def generar_normal():
    from stt import Stt
    pendientes = [(h, m) for h, m in hora.todas() if not os.path.exists(hora.ruta_normal(h, m))]
    print("Voz normal (gTTS): {} de 1440 pendientes; ~{:.0f} min".format(len(pendientes), len(pendientes) * 1.4 / 60))
    if not pendientes:
        return
    stt = Stt()
    registro = os.path.join(os.path.dirname(hora.ruta_normal(0, 0)), "generacion.csv")
    mp3 = os.path.join(os.path.dirname(hora.ruta_normal(0, 0)), "_temporal.mp3")
    os.makedirs(os.path.dirname(mp3), exist_ok=True)
    inicio, dudosas = time.perf_counter(), []
    for n, (h, m) in enumerate(pendientes, 1):
        texto = hora.texto(h, m)
        for intento, espera in enumerate((0,) + ESPERAS_GTTS):
            time.sleep(espera)
            t = time.perf_counter()
            try:
                pcm = tts._pulir(tts._generar_voz(texto, mp3))
                break
            except Exception as e:                       # red o limite de Google
                print("  gTTS fallo en {} ({}): {}".format(hora.clave(h, m), type(e).__name__, e))
                if intento == len(ESPERAS_GTTS):
                    sys.exit("Se detiene tras {} reintentos. Para retomar: py entrenamiento/generar_hora.py --normal"
                             .format(len(ESPERAS_GTTS)))
            finally:
                if os.path.exists(mp3):
                    os.remove(mp3)
        guardar_wav(hora.ruta_normal(h, m), pcm)
        oido = stt.transcribir(pcm.astype("float32") / 32768)
        ok, sim = aceptable(oido, h, m)
        if not ok:
            dudosas.append((hora.clave(h, m), texto, oido, sim))
        anotar(registro, {"voz": "normal", "clave": hora.clave(h, m), "texto": texto, "intento": 1, "referencia": "gtts",
                          "texto_whisper": oido, "similitud": "{:.3f}".format(sim),
                          "duracion_s": "{:.2f}".format(len(pcm) / config.TASA), "estado": "guardada"})
        if n % 60 == 0 or n == len(pendientes):
            print("  {}/{}  ({:.1f} min)".format(n, len(pendientes), (time.perf_counter() - inicio) / 60))
        time.sleep(max(0.0, SEG_ENTRE_PETICIONES - (time.perf_counter() - t)))
    print("Listo. Whisper < {}: {}".format(SIMILITUD_MINIMA, len(dudosas)))
    for c, texto, oido, sim in dudosas:
        print("  {} {:.3f}  \"{}\" -> Whisper: \"{}\"".format(c, sim, texto, oido))


# ---------------- Voz clonada (F5) ----------------
def generar_persona(persona, horas):
    import generar_voces_f5 as g
    clips = g.cargar_referencias()[persona]
    pendientes = [(h, m) for h, m in horas
                  if not os.path.exists(ruta_persona(persona, h, m)) and not os.path.exists(ruta_revisar(persona, h, m))]
    print("{} (F5): {} de {} pendientes; ~{:.0f} min (3.4 s por frase)".format(
        persona, len(pendientes), len(horas), len(pendientes) * 3.4 / 60))
    if not pendientes:
        return
    motor = g.Motor()
    registro = os.path.join(carpeta_persona(persona), "generacion.csv")
    inicio, cuenta = time.perf_counter(), {"aprobada": 0, "revisar_de_oido": 0}
    for n, (h, m) in enumerate(pendientes, 1):
        texto, candidatos = hora.texto(h, m), []
        for intento, clip in g.plan_intentos(clips):
            pcm, _ = motor.generar(persona, clip, texto, g.semilla(persona, hora.clave(h, m), intento))
            oido = motor.stt.transcribir(pcm.astype("float32") / 32768)
            ok, sim = aceptable(oido, h, m)
            candidatos.append(((ok, sim), pcm, {"voz": persona, "clave": hora.clave(h, m), "texto": texto,
                                                "intento": intento, "referencia": clip, "texto_whisper": oido,
                                                "similitud": "{:.3f}".format(sim),
                                                "duracion_s": "{:.2f}".format(len(pcm) / config.TASA),
                                                "estado": "descartada" if sim < SIMILITUD_MINIMA or ok
                                                else "descartada (otra hora o minutos)"}))
            if ok:
                break
        mejor = max(candidatos, key=lambda c: c[0])          # primero las que tienen los numeros bien
        for c in candidatos:
            if c is not mejor:
                anotar(registro, c[2])
        (ok, sim), pcm, fila = mejor
        if ok:
            guardar_wav(ruta_persona(persona, h, m), pcm)
            estado = "aprobada"
        else:
            guardar_wav(ruta_revisar(persona, h, m), pcm)
            estado = "revisar_de_oido"
            print("  REVISAR {} \"{}\" -> Whisper: \"{}\" ({:.3f})".format(hora.clave(h, m), texto, fila["texto_whisper"], sim))
        cuenta[estado] += 1
        anotar(registro, dict(fila, estado=estado))
        if n % 30 == 0 or n == len(pendientes):
            print("  {}/{}  ({:.1f} min)  {}".format(n, len(pendientes), (time.perf_counter() - inicio) / 60, cuenta))
    print("Listo {}: {}".format(persona, cuenta))


def aprobar(persona, t):
    h, m = hhmm(t)
    if not os.path.exists(ruta_revisar(persona, h, m)):
        sys.exit("No hay audio en revision para {} / {}.".format(persona, t))
    os.replace(ruta_revisar(persona, h, m), ruta_persona(persona, h, m))
    anotar(os.path.join(carpeta_persona(persona), "generacion.csv"),
           {"voz": persona, "clave": hora.clave(h, m), "texto": hora.texto(h, m), "estado": "aprobada_de_oido"})
    print("Aprobada de oido:", os.path.relpath(ruta_persona(persona, h, m), RAIZ))


def rechazar(persona, t):
    h, m = hhmm(t)
    for r in (ruta_revisar(persona, h, m), ruta_persona(persona, h, m)):
        if os.path.exists(r):
            os.remove(r)
    generar_persona(persona, [(h, m)])


# ---------------- Revalidar (solo transcribe e informa) ----------------
def revalidar(voz):
    """Vuelve a transcribir las frases que ya existen de 'voz' y aplica aceptable(). No mueve ni regenera nada."""
    from stt import Stt
    stt = Stt()
    horas = [(h, m) for h, m in hora.todas()
             if os.path.exists(hora.ruta_normal(h, m) if voz == "normal" else ruta_persona(voz, h, m))]
    salida = os.path.join(ESCUCHAR, "revalidacion_{}.csv".format(voz))
    os.makedirs(ESCUCHAR, exist_ok=True)
    malas = []
    with open(salida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["clave", "texto", "texto_whisper", "similitud", "numeros_ok", "acepta"])
        for h, m in horas:
            pcm = hora.leer(hora.ruta_normal(h, m) if voz == "normal" else ruta_persona(voz, h, m))
            oido = stt.transcribir(pcm.astype("float32") / 32768) if pcm is not None else ""
            ok, sim = aceptable(oido, h, m)
            w.writerow([hora.clave(h, m), hora.texto(h, m), oido, "{:.3f}".format(sim), numeros_ok(oido, h, m), ok])
            if not ok:
                malas.append((hora.clave(h, m), sim, numeros_ok(oido, h, m), hora.texto(h, m), oido))
    print("{}: {} frases revisadas, {} NO pasan el control estricto ({})".format(
        voz, len(horas), len(malas), os.path.relpath(salida, RAIZ)))
    for c, sim, nums, texto, oido in malas:
        print("  {} sim {:.3f} {}  \"{}\" -> Whisper: \"{}\"".format(
            c, sim, "numeros OK" if nums else "OTRA HORA/MINUTOS", texto, oido))


# ---------------- Escuchar ----------------
def escuchar(voz, horas):
    destino = os.path.join(ESCUCHAR, "escuchar_" + voz)
    if os.path.isdir(destino):
        shutil.rmtree(destino)                       # solo copias para escuchar
    os.makedirs(destino)
    copiadas = 0
    for h, m in horas:
        origen, sufijo = (hora.ruta_normal(h, m) if voz == "normal" else ruta_persona(voz, h, m)), ""
        if not os.path.exists(origen) and voz != "normal":
            origen, sufijo = ruta_revisar(voz, h, m), "_revisar"
        if os.path.exists(origen):
            shutil.copyfile(origen, os.path.join(destino, "{:02d}{:02d}{}.wav".format(h, m, sufijo)))
            print("  {:02d}:{:02d}  {}{}".format(h, m, hora.texto(h, m), "   (EN REVISION)" if sufijo else ""))
            copiadas += 1
    print("{} copiadas. Por el parlante (cierra Doby antes):".format(copiadas))
    print('  py entrenamiento/reproducir_en_parlante.py --tal-cual "{}"'.format(
        os.path.relpath(os.path.join(destino, "*.wav"), RAIZ).replace("\\", "/")))


def main():
    parser = argparse.ArgumentParser(description="Frases de la hora (1440 por voz)")
    parser.add_argument("--normal", action="store_true", help="voz normal con gTTS")
    parser.add_argument("--persona", help="voz clonada F5 de esta persona (venv_f5)")
    parser.add_argument("--muestra", action="store_true", help="solo las 60 horas de muestra")
    parser.add_argument("--aprobar", nargs=2, metavar=("PERSONA", "HHMM"))
    parser.add_argument("--rechazar", nargs=2, metavar=("PERSONA", "HHMM"))
    parser.add_argument("--escuchar", metavar="VOZ", help="'normal' o una persona: copia para el parlante")
    parser.add_argument("--al-azar", type=int, help="con --escuchar: N horas al azar")
    parser.add_argument("--revalidar", metavar="VOZ", help="'normal' o una persona: transcribir de nuevo e informar")
    parser.add_argument("--hora-py", default=os.path.join(RAIZ, "pc", "hora.py"))
    args = parser.parse_args()
    if not os.path.exists(args.hora_py):
        sys.exit("No existe {}: pasa --hora-py con la ruta de hora.py.".format(args.hora_py))
    cargar_hora(args.hora_py)

    if args.revalidar:
        revalidar(args.revalidar)
    elif args.escuchar:
        horas = (muestra() if args.muestra else
                 sorted(random.sample(hora.todas(), args.al_azar)) if args.al_azar else muestra())
        escuchar(args.escuchar, horas)
    elif args.normal:
        generar_normal()
    elif args.aprobar:
        aprobar(*args.aprobar)
    elif args.rechazar:
        rechazar(*args.rechazar)
    elif args.persona:
        generar_persona(args.persona, muestra() if args.muestra else hora.todas())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
