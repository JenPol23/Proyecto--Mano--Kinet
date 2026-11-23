"""
consola_mano.py  -  CORRE EN EL PC (py -3.11)
La mano por Bluetooth (BLE): clase Mano para el programa de la fusion + prueba por consola.

- Logica BLE copiada de consola_pc.py (UART de Nordic, trozos de 20 bytes, "auth <TOKEN>"), con el protocolo
  que SI envia main.py: ok:auth, gesto_x_ok, letra_actual:x, deletreo_completo, reset_ok.
- NOMBRE y TOKEN se leen de config_ble.py (raiz del proyecto) sin ejecutarlo; el token nunca se muestra.
- La conexion se abre una vez y queda abierta, en un hilo con su propio bucle asyncio (asi bleak no choca con
  la ventana de OpenCV). Las funciones publicas esperan el resultado y devuelven (ok, mensaje): nunca lanzan.
- deletrear() sigue los tramos de reconocer.py: tramo de 2+ letras -> espera deletreo_completo; tramo de 1 letra
  -> gesto_x_ok + 1 s + reset; letra con movimiento -> reset + 1,5 s (la muestra la pantalla); al final reset y
  reset_ok (main.py envia deletreo_completo ANTES de abrir la mano; el reset_ok llega con la mano ya quieta).
- hablar(nombres, espera) manda "voz <nombres>" (firmware de firmware_mano/main.py) y espera voz_ok,
  voz_falta:<...> o voz_error:<motivo> como mucho 'espera' segundos (voz.py pasa la duracion del audio + 5 s).
- version() manda "?" (el firmware sin voz responde comando_no_reconocido SIN mover la mano; "version" se
  deletrearia) y devuelve (True, "voz-2") o (False, MSG_SIN_VOZ).
- al_evento(tipo, dato) se llama desde el hilo BLE. Para el CSV y la consola: 'letra' x (letra formada),
  'movimiento' x, 'espacio', 'aviso' texto, 'fin'. Para la pantalla (pantalla_mano.py): 'envio' letras (se manda
  un tramo), 'reset' (se manda reset), 'reset_ok', 'deletreo_completo'.
- Las esperas se cortan con Ctrl+C (se espera en pasos de 0,2 s) y cerrar() siempre suelta el Bluetooth: cancela
  la orden en curso y desconecta en 3 s como mucho; tambien se llama sola al salir del programa (atexit).
- detener() (desde cualquier hilo) cancela la orden en curso SIN soltar el Bluetooth: deletrear() no manda el
  tramo siguiente y devuelve (False, MSG_DETENIDO); despues se puede mandar reset(). La bandera se limpia al
  empezar la orden siguiente.
- Modo interactivo: lo que empieza con "!" se manda tal cual a la placa y se muestran sus respuestas
  (!version, !voz jean, !voz jean paul, !voz xyz, !reset, !a ...).
- Cada deletreo agrega filas a fusion/registros/tiempos_mano.csv (nunca borra las anteriores): una por evento,
  con seg_letra = tiempo desde el evento anterior y seg_acumulado = desde el inicio; 'resultado' es 'ok' o
  'error: <mensaje>' en todas las filas de ese deletreo. Si el CSV no se puede escribir (abierto en Excel), se
  avisa y el deletreo cuenta igual.

Uso (desde la carpeta del proyecto; cerrar Thonny y cualquier otro programa conectado a la mano):
  py -3.11 fusion/consola_mano.py                     modo interactivo (un nombre, "!orden", "reset" o "salir")
  py -3.11 fusion/consola_mano.py --palabra "Raigozo"
"""

import argparse
import ast
import asyncio
import atexit
import concurrent.futures
import csv
import os
import sys
import threading
import time
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)

from reconocer import Integrantes, interpretar, texto_tramos   # noqa: E402

RUTA_CONFIG = os.path.join(RAIZ, "config_ble.py")
RUTA_TIEMPOS = os.path.join(AQUI, "registros", "tiempos_mano.csv")
COLUMNAS_TIEMPOS = ["id_prueba", "fecha_hora", "texto", "palabra", "tramo", "letra", "tipo",
                    "seg_letra", "seg_acumulado", "resultado"]
