"""
generar_hora_noche.py  -  CORRE EN EL PC, CON venv_f5 (pensado para correr solo, toda la noche)
Las frases de la hora de TODAS las voces, una detras de otra, en un solo proceso: jenpol, camila, harry y lina,
1440 horas cada una, con el control estricto de generar_hora.py (similitud >= 0.95 y hora/minutos exactos).
Lo que falla va a _revisar_de_oido/ y se sigue. Se puede retomar: salta lo que ya existe. Al terminar escribe
datos_voz/reportes/resumen_hora_noche.md.

Uso (desde la carpeta del proyecto):
  venv_f5\\Scripts\\python.exe -u entrenamiento/generar_hora_noche.py
  venv_f5\\Scripts\\python.exe -u entrenamiento/generar_hora_noche.py --solo-resumen [--salida RUTA.md]
Para que no dependa de Claude Code se lanza como tarea programada de Windows ("DobyHoraNoche"):
  Start-ScheduledTask -TaskName DobyHoraNoche          (lanzar o retomar)
  Stop-ScheduledTask -TaskName DobyHoraNoche           (detener; se retoma despues sin perder nada)

- Log del avance: logs/hora_noche_<fecha>.log. Candado: logs/hora_noche.lock (no corren dos a la vez).
- Mientras corre le pide a Windows que no se suspenda por inactividad (SetThreadExecutionState). NO evita
  que se suspenda al cerrar la tapa ni al apagar.
- Si una voz falla por un error inesperado, se anota y se sigue con la siguiente; al final se reintenta una vez.

Dependencias (por importacion, sin modificarlas): entrenamiento/generar_hora.py (generar_persona, escuchar,
aceptable, rutas), pc/hora.py, pc/voz_clonada.py (cobertura).
"""

import argparse
import csv
import ctypes
import gc
import os
import random
import sys
import time
import traceback
from datetime import datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "entrenamiento"))
sys.path.insert(0, os.path.join(RAIZ, "pc"))

VOCES = ["jenpol", "camila", "harry", "lina"]
LOGS = os.path.join(RAIZ, "logs")
CANDADO = os.path.join(LOGS, "hora_noche.lock")
RESUMEN = os.path.join(RAIZ, "datos_voz", "reportes", "resumen_hora_noche.md")
REVALIDACIONES = os.path.join(RAIZ, "voz_comparacion_f5", "_prueba_hora")


class Log:
    """Todo lo que se imprime va al log (con la hora) y, si hay consola, tambien a la consola."""

    def __init__(self, ruta, consola):
        self.f = open(ruta, "a", encoding="utf-8", buffering=1)
        self.consola = consola
        self.pendiente = ""                              # print() escribe en pedazos: se arma la linea completa

    def write(self, texto):
        self.pendiente += texto.replace("\r", "\n")
        while "\n" in self.pendiente:
            linea, self.pendiente = self.pendiente.split("\n", 1)
            if not linea.strip() or "%|" in linea or "it/s]" in linea or linea.lstrip().startswith(
                    ("gen_text", "pygame", "Hello from", "ref_text", "Converting audio")):
                continue                                 # barras de progreso y avisos de F5/pygame: no al log
            linea = "[{}] {}\n".format(datetime.now().strftime("%H:%M:%S"), linea)
            self.f.write(linea)
            if self.consola is not None:
                try:
                    self.consola.write(linea)
                except Exception:
                    pass

    def flush(self):
        self.f.flush()

    def isatty(self):
        return False


def proceso_vivo(pid):
    """Sin os.kill (en Windows termina el proceso): OpenProcess + GetExitCodeProcess."""
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)                # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    codigo = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(codigo))
    k.CloseHandle(h)
    return codigo.value == 259                           # STILL_ACTIVE


def tomar_candado():
    if os.path.exists(CANDADO):
        try:
            pid = int(open(CANDADO).read().split()[0])
            if proceso_vivo(pid):
                print("Ya hay otro proceso de la noche corriendo (PID {}). Salgo.".format(pid))
                sys.exit(0)
        except (ValueError, IndexError, OSError):
            pass
    with open(CANDADO, "w") as f:
        f.write("{} {}".format(os.getpid(), datetime.now().isoformat(timespec="seconds")))


