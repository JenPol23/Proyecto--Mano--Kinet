"""
prueba_wifi_envio.py  -  CORRE EN EL PC (py -3.11)
FASE 1 del audio por WiFi (prueba minima): manda frases enteras de la hora de Doby a
firmware_mano/prueba_wifi_audio.py, que corre en la placa desde Thonny, y mide cuanto tarda.
No usa el Bluetooth ni la mano. Solo lee voz_cache_f5 de Doby y secretos.py (sin ejecutarlo).

Version 2 (streaming): la placa no guarda la frase; la hace sonar mientras llega en bloques de 4 KB.

Uso (desde la carpeta del proyecto, con el PC en el mismo punto de acceso que la placa):
  py -3.11 fusion/pruebas/prueba_wifi_envio.py --ip 192.168.x.y      la IP que muestra Thonny
  py -3.11 fusion/pruebas/prueba_wifi_envio.py                        prueba con mano.local
  py -3.11 fusion/pruebas/prueba_wifi_envio.py --simulada             SIN PLACA: placa falsa en 127.0.0.1
  Opciones: --voz lina|harry|jeanpaul|paula (o el nombre de Doby: jenpol, camila)
            --horas 0745 1535 2359   --repetir N   --nota "con BLE"   --salir (termina la prueba de la placa)

- Protocolo (= prueba_wifi_audio.py): auth <TOKEN> -> ok:auth; ping -> pong; mem -> mem:<KB>;
  red <n> -> listo, n bytes -> red:<n>:<ms> (velocidad de la red, sin audio);
  wav <n> -> listo (o voz_error:tamano), n bytes PCM 16 kHz mono 16 bits que suenan mientras llegan ->
  recibido:<n>:<ms>:<cortes>:<ms_sin_datos> -> ram:<antes>:<sonando>:<despues> -> voz_ok:<ms>
  (o voz_error:corte / voz_error:i2s).
- TOKEN y PUERTO salen de secretos.py (raiz). Nunca se muestran: solo "cargado (N caracteres)".
- Registro: fusion/registros/prueba_wifi_stream.csv (solo agrega filas; --simulada no escribe).
  prueba_wifi.csv (version 1, con otras columnas) no se toca.
"""

import argparse
import ast
import csv
import glob
import math
import os
import socket
import statistics
import struct
import sys
import tempfile
import threading
import time
import wave
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
RUTA_SECRETOS = os.path.join(RAIZ, "secretos.py")
RUTA_CSV = os.path.join(RAIZ, "fusion", "registros", "prueba_wifi_stream.csv")
DOBY_VOCES = r"C:\Users\miran\proyectoDoby\voz_cache_f5"
VOCES = {"jeanpaul": "jenpol", "harry": "harry", "lina": "lina", "paula": "camila"}   # este proyecto -> Doby
TASA = 16000
BYTES_POR_MS = 32
PUERTO_DEFECTO = 5001
NOMBRE_DEFECTO = "mano"
HORAS_DEFECTO = ["0745", "1535", "2359"]
BYTES_RED = 98304               # 96 KB (~ una frase) para medir la red sin audio
BLOQUE_ENVIO = 4096             # el PC manda en bloques (asi --simulada puede cortar a mitad)
SEG_CONEXION = 5.0
SEG_RESPUESTA = 10.0
MARGEN_VOZ = 5.0                # s sobre la duracion del audio para esperar el final
COLUMNAS = ["fecha_hora", "host", "como", "nota", "voz", "hora", "kb", "seg_audio", "ms_conexion", "ms_ping",
            "kb_s_red", "ms_recepcion", "cortes", "ms_sin_datos", "ms_hasta_voz_ok", "extra_s",
            "ram_antes", "ram_sonando", "ram_despues", "resultado"]


class ErrorPrueba(Exception):
    pass


# ---------------- secretos.py (sin ejecutarlo) ----------------
def leer_secretos(ruta=RUTA_SECRETOS):
    """(token, puerto, aviso). Lee solo asignaciones literales con ast: nunca ejecuta el archivo."""
    try:
        with open(ruta, encoding="utf-8-sig") as f:
            arbol = ast.parse(f.read())
    except OSError:
        return None, PUERTO_DEFECTO, "No existe secretos.py"
    except SyntaxError:
        return None, PUERTO_DEFECTO, "secretos.py tiene un error de sintaxis"
    valores = {}
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
            try:
                valores[nodo.targets[0].id] = ast.literal_eval(nodo.value)
            except ValueError:
                pass
    token = valores.get("TOKEN")
    if not isinstance(token, str) or not token:
        return None, PUERTO_DEFECTO, "Falta TOKEN en secretos.py"
    puerto = valores.get("PUERTO", PUERTO_DEFECTO)
    if not isinstance(puerto, int):
        return None, PUERTO_DEFECTO, "PUERTO de secretos.py no es un número"
    return token, puerto, ""