TIPOS = {"letra": "estática", "movimiento": "con movimiento", "espacio": "espacio", "fin": "fin"}
UART_RX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"     # el PC escribe aqui
UART_TX = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"     # la placa responde por aqui

SEG_BUSQUEDA = 10       # buscar la placa por nombre
SEG_CONEXION = 15
SEG_AUTH = 5            # la placa desconecta si no recibe el token en 3 s
SEG_RESPUESTA = 20      # por respuesta; una letra tarda como mucho ~5 s
SEG_CIERRE = 3          # cerrar(): desconectar como mucho en este tiempo
PASO_ESPERA = 0.2       # las esperas se hacen en pasos cortos para que Ctrl+C corte enseguida
VERSION_VOZ = "voz-2"   # = VERSION de firmware_mano/main.py
PAUSA_LETRA_SUELTA = 1.0    # = PAUSA_LETRA de main.py
PAUSA_MOVIMIENTO = 1.5      # la letra con movimiento queda en pantalla
PAUSA_ESPACIO = 1.0         # entre palabras

MSG_NO_RESPONDE = ("La mano no responde: revisa que esté prendida y cerca, que no esté emparejada en Windows "
                   "y que Thonny y cualquier otro programa conectado a la mano estén cerrados")
MSG_TOKEN = "La mano rechazó el token: config_ble.py no coincide con la placa"
MSG_BLUETOOTH = "El Bluetooth del PC está apagado: actívalo en Configuración > Bluetooth y dispositivos"
MSG_TIEMPO = "La mano no respondió a tiempo"
MSG_CORTE = "Se perdió la conexión con la mano"
MSG_SIN_VOZ = "La placa tiene el firmware sin voz: sube firmware_mano/main.py con Thonny"
MSG_DETENIDO = "Deletreo detenido"


class ErrorMano(Exception):
    pass


def leer_config(ruta=RUTA_CONFIG):
    """(NOMBRE, TOKEN) de config_ble.py, leidos sin ejecutar el archivo."""
    try:
        with open(ruta, encoding="utf-8") as f:
            arbol = ast.parse(f.read())
    except OSError:
        raise ErrorMano("Falta config_ble.py en la carpeta del proyecto ({})".format(ruta))
    valores = {}
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    try:
                        valores[destino.id] = ast.literal_eval(nodo.value)
                    except ValueError:
                        pass
    token = valores.get("TOKEN")
    if not isinstance(token, str) or len(token) < 16:
        raise ErrorMano("config_ble.py no tiene un TOKEN válido (mínimo 16 caracteres)")
    return valores.get("NOMBRE", "Mano-LSC"), token


def mensaje_de(error):
    """Mensaje claro para la pantalla a partir de cualquier error."""
    if isinstance(error, ErrorMano):
        return str(error)
    if type(error).__name__ == "BleakBluetoothNotAvailableError":
        return MSG_BLUETOOTH
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return MSG_TIEMPO
    return "{} ({})".format(MSG_NO_RESPONDE, type(error).__name__)


def guardar_tiempos(filas, resultado, ruta=RUTA_TIEMPOS):
    """Agrega las filas de un deletreo al CSV. Devuelve un aviso si no se pudo (o '' si todo bien)."""
    if not filas:
        return ""
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        nuevo = not os.path.exists(ruta)
        with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS_TIEMPOS)
            if nuevo:
                w.writeheader()
            for fila in filas:
                w.writerow(dict(fila, resultado=resultado))
        return ""
    except OSError as e:
        return "No se pudo guardar tiempos_mano.csv ({}): ¿está abierto en Excel?".format(e.strerror or e)


