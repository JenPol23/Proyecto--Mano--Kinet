"""Paso 1 F5: 3 clips de referencia por persona (6-12 s, cortados en pausas naturales) + .txt exacto."""
import csv, os, re, sys, wave
from difflib import SequenceMatcher
os.environ["HF_HUB_OFFLINE"] = "1"
import numpy as np
from scipy.signal import correlate
RAIZ = r"C:\Users\miran\proyectoDoby"
sys.path.insert(0, os.path.join(RAIZ, "pc")); sys.path.insert(0, os.path.join(RAIZ, "entrenamiento"))
import stt as modulo_stt
import av
from faster_whisper import decode_audio
import validar_audios as va
from texto import normalizar

SALIDA = os.path.join(RAIZ, "voz_comparacion_f5", "referencias")
MULETILLAS = {"eh", "ehh", "em", "emm", "este", "mm", "mmm", "ah", "aja", "jaja", "jajaja", "jeje"}
PAUSA_CORTE, PAUSA_MAX_INTERNA = 0.30, 0.9
DUR = (6.0, 12.0)
DOBY = re.compile(r"\b(Dobby|Dobbie|Dobie|Dobi|Dovi|Doby)\b", re.IGNORECASE)
stt = modulo_stt.Stt()


def nativo(ruta):
    with av.open(ruta) as c:
        sr = c.streams.audio[0].rate
    return decode_audio(ruta, sampling_rate=sr), sr, decode_audio(ruta, sampling_rate=16000)


def transcribir(x16):
    segs, _ = stt.modelo.transcribe(x16, language="es", word_timestamps=True)
    return list(segs)


def limpiar_texto(t):
    return DOBY.sub("Doby", " ".join(t.split())).strip()


def candidatos(x16, nat, sr, origen, pausa_max=PAUSA_MAX_INTERNA, prob_min=0.80, pausa_corte=PAUSA_CORTE):
    palabras = [w for s in transcribir(x16) for w in s.words]
    # frases separadas por pausas naturales
    frases, act = [], []
    for w in palabras:
        if act and w.start - act[-1].end >= pausa_corte:
            frases.append(act); act = []
        act.append(w)
    if act:
        frases.append(act)
    out = []
    for i in range(len(frases)):
        for j in range(i, len(frases)):
            ws = [w for f in frases[i:j + 1] for w in f]
            dur = ws[-1].end - ws[0].start
            if dur > DUR[1]:
                break
            internas = [frases[k + 1][0].start - frases[k][-1].end for k in range(i, j)]
            if dur < DUR[0] or any(g > pausa_max for g in internas):
                continue
            texto_n = normalizar(" ".join(w.word for w in ws))
            probs = [w.probability for w in ws]
            if set(texto_n.split()) & MULETILLAS or "jaj" in texto_n or np.mean(probs) < prob_min or min(probs) < 0.35:
                continue
            antes = frases[i - 1][-1].end if i > 0 else 0.0
            despues = frases[j + 1][0].start if j + 1 < len(frases) else len(x16) / 16000
            ini = max(antes + 0.05, ws[0].start - 0.25, 0.0)
            fin = min(despues - 0.05, ws[-1].end + 0.30)
            out.append({"ini": ini, "fin": fin, "texto_palabras": " ".join(w.word.strip() for w in ws),
                        "fluidez": len(ws) / dur, "prob": float(np.mean(probs)), "pausas": internas, "origen": origen,
                        "puntaje": len(ws) / dur * float(np.mean(probs)) * (1.1 if 8.0 <= dur <= 11.0 else 1.0)})
    out.sort(key=lambda c: -c["puntaje"])
    elegidos = []
    for c in out:
        if all(c["fin"] <= e["ini"] or c["ini"] >= e["fin"] for e in elegidos):
            elegidos.append(c)
    return elegidos


def clip_D_camila(nat, sr, x16):
    """Una frase del bloque D de camila (texto del guion, similitud 1.00, 6-12 s), ubicada exacta en el original."""
    with open(os.path.join(RAIZ, "datos_voz", "reportes", "segmentos_camila.csv"), encoding="utf-8-sig") as f:
        filas = [r for r in csv.DictReader(f) if r["bloque"] == "D" and r["similitud"] == "1.00" and r["archivo"]]
    mejores = []
    for r in sorted(filas, key=lambda r: -float(r["snr_db"])):
        with wave.open(os.path.join(RAIZ, "datos_voz", "procesados", "camila", r["archivo"])) as w:
            c16 = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
        if DUR[0] <= len(c16) / 16000 <= DUR[1]:
            k = int(np.argmax(correlate(x16, c16, mode="valid", method="fft")))
            mejores.append({"ini": k / 16000, "fin": (k + len(c16)) / 16000, "texto_palabras": r["texto_esperado"],
                            "origen": "D " + r["archivo"], "fluidez": 0, "prob": 1, "pausas": [], "puntaje": 0})
    return mejores[:1]


