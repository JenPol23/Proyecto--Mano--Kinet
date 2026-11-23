"""
wifi_hora.py  -  CORRE EN LA ESP32 (MicroPython). Archivo NUEVO: lo sube el usuario con Thonny.
Solo para el boton Hora: recibe por WiFi el audio de la fecha y la hora desde el PC y lo hace sonar en el
MAX98357 MIENTRAS LLEGA (bloques de 4 KB, nada se guarda en la flash). No mueve servos ni crea ningun PWM.
Los nombres, el deletreo y "voz a b" siguen por BLE en main.py, sin ningun cambio.

- Un solo hilo: main.py llama a atender() en su bucle (entre ordenes del BLE), igual que hace hoy con "voz".
  Por eso nunca hay dos I2S a la vez y una frase nunca suena a mitad de un deletreo.
- atender() nunca lanza errores hacia main.py: sin config_wifi.py, sin red, sin memoria o con cualquier error,
  el WiFi se apaga o espera, y la mano sigue EXACTAMENTE igual que hoy (solo Ctrl+C de Thonny pasa, como hoy).
- Protocolo TCP en PUERTO de config_wifi.py (una orden por linea; la primera, "auth <TOKEN>", en SEG_AUTH s):
    ping           -> pong
    mem            -> mem:<KB libres de MicroPython>:<KB libres de ESP-IDF (WiFi, BLE e I2S)>
    wav <n>        -> listo | voz_error:tamano ; n bytes PCM (16 kHz, mono, 16 bits) que suenan mientras llegan
                   -> voz_ok:<ms>  (o voz_error:corte si el PC deja de mandar SEG_CORTE s, o voz_error:i2s)
    fin            -> chao (y cierra)
  Una conexion por pulsacion del boton: auth, wav (fecha), wav (hora), fin.
- Nunca imprime la red, la clave ni el TOKEN.
"""
import gc
import socket
import time

from machine import Pin, I2S

try:
    import select
except ImportError:
    import uselect as select

PIN_BCLK = 15           # = main.py (MAX98357: DIN 7, BCLK 15, LRC 16)
PIN_LRC = 16
PIN_DIN = 7
TASA = 16000
IBUF = 20000            # = main.py y la prueba: ~0,6 s de colchon dentro del I2S
BLOQUE = 4096           # bytes leidos del socket por vuelta (128 ms de audio); un solo bufer para siempre
MAX_BYTES = 15 * TASA * 2   # una frase de mas de 15 s se rechaza
SEG_AUTH = 2            # el PC debe presentarse en este tiempo
SEG_ORDEN = 2           # entre ordenes; si no llega nada, se cierra (la mano no espera mas que esto)
SEG_CORTE = 2           # sin datos a mitad de una frase = envio cortado
SEG_REVISAR = 1         # cada cuanto se mira si hay red (no en cada vuelta del bucle)
SEG_REINTENTO = 30      # sin red: cada cuanto se vuelve a intentar conectar


def aviso(texto):
    print("# " + texto)                 # se ve en Thonny; el PC lo ignora (igual que los avisos del BLE)


def libre_kb():
    gc.collect()
    return gc.mem_free() // 1024


def libre_idf_kb():
    try:
        import esp32
        return sum(h[1] for h in esp32.idf_heap_info(esp32.HEAP_DATA)) // 1024
    except Exception:
        return -1


def responder(c, texto):
    c.write((texto + "\n").encode())


class Corte(Exception):
    pass


