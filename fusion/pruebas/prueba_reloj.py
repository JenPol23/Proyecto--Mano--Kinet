"""
Prueba de fusion/pantalla_mano.py (RelojMano, Seguimiento y VentanaMano) sin placa ni ventana.

1. Corre el firmware COMPLETO (firmware_mano/main.py) en el PC con machine/USB falsos, como si llegaran ordenes por
   USB, y mide cuando sale cada letra_actual:x, gesto_x_ok y deletreo_completo, y cuando termina de moverse la mano.
   Compara esos tiempos con los que predice RelojMano para las mismas ordenes.
2. Seguimiento: eventos con un reloj falso (formando -> mostrando -> abriendo, corrección con letra_actual, letras
   sueltas, letras con movimiento, espacio, hablando).
3. VentanaMano.dibujar() en varios estados (sin abrir la ventana).

Uso (desde la carpeta del proyecto):  py -3.11 fusion/pruebas/prueba_reloj.py
"""
import io, os, sys, types, time

FUSION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROYECTO = os.path.dirname(FUSION)
sys.path.insert(0, FUSION)
FIRMWARE = os.path.join(PROYECTO, "firmware_mano", "main.py")

from pantalla_mano import RelojMano, Seguimiento, VentanaMano   # noqa: E402  (antes de cambiar time)
from reconocer import Integrantes, interpretar                  # noqa: E402

reloj = RelojMano()                     # se carga antes de reemplazar time para la simulacion del firmware

# ---------------- 1. Firmware completo con ordenes por USB ----------------
T = [0]                                 # ms simulados
SALIDA, PWMS, ENTREGAS = [], [], []
ENTRADA = []


class Pin:
    OUT = 1
    def __init__(s, n, *a, **k):
        s.n = n


class PWM:
    def __init__(s, pin, freq):
        s.p = pin.n
    def duty_ns(s, ns):
        PWMS.append(T[0])


buf = []
class Stdin:
    def read(s, n):
        return buf.pop(0)
class Poll:
    def register(s, *a): pass
    def poll(s, t):
        while ENTRADA and ENTRADA[0][0] <= T[0]:
            ENTREGAS.append((T[0], ENTRADA[0][1]))
            buf.extend(ENTRADA.pop(0)[1] + "\n")
        return bool(buf)


class Captura(io.StringIO):
    def write(s, t):
        SALIDA.extend((T[0], l) for l in t.split("\n") if l)
        return len(t)


def avanzar(seg):
    T[0] += int(round(seg * 1000))


real = {m: sys.modules.get(m) for m in ("machine", "bluetooth", "micropython", "uselect", "config_ble")}
sys.modules["machine"] = types.SimpleNamespace(Pin=Pin, PWM=PWM, I2S=None)
sys.modules["bluetooth"] = types.SimpleNamespace(UUID=lambda x: x, BLE=None)
sys.modules["micropython"] = types.SimpleNamespace(const=lambda x: x)
sys.modules["uselect"] = types.SimpleNamespace(poll=Poll, POLLIN=1)
sys.modules["config_ble"] = None
tiempo_real = (time.sleep, getattr(time, "sleep_ms", None), getattr(time, "ticks_ms", None),
               getattr(time, "ticks_diff", None))
time.sleep = avanzar
time.sleep_ms = lambda ms: avanzar(ms / 1000)
time.ticks_ms = lambda: T[0]
time.ticks_diff = lambda a, b: a - b

PALABRAS = ["lina", "tatiana", "maldonado", "paul", "miranda", "camila"]
SUELTAS = ["a", "k", "o"]
ORDENES = PALABRAS + [x for s in SUELTAS for x in (s, "reset")] + ["salir"]
for k, o in enumerate(ORDENES):
    ENTRADA.append((10000 + k * 120000, o))
stdin_real, stdout_real = sys.stdin, sys.stdout
sys.stdin, sys.stdout = Stdin(), Captura()
try:
    exec(compile(open(FIRMWARE, encoding="utf-8").read(), FIRMWARE, "exec"), {"__name__": "__main__"})
finally:
    sys.stdin, sys.stdout = stdin_real, stdout_real
    time.sleep = tiempo_real[0]
    for m, v in real.items():
        if v is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = v
sys.stdout.reconfigure(encoding="utf-8")

