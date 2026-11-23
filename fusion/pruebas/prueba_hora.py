"""
prueba_hora.py  -  CORRE EN EL PC (py -3.11), SIN HARDWARE NI F5
Prueba la logica de fusion/hora.py y la parte sin F5 de fusion/herramientas/generar_fechas.py:
textos de fecha y hora, nombres de archivo, control de Whisper (fecha_ok), hora.json, eleccion de las frases
y lectura de los WAV. Si existe la carpeta de Doby, comprueba ademas que las 1440 horas de las 4 voces se
encuentran y que su texto coincide con texto_hora() (el md5 del nombre del archivo es el del texto).

Uso: py -3.11 fusion/pruebas/prueba_hora.py
"""

import glob
import json
import os
import re
import sys
import tempfile
import wave
from datetime import date, datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
FUSION = os.path.dirname(AQUI)
sys.path.insert(0, FUSION)
sys.path.insert(0, os.path.join(FUSION, "herramientas"))

import hora  # noqa: E402

fallas = []


def chequeo(nombre, ok, detalle=""):
    print("{}   {}{}".format("PASA " if ok else "FALLA", nombre, "  " + detalle if detalle else ""))
    if not ok:
        fallas.append(nombre)


def wav(ruta, segundos=0.2, tasa=16000):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(tasa)
        w.writeframes(b"\1\0" * int(segundos * tasa))


try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

print("1. Textos")
casos_fecha = {date(2026, 11, 12): "Hoy es jueves doce de noviembre.",
               date(2026, 12, 1): "Hoy es martes uno de diciembre.",
               date(2026, 11, 16): "Hoy es lunes dieciséis de noviembre.",
               date(2027, 1, 22): "Hoy es viernes veintidós de enero.",
               date(2026, 12, 30): "Hoy es miércoles treinta de diciembre.",
               date(2027, 1, 31): "Hoy es domingo treinta y uno de enero.",
               date(2026, 11, 21): "Hoy es sábado veintiuno de noviembre."}
for d, esperado in casos_fecha.items():
    chequeo("texto_fecha {}".format(d), hora.texto_fecha(d) == esperado, hora.texto_fecha(d))
casos_hora = {(21, 23): "Son las nueve y veintitrés de la noche.", (13, 0): "Es la una en punto de la tarde.",
              (0, 1): "Son las doce y uno de la noche.", (12, 30): "Son las doce y treinta del mediodía.",
              (3, 5): "Son las tres y cinco de la madrugada.", (7, 45): "Son las siete y cuarenta y cinco de la mañana.",
              (1, 0): "Es la una en punto de la madrugada.", (23, 59): "Son las once y cincuenta y nueve de la noche."}
for (h, m), esperado in casos_hora.items():
    chequeo("texto_hora {:02d}:{:02d}".format(h, m), hora.texto_hora(h, m) == esperado, hora.texto_hora(h, m))

dias_2028 = [date(2028, 1, 1) + timedelta(n) for n in range(366)]       # año bisiesto
nombres = [hora.nombre_fecha(d) for d in dias_2028]
chequeo("366 fechas de 2028: un nombre distinto por fecha", len(set(nombres)) == 366)
chequeo("nombres de archivo: solo [a-z0-9_.]", all(re.fullmatch(r"fecha_\d{8}_[0-9a-f]{8}\.wav", n) for n in nombres))
chequeo("29 de febrero de 2028", hora.texto_fecha(date(2028, 2, 29)) == "Hoy es martes veintinueve de febrero.")
chequeo("todos los textos de fecha terminan en un mes", all(hora.texto_fecha(d).rstrip(".").split()[-1] in hora.MESES
                                                            for d in dias_2028))

print("\n2. Control de Whisper (fecha_ok)")
d = date(2026, 11, 12)
for oido, debe in (("Hoy es jueves 12 de noviembre.", True), ("hoy es jueves doce de noviembre", True),
                   ("Hoy es viernes 12 de noviembre.", False), ("Hoy es jueves 2 de noviembre.", False),
                   ("Hoy es jueves 12 de diciembre.", False), ("", False)):
    ok, sim = hora.fecha_ok(oido, d)
    chequeo("'{}' -> {}".format(oido, "acepta" if debe else "rechaza"), ok == debe, "sim {:.3f}".format(sim))
chequeo("'1 de diciembre' = 'uno de diciembre'", hora.fecha_ok("Hoy es martes 1 de diciembre.", date(2026, 12, 1))[0])
chequeo("'31 de enero' = 'treinta y uno de enero'", hora.fecha_ok("Hoy es domingo 31 de enero.", date(2027, 1, 31))[0])

print("\n3. hora.json real")
config = hora.Config()
chequeo("4 voces en el menú, en orden", config.orden == ["jeanpaul", "harry", "lina", "paula"])
chequeo("mapeo jeanpaul->jenpol, paula->camila", config.personas["jeanpaul"]["voz_doby"] == "jenpol"
        and config.personas["paula"]["voz_doby"] == "camila")
chequeo("Harry se muestra solo como 'Harry'", config.mostrar("harry") == "Harry")
chequeo("rango de fechas: 2026-11-12 a 2026-12-31 (50 fechas)", len(config.fechas()) == 50 and
        config.fechas()[0] == date(2026, 11, 12) and config.fechas()[-1] == date(2026, 12, 31),
        "{} fechas".format(len(config.fechas())))
