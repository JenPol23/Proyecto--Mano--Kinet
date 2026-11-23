"""
config_fusion.py  -  CORRE EN EL PC
Configuracion de la voz de la fusion (MAX98357 en la ESP32 de la mano; los WAV se preparan aqui en el PC).
Tasa y volumen copiados de la configuracion de Doby (pc/config.py); procesado copiado de Doby (pc/tts.py).
"""

# ---------------- Audio ----------------
TASA = 16000        # Hz de los WAV (= TASA_VOZ del firmware de la mano)
VOLUMEN = 0.35      # 0.0 a 1.0 -> no pasar de 0.5 (parlante de 1.5 W)

# ---------------- Procesado (basado en _pulir de tts.py, mas suave) ----------------
# Los audios ya vienen cortados: no se recorta nada y la duracion queda igual a la del original.
CORTE_GRAVES = 100      # Hz (Doby: 200). Solo quita graves, no acorta nada. Si el parlante distorsiona: 200
SILENCIO_FINAL = 0.3    # segundos, una sola vez al final del audio completo (lo pone la placa)
RAMPA_MS = 2            # (Doby: 10) rampa minima contra el "clic"; Lina, Harry y Paula tienen voz en el borde

# ---------------- Recorte de silencio: DESACTIVADO ----------------
RECORTAR_SILENCIO = False
UMBRAL_SILENCIO_DB = -40    # respecto al pico de cada grabacion
MARGEN_SILENCIO_MS = 30     # se deja este margen antes y despues de la voz