class Wifi:
    def __init__(self):
        self.activo = False
        self.wlan = None
        self.servidor = None
        self.poll = None
        try:
            import network
            import config_wifi as cfg
            self.red = getattr(cfg, "RED", None)
            self.clave = getattr(cfg, "CLAVE", None)
            self.token = getattr(cfg, "TOKEN", None)
            self.puerto = int(getattr(cfg, "PUERTO", 5001))
            if not self.red or not self.token:
                raise ValueError("faltan RED o TOKEN en config_wifi.py")
            self.buf = bytearray(BLOQUE)        # todo lo que se reserva, una sola vez
            self.mv = memoryview(self.buf)
            self.silencio = bytearray(1600)     # 50 ms
            try:
                network.hostname(getattr(cfg, "NOMBRE", "mano"))    # <NOMBRE>.local (mDNS)
            except Exception:
                pass
            self.wlan = network.WLAN(network.STA_IF)
            self.wlan.active(True)
            self.wlan.connect(self.red, self.clave)               # vuelve enseguida: no espera la red
            self.intento = time.ticks_ms()
            self.revisado = time.ticks_ms()
            self.activo = True
            aviso("WiFi: conectando (red cargada, {} caracteres; TOKEN cargado, {} caracteres)".format(
                len(self.red), len(self.token)))
        except Exception as e:
            self.apagar("WiFi desactivado: {}".format(e))

    # ---------------- Lo unico que llama main.py ----------------
    def atender(self):
        """Una pasada, sin esperar: revisa la red y atiende al PC si se conecto. Nunca lanza errores."""
        if not self.activo:
            return
        try:
            if self.servidor is None or time.ticks_diff(time.ticks_ms(), self.revisado) > SEG_REVISAR * 1000:
                self.revisado = time.ticks_ms()
                self._revisar_red()
            if self.servidor is not None:
                for _ in self.poll.ipoll(0):    # sin esperar y sin reservar memoria
                    self._sesion()
                    break
        except MemoryError:
            self.apagar("WiFi apagado: sin memoria (la mano sigue igual)")
        except Exception as e:
            aviso("WiFi: error {}; se reintenta".format(e))
            self._cerrar_servidor()

    def apagar(self, motivo):
        self.activo = False
        self._cerrar_servidor()
        try:
            if self.wlan is not None:
                self.wlan.active(False)         # libera la RAM del WiFi para el BLE
        except Exception:
            pass
        self.buf = self.mv = self.silencio = None
        aviso(motivo)

    # ---------------- Red ----------------
    def _revisar_red(self):
        if not self.wlan.isconnected():
            if self.servidor is not None:
                aviso("WiFi: se perdio la red")
                self._cerrar_servidor()
            if time.ticks_diff(time.ticks_ms(), self.intento) > SEG_REINTENTO * 1000:
                self.intento = time.ticks_ms()
                try:
                    self.wlan.disconnect()
                except Exception:
                    pass
                self.wlan.connect(self.red, self.clave)
            return
        if self.servidor is None:
            s = socket.socket()
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", self.puerto))
                s.listen(1)
                p = select.poll()
                p.register(s, select.POLLIN)
            except Exception:
                s.close()
                raise
            self.servidor, self.poll = s, p
            aviso("WiFi listo: {} puerto {}  RAM {} KB  ESP-IDF {} KB".format(
                self.wlan.ifconfig()[0], self.puerto, libre_kb(), libre_idf_kb()))

    def _cerrar_servidor(self):
        if self.servidor is not None:
            try:
                self.servidor.close()
            except Exception:
                pass
        self.servidor = self.poll = None

    # ---------------- Una conexion del PC ----------------
    def _sesion(self):
        c, _ = self.servidor.accept()
        try:
            c.settimeout(SEG_AUTH)
            if c.readline().decode().strip() != "auth " + self.token:
                responder(c, "error:auth")
                return
            responder(c, "ok:auth")
            while True:
                c.settimeout(SEG_ORDEN)
                linea = c.readline()
                if not linea:
                    return
                partes = linea.decode().strip().split()
                if not partes:
                    continue
                orden = partes[0]
                c.settimeout(SEG_CORTE)
                if orden == "ping":
                    responder(c, "pong")
                elif orden == "mem":
                    responder(c, "mem:{}:{}".format(libre_kb(), libre_idf_kb()))
                elif orden == "fin":
                    responder(c, "chao")
                    return
                elif orden == "wav" and len(partes) == 2:
                    try:
                        n = int(partes[1])
                    except ValueError:
                        n = -1
                    if n <= 0 or n > MAX_BYTES or n % 2:
                        responder(c, "voz_error:tamano")
                    elif not self._sonar(c, n):
                        return                  # a mitad de una frase: se cierra la conexion
                else:
                    responder(c, "comando_no_reconocido")
        except (OSError, Corte, UnicodeError):
            pass                                # el PC se fue o tardo: se cierra y la mano sigue
        finally:
            try:
                c.close()
            except Exception:
                pass
            gc.collect()

    def _leer(self, c, cuanto):
        total = 0
        while total < cuanto:
            try:
                k = c.readinto(self.mv[total:cuanto])
            except OSError:
                raise Corte()                   # SEG_CORTE sin datos
            if not k:
                raise Corte()                   # el PC cerro
            total += k
        return total

    def _sonar(self, c, n):
        """Lee n bytes en bloques y los escribe al I2S a medida que llegan. True = voz_ok."""
        i2s = None
        try:
            try:
                i2s = I2S(0, sck=Pin(PIN_BCLK), ws=Pin(PIN_LRC), sd=Pin(PIN_DIN), mode=I2S.TX,
                          bits=16, format=I2S.MONO, rate=TASA, ibuf=IBUF)
            except Exception:
                responder(c, "voz_error:i2s")
                return True                     # no llego ningun byte: la conexion sigue en orden
            responder(c, "listo")
            t = time.ticks_ms()
            escrito = 0
            while escrito < n:
                k = self._leer(c, min(BLOQUE, n - escrito))
                i2s.write(self.mv[:k])          # se bloquea solo si el colchon de IBUF esta lleno
                escrito += k
            for _ in range(6):
                i2s.write(self.silencio)        # 0,3 s de silencio al final (como main.py)
            time.sleep_ms(IBUF // 32 + 5)       # lo que tarda en vaciarse IBUF (20000 -> 630 ms, como main.py)
            responder(c, "voz_ok:{}".format(time.ticks_diff(time.ticks_ms(), t)))
            return True
        except Corte:
            try:
                responder(c, "voz_error:corte")
            except OSError:
                pass
            return False
        except Exception:                       # I2S (o el socket al responder): se avisa si se puede
            try:
                responder(c, "voz_error:i2s")
            except OSError:
                pass
            return False
        finally:
            if i2s is not None:
                try:
                    i2s.deinit()                # suelta los pines; sin reloj el MAX98357 se apaga solo
                except Exception:
                    pass