class Mano:
    def __init__(self, ruta_config=RUTA_CONFIG, ruta_tiempos=RUTA_TIEMPOS):
        self.ruta_config = ruta_config
        self.ruta_tiempos = ruta_tiempos
        self.aviso_tiempos = ""          # ultimo problema al escribir el CSV ('' si ninguno)
        self.nombre = None
        self.cliente = None
        self.conectada = False
        self.lineas = None
        self.buffer = b""
        self.cerrada = False
        self.pendientes = set()          # ordenes en curso (cerrar() y detener() las cancelan)
        self._detenido = False           # detener(): deletrear no manda el tramo siguiente
        self.bucle = asyncio.new_event_loop()
        self.hilo = threading.Thread(target=self.bucle.run_forever, daemon=True)
        self.hilo.start()
        atexit.register(self.cerrar)     # el Bluetooth se suelta aunque el programa termine por un error

    # ---------------- API publica (esperan; nunca lanzan, salvo Ctrl+C) ----------------
    def conectar(self):
        """(ok, mensaje)."""
        return self._llamar(self._conectar(), "Mano conectada")

    def deletrear(self, resultado, al_evento=None):
        """(ok, mensaje). 'resultado' es un reconocer.Resultado con ok=True."""
        if not resultado.ok:
            return False, "Nada que deletrear: " + resultado.motivo
        filas = []
        try:
            ok, mensaje = self._llamar(self._deletrear(resultado, al_evento, filas), "Deletreo completo")
        except KeyboardInterrupt:
            self.aviso_tiempos = guardar_tiempos(filas, "error: interrumpido (Ctrl+C)", self.ruta_tiempos)
            raise
        self.aviso_tiempos = guardar_tiempos(filas, "ok" if ok else "error: " + mensaje, self.ruta_tiempos)
        return ok, mensaje

    def reset(self):
        return self._llamar(self._con_conexion(lambda: self._orden("reset", {"reset_ok"})), "Mano abierta")

    def hablar(self, nombres, espera=SEG_RESPUESTA):
        """Orden "voz <nombres>": suena /voz/<nombre>.wav en la placa y espera como mucho 'espera' segundos.
        (ok, respuesta); respuesta = 'voz_ok', 'voz_falta:<a>,<b>' o 'voz_error:<motivo>' (lo que respondio la
        placa) o el mensaje del error de conexion o de tiempo."""
        orden = "voz " + " ".join(nombres)
        try:
            respuesta = self._esperar(self._con_conexion(
                lambda: self._orden(orden, {"voz_ok"}, espera=espera, prefijos=("voz_falta:", "voz_error:"))))
            return respuesta == "voz_ok", respuesta
        except KeyboardInterrupt:
            raise
        except Exception as e:
            return False, mensaje_de(e)

    def version(self):
        """(True, 'voz-2') si la placa tiene el firmware con voz; (False, mensaje) si no o si no responde.
        Manda "?" y no "version": el firmware sin voz deletrearia "version" (moveria la mano ~35 s)."""
        try:
            respuesta = self._esperar(self._con_conexion(
                lambda: self._orden("?", set(), espera=5, prefijos=("version:",), no_reconocido_vale=True)))
        except KeyboardInterrupt:
            raise
        except Exception as e:
            return False, mensaje_de(e)
        if respuesta.startswith("version:"):
            version = respuesta.split(":", 1)[1]
            if version == VERSION_VOZ:
                return True, version
            return False, "La placa tiene otra versión del firmware ({}); se esperaba {}".format(version, VERSION_VOZ)
        return False, MSG_SIN_VOZ

    def orden_directa(self, texto, al_linea=None):
        """Manda 'texto' tal cual (modo !orden) y devuelve (ok, ultima_respuesta). Cada respuesta intermedia
        se pasa a al_linea. Sabe cual es la respuesta final segun la orden."""
        cmd = texto.strip().lower()
        finales, prefijos, espera = set(), (), SEG_RESPUESTA
        if cmd in ("reset", "1"):
            finales = {"reset_ok"}
        elif cmd in ("version", "?"):
            prefijos, espera = ("version:",), 5
        elif cmd == "voz" or cmd.startswith("voz "):
            finales, prefijos = {"voz_ok"}, ("voz_falta:", "voz_error:")    # 20 s: ningun nombre dura tanto
        elif len(cmd) == 1:
            prefijos = ("gesto_",)
        else:
            finales = {"deletreo_completo"}
        try:
            respuesta = self._esperar(self._con_conexion(
                lambda: self._orden(texto.strip(), finales, al_linea, espera, prefijos, no_reconocido_vale=True)))
            return True, respuesta
        except KeyboardInterrupt:
            raise
        except Exception as e:
            return False, mensaje_de(e)

    def cerrar(self):
        """Cancela lo que este en curso y suelta el Bluetooth (como mucho SEG_CIERRE s). Se puede llamar varias
        veces. No manda reset: podria mezclarse con una letra a medias."""
        if self.cerrada:
            return
        self.cerrada = True
        for futuro in list(self.pendientes):
            futuro.cancel()
        try:
            asyncio.run_coroutine_threadsafe(self._desconectar(), self.bucle).result(timeout=SEG_CIERRE)
        except BaseException:
            pass
        self.bucle.call_soon_threadsafe(self.bucle.stop)

    def detener(self):
        """Cancela la orden en curso sin soltar el Bluetooth. Se puede llamar desde cualquier hilo: la cancelacion
        se hace dentro del bucle BLE. No manda reset (lo manda quien llama, cuando la orden ya termino)."""
        self._detenido = True

        def cancelar():
            if not self._detenido:               # ya empezo otra orden (p. ej. el reset): no se cancela
                return
            for futuro in list(self.pendientes):
                futuro.cancel()

        if not self.cerrada:
            self.bucle.call_soon_threadsafe(cancelar)

    def _esperar(self, corrutina):
        """Ejecuta la corrutina en el hilo BLE y espera en pasos cortos (asi Ctrl+C corta enseguida en Windows).
        Con Ctrl+C cancela la orden y vuelve a lanzar KeyboardInterrupt."""
        if self.cerrada:
            corrutina.close()
            raise ErrorMano(MSG_CORTE)
        self._detenido = False                   # orden nueva: se olvida un detener() anterior
        futuro = asyncio.run_coroutine_threadsafe(corrutina, self.bucle)
        self.pendientes.add(futuro)
        try:
            while not futuro.done():             # (no usar result(timeout): en 3.11 su TimeoutError es el mismo
                concurrent.futures.wait([futuro], timeout=PASO_ESPERA)   # que el de la orden y se confundirian)
                if self.cerrada and not futuro.done():   # cerrar() llego mientras se enviaba: el bucle ya
                    futuro.cancel()                      # no corre y la orden no terminaria nunca
                    raise ErrorMano(MSG_CORTE)
            try:
                return futuro.result()
            except concurrent.futures.CancelledError:
                raise ErrorMano(MSG_DETENIDO if self._detenido and not self.cerrada else MSG_CORTE)
        except KeyboardInterrupt:
            futuro.cancel()
            raise
        finally:
            self.pendientes.discard(futuro)

    def _llamar(self, corrutina, mensaje_ok):
        try:
            self._esperar(corrutina)
            return True, mensaje_ok
        except KeyboardInterrupt:
            raise
        except Exception as e:
            return False, mensaje_de(e)

    # ---------------- Conexion (en el hilo BLE) ----------------
    async def _conectar(self):
        import bleak

        self.nombre, token = leer_config(self.ruta_config)
        await self._desconectar()
        dispositivo = await bleak.BleakScanner.find_device_by_name(self.nombre, timeout=SEG_BUSQUEDA)
        if dispositivo is None:
            raise ErrorMano(MSG_NO_RESPONDE)
        self.lineas = asyncio.Queue()
        self.buffer = b""
        cliente = bleak.BleakClient(dispositivo, disconnected_callback=self._al_desconectar)
        await cliente.connect(timeout=SEG_CONEXION)
        self.cliente = cliente
        self.conectada = True
        await cliente.start_notify(UART_TX, self._al_notificar)
        respuesta = await self._orden("auth " + token, {"ok:auth", "error:auth"}, espera=SEG_AUTH)
        if respuesta == "error:auth":
            await self._desconectar()
            raise ErrorMano(MSG_TOKEN)

    async def _desconectar(self):
        cliente, self.cliente, self.conectada = self.cliente, None, False
        if cliente is not None:
            try:
                await cliente.disconnect()
            except Exception:
                pass

    async def _con_conexion(self, fabrica):
        """Reconecta si hace falta y luego ejecuta la orden. 'fabrica' crea la corrutina de la orden solo cuando
        se va a usar (asi, si la mano ya esta cerrada, no queda ninguna corrutina sin esperar)."""
        if not self.conectada:
            await self._conectar()
        return await fabrica()

    def _al_notificar(self, _caracteristica, datos):
        self.bucle.call_soon_threadsafe(self._recibir, bytes(datos))

    def _recibir(self, datos):
        self.buffer += datos
        while b"\n" in self.buffer:
            linea, self.buffer = self.buffer.split(b"\n", 1)
            self.lineas.put_nowait(linea.decode("utf-8", "ignore").strip())

    def _al_desconectar(self, _cliente):
        self.bucle.call_soon_threadsafe(self._marcar_corte)

    def _marcar_corte(self):
        self.conectada = False
        if self.lineas is not None:
            self.lineas.put_nowait(None)          # despierta a quien este esperando una respuesta

    # ---------------- Ordenes ----------------
    async def _enviar(self, texto):
        if not self.conectada or self.cliente is None:
            raise ErrorMano(MSG_CORTE)
        datos = (texto + "\n").encode()
        for k in range(0, len(datos), 20):        # paquetes de 20 bytes: sirve con cualquier MTU
            await self.cliente.write_gatt_char(UART_RX, datos[k:k + 20], response=True)

    async def _orden(self, texto, finales, al_linea=None, espera=SEG_RESPUESTA, prefijos=(), no_reconocido_vale=False):
        """Envia una orden y lee respuestas hasta una de 'finales' o que empiece con 'prefijos' (que devuelve).
        comando_no_reconocido es un error, salvo con no_reconocido_vale (entonces se devuelve)."""
        while not self.lineas.empty():            # respuestas viejas: no se mezclan con esta orden
            if self.lineas.get_nowait() is None:
                raise ErrorMano(MSG_CORTE)
        await self._enviar(texto)
        while True:
            try:
                linea = await asyncio.wait_for(self.lineas.get(), espera)
            except asyncio.TimeoutError:
                raise ErrorMano(MSG_TIEMPO)
            if linea is None:
                raise ErrorMano(MSG_CORTE)
            if linea in finales or (prefijos and linea.startswith(prefijos)):
                return linea
            if linea == "comando_no_reconocido":
                if no_reconocido_vale:
                    return linea
                raise ErrorMano("La mano no entendió la orden '{}'".format(texto.split()[0]))
            if al_linea is not None:
                al_linea(linea)

    async def _deletrear(self, resultado, al_evento, filas):
        """Deletrea los tramos de 'resultado'; anota en 'filas' una fila por evento (para el CSV)."""
        inicio = anterior = time.perf_counter()
        id_prueba = datetime.now().isoformat(sep=" ", timespec="seconds")
        palabras = resultado.mostrar.split(" ")             # como se muestran (Enríquez con tilde)
        donde = {"palabra": "", "tramo": ""}

        def evento(tipo, dato=""):
            nonlocal anterior
            if tipo in TIPOS:
                ahora = time.perf_counter()
                filas.append({"id_prueba": id_prueba,
                              "fecha_hora": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                              "texto": resultado.mostrar, "palabra": donde["palabra"], "tramo": donde["tramo"],
                              "letra": dato, "tipo": TIPOS[tipo], "seg_letra": "{:.2f}".format(ahora - anterior),
                              "seg_acumulado": "{:.2f}".format(ahora - inicio)})
                anterior = ahora
            if al_evento is not None:
                al_evento(tipo, dato)

        def al_linea(linea):
            if linea.startswith("letra_actual:"):
                evento("letra", linea.split(":", 1)[1])
            elif linea.endswith("_no_disponible"):
                evento("aviso", linea)

        async def reset():
            evento("reset")
            await self._orden("reset", {"reset_ok"})
            evento("reset_ok")

        if not self.conectada:
            await self._conectar()
        await reset()
        for n, tramos in enumerate(resultado.tramos):
            donde["palabra"] = palabras[n] if n < len(palabras) else resultado.palabras_mano[n]
            if n:
                donde["tramo"] = ""
                await reset()
                evento("espacio")
                await asyncio.sleep(PAUSA_ESPACIO)
            for tipo, letras in tramos:
                if self._detenido:                  # detener(): no se manda el tramo siguiente
                    raise ErrorMano(MSG_DETENIDO)
                donde["tramo"] = letras if tipo == "mano" else "[{}]".format(letras.upper())
                if tipo == "movimiento":
                    await reset()
                    evento("movimiento", letras)
                    await asyncio.sleep(PAUSA_MOVIMIENTO)
                elif len(letras) == 1:
                    evento("envio", letras)
                    await self._orden(letras, {"gesto_{}_ok".format(letras)})
                    evento("letra", letras)
                    await asyncio.sleep(PAUSA_LETRA_SUELTA)
                    await reset()
                else:
                    evento("envio", letras)
                    await self._orden(letras, {"deletreo_completo"}, al_linea)
                    evento("deletreo_completo")
        donde["tramo"] = ""
        await reset()
        evento("fin")