def prioridad_normal():
    """
    Lanzado por el Programador de tareas y sin ventana, Windows lo trata como proceso de fondo: prioridad baja
    (cargar F5 y Whisper se quedaba casi detenido) y "ahorro de energia" (EcoQoS: 30 s por frase con la GPU al
    1 %, contra 3.8 s en una terminal). Se pide prioridad normal y que no se le aplique el ahorro de energia.
    """
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = ctypes.c_void_p            # HANDLE de 64 bits (sin esto se corta a 32)
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    k.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    proceso = k.GetCurrentProcess()
    k.SetPriorityClass(proceso, 0x00000020)                  # NORMAL_PRIORITY_CLASS

    class EstadoAhorro(ctypes.Structure):                    # PROCESS_POWER_THROTTLING_STATE
        _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]

    estado = EstadoAhorro(1, 0x1, 0x0)                       # EXECUTION_SPEED controlado y apagado = velocidad completa
    ok = k.SetProcessInformation(proceso, 4, ctypes.byref(estado), ctypes.sizeof(estado))   # 4 = ProcessPowerThrottling
    print("Prioridad normal; ahorro de energia de Windows {}.".format(
        "desactivado" if ok else "NO se pudo desactivar (error {})".format(ctypes.get_last_error())))


def no_suspender(activo):
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if activo else 0))


# ---------------- Resumen ----------------
def ultimas_filas(ruta):
    """clave -> ultima fila del generacion.csv de una voz."""
    if not os.path.exists(ruta):
        return {}
    with open(ruta, encoding="utf-8-sig") as f:
        return {r["clave"]: r for r in csv.DictReader(f)}


