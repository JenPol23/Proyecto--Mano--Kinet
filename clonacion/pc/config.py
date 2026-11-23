# Configuracion del PC para Doby. Todo lo que puede cambiar se ajusta aqui.

# Red: IP de la ESP32 (puede cambiar al reconectar el punto de acceso)
IP_ESP32 = "192.168.43.228"
PUERTO = 5000

# Audio (verificado en hardware, no cambiar)
TASA = 16000        # Hz, microfono y parlante
VOLUMEN = 0.35      # 0.0 a 1.0 -> no pasar de 0.5 (parlante de 1.5 W)

# Deteccion de voz: None = umbral calibrado (max(ruido x 3, 300)).
# Si el ventilador mete ruido, poner aqui un numero fijo (ej. 1500).
UMBRAL_MANUAL = None

# Aparatos: nombre -> numero de rele k (RELE k; activo en bajo; GPIO en esp32/main.py: 1=10, 2=11, 3=12, 4=13).
# "prende todo" y "apaga todo" actuan sobre TODOS los de esta lista. El orden es el de las frases de
# estado: "Estan encendidos el bombillo, el ventilador, el cautin y la plancha."
APARATOS = {
    "bombillo": 3,
    "ventilador": 1,
    "cautin": 2,           # soldador (antes el carro). Clave sin tilde; Doby dice "cautín" (tts.NOMBRES)
    "plancha": 4,          # plancha de cabello
}

# Aparatos que se calientan: se apagan solos tras APAGADO_AUTOMATICO minutos (Doby lo avisa), al cerrar
# Doby y en la ESP32 si pierde el PC (CALIENTES de esp32/main.py: reles 2 y 4).
CALIENTES = ("cautin", "plancha")
APAGADO_AUTOMATICO = 10      # minutos; None = sin apagado automatico

# Verificacion de hablante (entrenamiento/hablantes.py + modelos/hablantes/). Solo en modo voz.
# Con VERIFICAR_HABLANTE = False, Doby funciona exactamente como antes (ni siquiera carga el modelo).
VERIFICAR_HABLANTE = True    # verificar quien dice "Hola Doby"
VERIFICAR_ORDENES = True     # ademas, verificar cada orden estando despierto
MODO_RECHAZO = "avisar"      # "avisar": dice "No reconozco tu voz"; "silencio": ignora la frase
# Ordenes con Doby despierto (VERIFICAR_ORDENES): se aceptan si el mejor integrante es quien lo
# desperto y su similitud >= UMBRAL_SESION. 0.38: con las ordenes de la evaluacion, 4.8 % de
# ordenes propias rechazadas y 12.1 % de ordenes de otro aceptadas, a 10 dB.
UMBRAL_SESION = 0.38

# Voz clonada (F5-TTS, <CARPETA_VOZ_CLONADA>/<persona>/, de entrenamiento/generar_voces_f5.py).
# Con VOZ_CLONADA = False, Doby habla siempre con su voz normal (gTTS), exactamente como antes.
# Con VOZ_CLONADA = True (todo local, nunca se llama a gTTS ni a tts.pregenerar()):
#   - persona verificada: siempre su voz clonada. Si le falta un audio: otra version suya, su frase
#     generica o silencio (queda en logs/voz_<fecha>.csv); nunca otra voz.
#   - sin persona verificada (desconocido, zona gris, verificacion apagada o que no cargo): la voz
#     normal, SOLO de los WAV que ya existen en voz_cache/.
#   - al arrancar se comprueba la cobertura (como pruebas/verificar_cobertura.py).
VOZ_CLONADA = True           # responder con la voz de quien desperto a Doby (persona_activa)
VOZ_POR_DEFECTO = None       # sin persona verificada: None = voz normal (voz_cache/); o el nombre de un integrante
CARPETA_VOZ_CLONADA = "voz_cache_f5"   # relativa al proyecto (voz_cache_clonada/ = XTTS, descartada)
