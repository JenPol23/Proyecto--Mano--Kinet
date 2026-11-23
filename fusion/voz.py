"""
voz.py  -  CORRE EN EL PC (py -3.11)
Voz de la fusion: la voz ORIGINAL grabada de cada integrante suena por el MAX98357 conectado a la ESP32 de la
mano. Sin microfono, sin reconocimiento de voz y sin voz sintetica: la entrada es el texto que salio del Kinect.

- Los audios se buscan con Integrantes.buscar_audio() de reconocer.py en voces/ (raiz del proyecto), respetando
  no_usar. Los originales solo se leen.
- Conversion (una vez por audio; intermedio en fusion/cache_audio/<Base>_<huella>.wav, la huella cambia si cambia el
  original o el procesado):
    ffmpeg decodifica a su frecuencia original -> mono (promedio de canales, como Doby) -> resample_poly a 16 kHz
    -> _pulir() basada en la de Doby (pc/tts.py): pasa-altos CORTE_GRAVES, pico x VOLUMEN (igual para todos),
    rampas de RAMPA_MS; sin silencio final (la placa pone las pausas). NO se recorta nada (RECORTAR_SILENCIO =
    False): los audios ya vienen cortados y el WAV dura lo mismo que el original.
- Para la placa: fusion/audios_placa/<base en minusculas>.wav (nombres fijos: la orden "voz" los nombra).
- Que suena: si lo reconocido es exactamente una de las 'frases' de integrantes.json y existe su grabacion, solo ese
  archivo ("voz lina_maldonado"); si no, las palabras sueltas ("voz tatiana maldonado"; la placa pone 250 ms).
- Si falta un audio (en el PC o en la placa): "Falta audio: <palabra>" y no suena nada; nunca se cae.
- Se envia por BLE con la misma conexion de consola_mano.py (Mano.hablar). Cada intento agrega una fila a
  fusion/registros/tiempos_voz.csv (nunca borra las anteriores).

Uso (desde la carpeta del proyecto; cerrar Thonny y cualquier otro programa conectado a la mano):
  py -3.11 fusion/voz.py --preparar                       WAV para la placa en fusion/audios_placa/
  py -3.11 fusion/voz.py --texto "Lina"                   solo suena (la mano no se mueve)
  py -3.11 fusion/voz.py --texto "Lina" --deletrear       la mano deletrea (ventana sincronizada) y al final suena
  (--sin-ventana: solo la consola). Antes de hablar se comprueba que la placa tenga el firmware con voz
  (orden "?" -> version:voz-2). La espera de voz_ok es la duracion del audio + 0,93 s de la placa + 5 s.
  Ctrl+C, Esc o q cortan enseguida y siempre se suelta el Bluetooth.
"""

import argparse
import csv
import hashlib
import os
import subprocess
import sys
import time
import wave
from datetime import datetime
from math import gcd

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)

import numpy as np                                     # noqa: E402
from scipy.signal import butter, resample_poly, sosfilt   # noqa: E402

import config_fusion as config                         # noqa: E402
from reconocer import Integrantes, interpretar, normalizar   # noqa: E402

CARPETA_CACHE = os.path.join(AQUI, "cache_audio")
CARPETA_PLACA = os.path.join(AQUI, "audios_placa")
RUTA_TIEMPOS = os.path.join(AQUI, "registros", "tiempos_voz.csv")
COLUMNAS_TIEMPOS = ["id_prueba", "fecha_hora", "texto", "palabras", "archivos", "seg_audio", "seg_hasta_ok",
                    "resultado"]
SEG_VENTANA = 0.01          # ventanas de 10 ms para detectar el silencio
VERSION_PROCESADO = 1       # subirlo si cambia el procesado: obliga a convertir de nuevo
BYTES_CABECERA_WAV = 44
COLA_PLACA = 0.93           # s que agrega la placa al final: 0,3 s de silencio + 630 ms de vaciado del I2S
MARGEN_VOZ = 5.0            # s de margen sobre la duracion del audio para esperar voz_ok
MSG_TIEMPO_MANO = "La mano no respondió a tiempo"   # = consola_mano.MSG_TIEMPO (sin importarlo aqui)