# ---------------- Frases de Doby ----------------
def cargar_frase(voz, hhmm, carpeta=DOBY_VOCES):
    """(ruta, pcm bytes) de <carpeta>/<voz Doby>/hora/hora_HHMM_*.wav (16 kHz, mono, 16 bits)."""
    patron = os.path.join(carpeta, VOCES.get(voz, voz), "hora", "hora_{}_*.wav".format(hhmm))
    rutas = sorted(glob.glob(patron))
    if not rutas:
        raise ErrorPrueba("No hay frase {} para '{}' ({})".format(hhmm, voz, patron))
    with wave.open(rutas[0], "rb") as w:
        formato = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        if formato != (1, 2, TASA):
            raise ErrorPrueba("{} no es 16 kHz mono 16 bits: {}".format(os.path.basename(rutas[0]), formato))
        return rutas[0], w.readframes(w.getnframes())


# ---------------- Cliente ----------------
class Cliente:
    """Una conexion TCP con la prueba de la placa. Lanza ErrorPrueba si algo no responde como debe."""

    def __init__(self, host, puerto, token):
        t = time.perf_counter()
        try:
            self.sock = socket.create_connection((host, puerto), timeout=SEG_CONEXION)
        except OSError as e:
            raise ErrorPrueba("No se pudo conectar a {}:{} ({})".format(host, puerto, e))
        self.ms_conexion = (time.perf_counter() - t) * 1000
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.lector = self.sock.makefile("rb")
        respuesta = self.orden("auth " + token)
        if respuesta != "ok:auth":
            self.cerrar()
            raise ErrorPrueba("La placa rechazó el token ({})".format(respuesta))

    def linea(self, espera=SEG_RESPUESTA):
        self.sock.settimeout(espera)
        try:
            datos = self.lector.readline()
        except socket.timeout:
            raise ErrorPrueba("La placa no respondió en {:.0f} s".format(espera))
        except OSError as e:
            raise ErrorPrueba("Se perdió la conexión ({})".format(e))
        if not datos:
            raise ErrorPrueba("La placa cerró la conexión")
        return datos.decode("utf-8", "ignore").strip()

    def orden(self, texto, espera=SEG_RESPUESTA):
        self.sock.sendall((texto + "\n").encode("utf-8"))
        return self.linea(espera)

    def ping(self):
        t = time.perf_counter()
        if self.orden("ping") != "pong":
            raise ErrorPrueba("ping sin pong")
        return (time.perf_counter() - t) * 1000

    def mandar(self, datos, hasta=None, pausa=0.0):
        """Manda 'datos' en bloques; 'hasta' = solo esos bytes (para simular un corte); 'pausa' entre bloques."""
        self.sock.settimeout(SEG_RESPUESTA)
        fin = len(datos) if hasta is None else hasta
        for k in range(0, fin, BLOQUE_ENVIO):
            self.sock.sendall(datos[k:min(k + BLOQUE_ENVIO, fin)])
            if pausa:
                time.sleep(pausa)

    def red(self, n=BYTES_RED):
        """KB/s de la red sin audio (la placa descarta lo que llega)."""
        if self.orden("red {}".format(n)) != "listo":
            raise ErrorPrueba("la placa no aceptó 'red'")
        self.mandar(bytes(n))
        _, n2, ms = self.linea().split(":")
        return int(n2) / 1024 / max(int(ms), 1) * 1000

    def wav(self, pcm, pausa=0.0):
        """Manda el PCM (suena mientras llega) y espera voz_ok. dict con los tiempos; 'resultado' = 'ok' o el error."""
        seg = len(pcm) / (2 * TASA)
        r = {"kb": len(pcm) / 1024, "seg_audio": seg}
        respuesta = self.orden("wav {}".format(len(pcm)))
        if respuesta != "listo":
            r["resultado"] = respuesta
            return r
        t0 = time.perf_counter()
        self.mandar(pcm, pausa=pausa)
        while True:
            respuesta = self.linea(seg + MARGEN_VOZ)
            if respuesta.startswith("recibido:"):
                _, _, ms, cortes, sin_datos = respuesta.split(":")
                r.update(ms_recepcion=int(ms), cortes=int(cortes), ms_sin_datos=int(sin_datos))
            elif respuesta.startswith("ram:"):
                _, a, s, d = respuesta.split(":")
                r.update(ram_antes=int(a), ram_sonando=int(s), ram_despues=int(d))
            else:
                break
        r["ms_hasta_voz_ok"] = (time.perf_counter() - t0) * 1000
        r["extra_s"] = r["ms_hasta_voz_ok"] / 1000 - seg
        r["resultado"] = "ok" if respuesta.startswith("voz_ok") else respuesta
        return r

    def cerrar(self):
        for cosa in (getattr(self, "lector", None), getattr(self, "sock", None)):
            try:
                if cosa is not None:
                    cosa.close()
            except OSError:
                pass