persona, piloto = config.piloto()
chequeo("piloto: Jean Paul, 7 fechas con los 7 días de la semana", persona == "jeanpaul" and len(piloto) == 7 and
        sorted(d.weekday() for d in piloto) == list(range(7)))
chequeo("piloto: todas dentro del rango (sirven para el total)", all(d in config.fechas() for d in piloto))
chequeo("las fechas van fuera de voces/ (voces_clonadas/)",
        os.sep + "voces_clonadas" + os.sep in config.carpeta_fechas("lina") + os.sep)

print("\n4. Elegir las frases (carpetas de prueba)")
with tempfile.TemporaryDirectory() as tmp:
    doby = os.path.join(tmp, "doby")
    cfg = json.load(open(hora.RUTA_CONFIG, encoding="utf-8"))
    cfg["doby"] = doby
    cfg["fechas"] = os.path.join(tmp, "fechas", "{persona}")
    ruta_cfg = os.path.join(tmp, "hora.json")
    json.dump(cfg, open(ruta_cfg, "w", encoding="utf-8"))
    c = hora.Config(ruta_cfg)
    ahora = datetime(2026, 11, 12, 15, 35)
    wav(os.path.join(doby, "voz_cache_f5", "lina", "hora", "hora_1535_{}.wav".format(hora.huella(hora.texto_hora(15, 35)))))
    frases, aviso = hora.elegir(c, "lina", ahora)
    chequeo("sin la fecha -> suena solo la hora, con aviso", [f.tipo for f in frases] == ["hora"] and "fecha" in aviso, aviso)
    wav(os.path.join(c.carpeta_fechas("lina"), hora.nombre_fecha(ahora.date())))
    frases, aviso = hora.elegir(c, "lina", ahora)
    chequeo("fecha y hora -> [fecha, hora], sin aviso", [f.tipo for f in frases] == ["fecha", "hora"] and not aviso)
    chequeo("textos de lo que suena", frases[0].texto == "Hoy es jueves doce de noviembre." and
            frases[1].texto == "Son las tres y treinta y cinco de la tarde.")
    frases, aviso = hora.elegir(c, "lina", ahora.replace(minute=36))
    chequeo("sin la hora -> no suena nada", frases == [] and "hora 15:36" in aviso, aviso)
    chequeo("voz desconocida", hora.elegir(c, "pedro", ahora)[0] == [])
    chequeo("leer_pcm de un WAV de 16 kHz (0,2 s = 6400 bytes)",
            len(hora.leer_pcm(hora.elegir(c, "lina", ahora)[0][0].ruta)) == 6400)
    otro = os.path.join(tmp, "otro.wav")
    wav(otro, tasa=24000)
    for ruta, que in ((otro, "otra tasa"), (os.path.join(tmp, "no.wav"), "no existe")):
        try:
            hora.leer_pcm(ruta)
            chequeo("leer_pcm: " + que + " -> error", False)
        except hora.ErrorHora:
            chequeo("leer_pcm: " + que + " -> error", True)

    print("\n5. generar_fechas.py sin F5")
    import generar_fechas as gf
    chequeo("se importa sin cargar F5 ni el Motor de Doby", "generar_voces_f5" not in sys.modules
            and "f5_tts" not in sys.modules)
    chequeo("carga nuestro hora.py como 'hora_mano'", gf.hm.texto_fecha(date(2026, 11, 12)) == hora.texto_fecha(date(2026, 11, 12))
            and sys.modules.get("hora_mano") is gf.hm)
    principal, revisar = gf.rutas(c, "lina", date(2026, 11, 12))
    chequeo("rutas: carpeta y _revisar_de_oido/", principal.endswith(hora.nombre_fecha(date(2026, 11, 12))) and
            os.sep + "_revisar_de_oido" + os.sep in revisar)
    seg = gf.estimar(c, seg_por_fecha=4.0)
    chequeo("estimar: 50 fechas x 4 voces x 4 s (menos la que ya existe)", abs(seg - (50 * 4 - 1) * 4.0) < 1e-6,
            "{:.0f} min".format(seg / 60))

print("\n6. Horas de Doby (si la carpeta existe)")
if os.path.isdir(config.cfg["doby"]):
    for p in config.orden:
        faltan, distintas = [], []
        for h in range(24):
            for m in range(60):
                ruta = config.ruta_hora(p, h, m)
                if ruta is None:
                    faltan.append("{:02d}{:02d}".format(h, m))
                elif not os.path.basename(ruta).endswith("_{}.wav".format(hora.huella(hora.texto_hora(h, m)))):
                    distintas.append("{:02d}{:02d}".format(h, m))
        chequeo("{}: las 1440 horas existen y su texto = texto_hora()".format(config.mostrar(p)),
                not faltan and not distintas, "faltan {} distintas {}".format(faltan[:3], distintas[:3]))
    muestra = config.ruta_hora("paula", 15, 35)
    chequeo("las frases de Doby son 16 kHz mono 16 bits", len(hora.leer_pcm(muestra)) > 0)
else:
    print("  (no está {}: se salta)".format(config.cfg["doby"]))

print("\n{} fallas".format(len(fallas)))
sys.exit(1 if fallas else 0)
