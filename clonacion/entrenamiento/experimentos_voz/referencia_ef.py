"""refEF: tramo de E ('Sin embargo ... hablando.') + 0.3 s + jenpol_refF2, con el volumen de la voz igualado."""
import os, re, sys, wave
os.environ["HF_HUB_OFFLINE"] = "1"
import numpy as np
RAIZ = r"C:\Users\miran\proyectoDoby"
sys.path.insert(0, os.path.join(RAIZ, "pc"))
import stt as modulo_stt
import av
from faster_whisper import decode_audio
from texto import normalizar

CARPETA = os.path.join(RAIZ, "voz_comparacion_f5", "referencias", "jenpol")
DOBY = re.compile(r"\b(Dobby|Dobbie|Dobie|Dobi|Dovi|Doby)\b", re.IGNORECASE)
stt = modulo_stt.Stt()
ruta_e = os.path.join(RAIZ, "datos_voz", "originales", "Jenpol", "jenpol_E.m4a")
with av.open(ruta_e) as c:
    sr = c.streams.audio[0].rate
e_nat, e16 = decode_audio(ruta_e, sampling_rate=sr), decode_audio(ruta_e, sampling_rate=16000)
palabras = [w for s in stt.modelo.transcribe(e16, language="es", word_timestamps=True)[0] for w in s.words]
i = next(k for k, w in enumerate(palabras) if normalizar(w.word) == "sin" and normalizar(palabras[k + 1].word) == "embargo")
j = next(k for k in range(i, len(palabras)) if normalizar(palabras[k].word) == "hablando")
ini = max(palabras[i - 1].end + 0.05, palabras[i].start - 0.25)
fin = min(palabras[j + 1].start - 0.05, palabras[j].end + 0.30)
tramo_e = e_nat[int(ini * sr):int(fin * sr)].astype(np.float64)
with wave.open(os.path.join(CARPETA, "jenpol_refF2.wav")) as w:
    assert w.getframerate() == sr
    tramo_f = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768


def rms_voz(x):
    n = len(x) // 480
    r = np.sqrt(np.mean(x[:n * 480].reshape(n, 480) ** 2, axis=1))       # tramos de 10 ms
    return float(np.sqrt(np.mean(r[r > np.percentile(r, 50)] ** 2)))      # solo la mitad mas fuerte (voz)


tramo_f *= rms_voz(tramo_e) / rms_voz(tramo_f)
# pausa con el silencio REAL del cuarto (la pausa despues de "hablando" en E), no ceros digitales:
# con ceros, Whisper deja de transcribir ahi y F5 podria imitar un silencio artificial
centro = (palabras[j].end + palabras[j + 1].start) / 2
pausa = e_nat[int((centro - 0.15) * sr):int((centro + 0.15) * sr)].astype(np.float64)
x = np.concatenate([tramo_e, pausa, tramo_f])
x *= min(1.0, 0.95 / np.max(np.abs(x)))
ruta = os.path.join(CARPETA, "jenpol_refEF.wav")
with wave.open(ruta, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(np.round(x * 32767).astype("<i2").tobytes())
# texto exacto: el tramo de E transcrito ya cortado + el .txt de refF2
texto_e = DOBY.sub("Doby", " ".join(s.text for s in stt.modelo.transcribe(
    decode_audio(ruta, sampling_rate=16000)[:int(len(tramo_e) / sr * 16000)], language="es")[0]).strip())
texto_f = open(os.path.join(CARPETA, "jenpol_refF2.txt"), encoding="utf-8").read().strip()
texto = "{} {}".format(texto_e, texto_f)
open(ruta.replace(".wav", ".txt"), "w", encoding="utf-8").write(texto + "\n")
completo = DOBY.sub("Doby", " ".join(s.text for s in stt.modelo.transcribe(decode_audio(ruta, sampling_rate=16000), language="es")[0]).strip())
print("jenpol_refEF.wav: {:.1f} s ({:.1f} s de E {:.1f}-{:.1f} s + 0.3 s + {:.1f} s de refF2), {} Hz".format(
    len(x) / sr, len(tramo_e) / sr, ini, fin, len(tramo_f) / sr, sr))
print("TXT: " + texto)
print("Whisper del clip completo: " + completo)
