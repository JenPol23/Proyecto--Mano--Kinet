"""
generar_voces_f5.py  -  CORRE EN EL PC, CON venv_f5
Frases de Doby con la voz de cada integrante (F5-TTS, modelo F5-Spanish), en voz_cache_f5/<persona>/.

Uso (desde la carpeta del proyecto):
  venv_f5\\Scripts\\python.exe entrenamiento/generar_voces_f5.py --piloto      # 2 frases x 3 referencias x persona
  venv_f5\\Scripts\\python.exe entrenamiento/generar_voces_f5.py [--persona X] [--frase clave]
  venv_f5\\Scripts\\python.exe entrenamiento/generar_voces_f5.py --aprobar persona clave
  venv_f5\\Scripts\\python.exe entrenamiento/generar_voces_f5.py --rechazar persona clave

- Referencias: entrenamiento/referencias_voz_f5.json (persona -> [principal, respaldo 1, respaldo 2]),
  clips de voz_comparacion_f5/referencias/<persona>/<clip>.wav con el texto exacto en <clip>.txt.
- Por frase: 3 versiones con la referencia principal (semilla fija por persona, frase e intento). Cada una:
  F5 a 24 kHz -> resample_poly a 16 kHz -> tts._pulir (mismo procesado del parlante) -> int16, y Whisper
  sobre ESE audio final. Aprueba con similitud >= 0.95 (SequenceMatcher sobre texto.normalizar).
  La aprobada de mayor similitud queda como principal; las demas aprobadas van a _alternativas/.
  Si ninguna aprueba: hasta 3 intentos mas (respaldo 1, respaldo 2, respaldo 1, con semillas nuevas),
  hasta el primero que apruebe. Si ninguno: la mejor va a _revisar_de_oido/ (--aprobar / --rechazar).
- Archivos: voz_cache_f5/<persona>/<clave>_<md5 del texto>.wav, igual que voz_clonada.ruta().
  Se puede reanudar: salta lo que ya esta en la carpeta principal o en _revisar_de_oido/.
- Registro: voz_cache_f5/generacion.csv (una fila por candidato).

Dependencias (por importacion, sin modificarlas): pc/tts.py (FRASES, _pulir), pc/voz_clonada.py (texto,
sin "Doby"), pc/stt.py (Whisper del sistema: carga dentro de venv_f5 por --system-site-packages),
pc/texto.py (normalizar). El apano de soundfile es el de experimentos_voz/f5_prueba_minima.py.
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
import wave
import zlib
from datetime import datetime
from difflib import SequenceMatcher
from math import gcd

os.environ["HF_HUB_OFFLINE"] = "1"

import numpy as np
import soundfile as sf
import torch
import torchaudio
from scipy.signal import resample_poly

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "pc"))

import config                        # noqa: E402
import tts                           # noqa: E402
import voz_clonada                   # noqa: E402
from texto import normalizar         # noqa: E402

MODELO = os.path.join(RAIZ, "modelos", "f5-spanish")
CARPETA_REFS = os.path.join(RAIZ, "voz_comparacion_f5", "referencias")
RUTA_REFS = os.path.join(RAIZ, "entrenamiento", "referencias_voz_f5.json")
SALIDA = os.path.join(RAIZ, "voz_cache_f5")
RUTA_CSV = os.path.join(SALIDA, "generacion.csv")
TASA_F5 = 24000
SIMILITUD_MINIMA = 0.95
VERSIONES = 3
FRASES_PILOTO = ["saludo_1", "repite_hola"]
COLUMNAS = ["fecha", "persona", "frase", "texto", "referencia", "intento", "semilla", "texto_whisper",
            "similitud", "duracion_s", "seg_generacion", "estado", "archivo"]


# torchaudio.load (torchaudio 2.11) necesita FFmpeg via torchcodec: se lee con soundfile (WAV)
def _cargar(ruta, *a, **k):
    x, sr = sf.read(str(ruta), dtype="float32", always_2d=True)
    return torch.from_numpy(x.T.copy()), sr


torchaudio.load = _cargar


# ---------------- Frases ----------------
def frases():
    """clave -> texto clonado: las de tts.FRASES (sin 'Doby') + la generica (voz_clonada.claves())."""
    return {c: voz_clonada.texto(c) for c in voz_clonada.claves()}


def nombre(clave, texto):
    """<clave>_<md5 del texto>: misma convencion que voz_clonada.ruta()."""
    return "{}_{}".format(clave, hashlib.md5(texto.encode("utf-8")).hexdigest()[:8])


def similitud(a, b):
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def semilla(persona, clave, intento):
    return zlib.crc32("{}|{}|{}".format(persona, clave, intento).encode("utf-8"))


# ---------------- Motores ----------------
class Motor:
    def __init__(self):
        from importlib.resources import files
        from omegaconf import OmegaConf
        from f5_tts.infer.utils_infer import load_model, load_vocoder
        from f5_tts.model import DiT
        import stt as modulo_stt

        t = time.perf_counter()
        arch = OmegaConf.load(str(files("f5_tts").joinpath("configs/F5TTS_Base.yaml"))).model.arch
        self.vocoder = load_vocoder("vocos", is_local=True, local_path=os.path.join(MODELO, "vocos-mel-24khz"))
        self.modelo = load_model(DiT, OmegaConf.to_container(arch), os.path.join(MODELO, "model_1200000.safetensors"),
                                 mel_spec_type="vocos", vocab_file=os.path.join(MODELO, "vocab.txt"))
        print("F5 cargado en {:.1f} s".format(time.perf_counter() - t))
        self.stt = modulo_stt.Stt()
        self.refs = {}

    def referencia(self, persona, clip):
        """(audio preprocesado por F5, texto) del clip de referencia; se prepara una sola vez."""
        if clip not in self.refs:
            from f5_tts.infer.utils_infer import preprocess_ref_audio_text
            ruta = os.path.join(CARPETA_REFS, persona, clip + ".wav")
            with open(ruta[:-4] + ".txt", encoding="utf-8") as f:
                texto = f.read().strip()
            self.refs[clip] = preprocess_ref_audio_text(ruta, texto, show_info=lambda *a: None)
        return self.refs[clip]

    def generar(self, persona, clip, texto, sem):
        """Devuelve (pcm int16 16 kHz listo para el parlante, segundos de generacion)."""
        from f5_tts.infer.utils_infer import infer_process
        ref_audio, ref_texto = self.referencia(persona, clip)
        torch.manual_seed(sem)
        np.random.seed(sem % 2**32)
        t = time.perf_counter()
        wav, sr, _ = infer_process(ref_audio, ref_texto, texto, self.modelo, self.vocoder,
                                   mel_spec_type="vocos", show_info=lambda *a: None)
        seg = time.perf_counter() - t
        wav = np.asarray(wav, dtype=np.float64)
        g = gcd(config.TASA, sr)
        return tts._pulir(resample_poly(wav, config.TASA // g, sr // g)), seg

    def evaluar(self, pcm, texto):
        """(texto de Whisper, similitud) sobre el audio final."""
        oido = self.stt.transcribir(pcm.astype(np.float32) / 32768)
        return oido, similitud(oido, texto)


# ---------------- Archivos ----------------
def guardar_wav(ruta, pcm):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.TASA)
        w.writeframes(pcm.astype("<i2").tobytes())


def anotar(filas, ruta=RUTA_CSV):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def leer_csv(ruta=RUTA_CSV):
    if not os.path.exists(ruta):
        return []
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def rutas(persona, clave, texto):
    base = nombre(clave, texto)
    carpeta = os.path.join(SALIDA, persona)
    return (os.path.join(carpeta, base + ".wav"), os.path.join(carpeta, "_revisar_de_oido", base + ".wav"),
            os.path.join(carpeta, "_alternativas"), base)


def cargar_referencias():
    with open(RUTA_REFS, encoding="utf-8") as f:
        return {p: clips for p, clips in json.load(f).items() if not p.startswith("_")}


def fila(persona, clave, texto, clip, intento, sem, oido, sim, pcm, seg):
    return {"fecha": datetime.now().isoformat(sep=" ", timespec="seconds"), "persona": persona, "frase": clave,
            "texto": texto, "referencia": clip, "intento": intento, "semilla": sem, "texto_whisper": oido,
            "similitud": "{:.3f}".format(sim), "duracion_s": "{:.2f}".format(len(pcm) / config.TASA),
            "seg_generacion": "{:.2f}".format(seg), "estado": "", "archivo": ""}


# ---------------- Generacion de una frase ----------------
def plan_intentos(clips, desde=1):
    """[(intento, clip)]: 3 versiones con la principal y 3 reintentos con los respaldos."""
    respaldo = (clips[1:] or clips[:1]) * 2
    plan = [(desde + i, clips[0]) for i in range(VERSIONES)]
    plan += [(desde + VERSIONES + i, respaldo[i]) for i in range(3)]
    return plan


def generar_frase(motor, persona, clips, clave, texto, desde=1):
    principal, revisar, carpeta_alt, base = rutas(persona, clave, texto)
    candidatos = []
    for n, (intento, clip) in enumerate(plan_intentos(clips, desde)):
        sem = semilla(persona, clave, intento)
        pcm, seg = motor.generar(persona, clip, texto, sem)
        oido, sim = motor.evaluar(pcm, texto)
        candidatos.append((pcm, fila(persona, clave, texto, clip, intento, sem, oido, sim, pcm, seg)))
        print("    {} v{} {:13} {:.3f} {:5.2f} s  \"{}\"".format(clave, intento, clip, sim, len(pcm) / config.TASA, oido))
        aprobado = any(float(f["similitud"]) >= SIMILITUD_MINIMA for _, f in candidatos)
        if (n == VERSIONES - 1 and aprobado) or (n >= VERSIONES and aprobado):
            break

    orden = sorted(range(len(candidatos)), key=lambda i: -float(candidatos[i][1]["similitud"]))
    mejor = orden[0]
    if float(candidatos[mejor][1]["similitud"]) >= SIMILITUD_MINIMA:
        estado = "aprobada"
        guardar_wav(principal, candidatos[mejor][0])
        candidatos[mejor][1].update(estado="aprobada", archivo=os.path.relpath(principal, RAIZ))
        for i in orden[1:]:
            pcm, f = candidatos[i]
            if float(f["similitud"]) >= SIMILITUD_MINIMA:
                ruta = os.path.join(carpeta_alt, "{}_v{}.wav".format(base, f["intento"]))
                guardar_wav(ruta, pcm)
                f.update(estado="alternativa", archivo=os.path.relpath(ruta, RAIZ))
            else:
                f["estado"] = "descartada"
    else:
        estado = "revisar_de_oido"
        guardar_wav(revisar, candidatos[mejor][0])
        candidatos[mejor][1].update(estado="revisar_de_oido", archivo=os.path.relpath(revisar, RAIZ))
        for i in orden[1:]:
            candidatos[i][1]["estado"] = "descartada"
    anotar([f for _, f in candidatos])
    return estado


# ---------------- Modos ----------------
def piloto(motor, refs, personas):
    """FRASES_PILOTO x cada referencia x persona, una version: para elegir de oido la principal."""
    carpeta = os.path.join(SALIDA, "_piloto")
    textos = frases()
    filas = []
    for persona in personas:
        for clip in refs[persona]:
            destino = os.path.join(carpeta, persona)
            os.makedirs(destino, exist_ok=True)
            real = os.path.join(destino, clip + "_REAL.wav")
            if not os.path.exists(real):
                shutil.copyfile(os.path.join(CARPETA_REFS, persona, clip + ".wav"), real)
            for clave in FRASES_PILOTO:
                sem = semilla(persona, clave, 1)
                pcm, seg = motor.generar(persona, clip, textos[clave], sem)
                oido, sim = motor.evaluar(pcm, textos[clave])
                ruta = os.path.join(destino, "{}_{}.wav".format(clip, clave))
                guardar_wav(ruta, pcm)
                f = fila(persona, clave, textos[clave], clip, 1, sem, oido, sim, pcm, seg)
                f.update(estado="piloto" + ("" if sim >= SIMILITUD_MINIMA else " (no pasa Whisper)"),
                         archivo=os.path.relpath(ruta, RAIZ))
                filas.append(f)
                print("  {:13} {:12} {:.3f} {:5.2f} s  gen {:4.2f} s  \"{}\"".format(
                    clip, clave, sim, len(pcm) / config.TASA, seg, oido))
    anotar(filas, os.path.join(carpeta, "piloto.csv"))
    return filas


def completo(motor, refs, personas, solo_frase=None):
    textos = frases()
    resumen = {}
    for persona in personas:
        print("\n=== {} (principal {}, respaldos {})".format(persona, refs[persona][0], ", ".join(refs[persona][1:])))
        cuenta = resumen.setdefault(persona, {"aprobada": 0, "revisar_de_oido": 0, "ya_estaba": 0})
        for clave, texto in textos.items():
            if solo_frase and clave != solo_frase:
                continue
            principal, revisar, _, _ = rutas(persona, clave, texto)
            if os.path.exists(principal) or os.path.exists(revisar):
                cuenta["ya_estaba"] += 1
                continue
            cuenta[generar_frase(motor, persona, refs[persona], clave, texto)] += 1
    print("\nResumen (esta corrida):")
    for persona, c in resumen.items():
        print("  {:7} aprobadas {:3}  en revision {:3}  ya estaban {:3}".format(
            persona, c["aprobada"], c["revisar_de_oido"], c["ya_estaba"]))


def aprobar(persona, clave):
    texto = frases()[clave]
    principal, revisar, _, _ = rutas(persona, clave, texto)
    if not os.path.exists(revisar):
        sys.exit("No hay audio en revision para {} / {}.".format(persona, clave))
    os.replace(revisar, principal)
    anotar([{"fecha": datetime.now().isoformat(sep=" ", timespec="seconds"), "persona": persona, "frase": clave,
             "texto": texto, "estado": "aprobada_de_oido", "archivo": os.path.relpath(principal, RAIZ)}])
    print("Aprobada de oido:", os.path.relpath(principal, RAIZ))


def rechazar(motor, refs, persona, clave):
    texto = frases()[clave]
    _, revisar, _, _ = rutas(persona, clave, texto)
    if os.path.exists(revisar):
        os.remove(revisar)
    previos = [int(f["intento"]) for f in leer_csv() if f["persona"] == persona and f["frase"] == clave and f["intento"]]
    desde = max(previos, default=0) + 1                  # semillas nuevas
    print("Rechazada; se genera de nuevo desde el intento {}.".format(desde))
    print("Resultado:", generar_frase(motor, persona, refs[persona], clave, texto, desde))


def main():
    parser = argparse.ArgumentParser(description="Voces de Doby con F5-TTS")
    parser.add_argument("--piloto", action="store_true", help="2 frases x 3 referencias x persona")
    parser.add_argument("--persona", help="solo esta persona")
    parser.add_argument("--frase", help="solo esta frase (clave)")
    parser.add_argument("--aprobar", nargs=2, metavar=("PERSONA", "CLAVE"), help="pasar de _revisar_de_oido/ a la carpeta")
    parser.add_argument("--rechazar", nargs=2, metavar=("PERSONA", "CLAVE"), help="borrar la de revision y generar otra")
    args = parser.parse_args()

    if args.aprobar:
        aprobar(*args.aprobar)
        return
    refs = cargar_referencias()
    personas = [args.persona] if args.persona else sorted(refs)
    for p in personas:
        if p not in refs:
            sys.exit("'{}' no esta en {}".format(p, RUTA_REFS))
    if args.frase and args.frase not in frases():
        sys.exit("frase desconocida: {}".format(args.frase))

    motor = Motor()
    inicio = time.perf_counter()
    if args.rechazar:
        rechazar(motor, refs, *args.rechazar)
    elif args.piloto:
        piloto(motor, refs, personas)
    else:
        completo(motor, refs, personas, args.frase)
    print("\nTiempo total {:.1f} min; GPU torch pico {:.0f} MiB".format(
        (time.perf_counter() - inicio) / 60, torch.cuda.max_memory_allocated() / 2**20))


if __name__ == "__main__":
    main()