fallas = 0


def chequeo(nombre, cond, extra=""):
    global fallas
    fallas += not cond
    print("{}  {}{}".format("PASA " if cond else "FALLA", nombre, "  " + extra if extra else ""))


def medido(orden):
    """Tiempos (s) desde que la placa recibe 'orden': marcas de letra, deletreo_completo y fin del movimiento."""
    t0 = next(t for t, o in ENTREGAS if o == orden)
    siguiente = min([t for t, o in ENTREGAS if t > t0] + [10 ** 12])
    lineas = [(t, l) for t, l in SALIDA if t0 <= t < siguiente]
    marcas = [(t - t0) / 1000 for t, l in lineas if l.startswith("letra_actual:")]
    if len(orden) == 1:
        marcas = [(t - t0) / 1000 for t, l in lineas if l.startswith("gesto_")]
    completo = next(((t - t0) / 1000 for t, l in lineas if l == "deletreo_completo"), None)
    movs = [t for t in PWMS if t0 <= t < siguiente]
    fin = (max(movs) - t0) / 1000 + reloj.pausa_dedo if movs else 0.0
    return marcas, completo, fin


print("1. RelojMano contra el firmware completo (segundos desde que la placa recibe la orden)")
for palabra in PALABRAS:
    linea = reloj.simular_palabra(palabra)
    marcas, completo, fin = medido(palabra)
    iguales = (len(marcas) == len(linea.marcas) and all(abs(a - b) < 0.002 for a, b in zip(marcas, linea.marcas))
               and abs(completo - linea.t_completo) < 0.002 and abs(fin - linea.total) < 0.002)
    chequeo("{:10} letras {}  deletreo_completo {:5.1f} s  mano abierta {:5.1f} s".format(
        palabra, " ".join("{:.1f}".format(m) for m in linea.marcas), linea.t_completo, linea.total), iguales,
        "" if iguales else "firmware: {} {} {}".format(marcas, completo, fin))
for letra in SUELTAS:
    linea = reloj.simular_letra(letra)
    marcas, _, _ = medido(letra)
    chequeo("letra suelta {}: gesto_{}_ok a los {:.1f} s".format(letra, letra, linea.marcas[0]),
            len(marcas) == 1 and abs(marcas[0] - linea.marcas[0]) < 0.002, str(marcas))

# Fases de "lina": la primera letra se forma desde la mano abierta; entre letras, se abre y se forma la siguiente
linea = reloj.simular_palabra("lina")
fases = [(round(t0, 1), round(t1, 1), e, l) for t0, t1, e, l, _ in linea.segmentos]
print("       fases de 'lina':", fases)
chequeo("'lina' empieza formando la l y termina abriendo la mano",
        fases[0][2:] == ("formando", "l") and fases[-1][2] == "abriendo")
chequeo("cada letra se muestra PAUSA_LETRA = 1 s", all(abs((t1 - t0) - 1.0) < 1e-6
                                                       for t0, t1, e, *_ in linea.segmentos if e == "mostrando"))

# ---------------- 2. Seguimiento con un reloj falso ----------------
print("\n2. Seguimiento (eventos de Mano.deletrear con un reloj falso)")
ahora = [100.0]
ints = Integrantes()
r = interpretar("Lina", ints)
s = Seguimiento(reloj, r, ahora=lambda: ahora[0])


def en(t):
    ahora[0] = t
    e = s.estado()
    return e["estado"], e["letra"], e["posicion"]


s.evento("reset"); s.evento("reset_ok")
s.evento("envio", "lina")                        # en t = 100 (+ latencia)
lin = reloj.simular_palabra("lina")
m0 = lin.marcas[0]
chequeo("al enviar 'lina': formando l (posición 0)", en(100.1) == ("formando", "l", 0), str(en(100.1)))
chequeo("predicción: mostrando l después de su letra_actual", en(100 + 0.05 + m0 + 0.2) == ("mostrando", "l", 0))
ahora[0] = 100 + m0 + 0.6                         # letra_actual:l llega 0,6 s tarde (BLE lento)
s.evento("letra", "l")
chequeo("corrección: al llegar tarde, vuelve a 'mostrando l' desde ese instante",
        en(100 + m0 + 0.6 + 0.9) == ("mostrando", "l", 0), str(en(100 + m0 + 1.5)))
