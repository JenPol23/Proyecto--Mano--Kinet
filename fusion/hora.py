"""
hora.py  -  CORRE EN EL PC (py -3.11)
Fecha y hora del reloj del PC con la voz CLONADA de un integrante. Suena en la mano por WiFi (mano_wifi.py ->
firmware_mano/wifi_hora.py); el Bluetooth no se usa aqui.

- Hora: la frase entera ya aprobada de Doby, tal cual: <doby>/voz_cache_f5/<voz_doby>/hora/hora_HHMM_<md5>.wav
  ("Son las tres y treinta y cinco de la tarde."; Doby dice "de la madrugada" de 1:00 a 5:59 y "del mediodia"
  de 12:00 a 12:59). texto_hora() es la misma regla de Doby (pc/hora.py), solo para mostrarla en pantalla.
- Fecha: "Hoy es jueves doce de noviembre." (dia 1 = "uno", sin año), generada una vez por
  fusion/herramientas/generar_fechas.py en voces_clonadas/fecha/<persona>/fecha_AAAAMMDD_<md5>.wav.
  El dia de la semana depende del año: hay una frase por FECHA del calendario (rango_fechas de hora.json).
- Todo en 16 kHz, mono, 16 bits (lo que suena en el MAX98357). Nada se guarda en la placa.
- Configuracion: fusion/hora.json. Los nombres NO pasan por aqui (siguen con voces/ y "voz a b" por BLE).

Uso (sin hardware):
  py -3.11 fusion/hora.py                                   que sonaria ahora, con cada voz
  py -3.11 fusion/hora.py --fecha 2026-12-01 --a-las 00:01  otra fecha y hora
  py -3.11 fusion/hora.py --cobertura                       cuantas horas y fechas hay por voz
Con la mano (WiFi):
  py -3.11 fusion/hora.py --decir --voz lina                fecha de hoy y hora actual en la mano
  py -3.11 fusion/hora.py --decir --voz lina --ip 192.168.43.228    sin buscar mano.local
  py -3.11 fusion/hora.py --decir --voz lina --pc           plan B: por los parlantes del PC, sin WiFi
  Cada vez agrega una fila a fusion/registros/tiempos_hora.csv (tambien si falla).
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys
import time
import wave
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)

from reconocer import normalizar   # noqa: E402  (la misma de Doby: sin tildes ni signos)

RUTA_CONFIG = os.path.join(AQUI, "hora.json")
RUTA_TIEMPOS = os.path.join(AQUI, "registros", "tiempos_hora.csv")
PAUSA_PC = 0.4                      # s entre la fecha y la hora cuando suenan en el PC (en la placa ~0,9 s)
COLUMNAS = ["fecha_hora", "persona", "hora_dicha", "como", "ms_buscar", "seg_fecha", "ms_fecha", "seg_hora",
            "ms_hora", "ms_total", "resultado", "mensaje"]
TASA = 16000
SIMILITUD_MINIMA = 0.95             # = Doby (generar_hora.py)

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
# Las mismas palabras que Doby (pc/hora.py), para que fecha y hora suenen igual
HORAS = ["doce", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once"]
UNIDADES = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]
ESPECIALES = {10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince", 16: "dieciséis",
              17: "diecisiete", 18: "dieciocho", 19: "diecinueve", 20: "veinte", 21: "veintiuno", 22: "veintidós",
              23: "veintitrés", 24: "veinticuatro", 25: "veinticinco", 26: "veintiséis", 27: "veintisiete",
              28: "veintiocho", 29: "veintinueve"}
DECENAS = {3: "treinta", 4: "cuarenta", 5: "cincuenta"}


class ErrorHora(Exception):
    pass


# ---------------- Textos ----------------
def numero(n):
    """1..59 en palabras (= Doby): 1 -> 'uno', 23 -> 'veintitrés', 31 -> 'treinta y uno'."""
    if not 1 <= n <= 59:
        raise ValueError(n)
    if n < 10:
        return UNIDADES[n]
    if n in ESPECIALES:
        return ESPECIALES[n]
    return DECENAS[n // 10] + ("" if n % 10 == 0 else " y " + UNIDADES[n % 10])


def texto_fecha(d):
    """date(2026, 11, 12) -> 'Hoy es jueves doce de noviembre.'"""
    return "Hoy es {} {} de {}.".format(DIAS[d.weekday()], numero(d.day), MESES[d.month - 1])


def momento(h):
    """= Doby: madrugada 1-5, mañana 6-11, mediodía 12, tarde 13-18, noche 19-23 y 0."""
    if 1 <= h <= 5:
        return "de la madrugada"
    if 6 <= h <= 11:
        return "de la mañana"
    if h == 12:
        return "del mediodía"
    if 13 <= h <= 18:
        return "de la tarde"
    return "de la noche"


def texto_hora(h, m):
    """= texto() de Doby: (21, 23) -> 'Son las nueve y veintitrés de la noche.' (lo que dice el audio)."""
    inicio = "Es la una" if h % 12 == 1 else "Son las " + HORAS[h % 12]
    minutos = "en punto" if m == 0 else "y " + numero(m)
    return "{} {} {}.".format(inicio, minutos, momento(h))


def huella(texto):
    return hashlib.md5(texto.encode("utf-8")).hexdigest()[:8]


def nombre_fecha(d):
    """fecha_AAAAMMDD_<md5 del texto>.wav: si cambia el texto, cambia el archivo (como Doby)."""
    return "fecha_{:%Y%m%d}_{}.wav".format(d, huella(texto_fecha(d)))


# ---------------- Control de lo generado (lo usa generar_fechas.py) ----------------
def sin_cifras(texto):
    """Lo que escribio Whisper, normalizado y con las cifras en palabras: 'Hoy es jueves 12 de noviembre' ->
    'hoy es jueves doce de noviembre'."""
    salida = []
    for p in normalizar(texto).split():
        if p.isdigit() and 1 <= int(p) <= 59:
            p = normalizar(numero(int(p)))
        salida.append(p)
    return " ".join(salida)


def fecha_ok(oido, d):
    """(acepta, similitud): similitud >= SIMILITUD_MINIMA y EXACTAMENTE '<dia> <numero> de <mes>' (como el
    control estricto de Doby para la hora)."""
    esperado = normalizar(texto_fecha(d))
    oido = sin_cifras(oido)
    sim = SequenceMatcher(None, oido, esperado).ratio()
    nucleo = normalizar("{} {} de {}".format(DIAS[d.weekday()], numero(d.day), MESES[d.month - 1]))
    return sim >= SIMILITUD_MINIMA and re.search(r"\b{}\b".format(re.escape(nucleo)), oido) is not None, sim


# ---------------- Configuracion y archivos ----------------
@dataclass
class Frase:
    tipo: str           # 'fecha' | 'hora'
    texto: str
    ruta: str


class Config:
    def __init__(self, ruta=RUTA_CONFIG):
        with open(ruta, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.personas = self.cfg["personas"]
        self.orden = [p for p in self.cfg["orden_menu"] if p in self.personas]
        r = self.cfg["rango_fechas"]
        self.desde = date.fromisoformat(r["desde"])
        self.hasta = date.fromisoformat(r["hasta"])

    def mostrar(self, persona):
        return self.personas[persona]["mostrar"]

    def carpeta_horas(self, persona):
        return os.path.normpath(self.cfg["horas"].format(doby=self.cfg["doby"],
                                                         voz_doby=self.personas[persona]["voz_doby"]))

    def carpeta_fechas(self, persona):
        return os.path.normpath(os.path.join(RAIZ, self.cfg["fechas"].format(persona=persona)))

    def ruta_hora(self, persona, h, m):
        """La frase de Doby de esa hora, o None. (Doby: hora_HHMM_<md5>.wav)"""
        rutas = sorted(glob.glob(os.path.join(self.carpeta_horas(persona), "hora_{:02d}{:02d}_*.wav".format(h, m))))
        return rutas[0] if rutas else None

    def ruta_fecha(self, persona, d):
        ruta = os.path.join(self.carpeta_fechas(persona), nombre_fecha(d))
        return ruta if os.path.exists(ruta) else None

    def fechas(self):
        """Todas las fechas de rango_fechas (una frase por fecha del calendario)."""
        return [self.desde + timedelta(n) for n in range((self.hasta - self.desde).days + 1)]

    def piloto(self):
        p = self.cfg["piloto"]
        return p["persona"], [date.fromisoformat(f) for f in p["fechas"]]


def leer_pcm(ruta):
    """Bytes PCM de un WAV de 16 kHz, mono, 16 bits. Lanza ErrorHora si no existe o tiene otro formato."""
    try:
        with wave.open(ruta, "rb") as w:
            formato = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            if formato != (1, 2, TASA):
                raise ErrorHora("{} no es 16 kHz mono 16 bits: {}".format(os.path.basename(ruta), formato))
            return w.readframes(w.getnframes())
    except (OSError, EOFError, wave.Error) as e:
        raise ErrorHora("No se pudo leer {} ({})".format(os.path.basename(ruta), e))


def elegir(config, persona, ahora):
    """([Frase de la fecha, Frase de la hora], aviso). Si falta la fecha suena solo la hora (aviso); si falta la
    hora no suena nada ([] y aviso)."""
    if persona not in config.personas:
        return [], "Voz desconocida: {}".format(persona)
    nombre = config.mostrar(persona)
    ruta_h = config.ruta_hora(persona, ahora.hour, ahora.minute)
    if ruta_h is None:
        return [], "Falta audio de la hora {:%H:%M} ({})".format(ahora, nombre)
    frases = [Frase("hora", texto_hora(ahora.hour, ahora.minute), ruta_h)]
    d = ahora.date()
    ruta_f = config.ruta_fecha(persona, d)
    if ruta_f is None:
        return frases, "Falta audio de la fecha {:%d/%m/%Y} ({}): suena solo la hora".format(d, nombre)
    return [Frase("fecha", texto_fecha(d), ruta_f)] + frases, ""


# ---------------- En la mano, por WiFi ----------------
def decir(config, persona, ahora=None, ip=None, secretos=None, ruta_csv=RUTA_TIEMPOS, en_pc=False, sonar=None):
    """Hace sonar en la mano la fecha y la hora de 'ahora' (por defecto: el reloj del PC al llamar) con la voz de
    'persona'. Nunca lanza errores: devuelve {'resultado': 'ok'|'falta_audio'|'sin_wifi'|'error', 'mensaje': texto
    para la pantalla, ...tiempos} y agrega una fila a tiempos_hora.csv.
    en_pc=True (plan B, --voz-pc): los mismos WAV suenan por los parlantes del PC (voz_pc.sonar), sin WiFi."""
    import mano_wifi                                    # solo aqui: hora.py sigue sirviendo sin red
    ahora = (ahora or datetime.now()).replace(second=0, microsecond=0)
    fila = {"fecha_hora": datetime.now().isoformat(sep=" ", timespec="seconds"), "persona": persona,
            "hora_dicha": "{:%Y-%m-%d %H:%M}".format(ahora), "resultado": "error", "mensaje": ""}
    t = time.perf_counter()
    frases, aviso = elegir(config, persona, ahora)
    try:
        if not frases:
            fila.update(resultado="falta_audio", mensaje=aviso)
            return fila
        audios = [(f, leer_pcm(f.ruta)) for f in frases]
        if en_pc:
            if sonar is None:
                from voz_pc import sonar
            fila["como"] = "pc"
            for k, (f, pcm) in enumerate(audios):
                if k:
                    time.sleep(PAUSA_PC)
                t_frase = time.perf_counter()
                sonar(pcm)
                fila["seg_" + f.tipo] = round(len(pcm) / (2 * TASA), 2)
                fila["ms_" + f.tipo] = round((time.perf_counter() - t_frase) * 1000)
        else:
            with mano_wifi.conectar(secretos, ip) as mano:
                fila.update(como=mano.como, ms_buscar=round(mano.ms_buscar))
                for f, pcm in audios:
                    fila["seg_" + f.tipo] = round(len(pcm) / (2 * TASA), 2)
                    fila["ms_" + f.tipo] = round(mano.wav(pcm))
        fila.update(resultado="ok", mensaje=aviso or "{}: {}".format(config.mostrar(persona),
                                                                     " ".join(f.texto for f in frases)))
    except mano_wifi.ErrorWifi as e:
        fila.update(resultado="sin_wifi" if str(e).startswith("Sin WiFi") else "error", mensaje=str(e))
    except ErrorHora as e:
        fila.update(resultado="falta_audio", mensaje=str(e))
    except Exception as e:                              # nada de aqui puede tumbar al que llama
        fila.update(resultado="error", mensaje="Error inesperado: {}".format(e))
    finally:
        fila["ms_total"] = round((time.perf_counter() - t) * 1000)
        anotar(fila, ruta_csv)
    return fila


def anotar(fila, ruta=RUTA_TIEMPOS):
    """Agrega una fila a tiempos_hora.csv (solo se agregan filas). Si no se puede escribir, sigue igual."""
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        nuevo = not os.path.exists(ruta)
        with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS)
            if nuevo:
                w.writeheader()
            w.writerow({k: fila.get(k, "") for k in COLUMNAS})
    except OSError as e:
        print("(no se pudo anotar en {}: {})".format(os.path.basename(ruta), e))


# ---------------- Consola ----------------
def cobertura(config):
    fechas = config.fechas()
    print("Rango de fechas: {} a {} ({} fechas)".format(config.desde, config.hasta, len(fechas)))
    for p in config.orden:
        horas = sum(1 for h in range(24) for m in range(60) if config.ruta_hora(p, h, m))
        n_fechas = sum(1 for d in fechas if config.ruta_fecha(p, d))
        print("  {:10} horas {:4}/1440   fechas {:4}/{}".format(config.mostrar(p), horas, n_fechas, len(fechas)))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Fecha y hora con la voz clonada (solo lógica)")
    parser.add_argument("--fecha", help="AAAA-MM-DD (por defecto hoy)")
    parser.add_argument("--a-las", help="HH:MM (por defecto ahora)")
    parser.add_argument("--cobertura", action="store_true")
    parser.add_argument("--decir", action="store_true", help="hacerla sonar en la mano por WiFi (fecha y hora de ahora)")
    parser.add_argument("--voz", help="con --decir: jeanpaul, harry, lina o paula")
    parser.add_argument("--ip", help="con --decir: IP de la mano (si no: mano.local y luego IP_FIJA de secretos.py)")
    parser.add_argument("--pc", action="store_true", help="con --decir: por los parlantes del PC (plan B, sin WiFi)")
    args = parser.parse_args()
    config = Config()
    if args.cobertura:
        cobertura(config)
        return 0
    if args.decir:
        if args.voz not in config.personas:
            print("Falta --voz: una de {}".format(", ".join(config.orden)))
            return 2
        r = decir(config, args.voz, ip=args.ip, en_pc=args.pc)
        print(r["mensaje"])
        if r["resultado"] == "ok":
            print("  por {} (buscar {} ms)  fecha {} ms  hora {} ms  total {} ms".format(
                r.get("como"), r.get("ms_buscar"), r.get("ms_fecha", "-"), r.get("ms_hora"), r["ms_total"]))
        return 0 if r["resultado"] == "ok" else 1
    ahora = datetime.now().replace(second=0, microsecond=0)
    if args.fecha:
        d = date.fromisoformat(args.fecha)
        ahora = ahora.replace(year=d.year, month=d.month, day=d.day)
    if args.a_las:
        h, m = (int(x) for x in args.a_las.split(":"))
        ahora = ahora.replace(hour=h, minute=m)
    print("{:%Y-%m-%d %H:%M}".format(ahora))
    for p in config.orden:
        frases, aviso = elegir(config, p, ahora)
        print("\n{}".format(config.mostrar(p)))
        for f in frases:
            print("  {:5} {:48} {}".format(f.tipo, f.texto, os.path.basename(f.ruta)))
        if aviso:
            print("  ! " + aviso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
