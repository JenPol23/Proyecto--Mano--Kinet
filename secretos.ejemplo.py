# secretos.ejemplo.py  -  PLANTILLA para el PC (sin datos reales)
#
# Copiar como secretos.py en la RAIZ del proyecto (junto a este archivo). Lo lee fusion/mano_wifi.py (boton Hora)
# sin ejecutarlo, y nunca muestra el TOKEN (solo "TOKEN cargado (N caracteres)").
# secretos.py esta en .gitignore: NUNCA se sube al repositorio.
#
# Es la pareja de config_wifi.py de la placa: TOKEN, PUERTO y NOMBRE tienen que ser IGUALES en los dos archivos.
# Para generar un TOKEN nuevo (32 caracteres):
#     py -3.11 -c "import secrets; print(secrets.token_hex(16))"
# y pegar el MISMO texto aqui y en config_wifi.py (y volver a subir config_wifi.py a la placa).
#
# No confundir con config_ble.py: ese es el TOKEN del Bluetooth (puede ser otro distinto).

RED = "TU_RED"          # el PC no lo usa (se deja para tener los datos de la red en un solo lugar)
CLAVE = "TU_CLAVE"      # el PC no lo usa
TOKEN = "PEGAR_AQUI_EL_TOKEN_GENERADO"   # el mismo de config_wifi.py de la placa
PUERTO = 5001           # el mismo de config_wifi.py (por defecto 5001)
NOMBRE = "mano"         # el mismo de config_wifi.py: el PC busca primero <NOMBRE>.local
IP_FIJA = "192.168.0.50"   # EJEMPLO. Plan B si <NOMBRE>.local no responde: la IP que el punto de acceso le dio a la
                           # placa. Se ve en Thonny al arrancar: "# WiFi listo: <IP> puerto 5001 ...".
                           # Si no la saben, dejar IP_FIJA = None (o borrar la linea).
