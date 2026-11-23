"""
mano_wifi.py  -  CORRE EN EL PC (py -3.11). Solo biblioteca estandar (sin bleak, sin torch).
Cliente del WiFi de la mano (firmware_mano/wifi_hora.py): SOLO para el audio de la fecha y la hora.
Los nombres, el deletreo y "voz a b" siguen por BLE con consola_mano.py, sin cambios.

- Datos: TOKEN y PUERTO (y, si existen, IP_FIJA y NOMBRE) de secretos.py en la raiz del proyecto. Se leen con
  ast, sin ejecutar el archivo, y NUNCA se muestran (solo "TOKEN cargado (N caracteres)").
- Busca la placa: <NOMBRE>.local (mDNS, NOMBRE "mano" por defecto) y, si no responde, IP_FIJA.
  En cada una: conectar + "auth <TOKEN>" + "ping". La primera que contesta "pong" es la mano.
- Protocolo (el de wifi_hora.py): auth, ping, mem, wav <n> (+ n bytes PCM) -> listo ... voz_ok:<ms>, fin.
- Cualquier problema lanza ErrorWifi con un mensaje claro para mostrar en pantalla; nada mas se afecta.
"""

import ast
import os
import socket
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
RUTA_SECRETOS = os.path.join(RAIZ, "secretos.py")

PUERTO_DEFECTO = 5001
NOMBRE_DEFECTO = "mano"
TASA = 16000
BLOQUE_ENVIO = 4096
SEG_CONEXION = 1.5      # conectar (por direccion)
SEG_RESPUESTA = 2.0     # auth, ping, listo
MARGEN_VOZ = 3.0        # voz_ok llega a lo sumo duracion + MARGEN_VOZ despues de "listo"


class ErrorWifi(Exception):
    pass


def leer_secretos(ruta=RUTA_SECRETOS):
    """dict con TOKEN, PUERTO, IP_FIJA (o None) y NOMBRE. Lanza ErrorWifi si falta algo. Nunca ejecuta el archivo."""
    try:
        with open(ruta, encoding="utf-8-sig") as f:
            arbol = ast.parse(f.read())
    except OSError:
        raise ErrorWifi("Sin WiFi en la mano: no existe secretos.py")
    except SyntaxError:
        raise ErrorWifi("Sin WiFi en la mano: secretos.py tiene un error de sintaxis")
    valores = {}
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
            try:
                valores[nodo.targets[0].id] = ast.literal_eval(nodo.value)
            except ValueError:
                pass
    token = valores.get("TOKEN")
    if not isinstance(token, str) or not token:
        raise ErrorWifi("Sin WiFi en la mano: falta TOKEN en secretos.py")
    puerto = valores.get("PUERTO", PUERTO_DEFECTO)
    if not isinstance(puerto, int):
        raise ErrorWifi("Sin WiFi en la mano: PUERTO de secretos.py no es un número")
    ip_fija = valores.get("IP_FIJA")
    return {"TOKEN": token, "PUERTO": puerto, "IP_FIJA": ip_fija if isinstance(ip_fija, str) and ip_fija else None,
            "NOMBRE": valores.get("NOMBRE", NOMBRE_DEFECTO) if isinstance(valores.get("NOMBRE"), str)
            else NOMBRE_DEFECTO}