class ErrorAudio(Exception):
    pass


# ---------------- Procesado ----------------
def decodificar(ruta):
    """(muestras float32 mono, frecuencia original) de cualquier audio que abra ffmpeg."""
    try:
        info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                               "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", ruta],
                              capture_output=True, text=True, timeout=30)
        tasa, canales = (int(x) for x in info.stdout.strip().split(",")[:2])
        crudo = subprocess.run(["ffmpeg", "-v", "error", "-i", ruta, "-vn", "-f", "f32le", "-acodec", "pcm_f32le", "-"],
                               capture_output=True, timeout=60)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        raise ErrorAudio("ffmpeg no pudo leerlo ({})".format(type(e).__name__))
    if crudo.returncode != 0 or not crudo.stdout:
        raise ErrorAudio("ffmpeg no pudo leerlo")
    muestras = np.frombuffer(crudo.stdout, dtype="<f4")
    muestras = muestras[:len(muestras) // canales * canales].reshape(-1, canales)
    return muestras.mean(axis=1).astype(np.float32), tasa


def a_16k(muestras, tasa_real):
    """Remuestreo de calidad a 16 kHz (con filtro antialiasing), como tts.py."""
    if tasa_real == config.TASA:
        return muestras
    g = gcd(config.TASA, tasa_real)
    return resample_poly(muestras, config.TASA // g, tasa_real // g)


def recortar_silencio(audio):
    """Quita el silencio solo del inicio y del final. Devuelve (audio, seg_quitados_inicio, seg_quitados_final)."""
    if not config.RECORTAR_SILENCIO or len(audio) == 0:
        return audio, 0.0, 0.0
    # Se mide sobre una copia sin graves (el zumbido de fondo no cuenta como voz)
    filtro = butter(2, config.CORTE_GRAVES, btype="highpass", fs=config.TASA, output="sos")
    medido = sosfilt(filtro, audio - audio.mean())
    n = int(SEG_VENTANA * config.TASA)
    ventanas = len(medido) // n
    if ventanas == 0:
        return audio, 0.0, 0.0
    rms = np.sqrt(np.mean(medido[:ventanas * n].reshape(ventanas, n) ** 2, axis=1))
    umbral = rms.max() * 10 ** (config.UMBRAL_SILENCIO_DB / 20)
    con_voz = np.nonzero(rms > umbral)[0]
    if len(con_voz) == 0:
        return audio, 0.0, 0.0
    margen = int(config.MARGEN_SILENCIO_MS / 1000 * config.TASA)
    inicio = max(0, con_voz[0] * n - margen)
    fin = min(len(audio), (con_voz[-1] + 1) * n + margen)
    return audio[inicio:fin], inicio / config.TASA, (len(audio) - fin) / config.TASA


def _pulir(audio, silencio_final=config.SILENCIO_FINAL):
    """Basada en _pulir() de Doby (pc/tts.py), con CORTE_GRAVES y RAMPA_MS de config_fusion: quita graves, normaliza el volumen, suaviza inicio y final y agrega silencio."""
    audio = audio.astype(np.float32)
    audio -= audio.mean()

    filtro = butter(2, config.CORTE_GRAVES, btype="highpass", fs=config.TASA, output="sos")
    audio = sosfilt(filtro, audio)

    pico = np.max(np.abs(audio))
    if pico > 0:
        audio = audio / pico * config.VOLUMEN * 32767

    n = int(config.RAMPA_MS / 1000 * config.TASA)   # rampa corta para evitar "clics"
    rampa = np.linspace(0, 1, n)
    audio[:n] *= rampa
    audio[-n:] *= rampa[::-1]

    silencio = np.zeros(int(silencio_final * config.TASA), dtype=np.float32)
    return np.concatenate([audio, silencio]).astype(np.int16)


def silencio(segundos):
    return np.zeros(int(round(segundos * config.TASA)), dtype=np.int16)


# ---------------- Archivos ----------------
def huella(ruta):
    """Cambia si cambia el original (tamaño o fecha) o el procesado."""
    st = os.stat(ruta)
    datos = "|".join(str(x) for x in (os.path.relpath(ruta, RAIZ).lower(), st.st_size, st.st_mtime_ns,
                                      VERSION_PROCESADO, config.TASA, config.VOLUMEN, config.CORTE_GRAVES,
                                      config.RAMPA_MS, config.RECORTAR_SILENCIO, config.UMBRAL_SILENCIO_DB,
                                      config.MARGEN_SILENCIO_MS))
    return hashlib.md5(datos.encode("utf-8")).hexdigest()[:8]


def leer_wav(ruta):
    with wave.open(ruta, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").copy()


def guardar_wav(ruta, pcm):
    """WAV de 16 kHz, mono, 16 bits, con la cabecera estandar de 44 bytes (la que lee la placa)."""
    temporal = ruta + ".tmp"
    with wave.open(temporal, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.TASA)
        w.writeframes(pcm.astype("<i2").tobytes())
    os.replace(temporal, ruta)                      # nunca queda un .wav a medias


def nombre_placa(base):
    """'Lina_Maldonado' -> 'lina_maldonado' (la placa recibe la orden en minusculas)."""
    return base.lower()


def guardar_tiempos(fila, ruta=RUTA_TIEMPOS):
    """Agrega una fila al CSV. Devuelve un aviso si no se pudo (o '' si todo bien)."""
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        nuevo = not os.path.exists(ruta)
        with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS_TIEMPOS)
            if nuevo:
                w.writeheader()
            w.writerow(fila)
        return ""
    except OSError as e:
        return "No se pudo guardar tiempos_voz.csv ({}): ¿está abierto en Excel?".format(e.strerror or e)


# ---------------- Audios del grupo ----------------
class Audios:
    """Busca, convierte y prepara los audios originales. Base de Voz (BLE)."""

    def __init__(self, integrantes=None, carpeta_cache=CARPETA_CACHE, carpeta_placa=CARPETA_PLACA):
        self.integrantes = integrantes or Integrantes()
        self.carpeta_cache = carpeta_cache
        self.carpeta_placa = carpeta_placa
        self.ultimo = {}                            # info de la ultima conversion (para la consola)

    def palabra_procesada(self, base):
        """PCM int16 de un audio (pulido, sin silencio final), desde la cache o convirtiendo el original.
        None si no hay audio. Lanza ErrorAudio si existe pero no se pudo leer."""
        ruta = self.integrantes.buscar_audio(base)
        if ruta is None:
            return None
        destino = os.path.join(self.carpeta_cache, "{}_{}.wav".format(base, huella(ruta)))
        if os.path.exists(destino):
            pcm = leer_wav(destino)
            self.ultimo = dict(original=ruta, cache=destino, nuevo=False, seg=len(pcm) / config.TASA)
            return pcm
        muestras, tasa = decodificar(ruta)
        audio = a_16k(muestras, tasa)
        seg_original = len(audio) / config.TASA
        audio, quitado_ini, quitado_fin = recortar_silencio(audio)
        pcm = _pulir(audio, silencio_final=0)
        os.makedirs(self.carpeta_cache, exist_ok=True)
        guardar_wav(destino, pcm)
        self.ultimo = dict(original=ruta, cache=destino, nuevo=True, seg=len(pcm) / config.TASA,
                           seg_original=seg_original, quitado_ini=quitado_ini, quitado_fin=quitado_fin)
        return pcm

    def preparar_placa(self, base):
        """Deja fusion/audios_placa/<base>.wav al dia. Devuelve (ruta, pcm) o (None, None) si no hay audio."""
        pcm = self.palabra_procesada(base)
        if pcm is None or len(pcm) == 0:
            return None, None
        ruta = os.path.join(self.carpeta_placa, nombre_placa(base) + ".wav")
        if not (os.path.exists(ruta) and np.array_equal(leer_wav(ruta), pcm)):
            os.makedirs(self.carpeta_placa, exist_ok=True)
            guardar_wav(ruta, pcm)
        return ruta, pcm

    def elegir(self, resultado):
        """[(base, como se muestra)] que deben sonar: la frase grabada si existe; si no, las palabras sueltas."""
        frases = self.integrantes.cfg["personas"][resultado.persona].get("frases", [])
        for frase in frases:
            if [normalizar(p) for p in frase["palabras"]] == resultado.palabras_mano:
                if self.integrantes.buscar_audio(frase["audio"]) is not None:
                    return [(frase["audio"], " ".join(frase["palabras"]))]
        # cada 'texto' de integrantes.json es una sola palabra
        return list(zip(resultado.audios, resultado.mostrar.split()))


class Voz(Audios):
    """La voz por la ESP32 de la mano: orden "voz ..." por BLE. hablar() devuelve (ok, mensaje): nunca lanza."""

    def __init__(self, mano, integrantes=None, ruta_tiempos=RUTA_TIEMPOS, **carpetas):
        super().__init__(integrantes, **carpetas)
        self.mano = mano
        self.ruta_tiempos = ruta_tiempos
        self.aviso_tiempos = ""

    def preparar(self, resultado):
        """([(base, mostrar, segundos)], '') listos en audios_placa/, o (None, 'Falta audio: ...')."""
        if not resultado.ok:
            return None, resultado.motivo
        listos, faltan = [], []
        for base, mostrar in self.elegir(resultado):
            try:
                ruta, pcm = self.preparar_placa(base)
            except (ErrorAudio, OSError, ValueError, wave.Error):
                ruta = None
            if ruta is None:
                faltan.append(mostrar)
            else:
                listos.append((base, mostrar, len(pcm) / config.TASA))
        if faltan:                                  # se revisan todos antes de sonar: si falta uno, no suena nada
            return None, "Falta audio: " + ", ".join(faltan)
        return listos, ""

    def espera_voz(self, listos):
        """Segundos que se espera voz_ok: duracion del audio + pausas + cola de la placa + MARGEN_VOZ."""
        pausas = (len(listos) - 1) * self.integrantes.pausa_ms / 1000
        return sum(s for _, _, s in listos) + pausas + COLA_PLACA + MARGEN_VOZ

    def comprobar_placa(self):
        """(True, 'voz-2') si la placa tiene el firmware con voz; si no, (False, mensaje). No mueve la mano."""
        return self.mano.version()

    def hablar(self, resultado):
        """Hace sonar el Resultado de reconocer.interpretar() en la placa y espera voz_ok. (ok, mensaje)."""
        fila = {"id_prueba": datetime.now().isoformat(sep=" ", timespec="seconds"),
                "fecha_hora": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                "texto": resultado.leido, "palabras": resultado.mostrar, "archivos": "",
                "seg_audio": "", "seg_hasta_ok": ""}
        try:
            listos, mensaje = self.preparar(resultado)
            if listos is None:
                ok = False
            else:
                nombres = [nombre_placa(b) for b, _, _ in listos]
                fila["archivos"] = " ".join(nombres)
                pausas = (len(listos) - 1) * self.integrantes.pausa_ms / 1000
                fila["seg_audio"] = "{:.3f}".format(sum(s for _, _, s in listos) + pausas)
                inicio = time.perf_counter()
                ok, respuesta = self.mano.hablar(nombres, espera=self.espera_voz(listos))
                fila["seg_hasta_ok"] = "{:.3f}".format(time.perf_counter() - inicio)
                if ok:
                    mensaje = "Sonó: " + resultado.mostrar
                elif respuesta.startswith("voz_falta:"):
                    mostrar = {nombre_placa(b): m for b, m, _ in listos}
                    faltan = [mostrar.get(n, n) for n in respuesta.split(":", 1)[1].split(",")]
                    mensaje = "Falta audio: {} (no está en la placa: súbelo a /voz con Thonny)".format(
                        ", ".join(faltan))
                elif respuesta.startswith("voz_error:"):
                    mensaje = "La placa no pudo reproducir el audio ({})".format(respuesta.split(":", 1)[1])
                elif respuesta == MSG_TIEMPO_MANO:
                    mensaje = "La placa no respondió a la voz"
                else:
                    mensaje = respuesta
        except Exception as e:                      # el programa no se cae por la voz
            ok, mensaje = False, "Error en la voz ({})".format(type(e).__name__)
        fila["resultado"] = "ok" if ok else "error: " + mensaje
        self.aviso_tiempos = guardar_tiempos(fila, self.ruta_tiempos)
        return ok, mensaje


# ---------------- Consola ----------------
def lista_de_audios(integrantes):
    """[(persona, como se dice, base)]: las palabras y las frases de integrantes.json (los 18 audios)."""
    salida, vistos = [], set()
    for clave, datos in integrantes.cfg["personas"].items():
        elementos = [(p["texto"], p["audio"]) for p in datos["palabras"]]
        elementos += [(" ".join(f["palabras"]), f["audio"]) for f in datos.get("frases", [])]
        for dice, base in elementos:
            if base.lower() not in vistos:
                vistos.add(base.lower())
                salida.append((clave, dice, base))
    return salida


def preparar_todo(audios):
    """Convierte todos los audios que existen a fusion/audios_placa/ y lista los que faltan."""
    total, listos, faltan, persona = 0, 0, [], None
    lista = lista_de_audios(audios.integrantes)
    for clave, dice, base in lista:
        if clave != persona:
            persona = clave
            print("{} ({})".format(clave, audios.integrantes.nombre_completo(clave)))
        try:
            ruta, pcm = audios.preparar_placa(base)
        except (ErrorAudio, OSError, ValueError, wave.Error) as e:
            print("  ✗ {:24} no se pudo leer: {}".format(dice, e))
            faltan.append(dice)
            continue
        if ruta is None:
            print("  ✗ {:24} FALTA  (grabar como voces/{}.*)".format(dice, base))
            faltan.append(dice)
            continue
        tam = os.path.getsize(ruta)
        total += tam
        listos += 1
        u = audios.ultimo
        recorte = ""
        if u.get("nuevo") and config.RECORTAR_SILENCIO:
            recorte = "  (de {:.2f} s; silencio quitado {:.2f} s al inicio, {:.2f} s al final)".format(
                u["seg_original"], u["quitado_ini"], u["quitado_fin"])
        print("  ✔ {:24} {:30} -> {:26} {:.2f} s  {:5.1f} KB{}".format(
            dice, os.path.relpath(u["original"], RAIZ), os.path.basename(ruta), len(pcm) / config.TASA,
            tam / 1024, recorte))
    print("\nListos {} de {} audios: {:.1f} KB en total en {}".format(
        listos, len(lista), total / 1024, os.path.relpath(audios.carpeta_placa, RAIZ)))
    if faltan:
        print("Faltan {}: {}".format(len(faltan), ", ".join(faltan)))
        if listos:
            estimado = total + len(faltan) * total / listos
            print("Con los {} completos serían unos {:.0f} KB (estimado con el promedio de los que ya están).".format(
                len(lista), estimado / 1024))
    print("\nPara subirlos (solo USB, sin los 12 V): Thonny > Ver > Archivos; en la placa crea la carpeta /voz;")
    print("selecciona todos los .wav de fusion/audios_placa/ > clic derecho > «Subir a /voz».")


def probar(texto, deletrear, ventana=True):
    import threading

    from consola_mano import ErrorMano, Mano, leer_config, texto_tramos

    integrantes = Integrantes()
    r = interpretar(texto, integrantes)
    if not r.ok:
        print("  ✗ {}".format(r.motivo))
        return False
    print("  Entendí: \"{}\" ({})".format(r.mostrar, integrantes.nombre_completo(r.persona)))
    mano = Mano()
    voz = Voz(mano, integrantes)
    try:
        listos, mensaje = voz.preparar(r)
        if listos is None:
            print("  ✗ {}  (no va a sonar nada)".format(mensaje))
        else:
            print("  Va a sonar: voz {}  ({:.2f} s de audio; se espera voz_ok como mucho {:.1f} s)".format(
                " ".join(nombre_placa(b) for b, _, _ in listos), sum(s for _, _, s in listos),
                voz.espera_voz(listos)))
        try:
            nombre, token = leer_config()
        except ErrorMano as e:
            print("  ✗ {}".format(e))
            return False
        print("  Buscando '{}' por Bluetooth (token cargado: {} caracteres)...".format(nombre, len(token)))
        ok, mensaje = mano.conectar()
        print("  {}".format(mensaje))
        if not ok:
            return False
        ok, version = voz.comprobar_placa()
        if not ok:
            print("  ✗ {}".format(version))
            return False
        print("  Firmware de la placa: {}".format(version))
        inicio = time.perf_counter()
        if not deletrear:
            ok, mensaje = voz.hablar(r)
            print("  [{:5.1f} s] {} {}".format(time.perf_counter() - inicio, "✔" if ok else "✗", mensaje))
            print("  {}".format(voz.aviso_tiempos or "Tiempos guardados en " + os.path.relpath(voz.ruta_tiempos, RAIZ)))
            return ok

        # Con --deletrear: el deletreo y la voz van en un hilo; la ventana (OpenCV) en el hilo principal
        print("  Deletreando:  {}".format("  |  ".join(texto_tramos(t) for t in r.tramos)))
        seguimiento = None
        if ventana:
            from pantalla_mano import RelojMano, Seguimiento, VentanaMano
            seguimiento = Seguimiento(RelojMano(), r)

        def al_evento(tipo, dato):
            if seguimiento is not None:
                seguimiento.evento(tipo, dato)
            t = time.perf_counter() - inicio
            if tipo == "letra":
                print("  [{:5.1f} s] letra {}".format(t, dato))
            elif tipo == "movimiento":
                print("  [{:5.1f} s] {}  (con movimiento: mano abierta)".format(t, dato.upper()))
            elif tipo == "espacio":
                print("  [{:5.1f} s] -- espacio --".format(t))
            elif tipo == "fin":
                print("  [{:5.1f} s] mano abierta: fin del deletreo".format(t))

        final = {}

        def trabajo():
            ok, mensaje = mano.deletrear(r, al_evento)
            if not ok:
                final["r"] = (False, mensaje + "  (no se hace sonar la voz)")
            else:
                if seguimiento is not None:
                    seguimiento.hablando()
                final["r"] = voz.hablar(r)
            if seguimiento is not None:
                seguimiento.terminado(*final["r"])

        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()
        if seguimiento is not None:
            if not VentanaMano(seguimiento).mostrar(lambda: not hilo.is_alive()):
                print("  Ventana cerrada: se corta y se suelta el Bluetooth.")
                mano.cerrar()
                return False
        while hilo.is_alive():
            hilo.join(0.2)                          # en pasos cortos: Ctrl+C corta enseguida
        ok, mensaje = final.get("r", (False, "Se cortó"))
        print("  [{:5.1f} s] {} {}".format(time.perf_counter() - inicio, "✔" if ok else "✗", mensaje))
        print("  {}".format(voz.aviso_tiempos or "Tiempos guardados en " + os.path.relpath(voz.ruta_tiempos, RAIZ)))
        return ok
    finally:
        mano.cerrar()                               # siempre suelta el Bluetooth (tambien con Ctrl+C)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Voz por el MAX98357 de la ESP32 de la mano (sin Kinect)")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--preparar", action="store_true", help="convertir los audios a fusion/audios_placa/")
    grupo.add_argument("--texto", help="interpretar este texto y hacerlo sonar en la placa")
    parser.add_argument("--deletrear", action="store_true",
                        help="con --texto: la mano deletrea (con la ventana sincronizada) y después suena")
    parser.add_argument("--sin-ventana", action="store_true", help="con --deletrear: solo la consola")
    args = parser.parse_args()
    if args.deletrear and not args.texto:
        parser.error("--deletrear va con --texto")

    try:
        if args.preparar:
            preparar_todo(Audios())
            return 0
        return 0 if probar(args.texto, args.deletrear, ventana=not args.sin_ventana) else 1
    except KeyboardInterrupt:
        print("\nSaliste (Ctrl+C). El Bluetooth quedó suelto; la mano queda como estaba.")   # sin reset: podria
        return 0                                                                          # mezclarse con una letra


if __name__ == "__main__":
    sys.exit(main())