def resolver(nombre, puerto):
    """(ip o None, ms, error) de <nombre>.local con el resolvedor de Windows (mDNS)."""
    t = time.perf_counter()
    try:
        info = socket.getaddrinfo(nombre + ".local", puerto, socket.AF_INET, socket.SOCK_STREAM)
        return info[0][4][0], (time.perf_counter() - t) * 1000, ""
    except OSError as e:
        return None, (time.perf_counter() - t) * 1000, str(e)


def guardar(filas, ruta=RUTA_CSV):
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        nuevo = not os.path.exists(ruta)
        with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS)
            if nuevo:
                w.writeheader()
            w.writerows(filas)
        print("Registro: {} (+{} filas)".format(os.path.relpath(ruta, RAIZ), len(filas)))
    except OSError as e:
        print("No se pudo escribir {} ({})".format(ruta, e))


def fmt(x, d=0):
    return "" if x is None else "{:.{}f}".format(x, d)


# ---------------- Con la placa ----------------
def con_placa(args):
    token, puerto, aviso = leer_secretos()
    if token is None:
        print("✗ " + aviso)
        return 1
    print("TOKEN cargado ({} caracteres), PUERTO {}".format(len(token), puerto))

    ip_local, ms_mdns, error = resolver(args.nombre, puerto)
    print("{}.local -> {} ({:.0f} ms){}".format(args.nombre, ip_local or "NO resuelve", ms_mdns,
                                                 "  [{}]".format(error) if error else ""))
    host, como = (args.ip, "ip") if args.ip else (ip_local, "mano.local")
    if host is None:
        print("✗ Sin IP: pasa --ip con la que muestra Thonny")
        return 1

    frases = []
    for hhmm in args.horas:
        try:
            ruta, pcm = cargar_frase(args.voz, hhmm, args.doby)
            frases.append((hhmm, ruta, pcm))
        except (ErrorPrueba, OSError, wave.Error) as e:
            print("✗ {}".format(e))
    if not frases:
        return 1

    filas, resultado = [], 0
    try:
        cliente = Cliente(host, puerto, token)
    except ErrorPrueba as e:
        print("✗ {}".format(e))
        return 1
    try:
        print("Conectado a {}:{} en {:.0f} ms".format(host, puerto, cliente.ms_conexion))
        pings = [cliente.ping() for _ in range(5)]
        ms_ping = statistics.median(pings)
        print("ping: mediana {:.0f} ms (min {:.0f}, max {:.0f})".format(ms_ping, min(pings), max(pings)))
        print("RAM de la placa: {}".format(cliente.orden("mem")))
        redes = [cliente.red() for _ in range(3)]
        kb_s_red = statistics.median(redes)
        print("Red sin audio (96 KB x 3): mediana {:.0f} KB/s (min {:.0f}, max {:.0f}); el audio necesita 31 KB/s".format(
            kb_s_red, min(redes), max(redes)))
        print("\n{:5} {:>6} {:>6} {:>7} {:>8} {:>10} {:>7} {:>14}  {}".format(
            "hora", "KB", "audio", "cortes", "sin dat.", "hasta ok", "extra", "RAM a/s/d KB", "resultado"))
        for vuelta in range(args.repetir):
            for hhmm, ruta, pcm in frases:
                r = cliente.wav(pcm)
                ram = "{}/{}/{}".format(r.get("ram_antes", "?"), r.get("ram_sonando", "?"), r.get("ram_despues", "?"))
                print("{:5} {:6.1f} {:5.2f}s {:>7} {:>6}ms {:>8}ms {:>6}s {:>14}  {}".format(
                    hhmm, r["kb"], r["seg_audio"], fmt(r.get("cortes")), fmt(r.get("ms_sin_datos")),
                    fmt(r.get("ms_hasta_voz_ok")), fmt(r.get("extra_s"), 2), ram, r["resultado"]))
                filas.append({"fecha_hora": datetime.now().isoformat(sep=" ", timespec="seconds"), "host": host,
                              "como": como, "nota": args.nota, "voz": args.voz, "hora": hhmm,
                              "kb": fmt(r["kb"], 1), "seg_audio": fmt(r["seg_audio"], 2),
                              "ms_conexion": fmt(cliente.ms_conexion), "ms_ping": fmt(ms_ping),
                              "kb_s_red": fmt(kb_s_red), "ms_recepcion": fmt(r.get("ms_recepcion")),
                              "cortes": fmt(r.get("cortes")), "ms_sin_datos": fmt(r.get("ms_sin_datos")),
                              "ms_hasta_voz_ok": fmt(r.get("ms_hasta_voz_ok")), "extra_s": fmt(r.get("extra_s"), 2),
                              "ram_antes": fmt(r.get("ram_antes")), "ram_sonando": fmt(r.get("ram_sonando")),
                              "ram_despues": fmt(r.get("ram_despues")), "resultado": r["resultado"]})
                if r["resultado"] != "ok":
                    resultado = 1
                    if r["resultado"].startswith("voz_error:"):
                        raise ErrorPrueba("la placa respondió {}: se termina esta conexión".format(r["resultado"]))
        total_cortes = sum(int(f["cortes"]) for f in filas if f["cortes"])
        print("\nCortes en total: {} (0 = sonó sin interrupciones)".format(total_cortes))
        if args.salir:
            print("Placa: {}".format(cliente.orden("salir")))
    except ErrorPrueba as e:
        print("✗ {}".format(e))
        resultado = 1
    finally:
        cliente.cerrar()
        if filas:
            guardar(filas)
    return resultado


