"""
validar_audios.py  -  CORRE EN EL PC
Valida las grabaciones del celular (bloques A-E del guion), las corta en
frases y deja un reporte por persona.

Uso:
  py entrenamiento/validar_audios.py --persona lina --listar   # solo la asignacion de archivos
  py entrenamiento/validar_audios.py --persona lina
  py entrenamiento/validar_audios.py --todos

Entrada:  datos_voz/originales/<Nombre>/   (solo se leen; la persona = carpeta en minusculas)
          datos/guion_voces/guion_voces.json
Salida:   datos_voz/procesados/<nombre>/<nombre>_<bloque>_<nn>.wav   (A, B, D; nn = frase del guion)
          datos_voz/procesados/<nombre>/<nombre>_C.wav, <nombre>_E.wav
          datos_voz/reportes/reporte_<nombre>.md, segmentos_<nombre>.csv

Identificacion de archivos: el bloque es la primera parte del nombre que sea
una sola letra A-E; la parte es el numero final (_1, _2). Lo que no se pueda
identificar con seguridad se lista y NO se procesa.

DEPENDENCIAS (se importan sin modificarlas):
  - pc/stt.py: Stt (mismo Whisper que Doby, "medium", language="es"). Los cortes de
    A, B y D usan Stt.transcribir() tal cual; C y E usan el mismo modelo con la regla
    estandar de no_speech (ver transcribir_largo()).
  - pc/texto.py: normalizar()
  - entrenamiento/preproceso.py: pasa_altos() (unica implementacion del filtro)
El modelo se carga con HF_HUB_OFFLINE=1: si no esta en disco falla, no descarga.
"""

import argparse
import csv
import difflib
import json
import math
import os
import re
import sys
import wave
from datetime import datetime
from itertools import combinations

os.environ.setdefault("HF_HUB_OFFLINE", "1")          # nunca descargar modelos

import av
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "pc"))

from preproceso import pasa_altos                     # noqa: E402
from texto import normalizar                          # noqa: E402

CARPETA_ORIGINALES = os.path.join(RAIZ, "datos_voz", "originales")
CARPETA_PROCESADOS = os.path.join(RAIZ, "datos_voz", "procesados")
CARPETA_REPORTES = os.path.join(RAIZ, "datos_voz", "reportes")
CARPETA_INMP441 = os.path.join(RAIZ, "datos_voz", "inmp441")
NO_APLICA = "grabado con INMP441 (no aplica)"      # A o B sin archivo de celular pero con grabaciones del INMP441
RUTA_GUION = os.path.join(RAIZ, "datos", "guion_voces", "guion_voces.json")

TASA = 16000
BLOQUES = "ABCDE"
ESPERADAS = {"A": 15, "B": 22, "D": 12}
EXTENSIONES = {".mp3", ".mpeg", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".flac", ".mp4", ".3gp", ".amr", ".webm"}

# ---- Niveles y corte ----
TRAMO = 320                    # 20 ms
MAX_OFFSET_UMBRAL = 10.0       # umbral = ruido + min(10 dB, (voz - ruido) / 2)
SILENCIO_FIN = {"A": 0.8, "B": 0.8, "D": 1.0}
SEG_MINIMO = 0.25              # sonidos mas cortos se descartan
MARGEN_ANTES = 0.2
MARGEN_DESPUES = 0.3
REJILLA_SILENCIO = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5]
REJILLA_OFFSET = [6.0, 8.0, 10.0, 12.0, 14.0]
SATURADO = 0.999               # |x| >= 0.999 del fondo de escala

# ---- Estados ----
SIM_OK, SIM_MIN = 0.85, 0.60
SIM_E_OK = 0.80
SNR_OK, SNR_MIN = 20.0, 10.0
SAT_SEG_MAX = 0.1              # % de muestras saturadas en una frase (o en C/E): desde aqui x
SAT_SEG_AVISO = 0.01           # desde aqui revisar (menos: 1-3 muestras sueltas, se ignora)
SAT_ARCHIVO_MAX = 1.0          # % en el archivo entero
PICO_VOZ_MIN = -30.0
DUR_AB = (0.4, 6.0)
C_MINIMO = 60.0
FRASES_MAL_BLOQUE = 3          # frases con x para marcar el bloque entero x
PISO_DIGITAL = -120.0          # ruido de fondo por debajo: silencios en cero digital
NOTA_DIGITAL = "silencios en cero digital (audio editado o con compuerta de ruido): la SNR no es medible"

OK, REVISAR, MAL = "✅", "⚠️", "❌"
TEXTO_ESTADO = {OK: "sirve", REVISAR: "revisar", MAL: "regrabar"}

# ---- Alineacion ----
BASE_SIM = 0.4                 # un emparejamiento suma (similitud - 0.4) por frase
CASTIGO_HUECO = 0.05
VARIANTES_DOBY = re.compile(r"\b(dobi|dobby|dobbie|dobie|dobin|dovi|dovy|dubi|dubby|toby|tobi|tobby)\b")
MAX_PAUSAS = 4                 # pausas internas que se prueban al separar frases unidas
MAX_FRASES_CORTE = 3           # un corte puede traer hasta 3 frases dichas sin pausa
TRAMOS_PAUSA = 3               # 60 ms: pausa interna minima

COLUMNAS_CSV = ["archivo", "bloque", "n", "texto_esperado", "texto_whisper", "texto_real", "similitud",
                "pico_voz_dbfs", "snr_db", "estado", "uso", "motivo"]

# ---- Uso de cada segmento ----
# enrolar: identificar a la persona (A, B, C); referencia_voz: clonar la voz (D, E),
# necesita que el texto coincida; excluir: no usar (x, sin archivo o texto que no coincide en D/E).
USO_BLOQUE = {"A": "enrolar", "B": "enrolar", "C": "enrolar", "D": "referencia_voz", "E": "referencia_voz"}
SIM_TEXTO_IGUAL = 0.95         # por encima, texto_real = texto del guion; si no, lo que entendio Whisper
ORDEN_VERBO = re.compile(r"\b(prende|prendeme|enciende|enciendeme|apaga|apagame|activa|desactiva|deten|detener|conecta|desconecta)\b")
ORDEN_OBJETO = re.compile(r"\b(ventilador|bombillo|bombilla|luz|luces|carro|motor|cautin|soldador|plancha|"
                          r"planchita|alisadora|todo|todos|aparatos)\b")    # carro/motor: audios ya grabados