# ---------------- Prueba por consola ----------------
def probar(mano, integrantes, texto):
    r = interpretar(texto, integrantes)
    if not r.ok:
        print("  ✗ {}".format(r.motivo))
        return False
    print("  Deletreando \"{}\" ({}):  {}".format(r.mostrar, integrantes.nombre_completo(r.persona),
                                                "  |  ".join(texto_tramos(t) for t in r.tramos)))
    inicio = time.perf_counter()

    def al_evento(tipo, dato):
        t = time.perf_counter() - inicio
        if tipo == "letra":
            print("  [{:5.1f} s] letra {}".format(t, dato))
        elif tipo == "movimiento":
            print("  [{:5.1f} s] {}  (con movimiento: mano abierta)".format(t, dato.upper()))
        elif tipo == "espacio":
            print("  [{:5.1f} s] -- espacio --".format(t))
        elif tipo == "aviso":
            print("  [{:5.1f} s] aviso: {}".format(t, dato))
        elif tipo == "fin":
            print("  [{:5.1f} s] mano abierta: fin".format(t))

    ok, mensaje = mano.deletrear(r, al_evento)
    print("  {} {}  (total {:.1f} s)".format("✔" if ok else "✗", mensaje, time.perf_counter() - inicio))
    print("  {}".format(mano.aviso_tiempos or "Tiempos guardados en " + os.path.relpath(mano.ruta_tiempos, RAIZ)))
    return ok


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Probar la mano por Bluetooth (sin Kinect ni voz)")
    parser.add_argument("--palabra", help="deletrear este nombre una vez y terminar")
    args = parser.parse_args()

    integrantes = Integrantes()
    mano = Mano()
    try:
        nombre, token = leer_config()
    except ErrorMano as e:
        print(e)
        return 1
    print("Buscando '{}' por Bluetooth (token cargado: {} caracteres)...".format(nombre, len(token)))
    try:
        ok, mensaje = mano.conectar()
        print(mensaje)
        if not ok:
            return 1
        if args.palabra:
            return 0 if probar(mano, integrantes, args.palabra) else 1
        print("Escribe un nombre del grupo, \"!orden\" (se manda tal cual: !version, !voz jean), \"reset\" o "
              "\"salir\". Ctrl+C sale enseguida.")
        while True:
            texto = input("> ").strip()
            if texto.lower() in ("salir", "0"):
                mano.reset()
                break
            if texto.startswith("!"):
                orden = texto[1:].strip()
                if orden:
                    inicio = time.perf_counter()
                    ok, respuesta = mano.orden_directa(
                        orden, lambda linea: print("  [{:5.1f} s] {}".format(time.perf_counter() - inicio, linea)))
                    print("  [{:5.1f} s] {} {}".format(time.perf_counter() - inicio, "<-" if ok else "✗", respuesta))
            elif texto.lower() == "reset":
                print("  {}".format(mano.reset()[1]))
            elif texto:
                probar(mano, integrantes, texto)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nSaliste. La mano queda como estaba.")    # no se manda reset: podria mezclarse con un deletreo
        return 0
    finally:
        mano.cerrar()


if __name__ == "__main__":
    sys.exit(main())