# ---------------- Sin placa: placa falsa en 127.0.0.1 ----------------
class I2SFalso:
    """Como el I2S de la placa: write() se bloquea si el colchon (ibuf) esta lleno y suena a 32 bytes/ms."""

    def __init__(self, ibuf=20000):
        self.ibuf = ibuf
        self.inicio = None
        self.escrito = 0

    def sonado(self):
        if self.inicio is None:
            return 0
        return min(self.escrito, int((time.perf_counter() - self.inicio) * 1000 * BYTES_POR_MS))

    def write(self, datos):
        if self.inicio is None:
            self.inicio = time.perf_counter()
        elif self.sonado() >= self.escrito:          # se quedo sin datos: lo que siga suena "desde ahora"
            self.inicio = time.perf_counter() - self.escrito / BYTES_POR_MS / 1000
        while self.escrito - self.sonado() + len(datos) > self.ibuf:
            time.sleep(0.002)
        self.escrito += len(datos)


class PlacaFalsa(threading.Thread):
    """El mismo protocolo y la misma cuenta de cortes que prueba_wifi_audio.py, con un I2S de mentira."""

    BLOQUE = 4096
    SEG_CORTE = 0.5

    def __init__(self, token):
        super().__init__(daemon=True)
        self.token = token
        self.servidor = socket.socket()
        self.servidor.bind(("127.0.0.1", 0))
        self.servidor.listen(1)
        self.puerto = self.servidor.getsockname()[1]
        self.recibidos = []

    def run(self):
        while True:
            try:
                c, _ = self.servidor.accept()
            except OSError:
                return
            with c, c.makefile("rb") as lector:
                try:
                    if not self.atender(c, lector):
                        self.servidor.close()
                        return
                except OSError:
                    pass

    def leer(self, c, lector, n):
        c.settimeout(self.SEG_CORTE)
        try:
            datos = lector.read(n)
        except (socket.timeout, OSError):
            return None
        return datos if len(datos) == n else None

    def atender(self, c, lector):
        def responder(texto):
            c.sendall((texto + "\n").encode())

        if lector.readline().decode().strip() != "auth " + self.token:
            responder("error:auth")
            return True
        responder("ok:auth")
        while True:
            c.settimeout(None)
            linea = lector.readline()
            if not linea:
                return True
            partes = linea.decode().split()
            if not partes:
                continue
            if partes[0] == "ping":
                responder("pong")
            elif partes[0] == "mem":
                responder("mem:100")
            elif partes[0] == "salir":
                responder("chao")
                return False
            elif partes[0] in ("wav", "red") and len(partes) == 2:
                try:
                    n = int(partes[1])
                except ValueError:
                    n = -1
                if n <= 0 or n > 15 * TASA * 2 or n % 2:
                    responder("voz_error:tamano")
                    continue
                responder("listo")
                t_red = time.perf_counter()
                if partes[0] == "red":
                    if self.leer(c, lector, n) is None:
                        return True
                    responder("red:{}:{}".format(n, int((time.perf_counter() - t_red) * 1000)))
                    continue
                i2s, recibido, escrito, cortes, sin_datos, t_inicio = I2SFalso(), [], 0, 0, 0, None
                while escrito < n:
                    bloque = self.leer(c, lector, min(self.BLOQUE, n - escrito))
                    if bloque is None:
                        responder("voz_error:corte")
                        return True
                    ahora = time.perf_counter()
                    if t_inicio is None:
                        t_inicio = ahora
                    else:
                        atraso = (ahora - t_inicio) * 1000 - escrito / BYTES_POR_MS     # = cuenta de la placa
                        if atraso > 5:
                            cortes += 1
                            sin_datos += atraso
                            t_inicio += atraso / 1000
                    i2s.write(bloque)
                    recibido.append(bloque)
                    escrito += len(bloque)
                self.recibidos.append(b"".join(recibido))
                responder("recibido:{}:{}:{}:{}".format(n, int((time.perf_counter() - t_red) * 1000), cortes,
                                                         int(sin_datos)))
                while i2s.sonado() < i2s.escrito:     # como la placa: voz_ok cuando termino de sonar
                    time.sleep(0.005)
                responder("ram:100:96:100")
                responder("voz_ok:{}".format(int((time.perf_counter() - t_red) * 1000)))
            else:
                responder("comando_no_reconocido")


