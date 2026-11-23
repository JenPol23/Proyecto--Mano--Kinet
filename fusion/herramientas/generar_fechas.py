"""
generar_fechas.py  -  CORRE EN EL PC CON EL venv_f5 DE DOBY (F5-TTS + Whisper, sin internet)
Genera UNA VEZ las frases "Hoy es jueves doce de noviembre." con la voz clonada de cada integrante, en
voces_clonadas/fecha/<persona>/fecha_AAAAMMDD_<md5>.wav (16 kHz, mono, 16 bits). Unica excepcion a "sin voces
clonadas": solo fecha y hora. Los nombres siguen con la grabacion original de voces/.

Uso (desde la carpeta de ESTE proyecto):
  C:\\Users\\miran\\proyectoDoby\\venv_f5\\Scripts\\python.exe fusion/herramientas/generar_fechas.py --piloto
  ...python.exe fusion/herramientas/generar_fechas.py --estimar                 (no genera: tiempo del total)
  ...python.exe fusion/herramientas/generar_fechas.py --persona lina            todo rango_fechas de hora.json
  ...python.exe fusion/herramientas/generar_fechas.py --aprobar lina 2026-11-16  de _revisar_de_oido/ a la carpeta
  ...python.exe fusion/herramientas/generar_fechas.py --rechazar lina 2026-11-16 borrar esa y generar otra

- Usa el Motor de Doby SOLO LEYENDO (entrenamiento/generar_voces_f5.py: modelo F5-Spanish local en
  <doby>/modelos/f5-spanish, referencias de <doby>/entrenamiento/referencias_voz_f5.json, semillas fijas,
  Whisper medium). Nada de Doby se modifica. HF_HUB_OFFLINE=1 (lo pone generar_voces_f5).
- Control igual que generar_hora.py de Doby: hasta 6 intentos (3 con la referencia principal y 3 con los
  respaldos); se acepta el primero con similitud Whisper >= 0.95 Y la fecha exacta ("jueves doce de
  noviembre", hora.fecha_ok). Si ninguno pasa, el mejor va a _revisar_de_oido/ para decidir de oido.
- Se puede retomar: salta lo que ya existe (en la carpeta o en _revisar_de_oido/).
- Registro: voces_clonadas/fecha/<persona>/generacion.csv (una fila por intento, con los segundos de generacion).
- Nuestro hora.py se carga como "hora_mano": Doby tiene su propio pc/hora.py y voz_clonada.py lo importa.
"""

import argparse
import csv
import importlib.util
import os
import statistics
import sys
import time
import wave
from datetime import date, datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
FUSION = os.path.dirname(AQUI)
RAIZ = os.path.dirname(FUSION)


