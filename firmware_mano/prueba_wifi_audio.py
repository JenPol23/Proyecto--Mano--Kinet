"""
prueba_wifi_audio.py  -  CORRE EN LA ESP32 (MicroPython), SOLO CON "Ejecutar script actual" DE THONNY
FASE 1 del audio por WiFi: prueba MINIMA y aislada. NO es el firmware: corre en RAM, no se guarda en la
placa, no toca main.py y no mueve la mano (no crea ningun PWM). Al reiniciar la placa vuelve main.py (voz-2).

Version 2 (streaming): esta placa no usa la PSRAM (~100-160 KB libres), asi que la frase NO se guarda entera:
se lee del socket en bloques de 4 KB (un solo bufer, reservado al empezar) y cada bloque va directo al I2S
mientras llega el siguiente. Nada se escribe en la flash.

Mide: RAM, conexion al WiFi con el config_wifi.py que YA esta en la placa, velocidad de la red (sin sonar),
y la reproduccion mientras recibe por el MAX98357 (DIN 7, BCLK 15, LRC 16: los de main.py), con los CORTES
(veces en que el I2S se quedo sin datos porque la red no alcanzo).
Protocolo (una orden por linea; el PC es fusion/pruebas/prueba_wifi_envio.py):
  auth <TOKEN>   -> ok:auth | error:auth (y cierra)                 primera linea, en 10 s
  ping           -> pong
  mem            -> mem:<KB libres>
  red <n>        -> listo ; n bytes que se descartan -> red:<n>:<ms>          (velocidad de la red, sin audio)
  wav <n>        -> listo | voz_error:tamano ; n bytes PCM (16 kHz, mono, 16 bits) que suenan mientras llegan
                 -> recibido:<n>:<ms>:<cortes>:<ms_sin_datos>  ram:<KB antes>:<KB sonando>:<KB despues>
                 -> voz_ok:<ms>          (o voz_error:corte si el PC deja de mandar SEG_CORTE s; o voz_error:i2s)
  salir          -> chao (termina la prueba)
Nunca imprime la red, la clave ni el TOKEN (solo cuantos caracteres tienen).
"""
import gc
import os
import socket
import time

import network
from machine import Pin, I2S

USAR_BLE = False        # True = Bluetooth activo y anunciandose a la vez (segunda corrida: convivencia)
PIN_BCLK = 15
PIN_LRC = 16
PIN_DIN = 7
TASA = 16000
BYTES_POR_MS = 32       # 16 kHz x 2 bytes
IBUF = 20000            # = main.py: ~0,6 s de audio de colchon dentro del I2S
BLOQUE = 4096           # bytes leidos del socket por vuelta (128 ms de audio)
MAX_BYTES = 15 * TASA * 2   # una frase de mas de 15 s se rechaza
SEG_WIFI = 20           # en la prueba se espera la red como mucho esto (el firmware real no esperara)
SEG_CORTE = 2           # sin datos del PC este tiempo a mitad de una frase = envio cortado
TOLERANCIA_MS = 5       # atraso menor que esto no se cuenta como corte


def libre():
    gc.collect()
    return gc.mem_free() // 1024