def tono(seg, hz=440):
    n = int(seg * TASA)
    return struct.pack("<{}h".format(n), *(int(8000 * math.sin(2 * math.pi * hz * i / TASA)) for i in range(n)))


def simulada():
    fallas = []

    def chequeo(nombre, ok, detalle=""):
        print("{}   {}{}".format("PASA " if ok else "FALLA", nombre, "  " + detalle if detalle else ""))
        if not ok:
            fallas.append(nombre)

    token = "token_de_prueba_1234567890"
    placa = PlacaFalsa(token)
    placa.start()

    c = Cliente("127.0.0.1", placa.puerto, token)
    chequeo("auth correcto -> ok:auth", True)
    chequeo("ping -> pong", c.ping() >= 0)
    chequeo("mem", c.orden("mem").startswith("mem:"))
    chequeo("red: mide KB/s sin audio", c.red() > 0)
    pcm = tono(1.0)
    r = c.wav(pcm)
    chequeo("wav de 1 s en streaming: llega completo y suena", r["resultado"] == "ok" and placa.recibidos[-1] == pcm,
            "{:.1f} KB".format(r["kb"]))
    chequeo("red rápida -> 0 cortes", r.get("cortes") == 0, "cortes={}".format(r.get("cortes")))
    chequeo("voz_ok llega cuando terminó de sonar (>= 0,95 x duración)",
            r["ms_hasta_voz_ok"] >= 950, "{:.0f} ms".format(r["ms_hasta_voz_ok"]))
    chequeo("trae la RAM antes/sonando/después", "ram_antes" in r and "ram_despues" in r)
    r = c.wav(tono(1.2, 330), pausa=0.25)
    chequeo("red lenta (pausa de 250 ms por bloque de 128 ms) -> cuenta cortes", r["resultado"] == "ok" and r["cortes"] > 0,
            "cortes={} sin datos={} ms".format(r.get("cortes"), r.get("ms_sin_datos")))
    chequeo("frase de más de 15 s -> voz_error:tamano sin mandar datos",
            c.wav(b"\0\0" * (15 * TASA + 1))["resultado"] == "voz_error:tamano")
    chequeo("tamaño impar -> voz_error:tamano", c.orden("wav 1001") == "voz_error:tamano")
    chequeo("después del rechazo la conexión sigue sirviendo", c.ping() >= 0)
    chequeo("orden desconocida -> comando_no_reconocido", c.orden("hola") == "comando_no_reconocido")

    pcm = tono(1.0)
    if c.orden("wav {}".format(len(pcm))) == "listo":
        c.mandar(pcm, hasta=12288)                    # 3 bloques y el PC "se cae"
        try:
            respuesta = c.linea(3)
        except ErrorPrueba as e:
            respuesta = str(e)
        chequeo("envío cortado a mitad -> voz_error:corte", respuesta == "voz_error:corte", respuesta)
    else:
        chequeo("envío cortado a mitad -> voz_error:corte", False, "no respondió listo")
    c.cerrar()

    c = Cliente("127.0.0.1", placa.puerto, token)
    chequeo("después de un corte se puede volver a conectar", c.ping() >= 0)
    c.cerrar()

    try:
        Cliente("127.0.0.1", placa.puerto, "otro_token_equivocado_123")
        chequeo("token incorrecto -> rechazado", False)
    except ErrorPrueba as e:
        chequeo("token incorrecto -> rechazado", "error:auth" in str(e))

    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, "secretos.py")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("import os\nos.system('echo NO_DEBE_EJECUTARSE')\nRED = 'x'\nCLAVE = 'y'\nTOKEN = 'abcdefghijklmnop'\n"
                    "PUERTO = 5001\n")
        chequeo("secretos.py: TOKEN y PUERTO sin ejecutar el archivo", leer_secretos(ruta) == ("abcdefghijklmnop", 5001, ""))
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("RED = 'x'\nCLAVE = 'y'\n")
        chequeo("secretos.py sin TOKEN -> 'Falta TOKEN en secretos.py'",
                leer_secretos(ruta) == (None, PUERTO_DEFECTO, "Falta TOKEN en secretos.py"))
        chequeo("sin secretos.py -> aviso", leer_secretos(os.path.join(tmp, "no_existe.py"))[2] == "No existe secretos.py")

        carpeta = os.path.join(tmp, "lina", "hora")
        os.makedirs(carpeta)
        for nombre, tasa in (("hora_1535_aaaa.wav", TASA), ("hora_0745_bbbb.wav", 24000)):
            with wave.open(os.path.join(carpeta, nombre), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(tasa)
                w.writeframes(tono(0.5))
        ruta_wav, datos = cargar_frase("lina", "1535", tmp)
        chequeo("cargar_frase: hora_HHMM_*.wav de la voz", ruta_wav.endswith("hora_1535_aaaa.wav") and len(datos) == 16000)
        for hhmm, que in (("0745", "otra tasa -> rechazada"), ("2359", "hora que no existe -> aviso")):
            try:
                cargar_frase("lina", hhmm, tmp)
                chequeo("cargar_frase: " + que, False)
            except ErrorPrueba:
                chequeo("cargar_frase: " + que, True)
    chequeo("mapeo de voces: jeanpaul->jenpol, paula->camila", VOCES["jeanpaul"] == "jenpol" and VOCES["paula"] == "camila")

    c = Cliente("127.0.0.1", placa.puerto, token)
    chequeo("salir -> chao", c.orden("salir") == "chao")
    c.cerrar()
    print("\n{} fallas".format(len(fallas)))
    return 1 if fallas else 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Fase 1: audio por WiFi a la placa, en streaming (prueba mínima)")
    parser.add_argument("--simulada", action="store_true", help="sin placa: placa falsa en 127.0.0.1")
    parser.add_argument("--ip", help="IP de la placa (la muestra Thonny); sin esto se usa <nombre>.local")
    parser.add_argument("--nombre", default=NOMBRE_DEFECTO, help="NOMBRE de config_wifi.py (mano -> mano.local)")
    parser.add_argument("--voz", default="lina", help="lina, harry, jeanpaul, paula (o jenpol, camila)")
    parser.add_argument("--horas", nargs="+", default=HORAS_DEFECTO, help="HHMM de las frases de Doby")
    parser.add_argument("--repetir", type=int, default=1)
    parser.add_argument("--nota", default="", help="texto libre para el CSV (por ejemplo 'con BLE')")
    parser.add_argument("--salir", action="store_true", help="al final, terminar la prueba de la placa")
    parser.add_argument("--doby", default=DOBY_VOCES, help="carpeta voz_cache_f5 de Doby")
    args = parser.parse_args()
    return simulada() if args.simulada else con_placa(args)


if __name__ == "__main__":
    sys.exit(main())
