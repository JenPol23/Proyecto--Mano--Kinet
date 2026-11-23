"""
preproceso.py
Preprocesamiento de audio comun para enrolar e identificar voces.
Es la UNICA implementacion del filtro: no copiarlo en otros scripts.

pasa_altos(): Butterworth orden 4, aplicado con sosfiltfilt (ida y vuelta,
sin desfase). Quita el vaiven de la fuente (< 20 Hz) y los golpes de aire
(explosivas, respiracion, < 100 Hz) del INMP441.
Al aplicarse dos veces, en la frecuencia de corte atenua 6 dB (no 3 dB).
"""

import numpy as np
from scipy.signal import butter, sosfiltfilt


def pasa_altos(audio, fs=16000, corte=100):
    """Devuelve el audio filtrado (float64, misma escala que la entrada)."""
    sos = butter(4, corte, btype="highpass", fs=fs, output="sos")
    return sosfiltfilt(sos, np.asarray(audio, dtype=np.float64))