def cargar_hora_mano():
    """fusion/hora.py como modulo 'hora_mano' (sin chocar con pc/hora.py de Doby)."""
    if FUSION not in sys.path:
        sys.path.append(FUSION)                       # AL FINAL: 'hora', 'config', 'tts' deben ser los de Doby
    spec = importlib.util.spec_from_file_location("hora_mano", os.path.join(FUSION, "hora.py"))
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["hora_mano"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


hm = cargar_hora_mano()
COLUMNAS = ["fecha_hora", "persona", "fecha", "texto", "intento", "referencia", "texto_whisper", "similitud",
            "duracion_s", "seg_intento", "estado"]


def doby(config):
    """Importa generar_voces_f5 de Doby (carga torch y F5; solo aqui, nunca en las pruebas)."""
    raiz_doby = config.cfg["doby"]
    for sub in ("pc", "entrenamiento"):
        ruta = os.path.join(raiz_doby, sub)
        if ruta not in sys.path:
            sys.path.insert(0, ruta)
    import generar_voces_f5 as g                       # noqa: E402
    return g


def rutas(config, persona, d):
    carpeta = config.carpeta_fechas(persona)
    nombre = hm.nombre_fecha(d)
    return os.path.join(carpeta, nombre), os.path.join(carpeta, "_revisar_de_oido", nombre)


def guardar_wav(ruta, pcm):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    temporal = ruta + ".tmp"
    with wave.open(temporal, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(hm.TASA)
        w.writeframes(pcm.astype("<i2").tobytes())
    os.replace(temporal, ruta)


def anotar(config, persona, filas):
    ruta = os.path.join(config.carpeta_fechas(persona), "generacion.csv")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def generar(config, persona, fechas, desde_intento=1):
    """Genera las fechas que falten de 'persona'. Devuelve {'aprobada': n, 'revisar_de_oido': n, 'seg': [..]}."""
    voz = config.personas[persona]["voz_doby"]
    pendientes = [d for d in fechas if not any(os.path.exists(r) for r in rutas(config, persona, d))]
    print("{} ({}): {} de {} fechas pendientes".format(config.mostrar(persona), voz, len(pendientes), len(fechas)))
    cuenta = {"aprobada": 0, "revisar_de_oido": 0, "seg": []}
    if not pendientes:
        return cuenta
    g = doby(config)
    clips = g.cargar_referencias()[voz]
    t = time.perf_counter()
    motor = g.Motor()
    print("Motor de Doby cargado en {:.1f} s".format(time.perf_counter() - t))
    inicio = time.perf_counter()
    for n, d in enumerate(pendientes, 1):
        t_fecha = time.perf_counter()
        texto, candidatos = hm.texto_fecha(d), []
        for intento, clip in g.plan_intentos(clips, desde_intento):
            t_int = time.perf_counter()
            pcm, _ = motor.generar(voz, clip, texto, g.semilla(voz, "fecha_{:%Y%m%d}".format(d), intento))
            oido = motor.stt.transcribir(pcm.astype("float32") / 32768)
            ok, sim = hm.fecha_ok(oido, d)
            candidatos.append(((ok, sim), pcm, {
                "fecha_hora": datetime.now().isoformat(sep=" ", timespec="seconds"), "persona": persona,
                "fecha": d.isoformat(), "texto": texto, "intento": intento, "referencia": clip, "texto_whisper": oido,
                "similitud": "{:.3f}".format(sim), "duracion_s": "{:.2f}".format(len(pcm) / hm.TASA),
                "seg_intento": "{:.2f}".format(time.perf_counter() - t_int), "estado": "descartada"}))
            if ok:
                break
        mejor = max(candidatos, key=lambda c: c[0])
        (ok, sim), pcm, fila = mejor
        principal, revisar = rutas(config, persona, d)
        estado = "aprobada" if ok else "revisar_de_oido"
        guardar_wav(principal if ok else revisar, pcm)
        fila["estado"] = estado
        anotar(config, persona, [c[2] for c in candidatos])
        cuenta[estado] += 1
        cuenta["seg"].append(time.perf_counter() - t_fecha)
        print("  {} {:46} {} intento(s)  {:.3f}  {:5.2f} s  {}{}".format(
            d, texto, len(candidatos), sim, len(pcm) / hm.TASA, estado,
            "" if ok else '  Whisper: "{}"'.format(fila["texto_whisper"])))
        if n % 30 == 0:
            print("  {}/{}  ({:.1f} min)".format(n, len(pendientes), (time.perf_counter() - inicio) / 60))
    return cuenta


def estimar(config, seg_por_fecha=None):
    """Cuanto tardaria generar todo rango_fechas para las 4 voces, con lo medido en generacion.csv."""
    if seg_por_fecha is None:
        tiempos = []
        for p in config.orden:
            ruta = os.path.join(config.carpeta_fechas(p), "generacion.csv")
            if not os.path.exists(ruta):
                continue
            with open(ruta, newline="", encoding="utf-8-sig") as f:
                por_fecha = {}
                for fila in csv.DictReader(f):
                    por_fecha[fila["fecha"]] = por_fecha.get(fila["fecha"], 0.0) + float(fila["seg_intento"] or 0)
                tiempos += list(por_fecha.values())
        if not tiempos:
            print("Todavía no hay nada medido: corre primero --piloto.")
            return None
        seg_por_fecha = statistics.mean(tiempos)
    total = len(config.fechas()) * len(config.orden)
    faltan = sum(1 for p in config.orden for d in config.fechas()
                 if not any(os.path.exists(r) for r in rutas(config, p, d)))
    print("Medido: {:.1f} s por fecha (incluye reintentos y Whisper).".format(seg_por_fecha))
    print("Total: {} fechas x {} voces = {}; faltan {} -> unos {:.0f} min ({:.1f} h), sin contar la carga del "
          "modelo (~1 min por voz).".format(len(config.fechas()), len(config.orden), total, faltan,
                                            faltan * seg_por_fecha / 60, faltan * seg_por_fecha / 3600))
    return faltan * seg_por_fecha


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Frases de la fecha con la voz clonada (F5 de Doby)")
    parser.add_argument("--piloto", action="store_true", help="las 7 fechas del piloto de hora.json")
    parser.add_argument("--persona", help="todo rango_fechas para esta persona (jeanpaul, harry, lina, paula)")
    parser.add_argument("--estimar", action="store_true", help="no genera: estima el tiempo de todo")
    parser.add_argument("--aprobar", nargs=2, metavar=("PERSONA", "AAAA-MM-DD"))
    parser.add_argument("--rechazar", nargs=2, metavar=("PERSONA", "AAAA-MM-DD"))
    args = parser.parse_args()
    config = hm.Config()

    if args.estimar:
        estimar(config)
    elif args.aprobar:
        persona, d = args.aprobar[0], date.fromisoformat(args.aprobar[1])
        principal, revisar = rutas(config, persona, d)
        if not os.path.exists(revisar):
            sys.exit("No hay audio en revisión para {} / {}.".format(persona, d))
        os.replace(revisar, principal)
        print("Aprobada de oído:", os.path.relpath(principal, RAIZ))
    elif args.rechazar:
        persona, d = args.rechazar[0], date.fromisoformat(args.rechazar[1])
        for r in rutas(config, persona, d):
            if os.path.exists(r):
                os.remove(r)                          # solo audios generados por este script
        generar(config, persona, [d], desde_intento=7)    # semillas nuevas
    elif args.piloto:
        persona, fechas = config.piloto()
        t = time.perf_counter()
        cuenta = generar(config, persona, fechas)
        print("\nPiloto: {} aprobadas, {} para revisar de oído, {:.1f} min".format(
            cuenta["aprobada"], cuenta["revisar_de_oido"], (time.perf_counter() - t) / 60))
        print("Escúchalas en {}".format(os.path.relpath(config.carpeta_fechas(persona), RAIZ)))
        if cuenta["seg"]:
            estimar(config, statistics.mean(cuenta["seg"]))
    elif args.persona:
        if args.persona not in config.personas:
            sys.exit("Persona desconocida: {}".format(args.persona))
        cuenta = generar(config, args.persona, config.fechas())
        print("\nListo: {} aprobadas, {} para revisar de oído".format(cuenta["aprobada"], cuenta["revisar_de_oido"]))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