DOBY_EN_TEXTO = re.compile(r"\b(dobby|dobbie|dobie|dobín|dobin|dobi|dovi|dovy|dubi|dubby|toby|tobi|tobby)\b", re.IGNORECASE)


# =====================================================================
#  Archivos
# =====================================================================
def quitar_extensiones(nombre):
    base = nombre
    while os.path.splitext(base)[1].lower() in EXTENSIONES:
        base = os.path.splitext(base)[0]
    return base


def identificar(carpeta):
    """
    Devuelve (bloques, problemas):
      bloques   = {letra: [(parte, ruta), ...] en orden}
      problemas = [(archivo, motivo), ...]   (vacios, sin identificar, ambiguos)
    """
    candidatos = {}
    problemas = []
    for nombre in sorted(os.listdir(carpeta)):
        ruta = os.path.join(carpeta, nombre)
        if not os.path.isfile(ruta):
            continue
        if os.path.getsize(ruta) == 0:
            problemas.append((nombre, "vacío (0 bytes)"))
            continue
        base = quitar_extensiones(nombre)
        partes = [t for t in re.split(r"[_\s()\-.]+", base) if t]
        letras = [t.upper() for t in partes if len(t) == 1 and t.upper() in BLOQUES]
        if not letras:
            problemas.append((nombre, "sin identificar: no hay una letra de bloque A-E en el nombre"))
            continue
        letra = letras[0]
        m = re.search(r"bloque[_\s\-]*([a-z])(?![a-z])", base, re.IGNORECASE)
        if m and m.group(1).upper() != letra:
            problemas.append((nombre, "ambiguo: letra {} pero dice Bloque {}".format(letra, m.group(1).upper())))
            continue
        m = re.search(r"(?:^|[_\s\-(])(\d+)\)?$", base)
        parte = int(m.group(1)) if m else None
        candidatos.setdefault(letra, []).append((parte, ruta))

    bloques = {}
    for letra, lista in candidatos.items():
        if len(lista) == 1:
            bloques[letra] = [(lista[0][0], lista[0][1])]
            continue
        numeros = [p for p, _ in lista]
        if None in numeros or len(set(numeros)) != len(numeros):
            for _, ruta in lista:
                problemas.append((os.path.basename(ruta),
                                  "ambiguo: el bloque {} tiene varias partes sin numero unico".format(letra)))
            continue
        bloques[letra] = sorted(lista)
    return bloques, problemas


def metadatos(ruta):
    """(duracion s, Hz, kbps, canales, codec) con PyAV."""
    with av.open(ruta) as contenedor:
        s = contenedor.streams.audio[0]
        duracion = contenedor.duration / 1e6 if contenedor.duration else float("nan")
        kbps = (s.bit_rate or contenedor.bit_rate or 0) / 1000
        return duracion, s.rate, kbps, s.channels, s.codec_context.name


def carpetas_personas():
    return {d.lower(): os.path.join(CARPETA_ORIGINALES, d) for d in sorted(os.listdir(CARPETA_ORIGINALES))
            if os.path.isdir(os.path.join(CARPETA_ORIGINALES, d))}


def listar(persona, carpeta):
    bloques, problemas = identificar(carpeta)
    print()
    print("Persona: {}   ({})".format(persona, os.path.relpath(carpeta, RAIZ)))
    for letra in BLOQUES:
        if letra not in bloques:
            print("  {}  faltante".format(letra))
            continue
        for parte, ruta in bloques[letra]:
            try:
                dur, hz, kbps, canales, codec = metadatos(ruta)
                info = "{:6.1f} s  {} Hz  {:.0f} kbps  {} canal(es)  {}".format(dur, hz, kbps, canales, codec)
            except Exception as e:
                info = "no se pudo leer: {}".format(e)
            print("  {}  parte {:6s}  {:60s} {}".format(letra, "unica" if parte is None else str(parte),
                                                        os.path.basename(ruta), info))
    for nombre, motivo in problemas:
        print("  -  {:60s} {}".format(nombre, motivo))
    return bloques, problemas


# =====================================================================
#  Niveles
# =====================================================================
def db_de(valor):
    return 20 * math.log10(valor / 32768.0) if valor > 0 else float("-inf")


def db_tramos(filtrado):
    n = len(filtrado) // TRAMO
    tramos = filtrado[:n * TRAMO].reshape(n, TRAMO)
    rms = np.sqrt(np.mean(tramos ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-3) / 32768.0)


def niveles(audio):
    """audio float32 [-1, 1]. Devuelve dict con escala int16 y los dB por tramo."""
    x = audio.astype(np.float64) * 32768.0
    f = pasa_altos(x, fs=TASA)
    db = db_tramos(f)
    piso = float(np.percentile(db, 10))
    voz = float(np.percentile(db, 95))
    return {"x": x, "f": f, "db": db, "piso": piso, "voz": voz, "snr": voz - piso,
            "pico_total": db_de(float(np.max(np.abs(x)))),
            "pico_voz": db_de(float(np.max(np.abs(f)))),
            "saturacion": 100.0 * float(np.mean(np.abs(audio) >= SATURADO))}


# =====================================================================
#  Corte por silencios
# =====================================================================
def segmentar(db, umbral, silencio_fin):
    """Tramos (inicio, fin) en indices de 20 ms."""
    tramos_fin = int(round(silencio_fin / 0.02))
    segmentos, inicio, fin, silencio = [], None, 0, 0
    for i, activo in enumerate(db > umbral):
        if activo:
            if inicio is None:
                inicio = i
            fin, silencio = i, 0
        elif inicio is not None:
            silencio += 1
            if silencio >= tramos_fin:
                segmentos.append((inicio, fin + 1))
                inicio = None
    if inicio is not None:
        segmentos.append((inicio, fin + 1))
    return [(a, b) for a, b in segmentos if (b - a) * 0.02 >= SEG_MINIMO]


