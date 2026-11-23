# config_ble.ejemplo.py  -  PLANTILLA (no tiene el token real)
# Copiar este archivo como config_ble.py en DOS lugares, con el MISMO contenido:
#   1. En la raiz del proyecto (lo lee fusion/consola_mano.py en el PC).
#   2. En la raiz de la placa, junto a main.py (lo sube cada uno con Thonny).
# config_ble.py esta en .gitignore: el token real nunca va al repositorio.
#
# TOKEN: minimo 16 caracteres (con "CAMBIAR_AQUI" la placa y el PC lo rechazan a proposito).
# Para generar uno:  py -3.11 -c "import secrets; print(secrets.token_hex(16))"

NOMBRE = "Mano-LSC"
TOKEN = "CAMBIAR_AQUI"
