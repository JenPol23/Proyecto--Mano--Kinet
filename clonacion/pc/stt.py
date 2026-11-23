"""
stt.py  -  CORRE EN EL PC
Voz a texto con Whisper "medium" (faster-whisper), local.

- GPU con float16. Si falla (en Windows suele ser por DLL de CUDA), CPU con int8.
- torch se importa ANTES que faster_whisper: asi Windows encuentra las DLL de CUDA.
- language="es", sin initial_prompt.
- Se descartan los segmentos con no_speech_prob > 0.6 y las alucinaciones
  tipicas de Whisper con silencio o ruido ("subtitulos", "amara", "gracias por
  ver", "siguiente video", "proximo video", "nos vemos en el").
"""

import torch  # noqa: F401  (debe ir antes de faster_whisper)
import numpy as np
from faster_whisper import WhisperModel

import config
from texto import normalizar

MODELO = "medium"
MAX_NO_SPEECH = 0.6
ALUCINACIONES = ("subtitulos", "amara", "gracias por ver",
                 "siguiente video", "proximo video", "nos vemos en el")


class Stt:
    def __init__(self, modelo=MODELO):
        try:
            self.modelo = WhisperModel(modelo, device="cuda", compute_type="float16")
            self._calentar()                  # los errores de DLL salen al transcribir
            self.dispositivo = "GPU (cuda, float16)"
        except Exception as e:
            print("AVISO: Whisper no pudo usar la GPU ({}). Uso la CPU con int8.".format(e))
            self.modelo = WhisperModel(modelo, device="cpu", compute_type="int8")
            self._calentar()
            self.dispositivo = "CPU (int8)"
        print("Whisper {} listo en {}".format(modelo, self.dispositivo))

    def _calentar(self):
        """Primera transcripcion (1 s de silencio): verifica el dispositivo y la deja lista."""
        self.transcribir(np.zeros(config.TASA, dtype=np.float32))

    def transcribir(self, audio):
        """audio: float32 en [-1, 1] a 16 kHz. Devuelve el texto ('' si no hay voz)."""
        segmentos, _ = self.modelo.transcribe(audio, language="es")
        partes = []
        for s in segmentos:                   # generador: aqui se hace el trabajo
            if s.no_speech_prob > MAX_NO_SPEECH:
                continue
            limpio = normalizar(s.text)
            if not limpio or any(a in limpio for a in ALUCINACIONES):
                continue
            partes.append(s.text.strip())
        return " ".join(partes)
