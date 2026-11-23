# Mano: pruebas de dedos por Bluetooth

| Comando | Qué hace |
|---|---|
| `1 <dedo>` / `2 <dedo>` | Abre / cierra un dedo (`indice medio anular menique pulgar pulgar2`) |
| `3` / `4` | Cierra / abre toda la mano (0,4 s entre dedos) |
| `0` | Abre la mano y termina |

1. **Sin 12 V y con USB**, en la Consola de Thonny: `import os; os.rename("main.py", "main_mano.py")`. Luego abre `main.py` de esta carpeta → **Fichero › Guardar como… › Dispositivo MicroPython** → `main.py`. Deja `config_ble.py` en la placa.
2. Cierra Thonny, **quita el USB** y conecta los 12 V. Cierra el servidor de la mano y no emparejes la placa en Windows.
3. En el PC: `py -3.11 consola_pc.py` y escribe los comandos tras `> `. Para volver a la mano: sin 12 V y con USB, `os.remove("main.py"); os.rename("main_mano.py", "main.py")`.