def cortar(niv, bloque):
    """Devuelve (segmentos, umbral, parametros). Si no coincide con lo esperado, prueba la rejilla."""
    esperado = ESPERADAS[bloque]
    offset = min(MAX_OFFSET_UMBRAL, niv["snr"] / 2)
    silencio = SILENCIO_FIN[bloque]
    segs = segmentar(niv["db"], niv["piso"] + offset, silencio)
    mejor = (abs(len(segs) - esperado), 0.0, segs, offset, silencio)
    if len(segs) != esperado:
        for s in REJILLA_SILENCIO:
            for o in REJILLA_OFFSET:
                if o >= niv["snr"]:
                    continue
                prueba = segmentar(niv["db"], niv["piso"] + o, s)
                distancia = abs(s - silencio) + abs(o - offset) / 10
                clave = (abs(len(prueba) - esperado), distancia)
                if clave < mejor[:2]:
                    mejor = (clave[0], clave[1], prueba, o, s)
    _, _, segs, offset, silencio = mejor
    parametros = "umbral ruido+{:.1f} dB, silencio {:.1f} s".format(offset, silencio)
    return segs, niv["piso"] + offset, parametros


def con_margen(segs, k, total_muestras):
    """Muestras (inicio, fin) del segmento k con margen, sin pasar la mitad del silencio vecino."""
    a, b = segs[k][0] * TRAMO, segs[k][1] * TRAMO
    antes = segs[k - 1][1] * TRAMO if k > 0 else None
    despues = segs[k + 1][0] * TRAMO if k + 1 < len(segs) else None
    ini = max(a - int(MARGEN_ANTES * TASA), 0 if antes is None else (antes + a) // 2)
    fin = min(b + int(MARGEN_DESPUES * TASA), total_muestras if despues is None else (b + despues) // 2)
    return ini, fin


def pausas_internas(seg, db, umbral):
    """Centros (en tramos) de las pausas internas del segmento, de la mas larga a la mas corta."""
    a, b = seg
    bajo = db[a:b] <= umbral
    pausas, i = [], 0
    while i < len(bajo):
        if bajo[i]:
            j = i
            while j < len(bajo) and bajo[j]:
                j += 1
            if i > 0 and j < len(bajo) and j - i >= TRAMOS_PAUSA:
                pausas.append((j - i, a + (i + j) // 2))
            i = j
        else:
            i += 1
    return [centro for _, centro in sorted(pausas, reverse=True)[:MAX_PAUSAS]]


# =====================================================================
#  Texto y alineacion
# =====================================================================
def limpiar(texto):
    return VARIANTES_DOBY.sub("doby", normalizar(texto))


def similitud(a, b):
    a, b = limpiar(a), limpiar(b)
    if not a and not b:
        return 1.0
    # autojunk=False: con textos de mas de 200 caracteres (bloque E) difflib ignoraria
    # los caracteres frecuentes (espacios, vocales) y la similitud saldria muy baja
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def alinear(textos, frases):
    """
    Alineacion en orden (programacion dinamica). textos: transcripciones de los
    segmentos; frases: textos del guion. Devuelve pasos (tipo, [segmentos], [frases]):
      '1:1', '2:1' (dos segmentos, una frase), 'dividir' (un segmento, 2 o 3 frases),
      'sobra' (segmento sin frase), 'falta' (frase sin segmento).
    """
    m, n = len(textos), len(frases)
    cache = {}

    def sim(i_s, j_s):
        clave = (tuple(i_s), tuple(j_s))
        if clave not in cache:
            cache[clave] = similitud(" ".join(textos[i] for i in i_s), " ".join(frases[j] for j in j_s))
        return cache[clave]

    menos_inf = float("-inf")
    dp = [[menos_inf] * (n + 1) for _ in range(m + 1)]
    paso = [[None] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    for i in range(m + 1):
        for j in range(n + 1):
            if dp[i][j] == menos_inf:
                continue
            opciones = []
            if i < m and j < n:
                opciones.append((i + 1, j + 1, sim([i], [j]) - BASE_SIM, ("1:1", [i], [j])))
            if i + 1 < m and j < n:
                opciones.append((i + 2, j + 1, sim([i, i + 1], [j]) - BASE_SIM, ("2:1", [i, i + 1], [j])))
            for k in range(2, MAX_FRASES_CORTE + 1):       # un corte con 2 o 3 frases dichas sin pausa
                if i < m and j + k <= n:
                    frases_k = list(range(j, j + k))
                    opciones.append((i + 1, j + k, k * (sim([i], frases_k) - BASE_SIM), ("dividir", [i], frases_k)))
            if i < m:
                opciones.append((i + 1, j, -CASTIGO_HUECO, ("sobra", [i], [])))
            if j < n:
                opciones.append((i, j + 1, -CASTIGO_HUECO, ("falta", [], [j])))
            for i2, j2, puntos, p in opciones:
                if dp[i][j] + puntos > dp[i2][j2]:
                    dp[i2][j2] = dp[i][j] + puntos
                    paso[i2][j2] = (i, j, p)
    pasos, i, j = [], m, n
    while (i, j) != (0, 0):
        i, j, p = paso[i][j]
        pasos.append(p)
    return pasos[::-1]


# =====================================================================
#  Estados
# =====================================================================
def calificar(sim, snr, pico_voz, saturacion, duracion, bloque, umbral_sim=SIM_OK):
    """Devuelve (estado, motivos)."""
    malos, dudas = [], []
    if sim is not None:
        if sim < SIM_MIN:
            malos.append("similitud {:.2f}".format(sim))
        elif sim < umbral_sim:
            dudas.append("similitud {:.2f}".format(sim))
    if snr < SNR_MIN:
        malos.append("SNR {:.0f} dB".format(snr))
    elif snr < SNR_OK:
        dudas.append("SNR {:.0f} dB".format(snr))
    if saturacion >= SAT_SEG_MAX:
        malos.append("saturación {:.2f} %".format(saturacion))
    elif saturacion >= SAT_SEG_AVISO:
        dudas.append("saturación {:.3f} %".format(saturacion))
    if pico_voz < PICO_VOZ_MIN:
        dudas.append("voz baja ({:.0f} dBFS)".format(pico_voz))
    if bloque in ("A", "B") and not DUR_AB[0] <= duracion <= DUR_AB[1]:
        dudas.append("duración {:.1f} s".format(duracion))
    if malos:
        return MAL, malos + dudas
    if dudas:
        return REVISAR, dudas
    return OK, []


def medir_tramo(niv, ini, fin):
    """Niveles de un trozo [ini, fin) en muestras, con el ruido de fondo del archivo."""
    db = niv["db"][ini // TRAMO:max(ini // TRAMO + 1, fin // TRAMO)]
    voz = float(np.percentile(db, 95))
    trozo_x = niv["x"][ini:fin]
    return {"pico_voz": db_de(float(np.max(np.abs(niv["f"][ini:fin])))),
            "snr": voz - niv["piso"],
            "saturacion": 100.0 * float(np.mean(np.abs(trozo_x) >= SATURADO * 32768)),
            "duracion": (fin - ini) / TASA}


# =====================================================================
#  Guardado
# =====================================================================
class Sobrescribir:
    """Pregunta antes de sobrescribir: [s] si, [n] no, [a] si a todos, [x] no a todos."""
    def __init__(self):
        self.siempre = None

    def permitido(self, ruta):
        if not os.path.exists(ruta):
            return True
        if self.siempre is not None:
            return self.siempre
        while True:
            r = input("  {} ya existe. Sobrescribir? [s] si, [n] no, [a] si a todos, [x] no a todos: ".format(
                os.path.relpath(ruta, RAIZ))).strip().lower()
            if r in ("s", "n"):
                return r == "s"
            if r in ("a", "x"):
                self.siempre = r == "a"
                return self.siempre


def guardar_wav(ruta, x, sobrescribir):
    """x en escala int16 (float, crudo sin filtrar). Devuelve True si se escribio."""
    if not sobrescribir.permitido(ruta):
        print("  (no se sobrescribe {})".format(os.path.basename(ruta)))
        return False
    pcm = np.clip(np.round(x), -32768, 32767).astype("<i2")
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TASA)
        w.writeframes(pcm.tobytes())
    return True


# =====================================================================
#  Un bloque
# =====================================================================
def procesar_segmentado(persona, bloque, audio, niv, frases_guion, stt, salida, sobrescribir):
    """A, B, D. Devuelve (filas del CSV, info del bloque)."""
    segs, umbral, parametros = cortar(niv, bloque)
    esperado = ESPERADAS[bloque]
    total = len(audio)
    print("  {} segmentos (esperados {}); {}".format(len(segs), esperado, parametros))

    def transcribir(ini, fin):
        return stt.transcribir(audio[ini:fin])

    margenes = [con_margen(segs, k, total) for k in range(len(segs))]
    textos = []
    for k, (ini, fin) in enumerate(margenes):
        textos.append(transcribir(ini, fin))
        print("    corte {:2d} {:6.1f}-{:6.1f} s  {}".format(k + 1, ini / TASA, fin / TASA, textos[-1]))

    esperados = [f["texto"] for f in frases_guion]
    pasos = alinear(textos, esperados)
    filas = []

    def fila(archivo, n, esperado_txt, whisper, sim, med, estado, motivos):
        return {"archivo": archivo, "bloque": bloque, "n": n, "texto_esperado": esperado_txt,
                "texto_whisper": whisper, "similitud": "" if sim is None else "{:.2f}".format(sim),
                "pico_voz_dbfs": "" if med is None else "{:.1f}".format(med["pico_voz"]),
                "snr_db": "" if med is None else "{:.1f}".format(med["snr"]),
                "estado": estado, "motivo": "; ".join(motivos), "_sim": sim, "_med": med}

    def guardar(nombre, ini, fin):
        ruta = os.path.join(salida, nombre)
        return nombre if guardar_wav(ruta, niv["x"][ini:fin], sobrescribir) else nombre + " (existente)"

    # --- A sin indicacion: todas las frases dicen "Hola Doby"; si la cuenta no cuadra no se
    # numera a ciegas. El numero de indicacion solo sirve para analisis, no para entrenar:
    # los cortes con voz de "Hola Doby" y SNR aceptable sirven para enrolar aunque repita.
    reconocidos = [k for k, t in enumerate(textos) if similitud(t, esperados[0]) >= SIM_MIN]
    if bloque == "A" and len(reconocidos) != esperado:
        for k, (ini, fin) in enumerate(margenes):
            med = medir_tramo(niv, ini, fin)
            sim = similitud(textos[k], esperados[0])
            estado, notas = calificar(None, med["snr"], med["pico_voz"], med["saturacion"], med["duracion"], bloque)
            if k not in reconocidos:
                estado, motivos = REVISAR, ["sin voz reconocida como 'Hola Doby'"] + notas
            elif estado == MAL:
                motivos = notas
            else:
                estado, motivos = OK, ["usable para enrolar (sin indicación)"] + notas
            archivo = guardar("{}_A_corte_{:02d}.wav".format(persona, k + 1), ini, fin)
            filas.append(fila(archivo, "", esperados[0], textos[k], sim, med, estado, motivos))
            filas[-1]["uso"] = "enrolar" if estado == OK else "excluir"
        ajustar_filas(filas, bloque)
        motivo = "{} de {} cortes reconocidos como 'Hola Doby' (se esperaban {}): se guardan sin número de indicación".format(
            len(reconocidos), len(segs), esperado)
        return filas, {"ambiguo": motivo, "parametros": parametros, "cortes": len(segs)}

    for tipo, i_s, j_s in pasos:
        if tipo == "falta":
            j = j_s[0]
            filas.append(fila("", frases_guion[j]["n"], esperados[j], "", None, None, MAL, ["frase faltante"]))
            continue
        if tipo == "sobra":
            k = i_s[0]
            ini, fin = margenes[k]
            sims = [similitud(textos[k], e) for e in esperados]
            j = int(np.argmax(sims))
            med = medir_tramo(niv, ini, fin)
            if sims[j] >= SIM_MIN:
                n = frases_guion[j]["n"]
                existentes = sum(1 for f in filas if f["archivo"].startswith("{}_{}_{:02d}_rep".format(persona, bloque, n)))
                archivo = guardar("{}_{}_{:02d}_rep{}.wav".format(persona, bloque, n, existentes + 1), ini, fin)
                filas.append(fila(archivo, n, esperados[j], textos[k], sims[j], med, REVISAR,
                                  ["repetida de la frase {}".format(n)]))
            else:
                filas.append(fila("", "", "", textos[k], sims[j], med, REVISAR,
                                  ["corte sin frase del guion (ruido o frase no reconocida); no se guarda"]))
            continue
        if tipo == "dividir":
            k = i_s[0]
            ini, fin = margenes[k]
            mejor = None                       # (trozos, textos, similitudes) de las mejores pausas
            ya_transcritos = {}
            pausas = sorted(pausas_internas(segs[k], niv["db"], umbral))
            for cortes_k in combinations(pausas, len(j_s) - 1):
                limites = [ini] + [c * TRAMO for c in cortes_k] + [fin]
                trozos = list(zip(limites[:-1], limites[1:]))
                textos_div = []
                for a, b in trozos:
                    if (a, b) not in ya_transcritos:
                        ya_transcritos[(a, b)] = transcribir(a, b)
                    textos_div.append(ya_transcritos[(a, b)])
                sims = [similitud(t, esperados[j]) for t, j in zip(textos_div, j_s)]
                if mejor is None or sum(sims) > sum(mejor[2]):
                    mejor = (trozos, textos_div, sims)
            if mejor and min(mejor[2]) >= SIM_MIN:
                for (ini, fin), texto_div, sim, j in zip(*mejor, j_s):
                    med = medir_tramo(niv, ini, fin)
                    estado, motivos = calificar(sim, med["snr"], med["pico_voz"], med["saturacion"], med["duracion"], bloque)
                    archivo = guardar("{}_{}_{:02d}.wav".format(persona, bloque, frases_guion[j]["n"]), ini, fin)
                    filas.append(fila(archivo, frases_guion[j]["n"], esperados[j], texto_div, sim, med, estado,
                                      ["cortada en su pausa interna"] + motivos))
            else:
                for j in j_s:
                    filas.append(fila("", frases_guion[j]["n"], esperados[j], textos[k],
                                      similitud(textos[k], esperados[j]), None, REVISAR,
                                      ["unida a otra frase sin pausa; no se pudo cortar, no se guarda"]))
            continue
        # 1:1 o 2:1
        ini, fin = margenes[i_s[0]][0], margenes[i_s[-1]][1]
        texto_seg = textos[i_s[0]] if len(i_s) == 1 else transcribir(ini, fin)
        j = j_s[0]
        sim = similitud(texto_seg, esperados[j])
        med = medir_tramo(niv, ini, fin)
        estado, motivos = calificar(sim, med["snr"], med["pico_voz"], med["saturacion"], med["duracion"], bloque)
        if len(i_s) == 2:
            motivos = ["unidos 2 cortes (pausa dentro de la frase)"] + motivos
        archivo = guardar("{}_{}_{:02d}.wav".format(persona, bloque, frases_guion[j]["n"]), ini, fin)
        filas.append(fila(archivo, frases_guion[j]["n"], esperados[j], texto_seg, sim, med, estado, motivos))

    ajustar_filas(filas, bloque)
    return filas, {"ambiguo": None, "parametros": parametros, "cortes": len(segs)}


def es_orden(texto):
    """Whisper entendio una orden valida para Doby (verbo + aparato)."""
    t = limpiar(texto)
    return bool(ORDEN_VERBO.search(t) and ORDEN_OBJETO.search(t))


def texto_real_de(fila):
    """Lo que la persona dijo: el guion si coincide, si no el texto de Whisper (con 'Doby' corregido)."""
    if not fila["archivo"]:
        return ""
    sim = fila.get("_sim")
    if fila["texto_esperado"] and sim is not None and sim >= SIM_TEXTO_IGUAL:
        return fila["texto_esperado"]
    return DOBY_EN_TEXTO.sub("Doby", fila["texto_whisper"])


def ajustar_filas(filas, bloque):
    """
    Reglas de uso (A, B, D):
      - repeticiones (_rep) con voz y SNR aceptable: usables
      - B leida distinto al guion pero es una orden valida con buena SNR: usable (texto distinto)
      - D que no coincide con el guion: excluir de referencias de voz (no hace falta regrabar)
    """
    for f in filas:
        f["texto_real"] = texto_real_de(f)
        if "uso" in f:                                     # A sin indicacion: ya decidido
            continue
        med, sim = f["_med"], f["_sim"]
        motivos = [m for m in f["motivo"].split("; ") if m]
        con_voz = (med is not None and med["snr"] >= SNR_MIN and med["saturacion"] < SAT_SEG_MAX
                   and bool(limpiar(f["texto_whisper"])))
        if f["archivo"] and con_voz:
            if "_rep" in f["archivo"]:
                f["estado"] = OK
                motivos = ["usable (repetición)"] + [m for m in motivos if not m.startswith("repetida")]
            elif (bloque == "B" and f["estado"] != OK and sim is not None and sim < SIM_OK
                  and med["snr"] >= SNR_OK and es_orden(f["texto_whisper"])):
                f["estado"] = OK
                motivos = ["usable (texto distinto)"] + [m for m in motivos if not m.startswith("similitud")]
        if bloque == "D" and f["archivo"] and sim is not None and sim < SIM_OK:
            if f["estado"] != MAL:
                f["estado"] = REVISAR
                f["_solo_excluir"] = True
            motivos.append("excluir de referencias de voz (no hace falta regrabar)")
            f["uso"] = "excluir"
        if "uso" not in f:
            f["uso"] = "excluir" if not f["archivo"] or f["estado"] == MAL else USO_BLOQUE[bloque]
        f["motivo"] = "; ".join(motivos)


def transcribir_largo(stt, audio):
    """
    C y E (60-100 s). Mismo modelo que Doby, pero Stt.transcribir() no sirve aqui:
    descarta segmentos con no_speech_prob > 0.6, y en audios largos ese valor sube
    por ventana de 30 s aunque haya habla clara (en E de Lina se perdia la mitad).
    Regla estandar de Whisper: se descarta solo si ademas avg_logprob < -1.
    """
    segmentos, _ = stt.modelo.transcribe(audio, language="es")
    partes = []
    for s in segmentos:
        if s.no_speech_prob > stt.modulo.MAX_NO_SPEECH and s.avg_logprob < -1.0:
            continue
        limpio = normalizar(s.text)
        if not limpio or any(a in limpio for a in stt.modulo.ALUCINACIONES):
            continue
        partes.append(s.text.strip())
    return " ".join(partes)


def procesar_entero(persona, bloque, audio, niv, guion, stt, salida, sobrescribir):
    """C y E: se guardan enteros; E se compara con el texto del guion."""
    texto = transcribir_largo(stt, audio)
    duracion = len(audio) / TASA
    print("  Whisper: {}{}".format(texto[:150], "..." if len(texto) > 150 else ""))
    malos, dudas = [], []
    sim = None
    if bloque == "E":
        sim = similitud(texto, guion["bloques"]["E"]["texto"])
        if sim < SIM_MIN:
            malos.append("similitud {:.2f}".format(sim))
        elif sim < SIM_E_OK:
            dudas.append("similitud {:.2f}".format(sim))
    else:
        if not limpiar(texto):
            malos.append("Whisper no reconoce habla")
        if duracion < C_MINIMO:
            dudas.append("dura {:.0f} s (se piden 1 a 2 min)".format(duracion))
    if niv["snr"] < SNR_MIN:
        malos.append("SNR {:.0f} dB".format(niv["snr"]))
    elif niv["snr"] < SNR_OK:
        dudas.append("SNR {:.0f} dB".format(niv["snr"]))
    if niv["saturacion"] >= SAT_SEG_MAX:           # C y E se guardan enteros: mismos umbrales que una frase
        malos.append("saturación {:.2f} %".format(niv["saturacion"]))
    elif niv["saturacion"] >= SAT_SEG_AVISO:
        dudas.append("saturación {:.3f} %".format(niv["saturacion"]))
    estado = MAL if malos else REVISAR if dudas else OK
    if niv["piso"] < PISO_DIGITAL:
        dudas.append(NOTA_DIGITAL)            # solo informa: no cambia el estado

    nombre = "{}_{}.wav".format(persona, bloque)
    escrito = guardar_wav(os.path.join(salida, nombre), niv["x"], sobrescribir)
    fila = {"archivo": nombre if escrito else nombre + " (existente)", "bloque": bloque, "n": "",
            "texto_esperado": guion["bloques"]["E"]["texto"] if bloque == "E" else "(habla libre)",
            "texto_whisper": texto, "texto_real": DOBY_EN_TEXTO.sub("Doby", texto),
            "similitud": "" if sim is None else "{:.2f}".format(sim),
            "pico_voz_dbfs": "{:.1f}".format(niv["pico_voz"]), "snr_db": "{:.1f}".format(niv["snr"]),
            "estado": estado, "motivo": "; ".join(malos + dudas),
            # E es referencia de voz solo si el texto coincide (OK); C sirve para enrolar si no es x
            "uso": ("referencia_voz" if estado == OK else "excluir") if bloque == "E"
                   else ("excluir" if estado == MAL else "enrolar")}
    return [fila], {"estado": estado, "motivo": "; ".join(malos + dudas) or "—"}


def estado_bloque(bloque, filas, niv, info):
    """(estado, motivo) del bloque segmentado."""
    malas = [f for f in filas if f["estado"] == MAL and "_rep" not in f["archivo"]]
    dudosas = [f for f in filas if f["estado"] == REVISAR and not f.get("_solo_excluir")]
    excluidas = [f for f in filas if f.get("_solo_excluir")]
    faltan = [f for f in filas if "frase faltante" in f["motivo"]]
    motivos = []
    if niv["piso"] < PISO_DIGITAL:
        motivos.append(NOTA_DIGITAL)
    if niv["snr"] < SNR_MIN:
        motivos.append("SNR del archivo {:.0f} dB".format(niv["snr"]))
    if niv["saturacion"] >= SAT_ARCHIVO_MAX:
        motivos.append("saturación del archivo {:.2f} %".format(niv["saturacion"]))
    if info["ambiguo"]:
        motivos.append(info["ambiguo"])
    if faltan:
        motivos.append("faltan {} frase(s)".format(len(faltan)))
    if malas:
        motivos.append("{} frase(s) para regrabar".format(len(malas)))
    if dudosas:
        motivos.append("{} para revisar".format(len(dudosas)))
    if excluidas:
        motivos.append("{} excluida(s) de referencias de voz".format(len(excluidas)))
    if niv["snr"] < SNR_MIN or niv["saturacion"] >= SAT_ARCHIVO_MAX or len(malas) >= FRASES_MAL_BLOQUE:
        estado = MAL
    elif malas or dudosas:
        estado = REVISAR
    else:
        estado = OK
    return estado, "; ".join(motivos) or "todas las frases sirven"


# =====================================================================
#  Una persona
# =====================================================================
def firma(partes):
    """Nombre y tamano de cada original del bloque: si cambia, el bloque ya procesado quedo viejo."""
    return [[os.path.basename(ruta), os.path.getsize(ruta)] for _, ruta in partes]


def ruta_resumen(persona):
    return os.path.join(CARPETA_REPORTES, "resumen_{}.json".format(persona))


def cargar_resumen(persona):
    ruta = ruta_resumen(persona)
    if not os.path.exists(ruta):
        return {"version": 1, "whisper": "", "bloques": {}}
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def guardar_resumen(persona, resumen):
    with open(ruta_resumen(persona), "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)


def pendientes_de(persona, bloques, resumen, rehacer):
    """Bloques a procesar: los nuevos y los pedidos con --rehacer. Avisa si un original cambio."""
    pendientes = []
    for letra in BLOQUES:
        if letra not in bloques:
            continue
        hecho = resumen["bloques"].get(letra)
        if hecho is None or letra in rehacer:
            pendientes.append(letra)
        elif hecho["firma"] != firma(bloques[letra]):
            print("  AVISO: el original del bloque {} de {} cambio desde que se proceso; "
                  "no se reprocesa solo. Usa --rehacer {}".format(letra, persona, letra))
    return pendientes


def grabado_inmp441(persona):
    """True si la persona tiene grabaciones del INMP441 (grabar_inmp441.py)."""
    carpeta = os.path.join(CARPETA_INMP441, persona)
    return os.path.isdir(carpeta) and any(n.lower().endswith(".wav") for n in os.listdir(carpeta))


def procesar_persona(persona, carpeta, guion, motor, sobrescribir, rehacer):
    """Procesa solo los bloques nuevos (o --rehacer) y regenera el reporte con todo."""
    bloques, problemas = listar(persona, carpeta)
    resumen = cargar_resumen(persona)
    pendientes = pendientes_de(persona, bloques, resumen, rehacer)
    hechos = [b for b in BLOQUES if b in resumen["bloques"] and b not in pendientes]
    print("  Ya procesados: {}   Por procesar: {}".format(", ".join(hechos) or "ninguno",
                                                        ", ".join(pendientes) or "ninguno"))
    salida = os.path.join(CARPETA_PROCESADOS, persona)
    os.makedirs(salida, exist_ok=True)
    os.makedirs(CARPETA_REPORTES, exist_ok=True)

    for letra in pendientes:
        stt = motor()
        resumen["whisper"] = "{} en {}".format(stt.nombre_modelo, stt.dispositivo)
        print()
        print("=== {} bloque {} ===".format(persona, letra))
        audios, originales = [], []
        from faster_whisper import decode_audio
        for parte, ruta in bloques[letra]:
            originales.append([parte, os.path.basename(ruta), list(metadatos(ruta))])
            audios.append(decode_audio(ruta, sampling_rate=TASA))
        audio = np.concatenate(audios).astype(np.float32)
        niv = niveles(audio)
        print("  {:.1f} s   pico voz {:.1f} dBFS   pico total {:.1f} dBFS   ruido {:.1f} dBFS   SNR {:.1f} dB   saturación {:.3f} %".format(
            len(audio) / TASA, niv["pico_voz"], niv["pico_total"], niv["piso"], niv["snr"], niv["saturacion"]))

        if letra in ESPERADAS:
            filas_b, info = procesar_segmentado(persona, letra, audio, niv, guion["bloques"][letra]["frases"],
                                                stt, salida, sobrescribir)
            estado, motivo = estado_bloque(letra, filas_b, niv, info)
        else:
            filas_b, info = procesar_entero(persona, letra, audio, niv, guion, stt, salida, sobrescribir)
            estado, motivo = info["estado"], info["motivo"]
        print("  Bloque {}: {} {}".format(letra, estado, motivo))
        avisar_sobrantes(persona, letra, salida, filas_b)

        # primero el CSV y despues el JSON: un bloque cuenta como hecho solo si ya tiene sus filas
        actualizar_csv(persona, letra, filas_b)
        resumen["bloques"][letra] = {
            "estado": estado, "motivo": motivo, "firma": firma(bloques[letra]), "originales": originales,
            "niv": {k: niv[k] for k in ("pico_voz", "pico_total", "piso", "snr", "saturacion")},
            "info": {k: info.get(k) for k in ("ambiguo", "parametros", "cortes")},
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M")}
        guardar_resumen(persona, resumen)

    escribir_reporte(persona, carpeta, resumen, problemas, bloques)


def avisar_sobrantes(persona, letra, salida, filas_b):
    """Al rehacer un bloque, WAV de la corrida anterior que ya no corresponden (no se borran)."""
    nuevos = {f["archivo"].replace(" (existente)", "") for f in filas_b if f["archivo"]}
    patron = re.compile(r"{}_{}(_.*)?\.wav$".format(re.escape(persona), letra))
    viejos = sorted(n for n in os.listdir(salida) if patron.match(n) and n not in nuevos)
    if viejos:
        print("  AVISO: quedan WAV de una corrida anterior que ya no corresponden (no se borran): {}".format(
            ", ".join(viejos)))


def ruta_csv(persona):
    return os.path.join(CARPETA_REPORTES, "segmentos_{}.csv".format(persona))


def leer_csv(persona):
    if not os.path.exists(ruta_csv(persona)):
        return []
    with open(ruta_csv(persona), newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def actualizar_csv(persona, letra, filas_b):
    """Reemplaza las filas del bloque 'letra' y conserva las de los demas bloques."""
    filas = [f for f in leer_csv(persona) if f["bloque"] != letra] + filas_b
    filas.sort(key=lambda f: BLOQUES.index(f["bloque"]))          # sort estable: mantiene el orden interno
    with open(ruta_csv(persona), "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS_CSV, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def escribir_reporte(persona, carpeta, resumen_json, problemas, bloques_actuales):
    """Reporte completo a partir de resumen_<nombre>.json y segmentos_<nombre>.csv."""
    filas = leer_csv(persona)
    inmp441 = grabado_inmp441(persona)
    resumen, originales = [], []
    for letra in BLOQUES:
        hecho = resumen_json["bloques"].get(letra)
        if hecho is None:
            if letra in bloques_actuales:
                motivo = "pendiente (no se proceso)"
            elif letra in ("A", "B") and inmp441:
                motivo = NO_APLICA
            else:
                motivo = "faltante"
            resumen.append({"bloque": letra, "niv": None, "motivo": motivo})
            continue
        for parte, nombre, meta in hecho["originales"]:
            originales.append((letra, parte, nombre, meta))
        resumen.append({"bloque": letra, "estado": hecho["estado"], "motivo": hecho["motivo"],
                        "niv": hecho["niv"], "info": hecho["info"],
                        "filas": [f for f in filas if f["bloque"] == letra]})

    ruta = os.path.join(CARPETA_REPORTES, "reporte_{}.md".format(persona))
    L = []
    L.append("# Reporte de audios: {}".format(persona))
    L.append("")
    L.append("- Fecha: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M")))
    L.append("- Originales: `{}`".format(os.path.relpath(carpeta, RAIZ).replace("\\", "/")))
    L.append("- Whisper: {}".format(resumen_json.get("whisper") or "—"))
    L.append("- Estados: {} sirve / {} revisar / {} regrabar".format(OK, REVISAR, MAL))
    L.append("- Transcripción: los cortes de A, B y D usan `Stt.transcribir()` de Doby tal cual "
             "(descarta segmentos con no_speech_prob > 0.6). C y E usan el mismo modelo con la regla "
             "estándar de Whisper (se descarta solo si no_speech_prob > 0.6 **y** avg_logprob < −1): "
             "en audios largos el filtro de Doby borra habla clara.")
    L.append("- Uso: `enrolar` (A, B, C: identificar a la persona), `referencia_voz` (D, E: clonar la voz, "
             "el texto debe coincidir), `excluir`. En A, si el conteo no coincide, los cortes se guardan sin "
             "número de indicación y sirven para enrolar igual.")
    L.append("")
    L.append("## Bloques")
    L.append("")
    L.append("| Bloque | Estado | Frases ✅/esperadas | Uso | Pico voz | Pico total | Ruido fondo | SNR | Saturación | Corte | Motivo |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in resumen:
        if r["niv"] is None:
            if r["motivo"] == NO_APLICA:
                estado, motivo = "➖ no aplica", NO_APLICA
            elif r["motivo"] == "faltante":
                estado, motivo = MAL + " faltante", "falta el archivo del bloque"
            else:
                estado, motivo = "⏳ pendiente", r["motivo"]
            L.append("| {} | {} | — | — | — | — | — | — | — | — | {} |".format(r["bloque"], estado, motivo))
            continue
        niv = r["niv"]
        if r["bloque"] in ESPERADAS:
            if r["info"]["ambiguo"]:
                usables = sum(1 for f in r["filas"] if f["estado"] == OK)
                frases = "{} cortes usables (sin indicación)".format(usables)
            else:
                buenas = sum(1 for f in r["filas"] if f["estado"] == OK and f["n"] != "" and "_rep" not in f["archivo"])
                frases = "{}/{}".format(buenas, ESPERADAS[r["bloque"]])
            corte = "{} cortes; {}".format(r["info"]["cortes"], r["info"]["parametros"])
        else:
            frases, corte = "—", "entero"
        usos = {}
        for f in r["filas"]:
            if f["archivo"]:
                usos[f["uso"]] = usos.get(f["uso"], 0) + 1
        uso = ", ".join("{} {}".format(u, c) for u, c in sorted(usos.items()))
        L.append("| {} | {} {} | {} | {} | {:.1f} dBFS | {:.1f} dBFS | {:.1f} dBFS | {:.1f} dB | {:.3f} % | {} | {} |".format(
            r["bloque"], r["estado"], TEXTO_ESTADO[r["estado"]], frases, uso, niv["pico_voz"], niv["pico_total"],
            niv["piso"], niv["snr"], niv["saturacion"], corte, r["motivo"]))
    L.append("")
    L.append("## Usables con nota")
    L.append("")
    con_nota = [f for f in filas if f["estado"] == OK and f["motivo"]]
    if not con_nota:
        L.append("Ninguna.")
    for f in con_nota:
        L.append("- **{} {}** {} {} ({}): {}  ".format(f["bloque"], f["n"] if f["n"] != "" else "—", OK,
                                                         f["archivo"], f["uso"], f["motivo"]))
        if f["texto_real"] and f["texto_real"] != f["texto_esperado"] and f["bloque"] in ESPERADAS:
            L.append("  esperado: «{}» · real: «{}»".format(f["texto_esperado"], f["texto_real"]))
    L.append("")
    L.append("## Frases con problemas")
    L.append("")
    problemas_frases = [f for f in filas if f["estado"] != OK]
    if not problemas_frases:
        L.append("Ninguna.")
    for f in problemas_frases:
        L.append("- **{} {}** {} {} ({}): {}  ".format(f["bloque"], f["n"] if f["n"] != "" else "—", f["estado"],
                                                         f["archivo"] or "(sin archivo)", f["uso"], f["motivo"]))
        if f["texto_esperado"] and f["bloque"] in ESPERADAS:
            L.append("  esperado: «{}» · Whisper: «{}»".format(f["texto_esperado"], f["texto_whisper"]))
    L.append("")
    L.append("## Archivos originales")
    L.append("")
    L.append("| Bloque | Parte | Archivo | Duración | Frecuencia | Tasa de bits | Canales | Códec |")
    L.append("|---|---|---|---|---|---|---|---|")
    for letra, parte, nombre, (dur, hz, kbps, canales, codec) in originales:
        L.append("| {} | {} | {} | {:.1f} s | {} Hz | {:.0f} kbps | {} | {} |".format(
            letra, "única" if parte is None else parte, nombre, dur, hz, kbps, canales, codec))
    if problemas:
        L.append("")
        L.append("No procesados:")
        L.append("")
        for nombre, motivo in problemas:
            L.append("- {} {}: {}".format(MAL if motivo.startswith("vacío") else REVISAR, nombre, motivo))
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("Reporte:", os.path.relpath(ruta, RAIZ))


# =====================================================================
#  Principal
# =====================================================================
def cargar_stt():
    import stt as modulo_stt       # importa torch antes que faster_whisper (DLL de CUDA)
    motor = modulo_stt.Stt()
    motor.nombre_modelo = modulo_stt.MODELO
    motor.modulo = modulo_stt
    return motor


def main(argv=None):
    parser = argparse.ArgumentParser(description="Valida y corta las grabaciones del celular.")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--persona", help="nombre de la carpeta en datos_voz/originales (sin importar mayusculas)")
    grupo.add_argument("--todos", action="store_true", help="todas las personas")
    parser.add_argument("--listar", action="store_true", help="solo mostrar que bloque y parte se asigna a cada archivo")
    parser.add_argument("--rehacer", default="", help="bloques a reprocesar aunque ya esten hechos (ej. B o D,E)")
    args = parser.parse_args(argv)

    rehacer = {b.strip().upper() for b in args.rehacer.split(",") if b.strip()}
    if rehacer - set(BLOQUES):
        parser.error("--rehacer solo admite bloques de {}".format(", ".join(BLOQUES)))

    personas = carpetas_personas()
    if args.persona:
        clave = args.persona.lower()
        if clave not in personas:
            parser.error("no existe la carpeta de {} en {} (hay: {})".format(
                args.persona, os.path.relpath(CARPETA_ORIGINALES, RAIZ), ", ".join(personas)))
        personas = {clave: personas[clave]}

    if args.listar:
        for persona, carpeta in personas.items():
            listar(persona, carpeta)
        return

    with open(RUTA_GUION, encoding="utf-8") as f:
        guion = json.load(f)
    for letra, cantidad in ESPERADAS.items():
        if len(guion["bloques"][letra]["frases"]) != cantidad:
            sys.exit("El guion debe tener {} frases en el bloque {}.".format(cantidad, letra))

    cargado = []

    def motor():
        """Whisper se carga solo la primera vez que hay un bloque que procesar."""
        if not cargado:
            cargado.append(cargar_stt())
        return cargado[0]

    sobrescribir = Sobrescribir()
    for persona, carpeta in personas.items():
        procesar_persona(persona, carpeta, guion, motor, sobrescribir, rehacer)
    if not cargado:
        print()
        print("Nada nuevo que procesar (Whisper no se cargo). Reportes regenerados.")


if __name__ == "__main__":
    main()
