"""
Compara firmware_mano/main.py (con voz) contra el respaldo que funciona (firmware_mano/main_funciona_sin_voz.py).

1. Muestra el diff completo, línea por línea.
2. Comprueba que el CÓDIGO de la mano sea idéntico: quita de main.py solo lo que es de la voz (sección VOZ de la
   configuración, sección VOZ de funciones, "import os", I2S en el import de machine y las ramas "version" y "voz"
   de atender_orden) y compara el resto con el respaldo sin comentarios ni líneas en blanco.

Uso (desde la carpeta del proyecto):
  py -3.11 fusion/pruebas/comparar_firmware.py [respaldo] [firmware]
"""
import difflib, os, re, sys

PROYECTO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESPALDO = os.path.join(PROYECTO, "firmware_mano", "main_funciona_sin_voz.py")
FIRMWARE = os.path.join(PROYECTO, "firmware_mano", "main.py")
ESPERADAS = {"SEG_SOLTAR = 3.0"}        # en el respaldo, sin uso; se borró a pedido del usuario


def sin_voz(lineas):
    """Las líneas de main.py sin lo que se agregó para la voz."""
    salida, saltar = [], None
    for linea in lineas:
        s = linea.strip()
        if saltar == "config":
            if not s:
                saltar = None
            continue
        if saltar == "funciones":
            if s.startswith("# ---------------- BUCLE PRINCIPAL"):
                saltar = None
            else:
                continue
        if saltar == "rama":
            if s.startswith("elif ") or s.startswith("else:"):
                if s.startswith('elif cmd == "voz"') or s.startswith('elif cmd == "version"'):
                    continue
                saltar = None
            else:
                continue
        if s.startswith("# ---------------- VOZ (MAX98357"):
            saltar = "config"
            continue
        if s == "# ---------------- VOZ ----------------":
            saltar = "funciones"
            continue
        if s.startswith('elif cmd == "version"') or s.startswith('elif cmd == "voz"'):
            saltar = "rama"
            continue
        if s == "import os":
            continue
        salida.append(linea.replace("from machine import Pin, PWM, I2S", "from machine import Pin, PWM"))
    return salida


def codigo(lineas):
    """Solo el código: sin comentarios al final de línea, sin líneas de comentario y sin líneas en blanco."""
    salida = []
    for n, linea in enumerate(lineas, 1):
        s = re.sub(r"\s*#.*$", "", linea.rstrip()) if not linea.lstrip().startswith("#") else ""
        if s.strip() and s.strip() not in ESPERADAS:
            salida.append((n, s))
    return salida


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    respaldo = sys.argv[1] if len(sys.argv) > 1 else RESPALDO
    firmware = sys.argv[2] if len(sys.argv) > 2 else FIRMWARE
    if not os.path.exists(respaldo):
        print("No existe {}.\nGuárdalo desde Thonny: Archivo > Abrir > Dispositivo MicroPython > main.py; "
              "Archivo > Guardar como > Este equipo > firmware_mano\\main_funciona_sin_voz.py".format(respaldo))
        return 2
    a = open(respaldo, encoding="utf-8-sig").read().splitlines()     # -sig: ignora el BOM del Bloc de notas
    b = open(firmware, encoding="utf-8-sig").read().splitlines()
    print("=" * 30, "diff completo:", os.path.relpath(respaldo, PROYECTO), "->", os.path.relpath(firmware, PROYECTO))
    print("\n".join(difflib.unified_diff(a, b, "respaldo", "main.py", lineterm="", n=1)) or "(idénticos)")
    ca, cb = codigo(a), codigo(sin_voz(b))
    distintas = [l for l in difflib.unified_diff([s for _, s in ca], [s for _, s in cb], "respaldo", "main.py sin voz",
                                                  lineterm="", n=0)]
    print("\n" + "=" * 30, "código de la mano (main.py sin lo de la voz, sin comentarios)")
    if not distintas:
        print("IDÉNTICO al respaldo: pines, rangos, reset_all, letras, deletreo, Bluetooth y respuestas.")
        print("Diferencias esperadas: solo comentarios{}".format(
            " y SEG_SOLTAR (sin uso)" if any("SEG_SOLTAR" in l for l in a) else ""))
        return 0
    print("HAY DIFERENCIAS EN LA PARTE DE LA MANO:")
    print("\n".join(distintas))
    return 1


if __name__ == "__main__":
    sys.exit(main())
