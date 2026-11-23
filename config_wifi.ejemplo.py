# config_wifi.ejemplo.py  -  PLANTILLA para la ESP32 (sin datos reales)
#
# Copiar como config_wifi.py, poner los datos de SU red y subirlo con Thonny a la RAIZ de la placa (/config_wifi.py),
# junto a main.py y wifi_hora.py. Lo lee firmware_mano/wifi_hora.py. Solo hace falta para el boton Hora:
# sin este archivo, la placa avisa "# WiFi desactivado" y la mano y la voz por Bluetooth funcionan igual.
# config_wifi.py esta en .gitignore: NUNCA se sube al repositorio.
#
# El TOKEN tiene que ser EXACTAMENTE el mismo que el de secretos.py en el PC (ver secretos.ejemplo.py).
# Para generar uno nuevo (32 caracteres), en el PC:
#     py -3.11 -c "import secrets; print(secrets.token_hex(16))"

RED = "TU_RED"          # nombre (SSID) de la red WiFi. En el proyecto: el punto de acceso de un celular (2,4 GHz)
CLAVE = "TU_CLAVE"      # clave de esa red
TOKEN = "PEGAR_AQUI_EL_TOKEN_GENERADO"   # contrasena entre el PC y la placa: la primera linea del PC es "auth <TOKEN>"
PUERTO = 5001           # puerto TCP donde escucha la placa (por defecto 5001). Debe ser el mismo en secretos.py
NOMBRE = "mano"         # nombre de la placa en la red: el PC la busca como <NOMBRE>.local (mano.local)

# IP_FIJA no se usa en la placa (la IP la da el punto de acceso); va solo en secretos.py del PC.