def resumen(gh, tiempos, salida):
    import voz_clonada
    hora = gh.hora
    lineas = ["# Resumen de la noche: frases de \"¿qué hora es?\"", "",
              "Generado el {} por `entrenamiento/generar_hora_noche.py`.".format(datetime.now().strftime("%Y-%m-%d %H:%M")), "",
              "Control estricto: similitud Whisper >= 0.95 **y** la hora y los minutos exactos (se aceptan solo "
              "\"doce\" por \"dos\" cuando la hora es \"las dos\" y \"dieciséis/diecisiete/diecinueve\" en 10:06, 10:07, "
              "10:09, 22:06, 22:07 y 22:09). Lo que no pasa queda en `<voz>/hora/_revisar_de_oido/`.", "",
              "## 1. Horas por voz", "", "| Voz | Aprobadas | En revisión | Faltan | Tiempo de esta corrida |",
              "|---|---|---|---|---|"]
    revision = {}
    for voz in VOCES:
        aprobadas = sum(os.path.exists(gh.ruta_persona(voz, h, m)) for h, m in hora.todas())
        revision[voz] = [(h, m) for h, m in hora.todas() if os.path.exists(gh.ruta_revisar(voz, h, m))]
        faltan = 1440 - aprobadas - len(revision[voz])
        lineas.append("| {} | {} | {} | {} | {} |".format(voz, aprobadas, len(revision[voz]), faltan,
                                                          tiempos.get(voz, "(no se corrió esta noche)")))
    normal = sum(os.path.exists(hora.ruta_normal(h, m)) for h, m in hora.todas())
    lineas += ["| normal (gTTS) | {} | — | {} | (15-oct) |".format(normal, 1440 - normal), ""]

    lineas += ["## 2. Horas en revisión", ""]
    if not any(revision.values()):
        lineas += ["Ninguna.", ""]
    for voz, horas in revision.items():
        if not horas:
            continue
        filas = ultimas_filas(os.path.join(gh.carpeta_persona(voz), "generacion.csv"))
        lineas += ["### {} ({})".format(voz, len(horas)), "", "| Hora | Debía decir | Whisper oyó (mejor intento) | Similitud |",
                   "|---|---|---|---|"]
        for h, m in horas:
            r = filas.get(hora.clave(h, m), {})
            lineas.append("| {:02d}:{:02d} | {} | {} | {} |".format(h, m, hora.texto(h, m), r.get("texto_whisper", "?"),
                                                                     r.get("similitud", "?")))
        lineas += ["", "Escuchar las de revisión (parlantes del PC):", "```powershell",
                   "Get-ChildItem \"{}\\*.wav\" | ForEach-Object {{ Write-Host $_.BaseName.Substring(5,4).Insert(2, ':'); "
                   "(New-Object System.Media.SoundPlayer $_.FullName).PlaySync(); Start-Sleep -Milliseconds 400 }}".format(
                       os.path.relpath(os.path.join(gh.carpeta_persona(voz), "_revisar_de_oido"), RAIZ)),
                   "```", "Aprobar o rechazar una (ej. 02:07): `venv_f5\\Scripts\\python.exe entrenamiento/generar_hora.py "
                   "--aprobar {0} 0207` / `--rechazar {0} 0207`".format(voz), ""]

    lineas += ["## 3. Revisión con el control estricto (15-oct, solo transcribir)", ""]
    for voz, nombre in (("jenpol", "jenpol (las 60 de la muestra)"), ("normal", "voz normal (las 1440)")):
        ruta = os.path.join(REVALIDACIONES, "revalidacion_{}.csv".format(voz))
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8-sig") as f:
                filas = list(csv.DictReader(f))
            malas = [r for r in filas if r["acepta"] != "True"]
            lineas.append("- {}: {} revisadas, **{} no pasan**{}".format(
                nombre, len(filas), len(malas), "" if not malas else ": " + ", ".join(r["clave"][5:] for r in malas)))
        else:
            lineas.append("- {}: no se encontró {}".format(nombre, os.path.relpath(ruta, RAIZ)))
    lineas.append("")

    ok, lineas_cobertura = voz_clonada.cobertura()
    lineas += ["## 4. Cobertura final (`py pruebas/verificar_cobertura.py`)", "", "```"] + lineas_cobertura + [
        "", "RESULTADO: {}".format("100 % - se puede activar VOZ_CLONADA" if ok else "FALLA - NO activar VOZ_CLONADA"),
        "```", ""]

    lineas += ["## 5. Escuchar 10 horas al azar de cada persona (parlantes del PC)", "",
               "Ya están copiadas en `voz_comparacion_f5/_prueba_hora/escuchar_<persona>/` (el nombre es la hora). "
               "Desde la carpeta del proyecto:", ""]
    for voz in VOCES:
        existentes = [hm for hm in hora.todas() if os.path.exists(gh.ruta_persona(voz, *hm))]
        if not existentes:
            lineas += ["- {}: todavía no tiene horas aprobadas.".format(voz), ""]
            continue
        elegidas = sorted(random.sample(existentes, min(10, len(existentes))))
        gh.escuchar(voz, elegidas)
        lineas += ["**{}**: {}".format(voz, ", ".join("{:02d}:{:02d}".format(h, m) for h, m in elegidas)), "",
                   "```powershell",
                   "Get-ChildItem \"voz_comparacion_f5\\_prueba_hora\\escuchar_{}\\*.wav\" | Sort-Object Name | ForEach-Object "
                   "{{ Write-Host $_.BaseName.Substring(0,4).Insert(2, ':'); (New-Object System.Media.SoundPlayer "
                   "$_.FullName).PlaySync(); Start-Sleep -Milliseconds 400 }}".format(voz), "```", ""]

    os.makedirs(os.path.dirname(salida), exist_ok=True)
    with open(salida, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print("Resumen escrito en", os.path.relpath(salida, RAIZ))


def main():
    parser = argparse.ArgumentParser(description="Frases de la hora de todas las voces, toda la noche")
    parser.add_argument("--voces", nargs="+", default=VOCES)
    parser.add_argument("--solo-resumen", action="store_true")
    parser.add_argument("--salida", default=RESUMEN)
    args = parser.parse_args()

    os.makedirs(LOGS, exist_ok=True)
    sys.stdout = sys.stderr = Log(os.path.join(LOGS, "hora_noche_{}.log".format(datetime.now().strftime("%Y-%m-%d"))),
                                  sys.__stdout__)
    import generar_hora as gh
    gh.cargar_hora(os.path.join(RAIZ, "pc", "hora.py"))
    if args.solo_resumen:
        resumen(gh, {}, args.salida)
        return

    tomar_candado()
    prioridad_normal()
    no_suspender(True)
    print("==== Inicio de la noche: {} ====".format(", ".join(args.voces)))
    tiempos, con_error = {}, []
    try:
        for ronda in (1, 2):
            pendientes = args.voces if ronda == 1 else con_error
            con_error = []
            for voz in pendientes:
                t = time.perf_counter()
                print("---- {} (ronda {}) ----".format(voz, ronda))
                try:
                    gh.generar_persona(voz, gh.hora.todas())
                except Exception:
                    print("ERROR INESPERADO con {}; sigo con la siguiente voz:\n{}".format(voz, traceback.format_exc()))
                    con_error.append(voz)
                tiempos[voz] = "{:.0f} min".format((time.perf_counter() - t) / 60 + float(tiempos.get(voz, "0 min").split()[0]))
                gc.collect()
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass
            if not con_error:
                break
        if con_error:
            print("Quedaron con error tras el reintento: {}".format(", ".join(con_error)))
        resumen(gh, tiempos, args.salida)
        print("==== Fin de la noche ====")
    finally:
        no_suspender(False)
        try:
            os.remove(CANDADO)
        except OSError:
            pass


if __name__ == "__main__":
    main()
