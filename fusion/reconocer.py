"""
reconocer.py  -  CORRE EN EL PC (py -3.11)
Dibujo del Kinect (o texto) -> integrante, palabras, tramos para la mano y audios para la voz.

- OCR: TrOCR "microsoft/trocr-large-handwritten" desde la cache local (HF_HUB_OFFLINE=1: nunca descarga),
  mismo preprocesado de dibujar.py (copia en fusion/referencia/dibujar_original.py), pero conservando TODAS las
  palabras.
- Cada palabra se compara con el vocabulario de fusion/integrantes.json: primero exacta; si no, difflib con
  similitud >= UMBRAL y la mejor debe superar a la segunda por >= MARGEN (si no: dudosa -> rechazado).
  Si no coincide, se prueba partirla en dos ("JeanPaul" -> jean + paul).
- Se acepta cualquier grupo de palabras de UNA misma persona, en el orden de integrantes.json, sin repetir.
  Mezcla de personas, desorden o repeticion -> "No coincide con un integrante".
- En pantalla se muestra el 'texto' del JSON (con sus tildes); la mano usa el texto sin tildes.
- Tramos: las letras con movimiento (las que no estan entre las 21 estaticas de LSC) cortan la palabra.

Uso (desde la carpeta del proyecto):
  py -3.11 fusion/reconocer.py --pruebas            casos fijos, sin TrOCR
  py -3.11 fusion/reconocer.py --texto "Jaen Mirnda"
  py -3.11 fusion/reconocer.py --imagen fusion/pruebas/palabra.png
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
RUTA_INTEGRANTES = os.path.join(AQUI, "integrantes.json")

UMBRAL = 0.75           # similitud minima (se ajusta con las pruebas reales)
MARGEN = 0.10           # la mejor debe superar a la segunda por esto
LETRAS_ESTATICAS = set("abcdefiklmnopqrtuvwxy")    # LSC sin movimiento (= tabla de main.py)
MODELO_OCR = "microsoft/trocr-large-handwritten"
MAX_TOKENS_OCR = 40     # nombre y apellido completos caben de sobra

NO_COINCIDE = "No coincide con un integrante"
SIN_TEXTO = "No se leyó ninguna palabra"


# ---------------- Texto ----------------
def normalizar(texto):
    """Copia de normalizar() de Doby (pc/texto.py): '¿Préndeme el VENTILADOR?' -> 'prendeme el ventilador'."""
    texto = texto.lower().replace("ñ", "\0")         # proteger la ñ
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")   # sin tildes
    texto = texto.replace("\0", "ñ")
    texto = re.sub(r"[^a-z0-9ñ]+", " ", texto)        # sin signos de puntuacion
    return " ".join(texto.split())                    # espacios limpios


def palabras_de(texto):
    """Palabras normalizadas, solo letras (en un nombre no hay digitos: '0.' -> nada, 'L1na' -> 'lna')."""
    return [p for p in (re.sub(r"[0-9]", "", w) for w in normalizar(texto).split()) if p]


def tramos(palabra):
    """'raigozo' -> [('mano','rai'), ('movimiento','g'), ('mano','o'), ('movimiento','z'), ('mano','o')]."""
    salida, actual = [], ""
    for letra in palabra:
        if letra in LETRAS_ESTATICAS:
            actual += letra
        else:
            if actual:
                salida.append(("mano", actual))
                actual = ""
            salida.append(("movimiento", letra))
    if actual:
        salida.append(("mano", actual))
    return salida


# ---------------- Integrantes ----------------
class Integrantes:
    """fusion/integrantes.json: personas, vocabulario y busqueda de audios."""

    def __init__(self, ruta=RUTA_INTEGRANTES):
        with open(ruta, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.personas = {clave: [(normalizar(p["texto"]), p) for p in d["palabras"]]
                         for clave, d in self.cfg["personas"].items()}
        self.vocabulario = sorted({n for lista in self.personas.values() for n, _ in lista})
        self.mostrar = {}                                # palabra normalizada -> como se muestra
        for lista in self.personas.values():
            for n, p in lista:
                self.mostrar.setdefault(n, p["texto"])
        self.ambiguos = {normalizar(k): v for k, v in self.cfg.get("ambiguos", {}).items()}
        self.no_usar = {x.lower() for x in self.cfg.get("no_usar", [])}
        self.carpetas = [os.path.join(RAIZ, c) for c in self.cfg["carpetas_audio"]]
        self.extensiones = [e.lower() for e in self.cfg["extensiones"]]
        self.pausa_ms = self.cfg.get("pausa_entre_palabras_ms", 250)

    def nombre_completo(self, clave):
        return self.cfg["personas"][clave]["nombre_completo"]

    def partir_nombre(self, archivo):
        """'Maldonado.mp3.mpeg' -> ('Maldonado', '.mpeg'): quita todas las extensiones de audio (asi llegan de
        WhatsApp). Devuelve la ultima extension, en minusculas."""
        nombre, ext = os.path.splitext(archivo)
        while os.path.splitext(nombre)[1].lower() in self.extensiones:
            nombre = os.path.splitext(nombre)[0]
        return nombre, ext.lower()

    def buscar_audio(self, base):
        """Ruta del audio 'base' (sin extension) en carpetas_audio, o None. Sin mayusculas; respeta no_usar."""
        for carpeta in self.carpetas:
            try:
                archivos = os.listdir(carpeta)
            except OSError:
                continue
            candidatos = {}
            for f in archivos:
                nombre, ext = self.partir_nombre(f)
                if nombre.lower() == base.lower() and ext in self.extensiones and f.lower() not in self.no_usar:
                    candidatos[ext] = os.path.join(carpeta, f)
            for ext in self.extensiones:                 # orden de preferencia del JSON
                if ext in candidatos:
                    return candidatos[ext]
        return None


# ---------------- Coincidencia ----------------
def emparejar_palabra(palabra, vocabulario):
    """('ok', [normalizada], similitud) | ('dudosa', [mejor, segunda], similitud) | ('nada', [], similitud)."""
    if palabra in vocabulario:
        return "ok", [palabra], 1.0
    puntajes = sorted(((SequenceMatcher(None, palabra, v).ratio(), v) for v in vocabulario), reverse=True)
    mejor, segunda = puntajes[0], (puntajes[1] if len(puntajes) > 1 else (0.0, ""))
    if mejor[0] >= UMBRAL:
        if mejor[0] - segunda[0] >= MARGEN - 1e-9:
            return "ok", [mejor[1]], mejor[0]
        return "dudosa", [mejor[1], segunda[1]], mejor[0]
    # Dos palabras pegadas por el OCR: se toma la particion con mas similitud en las dos mitades
    mejores = None
    for i in range(2, len(palabra) - 1):
        a = emparejar_palabra_simple(palabra[:i], vocabulario)
        b = emparejar_palabra_simple(palabra[i:], vocabulario)
        if a and b and (mejores is None or a[1] + b[1] > mejores[0]):
            mejores = (a[1] + b[1], [a[0], b[0]])
    if mejores:
        return "ok", mejores[1], mejores[0] / 2
    return "nada", [], mejor[0]


def emparejar_palabra_simple(palabra, vocabulario):
    """(normalizada, similitud) si la palabra coincide sin dudas (sin partirla), o None."""
    if palabra in vocabulario:
        return palabra, 1.0
    puntajes = sorted(((SequenceMatcher(None, palabra, v).ratio(), v) for v in vocabulario), reverse=True)
    mejor, segunda = puntajes[0], (puntajes[1] if len(puntajes) > 1 else (0.0, ""))
    if mejor[0] >= UMBRAL and mejor[0] - segunda[0] >= MARGEN - 1e-9:
        return mejor[1], mejor[0]
    return None


def en_orden(lista, normalizadas):
    """Indices de 'normalizadas' dentro de la lista de una persona, en orden y sin repetir; o None."""
    indices, desde = [], 0
    for n in normalizadas:
        for j in range(desde, len(lista)):
            if lista[j][0] == n:
                indices.append(j)
                desde = j + 1
                break
        else:
            return None
    return indices


# ---------------- Resultado ----------------
@dataclass
class Resultado:
    ok: bool
    motivo: str                       # mensaje para la pantalla
    leido: str                        # texto crudo del OCR
    persona: str = None               # clave de integrantes.json
    mostrar: str = ""                 # como se muestra (con tildes)
    tipo: str = None                  # 'nombre' | 'apellido' | 'nombre y apellido'
    palabras_mano: list = field(default_factory=list)    # sin tildes, para deletrear
    tramos: list = field(default_factory=list)           # un tramos() por palabra
    audios: list = field(default_factory=list)           # nombres base de archivo, en orden
    dudosas: list = field(default_factory=list)          # opciones de una palabra dudosa
    detalle: str = ""                 # por que se rechazo (para la consola)


def interpretar(texto, integrantes):
    leido = (texto or "").strip()
    crudas = palabras_de(leido)
    if not crudas:
        return Resultado(False, SIN_TEXTO, leido)

    normalizadas = []
    for palabra in crudas:
        estado, opciones, _ = emparejar_palabra(palabra, integrantes.vocabulario)
        if estado == "dudosa":
            a, b = (integrantes.mostrar[o] for o in opciones)
            return Resultado(False, "¿{} o {}? Dibuja de nuevo".format(a, b), leido, dudosas=[a, b],
                             detalle="'{}' no pasa el margen de {:.2f}".format(palabra, MARGEN))
        if estado == "nada":
            return Resultado(False, NO_COINCIDE, leido, detalle="'{}' no se parece a ningun nombre".format(palabra))
        normalizadas += opciones

    candidatos = {}
    for clave, lista in integrantes.personas.items():
        indices = en_orden(lista, normalizadas)
        if indices is not None:
            candidatos[clave] = indices
    if not candidatos:
        return Resultado(False, NO_COINCIDE, leido, detalle="mezcla de personas, desorden o palabra repetida")
    if len(candidatos) > 1:
        clave = integrantes.ambiguos.get(" ".join(normalizadas))
        if clave not in candidatos:
            return Resultado(False, NO_COINCIDE, leido, detalle="ambiguo: " + ", ".join(sorted(candidatos)))
    else:
        clave = next(iter(candidatos))

    palabras = [integrantes.personas[clave][j][1] for j in candidatos[clave]]
    tipos = {p["tipo"] for p in palabras}
    tipo = "nombre y apellido" if len(tipos) > 1 else tipos.pop()
    mostrar = " ".join(p["texto"] for p in palabras)
    mano = [normalizar(p["texto"]) for p in palabras]
    return Resultado(True, "Entendí: {} ({})".format(mostrar, integrantes.nombre_completo(clave)), leido,
                     persona=clave, mostrar=mostrar, tipo=tipo, palabras_mano=mano,
                     tramos=[tramos(m) for m in mano], audios=[p["audio"] for p in palabras])


# ---------------- OCR ----------------
class Ocr:
    """TrOCR local. Se crea una sola vez (tarda en cargar)."""

    def __init__(self):
        os.environ["HF_HUB_OFFLINE"] = "1"           # todo local: nunca descarga
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        self.procesador = TrOCRProcessor.from_pretrained(MODELO_OCR)
        self.modelo = VisionEncoderDecoderModel.from_pretrained(MODELO_OCR)

    def leer(self, ruta_png, max_tokens=MAX_TOKENS_OCR, guardar_vista=None):
        """Texto crudo con TODAS las palabras. Mismo preprocesado de dibujar.py. guardar_vista: ruta donde se guarda
        la imagen ya preparada (lo que de verdad recibe TrOCR)."""
        import cv2
        import numpy as np
        from PIL import Image

        imagen = cv2.imread(ruta_png)
        if imagen is None:
            raise FileNotFoundError("no se pudo abrir la imagen: {}".format(ruta_png))
        imagen = cv2.resize(imagen, (640, 480))
        fondo_blanco = np.ones_like(imagen) * 255
        gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        fondo_blanco[gris > 0] = (0, 0, 0)
        fondo_blanco = cv2.erode(fondo_blanco, np.ones((5, 5), np.uint8), iterations=2)
        if guardar_vista:
            cv2.imwrite(guardar_vista, fondo_blanco)

        pil_img = Image.fromarray(fondo_blanco).convert("RGB")
        pixel_values = self.procesador(images=pil_img, return_tensors="pt").pixel_values
        generated_ids = self.modelo.generate(pixel_values, max_new_tokens=max_tokens, no_repeat_ngram_size=2)
        return self.procesador.batch_decode(generated_ids, skip_special_tokens=True)[0]


# ---------------- Consola ----------------
def texto_tramos(lista):
    return " + ".join(t if tipo == "mano" else "[{}]".format(t.upper()) for tipo, t in lista)


def mostrar_resultado(r, integrantes):
    print("  Leí:      \"{}\"".format(r.leido))
    if not r.ok:
        print("  ✗ {}{}".format(r.motivo, "  ({})".format(r.detalle) if r.detalle else ""))
        return
    print("  Entendí:  \"{}\"  ->  {} ({})".format(r.mostrar, r.persona, integrantes.nombre_completo(r.persona)))
    print("  Tipo:     {}".format(r.tipo))
    print("  Mano:     {}".format("  |  ".join(texto_tramos(t) for t in r.tramos)))
    for base in r.audios:
        ruta = integrantes.buscar_audio(base)
        print("  Audio:    {:14} {}".format(base, "✔ " + os.path.relpath(ruta, RAIZ) if ruta else "FALTA"))


# (texto, esperado). esperado: ok, y si ok: persona, mostrar, tipo y opcionalmente tramos; si no: motivo
PRUEBAS = [
    ("Lina", dict(ok=True, persona="lina", mostrar="Lina", tipo="nombre")),
    ("Harry", dict(ok=True, persona="harry", mostrar="Harry", tipo="nombre",
                   tramos=[[("movimiento", "h"), ("mano", "arry")]])),
    ("Paul", dict(ok=True, persona="jeanpaul", mostrar="Paul", tipo="nombre")),
    ("Paula", dict(ok=True, persona="paula", mostrar="Paula", tipo="nombre")),
    ("ENRIQUEZ", dict(ok=True, persona="paula", mostrar="Enríquez", tipo="apellido",
                      tramos=[[("mano", "enrique"), ("movimiento", "z")]])),
    ("Díaz", dict(ok=False, motivo=NO_COINCIDE)),                  # el segundo apellido ya no se usa
    ("Raigozo", dict(ok=True, persona="harry", mostrar="Raigozo", tipo="apellido",
                     tramos=[[("mano", "rai"), ("movimiento", "g"), ("mano", "o"), ("movimiento", "z"), ("mano", "o")]])),
    ("Lina.", dict(ok=True, persona="lina", mostrar="Lina", tipo="nombre")),
    ("Jaen Mirnda", dict(ok=True, persona="jeanpaul", mostrar="Jean Miranda", tipo="nombre y apellido")),
    ("Lna", dict(ok=True, persona="lina", mostrar="Lina", tipo="nombre")),
    ("Jean", dict(ok=True, persona="jeanpaul", mostrar="Jean", tipo="nombre")),
    ("Jean Harry", dict(ok=False, motivo=NO_COINCIDE)),            # Harry no usa "Jean": mezcla de personas
    ("Harry Raigozo", dict(ok=True, persona="harry", mostrar="Harry Raigozo", tipo="nombre y apellido")),
    ("Jean Paul Miranda", dict(ok=True, persona="jeanpaul", mostrar="Jean Paul Miranda", tipo="nombre y apellido")),
    ("Jean Paul Miranda Rivera", dict(ok=False, motivo=NO_COINCIDE)),
    ("Tatiana Maldonado", dict(ok=True, persona="lina", mostrar="Tatiana Maldonado", tipo="nombre y apellido")),
    ("JeanPaul", dict(ok=True, persona="jeanpaul", mostrar="Jean Paul", tipo="nombre")),
    ("Lina Raigozo", dict(ok=False, motivo=NO_COINCIDE)),          # mezcla de personas
    ("Miranda Paul", dict(ok=False, motivo=NO_COINCIDE)),          # desorden
    ("Lina Lina", dict(ok=False, motivo=NO_COINCIDE)),             # repetida
    ("Pedro", dict(ok=False, motivo=NO_COINCIDE)),                 # desconocida
    ("Pauls", dict(ok=False, motivo="¿Paul o Paula? Dibuja de nuevo")),   # dudosa por margen
    ("0.", dict(ok=False, motivo=SIN_TEXTO)),                      # solo digitos y puntuacion
]


def correr_pruebas(integrantes):
    fallas = 0
    for texto, esperado in PRUEBAS:
        r = interpretar(texto, integrantes)
        errores = [clave for clave, valor in esperado.items() if getattr(r, clave) != valor]
        fallas += bool(errores)
        if r.ok:
            obtenido = "{} \"{}\" ({}) mano: {}".format(r.persona, r.mostrar, r.tipo,
                                                       " | ".join(texto_tramos(t) for t in r.tramos))
        else:
            obtenido = "✗ " + r.motivo
        print("  {}  {:26} -> {}".format("PASA " if not errores else "FALLA", "\"{}\"".format(texto), obtenido))
        if errores:
            print("         esperado: {}".format({k: esperado[k] for k in errores}))
    print("\n{} de {} pruebas pasan.".format(len(PRUEBAS) - fallas, len(PRUEBAS)))
    return fallas == 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")     # la consola de Windows no muestra bien las tildes
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Reconocimiento de integrantes (OCR + coincidencia aproximada)")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--pruebas", action="store_true", help="casos fijos, sin TrOCR")
    grupo.add_argument("--texto", help="interpretar este texto")
    grupo.add_argument("--imagen", help="leer esta imagen con TrOCR e interpretarla")
    args = parser.parse_args()

    integrantes = Integrantes()
    if args.pruebas:
        sys.exit(0 if correr_pruebas(integrantes) else 1)
    if args.texto is not None:
        mostrar_resultado(interpretar(args.texto, integrantes), integrantes)
        return
    print("Cargando TrOCR ({})...".format(MODELO_OCR))
    texto = Ocr().leer(args.imagen)
    mostrar_resultado(interpretar(texto, integrantes), integrantes)


if __name__ == "__main__":
    main()