chequeo("después de 1 s mostrando: abriendo / formando la i",
        en(100 + m0 + 0.6 + 1.0 + 0.01)[0] in ("abriendo", "formando"))
s.evento("deletreo_completo")
chequeo("deletreo_completo: abriendo mano", en(ahora[0] + 0.01)[0] == "abriendo")
s.evento("reset"); s.evento("reset_ok"); s.evento("fin")
chequeo("fin: mano abierta", en(ahora[0] + 0.1)[0] == "abierta")
s.hablando()
chequeo("hablando", en(ahora[0])[0] == "hablando")
s.terminado(True, "Sonó: Lina")
chequeo("terminado", en(ahora[0])[0] == "terminado")

# Harry Raigozo: [H] + arry | rai + [G] + o + [Z] + o
r = interpretar("Harry Raigozo", ints)
s = Seguimiento(reloj, r, ahora=lambda: ahora[0])
ahora[0] = 200.0
s.evento("reset"); s.evento("reset_ok")
s.evento("reset"); s.evento("reset_ok"); s.evento("movimiento", "h")
e = s.estado()
chequeo("letra con movimiento h: palabra 0, posición 0", (e["estado"], e["letra"], e["palabra"], e["posicion"])
        == ("movimiento", "h", 0, 0), str(e))
s.evento("envio", "arry")
e = s.estado()
chequeo("tramo 'arry': formando a en la posición 1", (e["estado"], e["letra"], e["posicion"]) == ("formando", "a", 1),
        str(e))
s.evento("deletreo_completo"); s.evento("reset"); s.evento("reset_ok"); s.evento("espacio")
chequeo("espacio", s.estado()["estado"] == "espacio")
s.evento("envio", "rai"); s.evento("deletreo_completo")
s.evento("reset"); s.evento("reset_ok"); s.evento("movimiento", "g")
e = s.estado()
chequeo("letra con movimiento g: palabra 1, posición 3", (e["palabra"], e["posicion"]) == (1, 3), str(e))

# Letra suelta (Raigozo: rai + [G] + o + [Z] + o)
r = interpretar("Raigozo", ints)
s = Seguimiento(reloj, r, ahora=lambda: ahora[0])
ahora[0] = 300.0
s.evento("reset"); s.evento("reset_ok"); s.evento("envio", "rai"); s.evento("deletreo_completo")
s.evento("reset"); s.evento("reset_ok"); s.evento("movimiento", "g")
s.evento("envio", "o")
chequeo("letra suelta o: formando o en la posición 4", en(300.05)[0] in ("formando", "abriendo") and
        s.estado()["posicion"] in (4, None), str(s.estado()))
ahora[0] = 301.0
s.evento("letra", "o")
chequeo("letra suelta o: queda mostrando hasta el reset", en(303.0) == ("mostrando", "o", 4), str(en(303.0)))
s.evento("reset")
chequeo("reset después de la letra suelta: abriendo mano", en(303.1)[0] == "abriendo")

# ---------------- 3. Ventana (sin abrirla) ----------------
print("\n3. VentanaMano.dibujar()")
r = interpretar("Harry Raigozo", ints)
s = Seguimiento(reloj, r)
v = VentanaMano(s)
try:
    imagenes = []
    for ev in [("reset", ""), ("movimiento", "h"), ("envio", "arry"), ("espacio", ""), ("envio", "rai"),
               ("movimiento", "g")]:
        s.evento(*ev)
        imagenes.append(v.dibujar())
    s.hablando(); imagenes.append(v.dibujar())
    s.terminado(False, "Falta audio: Harry, Raigozo"); imagenes.append(v.dibujar())
    chequeo("dibuja {} estados sin errores ({}x{})".format(len(imagenes), imagenes[0].shape[1], imagenes[0].shape[0]),
            all(i.shape == (VentanaMano.ALTO, VentanaMano.ANCHO, 3) for i in imagenes))
    import cv2
    ruta = os.path.join(os.environ.get("TEMP", "."), "ventana_mano_ejemplo.png")
    cv2.imwrite(ruta, imagenes[2])
    print("       ejemplo guardado en", ruta)
except Exception as e:
    chequeo("dibujar la ventana", False, repr(e))

print("\n{} fallas".format(fallas))
sys.exit(1 if fallas else 0)