def guardar_clip(persona, n, c, nat, sr):
    carpeta = os.path.join(SALIDA, persona)
    os.makedirs(carpeta, exist_ok=True)
    a, b = int(c["ini"] * sr), int(c["fin"] * sr)
    x = nat[a:b]
    nombre = "{}_ref{}{}".format(persona, c["origen"][0], n)
    with wave.open(os.path.join(carpeta, nombre + ".wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(np.round(np.clip(x, -1, 32767 / 32768) * 32768).astype("<i2").tobytes())
    # transcripcion del clip YA cortado (la que debe coincidir con lo que se dice)
    g16 = decode_audio(os.path.join(carpeta, nombre + ".wav"), sampling_rate=16000)
    texto_clip = limpiar_texto(" ".join(s.text for s in transcribir(g16)))
    esperado = limpiar_texto(c["texto_palabras"])
    if c["origen"].startswith("D "):                      # frase del guion leida tal cual: el texto del guion
        texto = esperado
    else:
        texto = texto_clip
    coincide = SequenceMatcher(None, normalizar(texto_clip), normalizar(esperado)).ratio()
    with open(os.path.join(carpeta, nombre + ".txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    return {"persona": persona, "clip": nombre + ".wav", "segundos": "{:.1f}".format((b - a) / sr), "sr": sr,
            "origen": "{} {:.1f}-{:.1f} s".format(c["origen"], c["ini"], c["fin"]), "texto": texto,
            "whisper_clip": texto_clip, "coincide_palabras": "{:.2f}".format(coincide),
            "fluidez": "{:.1f} pal/s".format(c["fluidez"]) if c["fluidez"] else "—",
            "pausas_internas": " ".join("{:.2f}".format(p) for p in c["pausas"]) or "—",
            "revisar": "SI" if coincide < 0.97 else ""}


filas = []
plan = {"jenpol": [("E", 3)], "lina": [("C", 3)], "camila": [("C", 2), ("D", 1)], "harry": [("E", 3)]}
nombres = {"jenpol": "Jenpol", "lina": "Lina", "camila": "Camila", "harry": "Harry"}
solo = sys.argv[1:]                                       # personas a (re)hacer; el resto se conserva del CSV
ruta_csv = os.path.join(SALIDA, "referencias.csv")
if "jenpol-F" in solo:                                    # solo agregar clips del bloque F de jenpol
    plan = {"jenpol": [("F", 3)]}
    filas = [r for r in csv.DictReader(open(ruta_csv, encoding="utf-8-sig")) if not r["clip"].startswith("jenpol_refF")]
    solo = []
elif solo and os.path.exists(ruta_csv):
    filas = [r for r in csv.DictReader(open(ruta_csv, encoding="utf-8-sig")) if r["persona"] not in solo]
for persona, fuentes in plan.items():
    if solo and persona not in solo:
        continue
    carpeta_orig = os.path.join(RAIZ, "datos_voz", "originales", nombres[persona])
    bloques, _ = va.identificar(carpeta_orig)
    n = 0
    for letra, cuantos in fuentes:
        if letra == "F":                                  # el validador no conoce F: se busca por nombre (*_F.*)
            ruta = [os.path.join(carpeta_orig, a) for a in os.listdir(carpeta_orig)
                    if va.quitar_extensiones(a).lower().endswith("_f")][0]
        else:
            (_, ruta), = bloques[letra]
        nat, sr, x16 = nativo(ruta)
        elegidos = clip_D_camila(nat, sr, x16) if (persona == "camila" and letra == "D") else candidatos(x16, nat, sr, letra)
        if len(elegidos) < cuantos and letra != "D":       # pocos tramos: se relaja (corte en pausas >= 0.2 s)
            for c in candidatos(x16, nat, sr, letra, pausa_max=1.3, prob_min=0.70, pausa_corte=0.20):
                if len(elegidos) < cuantos and all(c["fin"] <= e["ini"] or c["ini"] >= e["fin"] for e in elegidos):
                    c["origen"] += " (relajado)"
                    elegidos.append(c)
        for c in elegidos[:cuantos]:
            n += 1
            filas.append(guardar_clip(persona, n, c, nat, sr))
with open(os.path.join(SALIDA, "referencias.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(filas[0])); w.writeheader(); w.writerows(filas)
for r in filas:
    print("{clip} | {segundos} s | {sr} Hz | {origen} | fluidez {fluidez} | pausas {pausas_internas} | coincide {coincide_palabras} {revisar}\n    TXT: {texto}\n    Whisper del clip: {whisper_clip}".format(**r))
