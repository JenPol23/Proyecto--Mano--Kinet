"""
texto.py  -  normalizacion UNICA del texto para Doby.
La usan el entrenamiento (entrenamiento/preparar_datos.py) y doby.py, para que
el modelo vea el texto limpio igual en los dos lados:
MASSIVE viene en minusculas y sin puntuacion; Whisper trae mayusculas, tildes y signos.
"""

import re
import unicodedata


def normalizar(texto):
    """'¿Préndeme el VENTILADOR, porfa?' -> 'prendeme el ventilador porfa'."""
    texto = texto.lower().replace("ñ", "\0")         # proteger la ñ
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")   # sin tildes
    texto = texto.replace("\0", "ñ")
    texto = re.sub(r"[^a-z0-9ñ]+", " ", texto)        # sin signos de puntuacion
    return " ".join(texto.split())                    # espacios limpios