def resolver(nombre):
    """IP de <nombre>.local (resolvedor de Windows, mDNS) o None."""
    try:
        return socket.getaddrinfo(nombre + ".local", None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    except OSError:
        return None


class ManoWifi:
    """Una conexion autenticada con la mano. Usar con 'with' o llamar cerrar()."""

    def __init__(self, ip, puerto, token, como=""):
        self.ip, self.puerto, self.como = ip, puerto, como
        self.sock = self.lector = None
        try:
            self.sock = socket.create_connection((ip, puerto), timeout=SEG_CONEXION)
        except OSError:
            raise ErrorWifi("Sin WiFi en la mano: no responde en {}:{}".format(ip, puerto))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.lector = self.sock.makefile("rb")
        respuesta = self.orden("auth " + token)
        if respuesta != "ok:auth":
            self.cerrar()
            raise ErrorWifi("La mano rechazó el TOKEN del WiFi (revisa secretos.py y config_wifi.py)")
        if self.orden("ping") != "pong":
            self.cerrar()
            raise ErrorWifi("La mano no respondió el ping por WiFi")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.cerrar()

    def linea(self, espera=SEG_RESPUESTA):
        self.sock.settimeout(espera)
        try:
            datos = self.lector.readline()
        except socket.timeout:
            raise ErrorWifi("La mano no respondió por WiFi en {:.0f} s".format(espera))
        except OSError:
            raise ErrorWifi("Se perdió la conexión WiFi con la mano")
        if not datos:
            raise ErrorWifi("La mano cerró la conexión WiFi")
        return datos.decode("utf-8", "ignore").strip()

    def orden(self, texto, espera=SEG_RESPUESTA):
        try:
            self.sock.sendall((texto + "\n").encode("utf-8"))
        except OSError:
            raise ErrorWifi("Se perdió la conexión WiFi con la mano")
        return self.linea(espera)

    def mem(self):
        """(KB libres de MicroPython, KB libres de ESP-IDF) de la placa."""
        _, kb, kb_idf = self.orden("mem").split(":")
        return int(kb), int(kb_idf)

    def wav(self, pcm):
        """Hace sonar pcm (16 kHz, mono, 16 bits) en la mano y espera voz_ok. Devuelve los ms hasta voz_ok."""
        seg = len(pcm) / (2 * TASA)
        respuesta = self.orden("wav {}".format(len(pcm)))
        if respuesta != "listo":
            raise ErrorWifi("La mano no pudo sonar la frase ({})".format(respuesta))
        t = time.perf_counter()
        self.sock.settimeout(seg + MARGEN_VOZ)          # la mano recibe al ritmo del audio
        try:
            for k in range(0, len(pcm), BLOQUE_ENVIO):
                self.sock.sendall(pcm[k:k + BLOQUE_ENVIO])
        except OSError:
            raise ErrorWifi("Se cortó el WiFi a mitad de la frase")
        respuesta = self.linea(seg + MARGEN_VOZ)
        if not respuesta.startswith("voz_ok"):
            raise ErrorWifi("La mano no terminó la frase ({})".format(respuesta))
        return (time.perf_counter() - t) * 1000

    def cerrar(self):
        if self.sock is not None:
            try:
                self.sock.sendall(b"fin\n")
            except OSError:
                pass
        for cosa in (self.lector, self.sock):
            try:
                if cosa is not None:
                    cosa.close()
            except OSError:
                pass
        self.sock = self.lector = None


def conectar(secretos=None, ip=None):
    """La mano por WiFi: 'ip' si se da; si no, <NOMBRE>.local y luego IP_FIJA. Lanza ErrorWifi con un mensaje
    claro si ninguna responde. La conexion devuelta tiene .como ('ip', 'mano.local' o 'IP_FIJA') y .ms_buscar."""
    s = secretos or leer_secretos()
    t = time.perf_counter()
    if ip:
        candidatos = [(ip, "ip")]
    else:
        candidatos = []
        local = resolver(s["NOMBRE"])
        if local:
            candidatos.append((local, s["NOMBRE"] + ".local"))
        if s["IP_FIJA"] and s["IP_FIJA"] != local:
            candidatos.append((s["IP_FIJA"], "IP_FIJA"))
    ultimo = None
    for direccion, como in candidatos:
        try:
            mano = ManoWifi(direccion, s["PUERTO"], s["TOKEN"], como)
            mano.ms_buscar = (time.perf_counter() - t) * 1000
            return mano
        except ErrorWifi as e:
            if "TOKEN" in str(e):
                raise                                   # respondio pero con otro TOKEN: no seguir buscando
            ultimo = e
    if not candidatos:
        raise ErrorWifi("Sin WiFi en la mano: no se encontró {}.local{}".format(
            s["NOMBRE"], "" if s["IP_FIJA"] else " (y no hay IP_FIJA en secretos.py)"))
    raise ultimo