print("=" * 44)
print("PRUEBA WIFI + AUDIO EN STREAMING (no es main.py)")
print("os.uname():", os.uname())
print("RAM de MicroPython al empezar: {} KB libres".format(libre()))
try:
    import esp32
    print("RAM interna de ESP-IDF libre: {} KB".format(sum(h[1] for h in esp32.idf_heap_info(esp32.HEAP_DATA)) // 1024))
except Exception as e:
    print("(sin idf_heap_info: {})".format(e))

# ---------------- config_wifi.py (ya esta en la placa) ----------------
import config_wifi as cfg
RED = getattr(cfg, "RED", None)
CLAVE = getattr(cfg, "CLAVE", None)
TOKEN = getattr(cfg, "TOKEN", None)
PUERTO = int(getattr(cfg, "PUERTO", 5001))
NOMBRE = getattr(cfg, "NOMBRE", "mano")
if not RED or not TOKEN:
    raise SystemExit("Faltan RED o TOKEN en config_wifi.py")
print("config_wifi.py: red cargada ({} caracteres), clave cargada ({} caracteres), TOKEN cargado ({} caracteres),"
      " PUERTO {}, NOMBRE {}".format(len(RED), len(CLAVE or ""), len(TOKEN), PUERTO, NOMBRE))
print("(IP_FIJA y SEG_SIN_PC no se usan en esta prueba: la IP la da el punto de acceso)")

# ---------------- Bufers pequenos, reservados una sola vez ----------------
buf = bytearray(BLOQUE)
mv = memoryview(buf)
silencio = bytearray(1600)              # 50 ms de silencio
print("Bufer de red: {} bytes ({} ms de audio). RAM libre: {} KB".format(BLOQUE, BLOQUE // BYTES_POR_MS, libre()))

# ---------------- Bluetooth opcional (solo para medir la convivencia) ----------------
if USAR_BLE:
    import bluetooth
    ble = bluetooth.BLE()
    ble.active(True)
    nombre_ble = b"Mano-prueba"
    ble.gap_advertise(100000, adv_data=b"\x02\x01\x06" + bytes((len(nombre_ble) + 1, 0x09)) + nombre_ble)
    print("Bluetooth activo, anunciandose como Mano-prueba. RAM libre: {} KB".format(libre()))

# ---------------- WiFi: connect sin bloquear + espera acotada ----------------
try:
    network.hostname(NOMBRE)            # para <NOMBRE>.local (mDNS)
except Exception as e:
    print("(no se pudo fijar el nombre: {})".format(e))
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
try:
    wlan.config(pm=wlan.PM_NONE)        # sin ahorro de energia (como Doby)
except Exception:
    pass
t0 = time.ticks_ms()
if not wlan.isconnected():
    wlan.connect(RED, CLAVE)            # vuelve enseguida
while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), t0) < SEG_WIFI * 1000:
    time.sleep_ms(200)
if not wlan.isconnected():
    raise SystemExit("No conecto al WiFi en {} s: punto de acceso encendido y en 2.4 GHz?".format(SEG_WIFI))
IP = wlan.ifconfig()[0]
try:
    rssi = wlan.status("rssi")
except Exception:
    rssi = "?"
print("WiFi conectado en {:.1f} s. IP: {}   senal: {} dBm".format(time.ticks_diff(time.ticks_ms(), t0) / 1000, IP,
                                                                    rssi))
print("RAM con el WiFi activo: {} KB libres".format(libre()))


class Corte(Exception):
    pass


def leer_bloque(c, cuanto):
    """Llena mv[:cuanto] desde el socket. Lanza Corte si el PC deja de mandar SEG_CORTE s o cierra."""
    total = 0
    while total < cuanto:
        try:
            k = c.readinto(mv[total:cuanto])
        except OSError:
            raise Corte()               # timeout del socket
        if not k:
            raise Corte()               # el PC cerro
        total += k
    return total


def responder(c, texto):
    c.write((texto + "\n").encode())


def medir_red(c, n):
    """Recibe n bytes y los descarta: la velocidad de la red sin el ritmo del audio."""
    responder(c, "listo")
    t = time.ticks_ms()
    restante = n
    while restante > 0:
        restante -= leer_bloque(c, min(BLOQUE, restante))
    ms = time.ticks_diff(time.ticks_ms(), t)
    print("Red: {:.1f} KB en {} ms ({:.0f} KB/s)".format(n / 1024, ms, n / 1024 / max(ms, 1) * 1000))
    responder(c, "red:{}:{}".format(n, ms))


def sonar_mientras_llega(c, n):
    """Lee n bytes en bloques de BLOQUE y los escribe al I2S a medida que llegan.
    Corte = antes de escribir un bloque, el audio ya escrito termino de sonar (el I2S se quedo sin datos)."""
    antes = libre()
    i2s = None
    paso = "i2s"
    try:
        i2s = I2S(0, sck=Pin(PIN_BCLK), ws=Pin(PIN_LRC), sd=Pin(PIN_DIN), mode=I2S.TX,
                  bits=16, format=I2S.MONO, rate=TASA, ibuf=IBUF)
        sonando = libre()
        responder(c, "listo")
        t_inicio = None                 # cuando empezo a sonar (se corre si hubo un corte)
        escrito = 0
        cortes = 0
        ms_sin_datos = 0
        t_red = time.ticks_ms()
        while escrito < n:
            paso = "corte"
            k = leer_bloque(c, min(BLOQUE, n - escrito))
            paso = "i2s"
            ahora = time.ticks_ms()
            if t_inicio is None:
                t_inicio = ahora
            else:
                atraso = time.ticks_diff(ahora, t_inicio) - escrito // BYTES_POR_MS
                if atraso > TOLERANCIA_MS:
                    cortes += 1
                    ms_sin_datos += atraso
                    t_inicio = time.ticks_add(t_inicio, atraso)
            i2s.write(mv[:k])           # se bloquea solo si el colchon de IBUF esta lleno
            escrito += k
        ms_red = time.ticks_diff(time.ticks_ms(), t_red)
        responder(c, "recibido:{}:{}:{}:{}".format(n, ms_red, cortes, ms_sin_datos))
        for _ in range(6):
            i2s.write(silencio)         # 0,3 s de silencio al final (como main.py)
        time.sleep_ms(630)              # lo que tarda en vaciarse IBUF
        ms_total = time.ticks_diff(time.ticks_ms(), t_red)
        i2s.deinit()
        i2s = None
        despues = libre()
        responder(c, "ram:{}:{}:{}".format(antes, sonando, despues))
        print("Sono {:.2f} s: {} cortes ({} ms sin datos), voz_ok a los {} ms. RAM {} -> {} -> {} KB".format(
            n / (2 * TASA), cortes, ms_sin_datos, ms_total, antes, sonando, despues))
        responder(c, "voz_ok:{}".format(ms_total))
        return True
    except Corte:
        print("Envio cortado a mitad: silencio y fin")
        if i2s is not None:
            try:
                i2s.write(silencio)
            except Exception:
                pass
        try:
            responder(c, "voz_error:corte")
        except OSError:
            pass
        return False                    # la conexion queda en un estado desconocido: se cierra
    except Exception as e:
        print("Error del I2S:", e)
        try:
            responder(c, "voz_error:" + paso)
        except OSError:
            pass
        return False                    # a mitad de una frase: se cierra la conexion
    finally:
        if i2s is not None:
            try:
                i2s.deinit()            # suelta los pines; sin reloj el MAX98357 se apaga solo
            except Exception:
                pass


def atender(c):
    """Un PC conectado. Devuelve False con 'salir'."""
    linea = c.readline()
    if linea.decode().strip() != "auth " + TOKEN:
        responder(c, "error:auth")
        print("Token incorrecto: conexion cerrada")
        return True
    responder(c, "ok:auth")
    print("PC autenticado")
    while True:
        c.settimeout(None)              # entre ordenes se puede esperar lo que sea
        linea = c.readline()
        if not linea:
            print("El PC cerro la conexion")
            return True
        partes = linea.decode().strip().split()
        if not partes:
            continue
        orden = partes[0]
        c.settimeout(SEG_CORTE)         # dentro de una orden: SEG_CORTE sin datos = corte
        if orden == "ping":
            responder(c, "pong")
        elif orden == "mem":
            responder(c, "mem:{}".format(libre()))
        elif orden == "salir":
            responder(c, "chao")
            return False
        elif orden in ("wav", "red") and len(partes) == 2:
            try:
                n = int(partes[1])
            except ValueError:
                n = -1
            if n <= 0 or n > MAX_BYTES or n % 2:
                responder(c, "voz_error:tamano")
                continue
            if orden == "red":
                medir_red(c, n)
            elif not sonar_mientras_llega(c, n):
                return True             # corte: se cierra esta conexion y se espera otra
        else:
            responder(c, "comando_no_reconocido")


# ---------------- Servidor TCP ----------------
servidor = socket.socket()
servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
servidor.bind(("0.0.0.0", PUERTO))
servidor.listen(1)
print("=" * 44)
print("LISTO. En el PC (misma red):")
print("  py -3.11 fusion/pruebas/prueba_wifi_envio.py --ip {}".format(IP))
print("Para terminar: Stop en Thonny (o --salir desde el PC) y reiniciar la placa.")
seguir = True
try:
    while seguir:
        c, direccion = servidor.accept()
        print("PC conectado desde", direccion)
        c.settimeout(10)
        try:
            seguir = atender(c)
        except Corte:
            print("Envio cortado")
        except OSError as e:
            print("Conexion cortada:", e)
        finally:
            c.close()
finally:
    servidor.close()
    print("Fin de la prueba. Reinicia la placa (RST o desconectar el USB): vuelve main.py (voz-2).")
